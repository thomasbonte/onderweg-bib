# Library availability tracker

Tracks daily availability of one title across Flemish public libraries
(via `cataloguswebservices.bibliotheek.be`) and renders a dashboard of
how often it's borrowed, at which libraries, and what's still free.

## How it works

- **`crawl.py`** fetches the availability XML for one book, parses it,
  and appends one JSON snapshot per day to `docs/data/history.jsonl`
  (plus overwrites `docs/data/latest.json` with the newest snapshot).
- **`.github/workflows/daily-crawl.yml`** runs `crawl.py` once a day on
  GitHub's schedule, and commits the updated data files back to the repo.
- **`docs/index.html`** is a static dashboard that reads
  `docs/data/history.jsonl` in the browser (via `fetch`) and renders:
  - current availability per library, with expected return dates
  - a network-wide availability trend over time
  - loan & return activity (detected by diffing consecutive snapshots)
  - reservation/hold queue per library over time
  - a day-by-day, library-by-library availability calendar
  - loans by day of week
  - a "what changed since yesterday" alerts panel
  - a table of copies currently on loan, soonest due date first

A day-one snapshot, parsed from the XML file you uploaded, is already
seeded into `docs/data/history.jsonl` so the dashboard has something to
show immediately. Trend/pattern panels that need multiple days will
show a short explanation until there's enough history.

## Setup

1. **Create a new GitHub repo** and push these files to it.

2. **Add the feed URL as a secret**, so the authorization token isn't
   stored in the repo itself:
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `AVAILABILITY_URL`
   - Value: the full URL you gave me, e.g.
     `https://cataloguswebservices.bibliotheek.be/zbb/availability/?lang=nl&authorization=...&id=...`

3. **Enable GitHub Pages**:
   - Repo → Settings → Pages → Source: "Deploy from a branch" → Branch:
     `main`, folder: `/docs`
   - Your dashboard will be live at `https://<username>.github.io/<repo>/`
     (the fetch call needs http(s) — opening `index.html` by double-clicking
     it locally won't work, since browsers block `fetch` of local files).

4. **Trigger the first run manually** (don't wait for the schedule):
   - Repo → Actions → "Daily library availability crawl" → Run workflow

From then on it runs automatically once a day (`05:00 UTC` by default —
edit the cron line in `.github/workflows/daily-crawl.yml` to change it)
and the dashboard updates itself as new commits land.

## A note on responsible use

The library site's `robots.txt` disallows generic automated crawling.
You already hold an authorization token for this specific availability
endpoint, and a once-a-day check is a light load, but it's worth
confirming this kind of polling is fine under bibliotheek.be's terms
of service before relying on it long-term, and dialing back frequency
if asked.

## Tracking more than one book

Right now the crawler is wired to a single title via `AVAILABILITY_URL`.
To track several: change `crawl.py` to accept a list of `(id, url)`
pairs, write one history file per book (e.g.
`docs/data/<book-id>/history.jsonl`), and add a book switcher to
`index.html`. Happy to build that out if you get there.

## Data schema

Each line of `docs/data/history.jsonl` is one JSON snapshot:

```json
{
  "fetched_at": "2026-09-12T06:00:00+00:00",
  "book": { "title": "...", "author": "...", "id": "..." },
  "network": { "total_copies": 4, "available_copies": 1, "branch_count": 4 },
  "branches": [
    {
      "city": "Gent",
      "branch_name": "De Krook",
      "branch_id": "...",
      "latitude": 51.04855, "longitude": 3.72893,
      "total_copies": 1, "available_copies": 0,
      "on_loan_copies": 1, "reserved_copies": 0,
      "items": [
        { "item_id": "33508208", "available": false, "status_code": "loanedout",
          "return_date": "2026-10-02", "received_date": "2026-07-28" }
      ]
    }
  ]
}
```
