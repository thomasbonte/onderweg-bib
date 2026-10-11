#!/usr/bin/env python3
"""
Daily crawler for a Flemish public-library availability feed
(cataloguswebservices.bibliotheek.be).

Fetches the XML availability feed for one book/title, extracts a
per-library snapshot (available copies, on-loan copies, reservations,
expected return dates, ...) and appends it as one JSON line to
docs/data/history.jsonl, so the static dashboard in docs/index.html
can build trends over time.

The URL (which embeds an authorization token) is read from the
AVAILABILITY_URL environment variable rather than hard-coded, so the
token doesn't need to live in the repo. Set it as a GitHub Actions
secret (see README.md).
"""

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

AVAILABILITY_URL = os.environ.get("AVAILABILITY_URL")

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "docs" / "data"
HISTORY_FILE = DATA_DIR / "history.jsonl"
LATEST_FILE = DATA_DIR / "latest.json"


def fetch_xml(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "library-availability-tracker/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_date_ddmmyyyy(value):
    """Convert a DD-MM-YYYY date string to ISO (YYYY-MM-DD)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return value


# Item states used throughout the snapshot data and the dashboard:
#   available   - on the shelf, can be borrowed now
#   loaned      - currently lent out
#   reserved    - on hold for someone (not lent out, not free)
#   processing  - "Niet beschikbaar": owned by the library but still being
#                 processed (not yet available for lending)
#   other       - anything we don't recognise (logged as a warning)
KNOWN_STATUS_CODES = {
    "none": "available",
    "loanedout": "loaned",
    "hasreservation": "reserved",
}
# Extra status codes that mean "being processed". Add to this set if the
# crawl log warns about a status code for 'niet beschikbaar' that isn't
# matched by the label check below.
PROCESSING_STATUS_CODES = {"notavailable", "inprocess", "processing", "inprocessing"}
PROCESSING_LABELS = ("niet beschikbaar", "in verwerking", "in behandeling")


def classify_item(available, status_code, status_label):
    label = (status_label or "").strip().lower()
    code = (status_code or "").strip().lower()
    if available:
        return "available"
    if code in PROCESSING_STATUS_CODES or any(p in label for p in PROCESSING_LABELS):
        return "processing"
    if code in KNOWN_STATUS_CODES:
        return KNOWN_STATUS_CODES[code]
    return "other"


def extract_branches(locations_elem):
    """Walk the nested <location> tree and pull out every physical
    branch (a <location> that has a <holding> child), remembering the
    name of the nearest enclosing grouping location (the city/network)
    as we descend.
    """
    branches = []

    def walk(elem, city_name):
        for child in list(elem):
            if child.tag == "location":
                holding = child.find("holding")
                if holding is None:
                    # Grouping node (e.g. "Gent"), not a physical branch.
                    walk(child, child.attrib.get("name"))
                else:
                    branches.append(extract_branch(child, holding, city_name))
                    walk(child, city_name)
            else:
                walk(child, city_name)

    walk(locations_elem, None)
    return branches


def extract_branch(branch_elem, holding_elem, city_name):
    items_elem = branch_elem.find("items")
    items = []
    if items_elem is not None:
        for idx, item in enumerate(items_elem.findall("item")):
            count = int(item.attrib.get("count", "1") or 1)
            available = item.attrib.get("available") == "true"
            status_code = item.attrib.get("status")
            status_label = item.findtext("status")
            state = classify_item(available, status_code, status_label)
            if state == "other":
                # Surfaces in the GitHub Actions log so the classifier can be tuned.
                print(
                    f"::warning::Unrecognised item status at {branch_elem.attrib.get('name')}: "
                    f"code={status_code!r} label={status_label!r}"
                )
            # Items still being processed may not have an itemid yet; fall back
            # to other identifiers so the dashboard can still track them.
            item_id = (
                item.findtext("itemid")
                or item.findtext("wiseid")
                or f"{holding_elem.attrib.get('id')}-{idx}"
            )
            items.append(
                {
                    "item_id": item_id,
                    "wiseid": item.findtext("wiseid"),
                    "available": available,
                    "state": state,
                    "status_code": status_code,
                    "status_label": status_label,
                    "count": count,
                    "shelfmark": item.findtext("shelfmark"),
                    "location_in_branch": item.findtext("subloc"),
                    "received_date": item.findtext("receivaldate"),
                    "return_date": parse_date_ddmmyyyy(item.findtext("returndate")),
                }
            )

    def copies(state):
        return sum(i["count"] for i in items if i["state"] == state)

    total_copies = sum(i["count"] for i in items)
    available_copies = copies("available")
    on_loan_copies = copies("loaned")
    reserved_copies = copies("reserved")
    processing_copies = copies("processing")

    address_elem = holding_elem.find("address")
    address = None
    if address_elem is not None:
        address = {
            "street": address_elem.findtext("street"),
            "number": address_elem.findtext("number"),
            "postcode": address_elem.findtext("postcode"),
            "city": address_elem.findtext("city"),
        }

    # Some branches sit directly under the root with no city grouping above
    # them (e.g. Sint-Martens-Latem); fall back to the address city.
    if not city_name and address and address.get("city"):
        city_name = address["city"].title()

    lat = holding_elem.attrib.get("latitude")
    lon = holding_elem.attrib.get("longitude")

    return {
        "city": city_name,
        "branch_name": branch_elem.attrib.get("name"),
        "branch_id": holding_elem.attrib.get("id"),
        "wise_branch_id": holding_elem.attrib.get("wise-id"),
        "latitude": float(lat) if lat else None,
        "longitude": float(lon) if lon else None,
        "url": branch_elem.attrib.get("url"),
        "address": address,
        "total_copies": total_copies,
        "available_copies": available_copies,
        "on_loan_copies": on_loan_copies,
        "reserved_copies": reserved_copies,
        "processing_copies": processing_copies,
        "items": items,
    }


def parse_snapshot(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    record = root.find(".//record")
    book = {
        "title": record.findtext("title") if record is not None else None,
        "author": record.findtext("author") if record is not None else None,
        "publisher": record.findtext("publisher") if record is not None else None,
        "publisher_year": record.findtext("publisher-year") if record is not None else None,
        "id": root.findtext(".//id"),
        "detail_page": root.findtext(".//detail-page"),
    }

    locations_elem = root.find("locations")
    branches = extract_branches(locations_elem) if locations_elem is not None else []

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "book": book,
        "network": {
            "total_copies": sum(b["total_copies"] for b in branches),
            "available_copies": sum(b["available_copies"] for b in branches),
            "processing_copies": sum(b["processing_copies"] for b in branches),
            "branch_count": len(branches),
        },
        "branches": branches,
    }


def main():
    if not AVAILABILITY_URL:
        print("ERROR: set the AVAILABILITY_URL environment variable", file=sys.stderr)
        sys.exit(1)

    xml_text = fetch_xml(AVAILABILITY_URL)
    snapshot = parse_snapshot(xml_text)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    LATEST_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"Logged snapshot for '{snapshot['book']['title']}': "
        f"{snapshot['network']['available_copies']}/{snapshot['network']['total_copies']} "
        f"copies available across {snapshot['network']['branch_count']} branches."
    )


if __name__ == "__main__":
    main()
