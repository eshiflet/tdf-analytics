# Cycling Analytics — AI Context

Interactive cycling analytics app covering the **Tour de France** (all 113 editions, 1903–2026) and the **Giro d'Italia** (2026, all 21 stages). The 2026 Tour de France is in progress — stages are added incrementally as the race runs. The 2026 Giro d'Italia is complete (all 21 stages scraped, ingested, and exported). Live at **[ericshiflet.com/tdf-analytics/](https://ericshiflet.com/tdf-analytics/)**.

---

## Project Overview

The app visualizes per-rider performance across every stage of multiple Grand Tour races. Users select a **race** (Tour de France or Giro d'Italia) and **year** via dropdowns, then pick a metric and see a bump chart of every rider's ranking after each stage, with a sidebar legend and hover tooltips.

**Tech stack:**
- Frontend: Vite + TypeScript + D3.js (static site, no framework)
- Data: SQLite → Python export → JSON files bundled by Vite
- Hosting: GitHub Pages, deployed via GitHub Actions on push to `main`

**Multi-race support:** The frontend has a race dropdown (Tour de France / Giro d'Italia) next to the year dropdown. Each race has its own set of years. Data files are organized by subdirectory: TDF at `data/gc_by_stage_*.json`, Giro at `data/giro/gc_by_stage_*.json`. The DB schema is multi-race via the `races` table (race_id=1 TDF, race_id=2 Giro). The Giro currently has 2026 (all 21 stages). The "All Races Overview" and "Riders" views currently only have TDF data.

**Three views:**

1. **By Stage** — bump chart showing each rider's rank after every stage. Three selectable metrics:
   - *GC Position* — cumulative general classification rank
   - *Sprint Points* — cumulative green jersey points standing (data starts 1953; golf scoring 1953–1958 where lower = better)
   - *KOM Points* — cumulative King of the Mountains standing (data starts 1933)
   Sidebar has Top 10/20/All/None quick-select plus **Team** and **Nation** multi-select dropdown filters (OR within a filter, AND between the two); selections persist across a year change, dropping any value that doesn't exist in the new year and falling back to an empty ("None") selection if nothing carries over.

2. **Race Overview** — per-stage bar charts of distance, elevation gain, and difficulty score for the selected year, colored by route type (Flat / Hilly / Mountain / TT / TTT)

3. **All Races Overview** — four stacked line charts comparing every edition 1903–2026:
   - Total Distance (km)
   - Total Elevation (m)
   - GC Winner Time (h)
   - Average Speed (km/h) — GC winner (green) and slowest finisher (red) on shared axis

---

## Repository Structure

```
tdf-analytics/
├── .github/workflows/deploy.yml      # GitHub Actions: builds + deploys on push to main
├── ai-context.md                     # This file
├── cycling-app/                      # Vite web application
│   ├── index.html                    # App shell (nav buttons, sidebar, chart area)
│   ├── vite.config.ts                # base: "/tdf-analytics/" — required for GitHub Pages
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── main.ts                   # All chart logic, D3 rendering, event handling (~2,200 lines)
│       ├── types.ts                  # TypeScript interfaces
│       ├── style.css                 # All styles
│       └── data/                     # Generated JSON — one per year + summary
│           ├── gc_by_stage_1903.json  # TDF files live at top level
│           ├── ...
│           ├── gc_by_stage_2026.json  # 113 TDF files total (lazy-loaded, one chunk each)
│           ├── giro/                  # Giro d'Italia files in subdirectory
│           │   └── gc_by_stage_2026.json
│           ├── all_races_summary.json # Cross-year aggregate data for All Races view (TDF only currently)
│           └── riders_index.json      # Compact cross-year rider index (lazy-loaded by Riders view)
└── pipeline/                         # Data pipeline — not deployed
    ├── cycling.db                    # SQLite DB (gitignored — ~50MB, keep locally)
    ├── export_gc.py                  # Main exporter: cycling.db + JSON supplements → src/data/
    │                                 #   --year N for single year, --race giro|tdf to select race
    ├── export_riders_index.py        # Builds riders_index.json from the exported per-year files
    ├── export_all_races_summary.py   # Builds all_races_summary.json from cycling.db + supplements
    ├── build_db.py                   # STALE/DO NOT USE for adding years — see warning below
    ├── add_pre1960.py                # The actual tool for adding ANY TDF year additively (name is historical)
    ├── add_stages.py                 # Automated TDF stage addition: scrape files → JSON updates → DB → exports
    ├── scrape_stage_template.js      # JS snippets for extracting stage data from PCS in a browser
    ├── scrapes/                      # Per-stage TDF scrape output files (stage_N.json)
    ├── schema.sql                    # DB schema reference
    │
    │   # Giro d'Italia pipeline
    ├── ingest_giro.py                # Reads giro_scrapes/stage_N.json → inserts into cycling.db
    │                                 #   Creates race "Giro d'Italia" (race_id=2) if not present
    ├── build_giro_points.py          # Extracts sprint/KOM points from giro_scrapes/ → giro_*_points.json
    ├── giro_scrapes/                 # Per-stage Giro scrape output files (stage_N.json, all 21 for 2026)
    │   └── save_server.py            # Local HTTP server (localhost:8765) for saving stage JSON via POST
    ├── giro_sprint_points.json       # Giro sprint points per rider per stage (same format as sprint_points.json)
    ├── giro_kom_points.json          # Giro KOM points per rider per stage (same format as kom_points.json)
    │
    │   # TDF supplemental data files (all in git)
    ├── sprint_points.json            # Green jersey points per rider per stage (1953–2025)
    ├── kom_points.json               # KOM points per rider per stage (raw PCS scrape)
    ├── kom_points_reconciled.json    # KOM points after Wikipedia patching (authoritative)
    ├── kom_totals.json               # Final KOM totals from Wikipedia + bikeraceinfo
    ├── kom_reconcile_report.json     # Year-by-year reconciliation results
    ├── profile_icons.json            # Raw PCS profile-icon code per stage (p1–p5 — see warning below)
    ├── bri_stages.json               # Per-stage results from bikeraceinfo (1960–2005)
    ├── gc_winner_times.json          # Official GC winner total time per year from Wikipedia
    ├── gc_all_times.json             # Official GC times for top ~10 riders per year from Wikipedia
    ├── wiki_race_distances.json      # Official total race distance per year from Wikipedia infobox
    ├── all_races_summary_overrides.json # Per-year field overrides for export_all_races_summary.py
    │                                   #   (e.g. full-planned-route elevation for an in-progress year)
    │
    │   # Scraping scripts
    ├── tdf_YEAR_full.json            # Raw PCS scrape files (1903–1959 kept in git; 1960+ generated locally)
    ├── scrape_kom_points.py          # Scrapes KOM points from PCS stage -kom pages
    ├── scrape_kom_totals.py          # Scrapes final KOM totals from Wikipedia + bikeraceinfo
    ├── scrape_bri_stages.py          # Scrapes per-stage results from bikeraceinfo
    ├── scrape_gc_winner_times.py     # Scrapes GC winner total time from Wikipedia GC table
    ├── scrape_gc_all_times.py        # Scrapes GC times for all top-10 riders from Wikipedia
    ├── scrape_pcs_stages.py          # Scrapes stage data from PCS
    ├── scrape_pcs_kom_finals.py      # Scrapes final KOM standings from PCS
    ├── scrape_sprint_finals.py       # Scrapes final sprint standings
    ├── scrape_sprint_finals.py
    │
    │   # Patch / fix scripts
    ├── patch_kom_wikipedia.py        # Patches KOM data from Wikipedia (years 1933–1938 top 10)
    ├── patch_missing_distances.py    # Patches zero/null stage distances from PCS result pages
    ├── patch_bri_distances.py        # Patches distances from bikeraceinfo; reports conflicts
    ├── patch_route_types_wikipedia.py # Patches stage route types from Wikipedia
    │
    │   # Validation scripts
    ├── reconcile_kom.py              # Reconciles PCS KOM data against Wikipedia/BRI references
    ├── validate_exports.py           # CI gate: checks all gc_by_stage_*.json for data integrity
    │                                 #   (decreasing cumulatives, bad structure — hard error; duplicate
    │                                 #   ranks, KOM reference drift — warnings). Runs in deploy.yml.
    ├── validate_kom.py               # Validates KOM totals vs Wikipedia and bikeraceinfo
    └── validate_gc.py               # Validates per-stage GC leaders/gaps vs bikeraceinfo
```

> **Critical:** `cycling.db` is gitignored and must be kept locally at `pipeline/cycling.db`. Without it you cannot regenerate the JSON data files or add new years. Back it up separately.

> **`build_db.py` is stale — do not use it to add a year.** Despite being the script named in older instructions here, it (a) writes to `/tmp/cycling.db`, not the real DB, and (b) unconditionally wipes and rebuilds *every* edition in a hardcoded `EDITIONS` list, which requires raw scrape files for years that mostly no longer exist locally. **`add_pre1960.py` is the real tool**, despite its pre-1960-sounding name — it reads a CLI year argument (`python3 add_pre1960.py 2026`), writes additively to the real `pipeline/cycling.db`, and skips (never wipes) any year already present. See "Adding a New Year" below.

---

## Data Pipeline

### Tour de France pipeline
```
PCS website  →  tdf_YEAR_full.json  (scraped via a real browser — see note below)
                       ↓
                add_pre1960.py  →  cycling.db      (NOT build_db.py — see warning above)
                                      │
              ┌───────────────────────┴──────────────────────────────┐
              │  supplemental JSON files:                             │
              │  sprint_points.json       (green jersey pts)          │
              │  kom_points_reconciled.json (KOM pts)                 │
              │  profile_icons.json       (raw PCS icon codes)        │
              │  gc_all_times.json        (official rider times)      │
              │  gc_winner_times.json     (official winner times)     │
              └───────────────────────┬──────────────────────────────┘
                                      ↓
                       export_gc.py + export_all_races_summary.py
                                      │
                    ┌─────────────────┴──────────────────┐
                    ↓                                    ↓
       data/gc_by_stage_YEAR.json (×N)       all_races_summary.json
```

### Giro d'Italia pipeline
```
PCS website  →  giro_scrapes/stage_N.json  (scraped via real browser, same row format as TDF)
                       ↓
               build_giro_points.py  →  giro_sprint_points.json + giro_kom_points.json
                       ↓
               ingest_giro.py  →  cycling.db  (race_id=2, "Giro d'Italia")
                       ↓
               export_gc.py --race giro
                       ↓
              data/giro/gc_by_stage_YEAR.json
```

Both pipelines feed into the same `cycling.db` (the `races` table distinguishes them: race_id=1 = TDF, race_id=2 = Giro). The Giro pipeline is simpler because it stores sprint/KOM points inside each stage scrape file (not in a separate `tdf_YEAR_full.json` bundle). `export_gc.py --race giro` automatically picks up `giro_sprint_points.json` and `giro_kom_points.json` instead of the TDF versions.

```
                               vite build  →  build/  →  GitHub Pages
```

> **Scraping PCS in 2025+:** plain `curl`/`urllib` requests get a Cloudflare "Just a moment…" 403 challenge page — `scrape_pcs_stages.py` (urllib-based) no longer works against the live site. Use a real browser (e.g. the Chrome MCP tools) to load each stage page and extract the results table via injected JavaScript instead. See "Scraping a live/in-progress Tour" below for the exact DOM structure and a working extraction pattern.

### Key data files

**`cycling.db`** — SQLite database. Tables:
- `races` — (race_id, name, country, race_type) — race_id=1 "Tour de France", race_id=2 "Giro d'Italia"
- `race_editions` — (edition_id, race_id, year) — `race_id` FK to `races`; UNIQUE(race_id, year)
- `stages` — (stage_id, edition_id, stage_number, stage_date, start_location, finish_location, distance_km, vertical_meters, route_type)
- `riders` — (rider_id, full_name, nationality_code) — shared across races (same rider can appear in both)
- `teams` — (team_id, name)
- `countries` — (code, name)
- `stage_results` — (rider_id, stage_id, team_id, gc_rank, gc_gap_seconds, finish_time_seconds, status)

`finish_time_seconds` = time to complete that single stage (often null for pre-1960 and non-winners).  
`gc_gap_seconds` = cumulative gap to GC leader at that stage (often null for early years non-top-10).  
`gc_rank` = general classification rank after that stage.  
`status` = 'FINISHED', 'DNF', 'DNS', 'DSQ', etc.

**`profile_icons.json`** — `{"2025": ["p1", "p3", ...], ...}`. **Raw PCS profile-icon codes** (`p1`–`p5`), NOT decoded route-type letters — a past version of this doc said otherwise; the actual decoding happens in `add_pre1960.py`'s `detect_route_type(icon, won_how)`:
1. If `won_how` (the stage's "Won how" text, e.g. "Sprint of small group") contains "team time trial"/"ttt" → `route_type = "TTT"`.
2. Else if it contains "time trial" → `"TT"`.
3. Else fall back to `ICON_TO_ROUTE = {"p1": "F", "p2": "H", "p3": "H", "p4": "M", "p5": "M"}`.

This matters when scraping a TTT stage whose PCS page doesn't populate `won_how` with descriptive text (seen on 2026 stage 1) — you must **manually set that stage's `info["Won how"]`** in the raw `tdf_YEAR_full.json` to a string containing "team time trial" (or "time trial" for a lone ITT) before running `add_pre1960.py`, or it silently misclassifies as Flat/Hilly/Mountain from the icon alone.

**`sprint_points.json`** — Green jersey points per stage per rider.
```json
{ "2025": [ {}, {"rider/jonathan-milan": 12, ...}, ... ] }
```
Array index = stage position in DB ordering (matches `stages` table order). Each dict maps `rider/rider-slug` → points earned that stage from intermediate sprints + stage finish only (KOM sprint points excluded). Data starts at 1953. **Golf scoring 1953–1958**: lower cumulative points = better rank (Schär system).

**`kom_points_reconciled.json`** — KOM points, same structure as sprint_points. For 1933–1938, Wikipedia top-10 data was merged via `patch_kom_wikipedia.py` because PCS only had top 3–5. This is the authoritative source; `kom_points.json` is the raw PCS scrape.

**`gc_winner_times.json`** — `{"1903": 340380, "1904": 345955, ...}` — official total race time in seconds for the GC winner, scraped from Wikipedia's General Classification table. 103 of 112 years. Missing: 1905–1912 (points-system era, no times) and 1904 (non-standard table). 2000–2005 uses Armstrong's time (DSQ in 2012 but fastest in the race).

**`gc_all_times.json`** — `{"1903": {"rider/garin-maurice": 340394, ...}, ...}` — official total times for all riders listed in Wikipedia's GC table (typically top 10 per year). Used to set `totalTimeSeconds` in the export. 1,144 rider-times across 104 years.

**`wiki_race_distances.json`** — `{"1903": 2428.0, "1904": 2428.0, ...}` — official total race distance in km scraped from Wikipedia infoboxes. 109 of 112 years. Used in `all_races_summary.json` as the authoritative source (PCS stage sums had many errors including some 100–200 km off).

**`all_races_summary.json`** — Cross-year aggregate, used by All Races Overview.
```json
[
  {"year": 1903, "totalDistanceKm": 2428.0, "totalElevationM": null,
   "gcWinnerTimeSeconds": 340380, "slowestFinisherTimeSeconds": 386280},
  ...
]
```
All 124 years 1903–2026 are present (non-race years: WWI 1915–1918, WWII 1940–1946 = null values).  
`slowestFinisherTimeSeconds` = `gcWinnerTimeSeconds + MAX(gc_gap_seconds)` among FINISHED riders at last stage.  
Generated by `export_all_races_summary.py`, which merges in `all_races_summary_overrides.json` (`{"2026": {"totalElevationM": 53707}}`-shaped — any field there overwrites the DB-computed default for that year) after computing the defaults — currently only used to pin 2026's elevation to the full planned-route total instead of just the stages inserted so far.

**`gc_by_stage_YEAR.json`** — Per-year data bundled by Vite.
```json
{
  "stages": [{
    "stage_number": 1, "stage_label": "1",
    "start_location": "Paris", "finish_location": "Lyon",
    "distance_km": 185.5, "vertical_meters": 1200, "route_type": "F"
  }],
  "riders": [{
    "id": "rider/tadej-pogacar",
    "name": "Pogačar Tadej",
    "nationality": "Slovenia",
    "team": "UAE Team Emirates",
    "finalRank": 1,
    "totalTimeSeconds": 273632,
    "byStage": [{
      "stage": 1, "gcRank": 5, "gcGapSeconds": 12, "status": "FINISHED",
      "cumulativePoints": 0, "cumulativeKomPoints": 0,
      "sprintRank": null, "komRank": null
    }]
  }]
}
```
`finalRank` = 9999 for DNF/DSQ riders (for legend sort; never shown on chart y-axis).  
`sprintRank` / `komRank` — pre-computed in export_gc.py, never re-derived in frontend (required for golf-scoring years where lower points = better rank).

---

## export_gc.py — Key Logic

This is the most important script. It reads cycling.db + all supplemental JSON files and produces the per-year JSON files. Supports `--race giro` (or `--race tdf`, the default) to select which race to export. When `--race giro` is used, it reads `giro_sprint_points.json` / `giro_kom_points.json` instead of the TDF versions and outputs to `data/giro/`.

**`totalTimeSeconds` priority** (per rider):
1. `gc_all_times.json` — Wikipedia official time (top ~10 per year)
2. `gc_winner_times.json + gc_gap_seconds` — winner time + rider's gap at last stage
3. Sum of `finish_time_seconds` across stages — legacy fallback (often incomplete)

**Sprint rank computation**: Pre-computed per-stage before the rider loop using running cumulative totals. `GOLF_SPRINT_YEARS = set(range(1953, 1959))` controls ascending vs descending sort. Stored as `sprintRank` in each `byStage` entry.

**KOM rank computation**: Same approach as sprint, always descending (higher points = better). Stored as `komRank`.

**DNF tail catch-up**: After the per-stage loop for a rider, if they DNF'd before the last stage, their cumulative points are topped up with any points stored in later stage slots (some sources store final totals in the last stage entry). Their final `sprintRank`/`komRank` is also set from the pre-computed final-stage rank tables.

**`finalRank`**: Derived from each rider's last `byStage` entry's `gc_rank`, not from the last stage's result row. This ensures DNF'd KOM/sprint leaders still get correct classification ranks.

**gc_rank=999**: Used by PCS for disqualified riders in early years (1904, 1905). These are set to NULL in the DB so the y-axis doesn't extend to 999. These riders get `finalRank=9999` and appear at the bottom of the legend.

---

## Frontend — main.ts

All chart logic is in `cycling-app/src/main.ts` (~2,290 lines). Key functions:

- **`loadDataset(year)`** — **async**; awaits `getDataset(year)` (lazy chunk fetch + LRU), updates UI state, triggers chart redraw. Callers that depend on the result (year-select change, career-dot click-through) must handle the promise — the career-dot click does `loadDataset(...).then(() => switchView("stage"))` to avoid rendering the previously-loaded year.
- **`getDataset(year)`** — resolves a year's dataset from a 6-entry LRU (`DATASET_CACHE`, keyed by `race:year`); on miss it `fetch()`es the year's JSON asset (URL from `URLS_BY_RACE[currentRace]`) and `JSON.parse`s it. Re-visiting an evicted year re-fetches from the browser HTTP cache (no network, only re-parse).
- **`drawChart()`** — renders the bump chart for the current year/metric. Calls `buildRankMapsFromField()` to extract rank series per rider. Each metric has an optional "points" display mode toggled via a y-axis button: GC Time (ascending hours), Sprint Points (ascending cumulative), KOM Points (ascending cumulative).
- **`buildRankMapsFromField(getRank, getCumPts)`** — takes accessor functions, builds `rankAtStage` and `cumulativeAtStage` maps. Reads `sprintRank`/`komRank` fields directly (never re-derives them). `finalRank` is built only from riders who reached the final stage — DNF riders keep their mid-race rank in `rankAtStage` (so their lines still draw) but are excluded from `finalRank` (so they don't pollute Top N selection or legend ordering).
- **`setHighlight(id)`** — O(1) hover path: restyles only the previous and new highlighted rider's elements (line + dot + label) via `restyleRider()`, instead of sweeping all ~180 riders. `updateLineClasses()` still exists for full-sweep scenarios (selection changes, presets, filters).
- **`drawOverview()`** — renders the Race Overview bar charts
- **`drawAllRacesOverview()`** — renders the 4-panel All Races Overview. Uses `ALL_RACES` (imported from `all_races_summary.json`) and a shared `crosshairLines[]` array for the synchronized hover line
- **`drawRidersPage()`** — **async**; awaits `ensureRiderIndex()` (shows "Loading riders…" on first open) then renders the search/filter grid. `drawRiderDetail(id)` renders a rider's career chart.
- **`ensureRiderIndex()`** — idempotent; `fetch()`es `riders_index.json` once (URL via `?url` import) and builds `riderIndex` (Map) + `allTeamsSorted`. Lazy so it never weighs down first paint. The file is `{ teams: [names], riders: { slug: {...} } }`: rider keys are slugs (the `rider/` prefix is re-added on load) and teams are integer indexes into the shared `teams` string table (`-1` = no team) — both shrink the payload versus inlining strings. Year-tuples are `[gcRank, teamIdx]` (no points rankings that year) or `[gcRank, teamIdx, sprintRank, komRank]` with `0` = absent rank; normalized to `9999` sentinels on load.
- **`switchView(view)`** — handles "stage" | "overview" | "allraces" | "riders" transitions; calls `updateHash()` at the end
- **`wireControls()`** — attaches all event listeners (year select, metric select, sidebar buttons, view buttons, Team/Nation filter dropdowns)
- **`buildStageFilters()`** — rebuilds the Team/Nation dropdown checkbox lists for the current year's dataset; prunes `stageFilterTeams`/`stageFilterNations` to only values that still exist (carrying filter state across a year change), reapplies the filter if anything survived, or forces an empty selection if a filter was active but nothing carried over
- **`applyStageTeamNationFilter()`** — recomputes `selected` from `stageFilterTeams`/`stageFilterNations` (OR within a facet, AND across facets); no-ops if both are empty so it never fights with the quick-select buttons

**Hash routing (deep links)**: every view is URL-addressable — `#<year>/stage/<metric>` (metric: `gc`|`gc-time`|`points`|`sprint-points`|`kom`|`kom-points`), `#<year>/overview`, `#allraces`, `#riders`, `#riders/<rider-slug>` (slug = rider id minus the `rider/` prefix). The `-time`/`-points` suffixes select the alternate y-axis display mode for that metric. `computeHash()` derives the hash from state; `updateHash()` writes it via `location.hash` (pushes a history entry, so back/forward walk app states); `applyHash()` parses `location.hash` back onto state (async — awaits `loadDataset`/`ensureRiderIndex`). Loop protection: `applyHash` no-ops when the hash already equals `computeHash()` (our own write), and the `applyingHash` flag suppresses `updateHash` during an apply so intermediate draws don't push partial states. `init()` applies the initial hash, falling back to defaults + `history.replaceState` seed when the hash is empty/unrecognized; after applying, it loads the default dataset whenever none is in memory — this covers riders/allraces deep links (so stage/overview work on later navigation) AND deep links that exactly match the default state, which `applyHash()` short-circuits as "already in sync" without loading anything. When adding new app state that should be shareable, extend `computeHash` + `applyHash` together.

**No-data overlays**: If `currentMetric === "points"` and `year < 1953`, or `currentMetric === "kom"` and `year < 1933`, the chart area shows an explanatory text message instead of chart elements.

**Data loading (performance-critical)**: Per-year files are discovered with **two eager `?url` globs** — one for TDF (`./data/gc_by_stage_*.json`) and one for Giro (`./data/giro/gc_by_stage_*.json`). These put only the hashed asset *URLs* in the main bundle via `URLS_BY_RACE` (a `Record<RaceId, Record<string, string>>`); the data itself is emitted as raw `.json` assets and loaded via `fetch()` + `JSON.parse` on demand. The `currentRace` variable (`"tdf"` | `"giro"`) selects which URL map to use; `YEARS` is rebuilt from `getYearsForRace(currentRace)` on race change. Do **not** switch back to module imports (plain glob / dynamic `import()`): the browser's ES-module registry pins every imported module for the page's lifetime, so LRU eviction would no longer free memory, and parsing JSON-as-JS is slower than `JSON.parse`. Adding a new race is: drop files in a new subdirectory under `data/`, add a glob for that path, extend `URLS_BY_RACE` and the `RaceId` type, and add an `<option>` to the race dropdown in `index.html`. The Riders page's cross-year `riders_index.json` is fetched the same way (its URL comes from a `riders_index.json?url` import). Only the tiny `all_races_summary.json` is eagerly bundled. d3 is imported as modular submodules (`d3-selection`, `d3-scale`, `d3-axis`, `d3-shape`, `d3-array`) via a small `d3` shim object, not the full `d3` meta-package. Net result: initial download for the default stage view is ~76 KB gzipped, and only LRU-cached years (max 6) stay in memory.

---

## Local Development

```bash
cd cycling-app
npm install          # first time only
npm run dev          # dev server at http://localhost:5173/tdf-analytics/
```

After making data changes:
```bash
cd pipeline
# TDF exports (default)
python3 export_gc.py                 # regenerates all src/data/gc_by_stage_*.json (every TDF year in cycling.db)
python3 export_gc.py --year 2026     # single-year only (much faster — avoids rewriting all 113 files)
# Giro exports
python3 export_gc.py --race giro                # all Giro years → src/data/giro/
python3 export_gc.py --race giro --year 2026    # single Giro year
# Shared exports
python3 export_riders_index.py       # rebuilds riders_index.json (Riders page cross-year index)
python3 export_all_races_summary.py  # rebuilds all_races_summary.json (All Races Overview data — TDF only currently)
python3 validate_exports.py          # check all exported files (0 errors = good; warnings = informational)
python3 validate_exports.py --year 2026  # validate just one year

cd ../cycling-app
npm run build                # verify production build compiles
node verify.mjs              # smoke-test the built bundle (year switching, axes, tooltips)
node verify-views.mjs        # deep-link/view regressions (default-hash load, riders grid/detail, allraces, overview)
```

---

## Deployment

Push to `main` — GitHub Actions builds and deploys automatically (~2 min):
```bash
git add .
git commit -m "describe change"
git push
```

`.github/workflows/deploy.yml` runs: `python3 validate_exports.py` (data validation, hard-fails on decreasing cumulative points or malformed structure) → `npm ci && npm run build` → `node verify.mjs && node verify-views.mjs` (smoke tests on the built bundle) → deploy to GitHub Pages. A bad data export or a broken build cannot deploy.

> `vite.config.ts` must keep `base: "/tdf-analytics/"` — asset paths break without it.

---

## Adding a New Year (e.g. 2026)

1. **Scrape PCS data** for the new year into `tdf_2026_full.json` (`{"stages": [{"n": 1, "info": {...}, "rows": [...]}], "classifications": {}}`). For a live/in-progress Tour, this must be done via a real browser — see "Scraping a live/in-progress Tour" below for the exact method and DOM structure. Each row is `[rnk, gc_pos, gc_lag, bib, age, rider_name, rider_slug, nat, team_name, team_slug, uci_pts, pcs_pts, bonus_txt, abs_time_txt, gap_txt]` — only the stage winner (`rnk == "1"`) needs a real `abs_time_txt`; every other rider just needs `gap_txt` (finish time is computed as `winner_seconds + gap_seconds`). `gc_pos`/`gc_lag` can be left blank for stage 1 — there's a carry-forward fallback that fills them from the stage rank/gap.

2. **Add to DB — use `add_pre1960.py`, not `build_db.py`:**
   ```bash
   cd pipeline
   python3 add_pre1960.py 2026 --dry-run   # sanity check first
   python3 add_pre1960.py 2026             # real insert — additive, never wipes existing data
   ```
   This only works if `2026` is **not already** in `race_editions` — see "Adding stages to an in-progress year" below for what to do once it is.

3. **Add sprint points** for the year to `sprint_points.json`. Key = year string, value = array of dicts (one per stage, same order as DB stages) mapping `rider/slug` → points earned that stage from sprints + stage finish (exclude KOM sprint points). See "Scraping a live/in-progress Tour" for how to extract these from PCS's `-points` page.

4. **Add profile icons** for the year to `profile_icons.json` — an array of **raw PCS icon codes** (`p1`–`p5`), one per stage, in DB stage order. For a TTT/ITT stage, also make sure that stage's `info["Won how"]` in `tdf_2026_full.json` contains "team time trial"/"time trial" text (see the `profile_icons.json` warning above) — the icon code alone won't classify it correctly.

5. **Add KOM points** for the year to `kom_points_reconciled.json`. Same structure as sprint_points.json — see "Scraping a live/in-progress Tour" for extraction.

6. **Scrape Wikipedia GC times** (only meaningful once the race has an official classification — skip for an in-progress year):
   ```bash
   python3 scrape_gc_all_times.py 2026    # appends to gc_all_times.json + gc_winner_times.json
   ```

7. **Add the race distance** to `wiki_race_distances.json`. For a completed year this comes from the Wikipedia infobox; for the current year while it's in progress, use the PCS route page's official total instead (`https://www.procyclingstats.com/race/tour-de-france/2026/route` → "21 Stages » ... (3321.2km)" at the top of the page):
   ```bash
   python3 -c "
   import json
   with open('wiki_race_distances.json') as f: d = json.load(f)
   d['2026'] = 3321.2   # replace with actual
   with open('wiki_race_distances.json', 'w') as f: json.dump(d, f, ensure_ascii=False)
   "
   ```
   If the same PCS route page also gives a full-route vertical-meters total and the year is still in progress, add it to `all_races_summary_overrides.json` too (see below) so elevation doesn't undercount to just the stages raced so far.

8. **Re-export:**
   ```bash
   python3 export_gc.py --year 2026      # regenerate just the new year's JSON
   python3 export_riders_index.py        # rebuilds riders_index.json from the exported files
   python3 export_all_races_summary.py   # rebuilds all_races_summary.json
   python3 validate_exports.py --year 2026  # verify data integrity before pushing
   ```

9. **Push** — the app auto-discovers all years from the `?url` glob over `src/data/` (no hardcoded year list in the frontend).

---

## Adding stages to an in-progress year (e.g. more 2026 stages)

**Automated workflow** using `add_stages.py` + `scrape_stage_template.js`:

1. **Scrape each new stage** from PCS via the browser. For each stage N:
   - Navigate to `https://www.procyclingstats.com/race/tour-de-france/2026/stage-N`
   - Run the `EXTRACT_RESULTS` JS from `scrape_stage_template.js` via `javascript_tool`
   - Read the page text (`get_page_text`) and save as `pipeline/scrapes/stage_N.json`
   - Navigate to `.../stage-N-points`
   - Run the `EXTRACT_POINTS` JS via `javascript_tool`
   - Read the page text, parse the JSON, merge `sprint_points` and `kom_points` into `scrapes/stage_N.json`

2. **Run `add_stages.py`** — this handles everything else automatically:
   ```bash
   cd pipeline
   python3 add_stages.py 10 11        # stage numbers to add
   python3 add_stages.py 10 --dry-run # preview without writing
   ```
   It updates `tdf_2026_full.json`, `sprint_points.json`, `kom_points_reconciled.json`, `profile_icons.json`, deletes/re-inserts the year in `cycling.db`, runs all three exports, and validates.

Each `scrapes/stage_N.json` contains:
```json
{
  "n": 10,
  "info": { "Date": "...", "Distance": "...", "Won how": "...", ... },
  "rows": [ [rnk, gc_pos, gc_lag, bib, age, name, slug, nat, team, team_slug, uci, pnt, bonus, abs_time, gap], ... ],
  "profile_icon": "p2",
  "sprint_points": { "rider/slug": 25, ... },
  "kom_points": { "rider/slug": 3, ... }
}
```

**Key notes:**
- `add_stages.py` safely replaces stages that already exist in the data files (idempotent)
- The scrape files persist in `pipeline/scrapes/` so stages don't need re-scraping
- `--scrapes-only` flag updates just the JSON files without touching the DB or running exports
- `add_pre1960.py` is still the underlying DB inserter; `add_stages.py` orchestrates around it

### Manual fallback (if add_stages.py isn't suitable)

`add_pre1960.py`'s `insert_edition()` skips the entire year if it already exists in `race_editions`. The manual process is: delete the edition from all DB tables (no `ON DELETE CASCADE`), re-run `add_pre1960.py`, and manually update the supplemental JSON files. See `add_stages.py` source for the exact delete SQL.

---

## Adding Giro d'Italia stages

The Giro pipeline is separate from the TDF pipeline (different scripts, different scrape directory, different supplemental files), but uses the same DB schema and export format.

### Scraping new Giro stages

PCS URLs follow the same pattern as TDF — just substitute `giro-d-italia` for `tour-de-france`:
- Stage results: `https://www.procyclingstats.com/race/giro-d-italia/2026/stage-N`
- GC after stage: `https://www.procyclingstats.com/race/giro-d-italia/2026/stage-N-gc`
- Sprint points: `https://www.procyclingstats.com/race/giro-d-italia/2026/stage-N-points`
- KOM points: `https://www.procyclingstats.com/race/giro-d-italia/2026/stage-N-kom`

Use the save-server + navigate-and-extract methodology described in "Scraping a live/in-progress race from PCS" above. The save server at `pipeline/giro_scrapes/save_server.py` saves to the correct directory. Each `giro_scrapes/stage_N.json` has this format:
```json
{
  "n": 4,
  "info": { "Date": "2026-05-11", "Distance": "138 km", "Start": "Catanzaro", "Finish": "Cosenza", "Won how": "..." },
  "profile_icon": "p3",
  "rows": [ [rnk, gc_pos, gc_lag, bib, age, name, slug, nat, team, team_slug, uci, pnt, bonus, abs_time, gap], ... ],
  "sprint_points": { "rider/slug": 25, ... },
  "kom_points": { "rider/slug": 3, ... }
}
```

**2026 Giro status:** All 21 stages scraped and processed. 184 starters, 152 finishers. Started in Bulgaria (Nessebar), finished in Rome. The race ran May 8–31, 2026.

### Processing scraped Giro stages

After scraping new stage files into `giro_scrapes/`:

```bash
cd pipeline

# 1. If adding to an existing edition, delete it first (ingest_giro.py refuses if edition exists)
python3 -c "
import sqlite3
conn = sqlite3.connect('cycling.db')
eid = conn.execute('SELECT edition_id FROM race_editions WHERE race_id=2 AND year=2026').fetchone()
if eid:
    eid = eid[0]
    conn.execute('DELETE FROM stage_results WHERE stage_id IN (SELECT stage_id FROM stages WHERE edition_id=?)', (eid,))
    conn.execute('DELETE FROM stages WHERE edition_id=?', (eid,))
    conn.execute('DELETE FROM race_editions WHERE edition_id=?', (eid,))
    conn.commit()
    print(f'Deleted edition {eid}')
conn.close()
"

# 2. Rebuild points files from all stage scrapes
python3 build_giro_points.py

# 3. Re-ingest all stages into DB
python3 ingest_giro.py

# 4. Export to frontend
python3 export_gc.py --race giro --year 2026

# 5. Validate
python3 validate_exports.py --year 2026
```

> **Note:** Unlike the TDF pipeline which has `add_stages.py` for incremental stage addition, the Giro pipeline currently requires a full delete-and-reimport cycle when adding new stages. This is simpler but means all `giro_scrapes/stage_N.json` files must be present for a reimport.

---

## Scraping a live/in-progress race from PCS

PCS blocks plain HTTP scraping with a Cloudflare "Just a moment…" challenge (`scrape_pcs_stages.py` no longer works standalone against the live site). Use a real browser instead, navigate to each stage's PCS page, and extract data via injected JavaScript. The page structure below applies identically to both the Tour de France and Giro d'Italia — only the URL path differs (`tour-de-france` vs `giro-d-italia`).

### Efficient multi-stage scraping methodology

**The core constraint is Cloudflare rate-limiting:** after ~2-5 same-origin `fetch()` requests from a page, PCS starts returning Cloudflare challenge pages instead of real content. Navigating to a page in the browser (which passes Cloudflare's JS challenge) resets this counter. The optimal strategy uses a **local save server** + a **self-contained extraction JS snippet** to minimize both Cloudflare blocks and token/context usage.

#### Step 1: Start a local save server

Use `pipeline/giro_scrapes/save_server.py` (or copy it for TDF into `pipeline/scrapes/`). It runs on `localhost:8765` and accepts POSTed JSON, saving each stage to `stage_N.json`.

```bash
cd pipeline/giro_scrapes   # IMPORTANT: run from the correct directory
nohup python3 save_server.py > /dev/null 2>&1 &
echo "PID: $!"
```

**Critical:** The server resolves its save directory from `os.path.dirname(os.path.abspath(__file__))` — the script file's location, not the shell's working directory. But if you copy the script elsewhere or it gets started from a different context (e.g. a temp directory), files will be saved to the wrong place. **Always verify with a test POST** after starting:
```bash
curl -s -X POST http://localhost:8765 -H 'Content-Type: application/json' \
  -d '{"n":99,"rows":[],"info":{},"profile_icon":"p1","sprint_points":{},"kom_points":{}}'
ls stage_99.json && rm stage_99.json   # confirm it landed in the right directory
```

Chrome allows `localhost` HTTP POSTs from HTTPS pages (mixed-content exception), so the browser JS can POST directly from PCS pages.

#### Step 2: Navigate + extract, one stage at a time

For each stage, navigate to the PCS page in the browser (this passes Cloudflare), then run a single JS snippet that:
1. Parses the results table from the already-loaded DOM (no fetch needed for the main page)
2. Fetches the `-points` and `-kom` sub-pages via same-origin `fetch()` (these 2 fetches share the navigation's Cloudflare session and stay under the rate limit)
3. POSTs the combined JSON payload directly to `localhost:8765`

This approach uses **2 tool calls per stage** (navigate + javascript_tool) and **zero context window overhead** for the data itself — the extracted JSON goes straight to disk via the save server, never flowing through the conversation.

The extraction JS is a self-contained IIFE (~3KB minified) that handles:
- Table detection: finds the main results table by looking for `Rnk` + `GC` headers, falling back to any table with 50+ rows
- Rider/team slug extraction from `<a href="/rider/...">` and `<a href="/team/...">` anchors
- Nationality from `<span class="flag XX">` (second CSS class)
- Profile icon from `<span class="icon profile pN">` (class matching `/^p\d$/`)
- Date parsing from page text (`Date: DD Month YYYY`)
- "Won how" text extraction
- Time deduplication (PCS doubles time strings, e.g. `"21:4721:47"` → `"21:47"`)
- Sprint/KOM points parsing from `-points` and `-kom` sub-pages
- Route info (Start/Finish/Distance) passed in via a lookup table in the JS

**The route info lookup table** must be prepared before scraping. Get stage routes from the PCS race route page (e.g. `https://www.procyclingstats.com/race/giro-d-italia/2026/route`). Build a JS object mapping stage number → `{S: "Start City", F: "Finish City", D: "NNN km"}`. This avoids scraping route info from each individual stage page.

#### Step 3: Batch optimization (when Cloudflare cooperates)

After navigating to a stage page, the extraction JS can optionally try to `fetch()` the next 1-2 stages' main pages too (3 fetches per extra stage: main + points + kom). This works for ~2 extra stages before Cloudflare blocks. When a fetch returns a Cloudflare challenge page (detectable by checking for `"Just a moment"` in the response or response length < 5000 chars), skip that stage and navigate to it next.

**Practical cadence:** navigate to a stage, extract it from the DOM + fetch its sub-pages, then try fetching 1-2 more stages. When blocked, navigate to the next unprocessed stage and repeat. This cuts the total tool calls from 2×N to roughly 1.3×N for a 21-stage race.

#### Step 4: Verify and run the pipeline

After all stages are scraped, verify the files are on disk and run the appropriate pipeline:
```bash
# Verify all files exist with correct row counts
for f in stage_{1..21}.json; do
  echo "$f: $(python3 -c "import json; d=json.load(open('$f')); print(f'{len(d[\"rows\"])}r {len(d.get(\"sprint_points\",{}))}sp {len(d.get(\"kom_points\",{}))}km')")"
done

# Then run the pipeline (Giro example — see "Processing scraped Giro stages" section)
python3 build_giro_points.py
# delete existing edition if needed...
python3 ingest_giro.py
python3 export_gc.py --race giro --year 2026
```

### PCS page structure reference

**Normal stage** (`.../stage-N`) — one comprehensive table (`document.querySelectorAll('table')[0]`) with header row `Rnk | GC | Timelag | BIB | H2H | Specialty | Age | Rider | Team | UCI | Pnt | (blank) | Time`. Per-column extraction:
- Rider name/slug: `td.querySelector('a')` inside the `Rider` column (`a.textContent` = name, `new URL(a.href).pathname` = slug).
- Nationality: `td.querySelector('span.flag')`, second CSS class (first is always `flag`).
- Team name/slug: same anchor pattern in the `Team` column.
- **Text-duplication artifact**: the `Time` (and some other) cells contain the value twice concatenated with no separator (e.g. `"21:4721:47"`, `"0:120:12"`) — dedupe by stripping leading commas, then if the resulting string has even length and its first half equals its second half, keep only the first half.
- **Same-time artifact**: gap cells for riders tied in the same group render as `",,0:00"` (literal leading commas) — the dedupe function above strips those too.
- Only the stage winner's `Time` cell is an absolute time; every other rider's `Time` cell is their gap (matches the row format needed for `add_pre1960.py`).

**TTT stage** (e.g. 2026 stage 1) — PCS renders it as ~20+ small per-team tables (unhelpful), **plus one large table with PCS's own pre-computed individual ranks/gaps** — found by checking every `document.querySelectorAll('table')` for one with header `Rnk | BIB | H2H | Specialty | Age | Rider | Team | UCI | (blank) | Time | Time won/lost` (no `GC` column, since it's stage 1). This table exists on both `.../stage-N` and `.../stage-N-gc` — the two are identical, so either page confirms the other. No team-grouped offset arithmetic is needed; just extract this table like a normal stage (rank 1's `Time` cell is absolute, everyone else's is their gap) and leave `gc_pos`/`gc_lag` blank (the stage-1 carry-forward fallback in `add_pre1960.py` fills them in).

**Points classification** (`.../stage-N-points`) — look for `<h4>` headings whose text starts with `"Sprint |"` or equals exactly `"Points at finish"`; the table immediately following each such heading has a `Pnt` column and a `Rider` column with the same anchor structure as above. Sum `Pnt` per rider **across all matching headings on the page** (a rider can score at both an intermediate sprint and the finish) — this sum is that stage's entry in `sprint_points.json`. Ignore any `<h4>KOM Sprint...</h4>` headings on this page — those belong to the KOM classification, not points.

**KOM classification** (`.../stage-N-kom`) — same page layout, but now sum the `Pnt` column under every `<h4>KOM Sprint...</h4>` or `<h4>GPM Sprint...</h4>` heading (there's one per categorized climb on the stage) — this sum is that stage's entry in `kom_points_reconciled.json`. A flat/TTT stage with no climbs has no such headings at all → empty `{}` for that stage index in both files.

### Lessons learned from Giro 2026 scraping

1. **Always verify the save server's target directory** before scraping. The server uses `__file__`-relative paths, but if started from the wrong context (e.g. a temp directory from a previous Claude session), all POSTed data silently goes to the wrong place. A test POST + `ls` check takes 5 seconds and prevents losing 21 stages of work.

2. **Cloudflare rate limits vary by session.** Sometimes you get 5 extra fetches per navigation, sometimes only 1-2. Don't assume a fixed batch size — check for `"Just a moment"` in every fetch response and fall back to navigate-per-stage when blocked.

3. **The save server approach is far more token-efficient than returning data through the conversation.** Each stage's JSON is ~28KB. With 21 stages, that's ~588KB of data that would otherwise flow through context. The save server reduces each stage to a 2-tool-call round trip (navigate + JS extraction with POST) with only a one-line confirmation in the response.

4. **Stage 21 (final stage) often has 0 sprint and 0 KOM points** — this is normal for a processional/criterium-style final stage, not a scraping error.

---

## Key Implementation Notes

### Sprint points scoring system
The green jersey competition existed 1953–present. **1953–1958 used golf scoring** (lower cumulative points = better rank — the Schär system). From 1959 onward, higher = better. The constant `GOLF_SPRINT_YEARS = set(range(1953, 1959))` in `export_gc.py` controls ascending vs descending sort when pre-computing `sprintRank`. The frontend reads the pre-computed rank and never re-derives it, which is critical — re-deriving from points would get 1953–1958 backwards.

### KOM points
KOM competition started 1933. The polka-dot jersey wasn't introduced until 1975. Data for 1933–1938 top-10 was patched from Wikipedia (`patch_kom_wikipedia.py`) because PCS only had top 3–5 for those years.

### 1904 disqualifications
After the race, the top 4 finishers (Garin, Pothier, Cornet-original, Chevalier) were disqualified. Henri Cornet (5th on road) became the official winner. The DB stores DQ'd riders with `gc_rank = NULL` at the last stage (not 999) so the y-axis isn't distorted. Their `finalRank` becomes 9999 in the export, placing them at the bottom of the legend.

### Points-system years (1905–1912)
These Tours were decided by points (fewer = better), not elapsed time. There are no official total elapsed times for these years. `gc_winner_times.json` and `gc_all_times.json` have no entries for 1905–1912. The GC Winner Time and Average Speed panels in All Races Overview show gaps for these years. Wikipedia stage pages only list top-10 per stage, so stage-time summation gives inconsistent results (not used).

### Stage numbering and labels
`stage_number` in the DB matches PCS ordering. Stage 0 = Prologue. Split stages (e.g. 1a/1b) each have their own `stage_number`. Stage labels (`stage_label` in JSON) are computed in `export_gc.py` by grouping stages sharing the same `stage_date`: single stages get sequential numbers, paired stages get "Na"/"Nb" suffixes, prologue gets "P".

### Sprint/KOM point arrays alignment
`sprint_points.json`, `kom_points_reconciled.json`, and `profile_icons.json` all use the same array indexing: index 0 = first stage in DB ordering for that year. This matches the order returned by `SELECT ... FROM stages WHERE edition_id=? ORDER BY stage_number`. The `stage_num_to_idx` dict in `export_gc.py` maps `stage_number → array_index` to handle the alignment.

### DNF riders in classifications
A rider who DNFs before the final stage has their last `byStage` entry used for `finalRank`. Their cumulative points are topped up via a catch-up loop after the main `byStage` loop (some sources store final totals in stage slots after the rider's last actual stage). `sprintRank`/`komRank` at their last entry is also backfilled from the final-stage pre-computed rank tables.

### totalTimeSeconds resolution
Three-tier priority in `export_gc.py`:
1. Wikipedia official time from `gc_all_times.json` (top ~10 riders per year, all years back to 1903)
2. `gc_winner_times.json[year] + gc_gap_seconds` at last stage — covers all riders in modern years with PCS gap data
3. Sum of `finish_time_seconds` per stage — last resort, often incomplete for pre-1960 non-top-10 riders

### Distance data
`wiki_race_distances.json` stores the Wikipedia infobox total distance per year. This is used in `all_races_summary.json` instead of summing DB stage distances, because PCS per-stage distances had 85 errors vs Wikipedia (some 100–200 km off). The per-stage distances in the DB (and shown in the Race Overview) still come from PCS and haven't been individually corrected.

### Difficulty score (Race Overview chart)
Computed client-side: `(vertical_meters² / (distance_km × 1000)) × route_type_multiplier`. Multipliers: P=0.3, TT=0.5, TTT=0.6, F=1.0, H=1.3, M=1.8.

### PCS data notes
- **Sprint points vs. PCS points**: The DB has a `pcs_points` column = PCS prestige ranking system, completely unrelated to the green jersey. Green jersey points come exclusively from `sprint_points.json`.
- **1988 Prelude**: PCS lists 23 entries for 1988 — index 0 is an unofficial "Prélude" stage. The scraper drops index 0 for that year; `profile_icons.json` and `sprint_points.json` do the same.
- **`finish_time_seconds`**: Per-stage time for that individual stage, not cumulative. Often null for non-winning riders in pre-1960 years.

---

## Validation Tools

```bash
cd pipeline

# KOM validation — compares our totals against Wikipedia and bikeraceinfo
python3 validate_kom.py              # all years
python3 validate_kom.py 1982 1985   # specific years
python3 validate_kom.py --summary   # one line per year

# GC validation — per-stage GC leader and top-10 gaps vs bikeraceinfo
python3 validate_gc.py              # all years with BRI data (1960–2005)
python3 validate_gc.py 1982 1986   # specific years
python3 validate_gc.py --summary   # one line per year
```

---

## Data Quality Notes

### KOM data by era
- **1933–1938**: Patched from Wikipedia top-10 via `patch_kom_wikipedia.py`
- **1960–1976**: Old PCS format. Totals consistently 15–35% low vs Wikipedia (PCS missing some climbs)
- **1977–1984, 1986–1987, 1990, 1998–1999**: Modern PCS format, mostly good
- **1985, 1988–1997, 2000, 2003–2004, 2010, 2015, 2018**: Large PCS gaps, 0% match — these years need alternative sources

### Known DB quirks
- **1982 Stage 5** (Orchies→Fontaine-au-Pire, TTT): Cancelled due to farmer protest. Distance is null.
- **1987 Stage 25**: Had wrong `stage_date` (shared with stage 24). Fixed to 1987-07-27.
- **1904**: Post-DQ results patched manually — Garin et al. set to `gc_rank = NULL` at last stage, Cornet set to rank 1. Their Wikipedia times (all 15 finishers) are in `gc_all_times.json`.
- **1939**: A DNF rider (Jaminet, rank 64 mid-race) appears in the last stage with no gap; correctly excluded from "slowest finisher" calculation by `status = 'FINISHED'` filter.
- **1990 Stage 21** (Paris): Was stored as 45.5 km (duplicate of TT distance). Corrected to 182.5 km.
- **1905–1912 gc_gap_seconds**: All zeros at last stage for points-system years — PCS stored intra-stage gaps, not cumulative race time gaps. Not usable for time calculations.

### GC validation results
`validate_gc.py` against bikeraceinfo: 40/42 years pass at ≥70% GC leader match (1960–2005). The 2 failures (1979, 1998) are alignment issues around short TT stages, not real data errors.

---

## File Locations on Eric's Machine

- **Repo:** `~/Documents/GitHub/tdf-analytics/`
- **Database:** `~/Documents/GitHub/tdf-analytics/pipeline/cycling.db` (gitignored — back up separately)
- **Main site repo** (separate): hosts `www.ericshiflet.com`; TDF app lives at `/tdf-analytics/`
