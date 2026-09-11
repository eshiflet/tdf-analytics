# Cycling Analytics

Stage-by-stage results for professional road cycling, charted — every edition of
the Tour de France, the Giro d'Italia and the Vuelta a España, eleven one-day
classics, and seven gravel and mountain-bike races.

**Live: [ericshiflet.com/tdf-analytics](https://ericshiflet.com/tdf-analytics/)**

21 races · 1,365 race-years · 1892–2026 · 19,023 riders · 786,870 stage results

## What it shows

- **By Stage** — a bump chart of the general classification day by day, and the
  same for the points and mountains competitions. Switch the y-axis between
  position and time to watch a race converge or come apart.
- **Race Overview** — each edition's stage profiles, distances and elevation.
- **All Years Summary** — one race across its whole history: winners, distances,
  speeds, field sizes.
- **Riders** — a searchable grid of every rider, and a per-rider page charting
  their career across every race they appear in.

## Repository layout

| path | what it holds |
|---|---|
| `cycling-app/` | the site: TypeScript, D3, Vite. No framework. Deployed to GitHub Pages. |
| `cycling-app/src/data/` | exported JSON, one file per race-year — what the site actually loads |
| `pipeline/` | scrapers, ingest, validators and exporters (Python, standard library only) |
| `pipeline/*_scrapes/` | raw scraped JSON, tracked in git — the source of truth |
| `ai-context.md` | the long-form record: every defect found, why it happened, what the fix was |
| `architecture.md` | data model, module map, CI/CD flow |

`cycling.db` is **not** in git and **not** regenerable from scratch — some values
in it came from sources that no longer answer. Back it up with
`python3 pipeline/db_backup.py`.

## Working on it

```bash
cd cycling-app && npm install && npm run dev     # the site, on :5173
cd pipeline && python3 -m unittest discover -p 'test_*.py'
```

The pipeline needs no dependencies at all — Python 3 and the standard library.
The site needs Node 20.

A typical data change is scrape → ingest → export → validate:

```bash
python3 scrape_race.py --race tour 1985        # writes tour_scrapes/1985/
python3 preview_reingest.py --race tour 1985   # what the ingest WOULD change
python3 ingest_race.py --race tour 1985
python3 export_gc.py --race tdf --year 1985
python3 validate_db.py && python3 validate_exports.py
```

`preview_reingest.py` is worth the habit: it copies the database, ingests into
the copy and reports the diff, counting fills, overwrites and *clears*
separately. A rebuild that loses rows is the one to stop for.

## Why there is so much prose in the docs

Cycling data is wrong in quiet ways. A parser that stops matching returns
nothing, which becomes a NULL column and a blank chart rather than an error —
so the failures here are silent by default, and most of them look plausible.
Some real examples, all fixed:

- A winner "covering" 195.5 km in one second — the rider who won that stage was
  later stripped of it, and the promoted rider's row carries his *gap*.
- Ranks 1 through 5 sharing an identical time — that is a cumulative race total,
  not a stage time. Five riders on different teams cannot share a stage time.
- A team time trial's times landing nowhere, because the winning team's figure
  read `21:47.870` and the pattern allowed no fraction.
- 54,806 rows where a points total sat in a column meaning seconds.

`ai-context.md` records each one with the evidence, because the expensive part
is never the fix — it is working out that anything is wrong.

## Data

Results come from [procyclingstats.com](https://www.procyclingstats.com), with
Wikipedia and bikeraceinfo.com used to cross-check distances and classification
totals. Every stored value carries provenance: `data_provenance` records the
source and the URL for each field, and `unknown` is a real answer that means
nobody recorded where a number came from.
