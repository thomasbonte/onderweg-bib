# Library availability tracker

Tracks daily availability of the book [Onderweg](https://thomasbonte.github.io/onderweg-bib/) across Flemish public libraries
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
