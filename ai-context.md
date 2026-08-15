# Cycling Analytics — AI Context

Interactive cycling analytics app covering the **Tour de France** (all 113 editions, 1903–2026), the **Giro d'Italia** (109 editions with data), and the **Vuelta a España** (80 editions with data, back to 1935). The 2026 Tour de France is **complete** — all 21 stages are in the DB, Pogačar won in **73:56:26** and the slowest finisher was Cees Bol at **+6:22:08** (finalized 2026-08-15; see "Finalizing a completed year" below for what changed). Live at **[ericshiflet.com/tdf-analytics/](https://ericshiflet.com/tdf-analytics/)**.

---

## Project Overview

The app visualizes per-rider performance across every stage of multiple Grand Tour races. Users select a **race** (Tour de France, Giro d'Italia, or Vuelta a España) and **year** via dropdowns, then pick a metric and see a bump chart of every rider's ranking after each stage, with a sidebar legend and hover tooltips.

**Tech stack:**
- Frontend: Vite + TypeScript + D3.js (static site, no framework)
- Data: SQLite → Python export → JSON files bundled by Vite
- Hosting: GitHub Pages, deployed via GitHub Actions on push to `main`

**Multi-race support:** Each race has a canonical **slug** — `tour`, `giro`, `vuelta` — used consistently for the data subdirectory (`src/data/<slug>/gc_by_stage_*.json`), the frontend `RaceId` type, the race dropdown value, and the URL hash segment. The frontend race dropdown is populated from the `RACES` registry in raceRegistry.ts (see "Race registry" below); every view (stage chart, Race Overview, All Races Overview, Riders) works for all three races, and deep links are race-aware (`#giro/2026/stage/gc`). The DB schema is multi-race via the `races` table (race_id=1 TDF, race_id=2 Giro, race_id=3 Vuelta). Editions with data: TDF 113 (1903–2026), Giro 109 (~4,700 riders), Vuelta 80 (1935–2025, ~4,400 riders).

**Jersey colors by race:**
- **TDF**: Yellow = GC, Green = Sprint, Red polka-dot = KOM, White = Youth
- **Giro**: Pink (#E4007C) = GC, Purple (#8B1FA1) = Sprint, Blue (#0083CA) = KOM
- **Vuelta**: Red (#E30613) = GC, Green (#3FA535) = Sprint, White with blue (#0057B8) polka-dots = KOM, White = Youth

The frontend is race-aware via the `RACES` registry in raceRegistry.ts (see "Race registry" below): jersey icon colors, career-chart colors, jersey tooltip labels, war bands, and the youth-button visibility all come from each race's config entry.

**Four views:**

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

4. **Riders** — a searchable/filterable grid of every rider (current race only: name search, year/team/nationality filters, GC/Sprint/KOM/Youth jersey-win filters), and a per-rider detail page. The detail page is **cross-race** (not filtered to the current race): it shows every race the rider has results in, with toggle buttons to show/hide each race and each classification (GC/Sprint/KOM) independently — see "Rider detail chart" below.

---

## Recent structural changes (July 2026) — read before assuming older patterns

A cleanup + multi-race restructuring pass landed 2026-07-17. If you've seen older descriptions of this codebase, these supersede them:

**Data safety (pipeline):**
- All raw scraped data (`pipeline/tdf_*_full.json`, `scrapes/`, `giro_scrapes/`, `vuelta_scrapes/`) is now **tracked in git** — it used to be gitignored with the only copy on one machine.
- `cycling.db` is NOT regenerable; back it up with `python3 pipeline/db_backup.py` (rotating snapshots in `pipeline/db_backups/`). `add_stages.py` snapshots automatically before its destructive delete.
- `ingest_race.py --race {giro,vuelta}` (merged from `ingest_giro.py`/`ingest_vuelta.py` 2026-07-18 — see below): `--dry-run` is truly read-only (it used to delete the edition!), delete+reinsert is atomic, `vertical_meters`/`profile_score` are preserved across re-ingest, and a bare no-arg run is refused without `--all`.
- All TDF-only scripts filter `race_editions` by the TDF race_id (year-only lookups could silently hit a Giro/Vuelta edition of the same year).
- `build_db.py` was deleted (stale, dangerous). `validate_exports.py` validates **all three races** (302 files).
- Exports write compact JSON (`separators=(",", ":")`) — ~10% smaller payloads.

**Multi-race frontend (see "Race registry" and "Hash routing" sections):**
- Canonical race slugs: `tour`, `giro`, `vuelta` (the frontend's old `"tdf"` id is gone).
- The `RACES` registry in raceRegistry.ts is the single source of truth for per-race name, colors, jerseys, war bands, capabilities. Adding a race = one registry entry + a `src/data/<slug>/` directory (wildcard globs auto-discover the files).
- URL hashes are race-aware: `#giro/2026/stage/gc`, `#vuelta/allraces`, `#giro/riders/<slug>`; bare hashes (no race segment) mean `tour`, so all old links still work.

**Pipeline consolidation (2026-07-18):** the near-duplicate per-race pipeline scripts have been merged into slug-parameterized versions in four steps:
- `ingest_giro.py`/`ingest_vuelta.py` → `ingest_race.py --race {giro,vuelta}`, backed by a new `pipeline/race_common.py` module holding shared PCS-parsing helpers (`parse_time_to_seconds`, `parse_int`, `parse_bonus_seconds`, `detect_route_type`, `parse_year_args`, `COUNTRY_NAMES`) and a small per-race `RaceInfo` registry (DB name/country, scrapes dirname, Giro's legacy flat-2026-fallback flag). Race-specific behavior (that fallback, and Giro's automatic `fix_giro_rider_names.py` post-ingest pass) is now an explicit `race == "giro"` branch instead of being duplicated wholesale.
- `export_riders_index.py` (TDF-only) / `export_giro_riders_index.py` / `export_vuelta_riders_index.py` → one `export_riders_index.py --race {tdf,giro,vuelta}` (default `tdf`, unchanged invocation for existing callers). The youth/white-jersey DB lookup (`classification_standings`) only runs for TDF — Giro/Vuelta never tracked it, matching the frontend's `hasYouth` flag.
- `export_giro_races_summary.py` / `export_vuelta_races_summary.py` → one `export_race_summary.py --race {giro,vuelta}`. TDF's own summary (`export_all_races_summary.py`) is architecturally separate (predates these two, writes to the top-level `data/` dir instead of `data/tour/`) and is intentionally NOT covered — folding it in is tracked as item (c) below.
- `race_common.py` also gained `resolve_race_arg()` (a `{tdf,giro,vuelta} -> (db_name, data_subdir)` lookup) for the two export scripts above; it's separate from the ingest-only `RACES` registry since TDF's ingest mechanism doesn't fit that shape.

All four merges were verified byte-identical to the scripts they replaced before deletion: the ingest merge via an in-process run against scratch DB copies (2,120 Giro stages + 1,644 Vuelta stages + 8,973 rider names matched exactly; the real `cycling.db` was never opened, only redirected copies), and the two export merges via a real run + `git diff` showing zero changes to the committed `riders_index.json`/`all_races_summary.json` output files.

**Planned direction:** ~~one-day classics will be added as races with a single stage~~ — **done 2026-08-13**, see "One-day classics" below. Item (a), capability flags in the `RACES` registry, landed with it; there are no open items left in this note. (b) ~~consolidating the per-race ingest/export scripts~~ — done 2026-07-18, see above. (c) ~~moving TDF's unprefixed supplemental files into a per-race layout~~ — done 2026-07-31 (after the 2026 Tour ended, as planned): the frontend side (`export_all_races_summary.py`'s output) already wrote to `cycling-app/src/data/tour/`, matching Giro/Vuelta; the actual gap was in `pipeline/`, where TDF's per-stage supplement files predated the `{race}_` prefix convention. `sprint_points.json` → `tour_sprint_points.json`, `kom_points.json` → `tour_kom_points.json`, `kom_points_reconciled.json` → `tour_kom_points_reconciled.json`, `gc_winner_times.json` → `tour_gc_winner_times.json`, `all_races_summary_overrides.json` → `tour_all_races_summary_overrides.json`. `export_gc.py` also collapsed its two separate code paths (hardcoded TDF constants vs. a `race_subdir`-parameterized override for Giro/Vuelta) into one `resolve_supplement_paths()` lookup used by all three races. TDF-only files with no Giro/Vuelta sibling (`wiki_race_distances.json`, `gc_all_times.json`, `kom_totals.json`, `kom_reconcile_report.json`, `profile_icons.json`) were left unprefixed on purpose — there's no naming collision to resolve.

---

## Data integrity work (August 2026) — read before touching scrape/ingest code

A long correctness pass landed 2026-08-08 → 08-11. It found and fixed defects affecting
more than half the database. The invariants below are the durable output; violating any
of them is how the data got broken in the first place.

### The five rules

1. **A stage's identity is `stages.source_slug`, never `stage_number`.** PCS letters a
   split day `stage-3a`/`stage-3b`; the DB numbers contiguously, so the two diverge
   permanently after the first split (Tour 1981 `stage_number` 5 **is** PCS `stage-4`).
   Never rebuild a URL as `stage-{n}`: on a split edition it fetches a different stage, or
   returns HTTP 500 forever. All 6,224 slugs are now confirmed against PCS's own
   per-edition stage list, so the DB is the reliable map — read it. This mistake recurred
   *three separate times* during this pass alone.

2. **PCS prints the time and the gap in ONE cell** — `"4:15:284:15:28"` for the winner,
   `",,0:18"` for a rider 18s down. So the winner's row parses with `abs_time` and `gap`
   set to the same value. `finish = winner + gap` therefore doubled the winning time on
   **3,377 rows / 3,354 stages** (Giro 1914's Gremo at 34h29m for a 17h13m ride). The
   winner's row takes `winner_seconds` directly and his gap is zeroed; `winner_seconds` is
   set once and never overwritten, because a promoted co-winner after a DQ is also rank 1
   with a value in that cell (2008 TDF st4: Kirchen, 18s back).

3. **`",,"` means "same as the rider above".** The parser handles it correctly today, but
   ~1,300 Vuelta scrape *files* on disk predated that fix and recorded `+0:00` for riders
   who were minutes down. Re-scraped 2026-08-11. **Careful with the detector:** gaps
   never decrease in an old result, but they legitimately do in a modern one — a rider
   caught in a crash inside the last 3 km gets the group's time while still classified
   behind riders who lost time. So a "gap violation" is only actionable if a *fresh*
   scrape has fewer of them. Do not add this as a `validate_db` check; it would warn on 70
   clean Tour stages forever.

4. **Re-ingest rebuilds an edition from its scrape FILES**, so anything living only in the
   DB dies unless carried across. This has cost elevation, patched distances, the
   cancelled flag, `source_slug`, and three whole stages (Vuelta 1941 st20/st22, 1968
   st20 — restored from backup). `ingest_race.py` preserves the first four and now
   **refuses** to drop a stage the incoming files do not cover, requiring `--allow-drop`.
   A renumbering repair legitimately shrinks the file set and must opt in.

5. **PCS's stage HEADLINE carries what the info panel omits.** `Stage 23 (ITT) (Final) »
   Versailles › Paris (54km)` holds the distance when the panel says "Distance: 0 km",
   and an explicit `(ITT)`/`(TTT)` marker when "Won how" is empty (which is why 44 time
   trials were stored as flat road stages). `race_common.parse_stage_title` /
   `apply_stage_title`; all three scrapers call it. Scope both to the headline block — a
   road stage's page links its siblings ("Stage 22b (ITT)") and carries other stages'
   distances. **It is not infallible:** the 1986 TDF stage-23 headline repeats stage 16's
   246.5 km, so `patch_missing_distances.py` refuses a value another stage already holds.

### Provenance

`data_provenance` records where every stored fact came from at (entity, entity_id, field)
granularity — `pcs`, `wikipedia`, `bikeraceinfo`, `manual`, `derived`, `unknown` — with
the exact URL in `source_ref`. **Every writer must call `record_provenance()`.** A source
of `unknown` means "patched by something nobody recorded" and is a real signal: it is how
six Paris finales carrying the *previous* stage's distance were found. `entity_id` is
polymorphic, so there is no FK and `ingest_race.py` deletes an edition's rows itself.

### Tools added (all with `--dry-run`, all guarded)

| script | what it does |
|---|---|
| `validate_db.py` | DB-level integrity; ERROR exits 1, WARN = known upstream limit |
| `audit_stage_counts.py` | reconciles editions against PCS's stage list by route; `--fix-slugs`, `--confirm-slugs` |
| `patch_missing_distances.py` | fills 0 km distances from the headline; refuses a neighbour's value |
| `fix_tt_route_types.py` | reclassifies TTs mis-stored as flat; `ADJUDICATED_NOT_TT` holds 34 Eric ruled on |
| `reingest_tdf_stage.py --from-pcs` | replaces one TDF stage's results; the only route for 1960+ (no `tdf_YEAR_full.json`) |
| `derive_ttt_rider_times.py` | team time → each rider, for TTTs where PCS's rider tables are empty |
| `rescrape_ditto_stages.py` | re-scrapes stale-ditto files; rewrites only on strictly fewer violations |
| `fix_doubled_winner_times.py` | the 3,377-row winner repair (arithmetic, no re-scrape) |
| `backfill_stage_metadata.py` | fills NULL route/date from PCS's info panel |

### State as of 2026-08-11

`validate_db` 0 errors / 3 warnings · `validate_exports` 302 files, 0 errors ·
**142 tests** passing (`python3 -m unittest discover -p 'test_*.py'`, runs in CI).
Every stage has a route, a date, a distance and a confirmed `source_slug`; 0 derived
slugs remain. Every Tour TTT has per-rider results. Elevation is the one field with a
real remaining gap: PCS never published it for the Paris finales, so 2001–2010 are
reconstructed (see the next section) and ~25 stages since 1990 are still NULL.

**Known-open, deliberately not fixed:** 36 stages with two rank-1 finishers (doping DQs
where PCS lists both the stripped and the promoted rider — how to model a stripped win is
Eric's call, do not guess); 14 stages with no finishing positions (neutralised or
abandoned mid-race, plus three 1980s TTTs where PCS's rider tables are empty); 17 editions
with a sparse final stage. Test new work with **mutation checks** — substitute the
original bug back and confirm the test fails; that caught two blind spots in this pass.

---

## One-day classics (August 2026)

Eleven monuments/classics, **1892–2026**, added 2026-08-13. In the DB they are
**11 independent races** (`races.race_type='one_day'`, race_id 4–14, one stage per
edition). The frontend shows **one** race, `classics` — "One-day Classics" — whose
"stages" are those races. That aggregation happens only at export time.

| slug | display | short | | slug | display | short |
|---|---|---|---|---|---|---|
| `omloop-het-nieuwsblad` | Omloop Het Nieuwsblad | OHN | | `amstel-gold-race` | Amstel Gold Race | AGR |
| `strade-bianche` | Strade Bianche | SB | | `la-fleche-wallonne` | La Flèche Wallonne | FW |
| `milano-sanremo` | Milan–San Remo | MSR | | `liege-bastogne-liege` | Liège–Bastogne–Liège | LBL |
| `gent-wevelgem` | Gent–Wevelgem | GW | | `san-sebastian` | Clásica de San Sebastián | CSS |
| `ronde-van-vlaanderen` | Tour of Flanders | RVV | | `il-lombardia` | Il Lombardia | IL |
| `paris-roubaix` | Paris–Roubaix | PR | | | | |

**968 race-years · 102,261 results · 11,934 riders · 5 cancelled.**

Coverage is bounded by each race's founding year, established from PCS returning
**HTTP 500** for editions that never happened — not from assumption:

| race | first edition present | note |
|---|---|---|
| Liège–Bastogne–Liège | **1892** | the oldest; ran irregularly before WWI |
| Paris–Roubaix | **1896** | |
| Il Lombardia | **1905** | |
| Milan–San Remo | **1907** | |
| Tour of Flanders | **1913** | ran through WWII |
| Gent–Wevelgem | **1934** | |
| La Flèche Wallonne | **1936** | |
| Omloop Het Volk | **1945** | |
| Amstel Gold Race | **1966** | |
| Clásica de San Sebastián | **1981** | |
| Strade Bianche | **2007** | |


Cancellations found: 2020 lost Paris–Roubaix, Amstel Gold and San Sebastián to
COVID; **Omloop Het Volk was also cancelled in 1986 and 2004**.

**2026 is an IN-PROGRESS season** — 10 of 11 races are in, and **Il Lombardia
(scheduled 2026-10-10) has not been run**. It is deliberately *absent* from the
season rather than stored as cancelled, so 2026 shows 10 race columns. Re-run the
capture snippet and `ingest_classics.py --year 2026` after it happens; ingest is
atomic per race-year, so re-running is safe and adds the race without duplicating
anything.

### A no-results page means THREE different things

This has now caused one real data-fabrication incident and one near-miss, so the
parser distinguishes all three cases and the capture snippet records the HTTP
status precisely so it can:

| signal | meaning | handling |
|---|---|---|
| HTTP 500 | the edition never existed (Strade Bianche pre-2007) | skipped, no file |
| 200 + date in the **past** | genuinely cancelled (Omloop 1986, Roubaix 2020) | stored with `cancelled=1` |
| 200 + date in the **future** | not run yet (Lombardia 2026) | skipped, no file |

Without the date check, an in-progress season silently records every remaining
race as a cancellation.

### The rules that matter here

1. **Stages are ordered by `stage_date`, never a fixed calendar.** COVID moved
   **Il Lombardia to August 2020**, ahead of Flèche and Liège, and pushed
   Paris–Roubaix to October in both 2020 and 2021. A hardcoded order renders those
   seasons wrong; date ordering gets them right for free.

2. **`finalRank` is the rider's BEST finish of the season**, not their last. It drives
   legend order and Top 10/20. "Their placing at Lombardia" would be meaningless for
   ranking a season. Consequence: **ties are normal** — 2021 has nine riders at #1
   (the nine winners of its eleven races), so `validate_exports.py` skips its
   duplicate-`finalRank` check for any race in `AGGREGATE_FINAL_RANK`. Leaving it on
   emitted 325 warnings on clean data.

3. **`totalTimeSeconds` is null** and the GC Time toggle is hidden — a season of
   unrelated races has no total time.

4. **Cancelled races are ingested, not dropped** (`stages.cancelled=1`, planned date
   and distance, no results). 2020 lost Paris–Roubaix, Amstel Gold and San Sebastián.
   They keep their calendar slot, draw muted in the Race Overview, and are excluded
   from its distance/elevation totals — which also fixed a **pre-existing bug where
   cancelled Grand Tour stages were counted** in those totals.

5. **PCS slugs are not guessable.** San Sebastián is `san-sebastian`, **not**
   `clasica-san-sebastian` — the latter 500s. A 500 page has no results table and so
   looks *exactly* like a cancelled race to a parser: it silently produced six
   fabricated cancellations before Eric spotted it. `parse_classics_bundle.py` now
   distinguishes an HTTP error from a genuine no-results page. **Verify a slug
   against a real URL before adding one.**

6. **`route_type` is derived, not scraped** — `race_common.classic_route_type()` bands
   PCS's own ProfileScore (<60 F, ≤150 H, else M), recorded as `SOURCE_DERIVED`. Raw
   m/km does not separate these honestly; ProfileScore puts Roubaix at 15,
   Gent–Wevelgem 33, Flanders 93, Liège 182, Lombardia 260.

### Pipeline

```
DevTools snippet → ~/Downloads/classics_*.txt
       ↓  parse_classics_bundle.py
classics_scrapes/<race>/<year>.json      (+ .raw.txt captures, tracked in git)
       ↓  ingest_classics.py             (--dry-run; atomic per race-year re-ingest)
   cycling.db                            (11 races, race_type='one_day')
       ↓  export_classics.py
cycling-app/src/data/classics/gc_by_stage_YEAR.json + riders_index.json
```

`export_classics.py` is deliberately **separate from `export_gc.py`**, which is built
around "one edition = one race with N stages". The classics invert that (N editions of
N races = one displayed season), so sharing the code would contort both. There is no
`all_races_summary.json` and never will be.

### Data quality by era (measured — read before "fixing" a perceived gap)

**Finishing times are 100% complete for every finisher in every era measured**
(1946 onward). What degrades going back is *team* attribution and field size:

Team attribution is the weak field; **bikeraceinfo has filled 6,254 gaps** (see
below). Coverage by decade after that fill: 1890s 46%, 1900s 27%, 1910s 44%,
1920s 34%, 1930s 36%, 1940s 17%, 1950s 32%, 1960s 31%, 1970s 72%, 1980s 96%,
1990s+ 99–100%. What remains missing is concentrated in the five non-Monument
races, which bikeraceinfo only stubs pre-1990.

**Field size shrinks hard going back**: 51 race-years before 1946 carry fewer
than 25 riders — PCS stores a top-10/20 for the oldest editions, not a full
result. Ages are 83% present pre-1946 (100% after).

Field size shrinks too: 1946–1969 races carry mostly **25–75 riders** against ~175
today, and only 344 non-finishers across 12,331 rows — PCS stores a partial field
for old races, not the full result. Bib coverage is 4% in that era (20% in the 70s/80s),
which is the other reason the classics table ignores bibs entirely.

Sparse bibs no longer matter for the classics: the by-Stage Table **hides the bib
column and groups by team** for any race with `stagesAreRaces` (see below). Stage
races are untouched and still order by bib.

The 1970s/80s calendar also differs from the modern one, which the date ordering
handles for free — Amstel Gold ran **29 March 1975, before** the Tour of Flanders
on 6 April, and Gent–Wevelgem sat midweek between Flanders and Roubaix.

### Era differences found scraping 1990–2019

The 1990s/2000s pages are **not** shaped like the modern ones. Three things a
future scrape must keep handling:

- **Columns vary by era.** 200 of 313 historical race-years have **no `UCI`
  column** at all, and Gent–Wevelgem 2005 has **no `Time` column** — those
  riders have ranks but no times, which is a source limitation, not a parse
  failure. (Gent–Wevelgem 2005 has since been filled from bikeraceinfo — see
  "Filling times PCS omits" below.) Read columns **by header name with an
  explicit absent-check**; the
  obvious `td[headers.indexOf('UCI')]` silently becomes `td[-1]` and maps to
  the wrong cell. The capture snippet emits a `##HEADERS` line per race so
  this stays auditable.
- **Bib numbers are only unique WITHIN a team**, not across the race. Flanders
  2010 has AG2R and Liquigas both numbered 11–17, every rider correctly
  attached to their own team. A global bib-uniqueness check flags 8 whole-team
  blocks of pure noise and would bury a real name-swap; `parse_classics_bundle`
  therefore keys on **(team, bib)**.
- **Races have founding years.** Strade Bianche returns **HTTP 500** for
  1990–2006 because it began in 2007. That is "did not exist", not "cancelled" —
  which is only distinguishable because the snippet records the HTTP status.
  A 500 page and a cancelled race look identical otherwise.
- **Omloop was "Omloop Het Volk" until 2009** (the 2004 H1 reads "59th Omloop
  Het Volk"). PCS keeps one slug across the rename, so we store one display
  name for all years. Its **2004 and 1986 editions were genuinely cancelled** —
  real 200 pages, dated, with no results.
- **Omloop was NOT HELD in 1960** — a dispute between the race organisers and the
  sport's governing body (Eric, 2026-08-14). PCS reflects this with a reproducible
  HTTP 500 while every other year 1946–2026 resolves, so recording nothing is
  correct: there is no edition to store, and it is not a cancellation of a race
  that took place.

### National teams: a Grand Tour thing, NOT a classics thing

Worth stating because it looks like it should explain the sparse pre-1970 team
data, and it does not. Checked against this DB:

- **The Tour de France really did run national teams**: France and Belgium
  1930–1961, Italy/Spain 1930–1968, Netherlands 1936–1968, Switzerland 1932–1957,
  Germany 1930–1938, Luxembourg 1937–1953 — thousands of results each.
- **The classics never did.** Every team in the 1946–1969 classics is commercial
  (Faema, Bertin–Wolber, Mercier–BP–Hutchinson, Peugeot–BP–Michelin, Salvarani,
  Alcyon–Dunlop, Bic). The sole national squad in 81 years is **Italy at Strade
  Bianche 2015** — six riders on a wildcard invite, `team/italy-2015`.

So the missing pre-1970 team attribution is **genuinely absent PCS data**, not
riders racing under a national banner. Do not relabel it as nationality on that
theory. Rider **nationality**, by contrast, is **100% populated in every decade**,
which makes it the only viable fallback grouping if one is ever wanted.

### by-Stage Table for an aggregate race

Gated on `RaceConfig.stagesAreRaces`, so only the classics get it:

- **No bib column.** Bibs are reassigned every race and two teams can share a
  range (Flanders 2010: AG2R and Liquigas both 11–17), so a bib is neither a
  stable identity nor a sensible ordering across a season.
- **Riders are grouped into one contiguous block per team**, ordered like a
  **medal table**: most wins first, ties broken by most 2nd places, then 3rd, and
  so on down. Within a team, the best finisher leads, then alphabetical. A team
  with no finishers sorts last among equals by name; riders with no team go last.
- `buildTeamOrder()` resolves the ordering **once** and hands each rider an
  integer key — comparing full count vectors inside the rider comparator would be
  O(maxRank) per comparison.
- DNF/DNS contribute nothing: a team is ranked on what it achieved, not on how
  many riders it entered.
- **The sticky rider column's `left` must equal the total width of the sticky
  columns before it** — team (22 px) and/or bib (52 px). All four combinations are
  spelled out in CSS, and getting one wrong does more than misalign: sticky SHIFTS
  the column to that offset, and being opaque with `z-index: 1` it then **paints
  over the first race column**. That is how 1892-1894 Liege-Bastogne-Liege — the
  only three seasons where no rider has a known team, so neither a team nor a bib
  column exists — rendered as a table that appeared to contain no races at all,
  while the DOM was perfectly correct. **jsdom does no layout, so verify-views
  cannot catch this class of bug**; it asserts the DOM and class combination only.
  Any future column change here must revisit those offsets in a real browser.

**Team banding** (all races, not just the classics): every other contiguous team
block takes a faint wash so a team's riders read as one group. Two CSS variables,
because the rider/team columns are **sticky and must stay opaque** — a translucent
band would let scrolled cells show through them. Placement cells are untouched:
they set their heat colour *inline*, and an inline style always beats a stylesheet
rule, so the band lands only on the empty cells. Banding is keyed on the team
**boundary**, not on team identity, so a trailing run of team-less riders reads as
one block instead of strobing once per rider.

2021 is the worked example, and shows the tiebreak doing real work at two levels:
Quick Step (3 wins) → Jumbo-Visma (2 wins, 1 second) → UAE (2 wins, 0 seconds) →
Alpecin (1/1/1) → Bahrain (1/1/0). Without the flag the same table fragments 40
teams into **620 blocks**, which is what the old bib ordering was doing.

### Race History view (small multiples)

`export_classics_history.py` -> `race_history.json` -> `views/classicsHistory.ts`.
One panel per race across its own lifetime (winning speed / distance / finishers),
sharing the cross-year nav slot with the Grand Tours' All Years Summary — the
button relabels to "Race History" via `hasRaceHistory`.

**Faceted, not eleven overlaid lines.** Categorical color tops out at eight hues
before adjacent series stop being reliably distinguishable, and there are eleven
races. Faceting also removes the need for a categorical palette entirely: each
panel is a single series, so the panel title carries identity and one accent
serves all eleven. That accent (`#3987e5`) was validated against this app's
`#0f1115` surface — inside the L 0.48–0.67 band, chroma floor, ≥3:1 contrast.

Axes are SHARED across panels; comparing races to each other is the whole point,
and a per-panel axis would quietly prevent it. Lines break across gaps of >3
years so the war years read as holes rather than a straight line implying racing
continued.

**Speed is derived** (distance ÷ winning time), not read from PCS's "Avg. speed
winner" field, which is absent for most historical editions. The exporter
**rejects and reports** any speed outside 15–60 km/h rather than publishing it:
Milan–San Remo 1915 was the case that proved this, where PCS serves "3:18",
parsing to 198 seconds and charting at 5,254 km/h. A rejection means the DB needs
fixing, not that the guard did its job.

Known upstream oddities this view surfaces, left as-is:
- **Milan–San Remo 2013, 121 km** — PCS's own figure, but its 5:37:20 winning
  time implies 21.5 km/h. Distance and time disagree at source. That edition was
  genuinely disrupted by a snowstorm, so an outlier is arguably honest.
- **Gent–Wevelgem 1934/35, 120 km** — NOT an error. It began as a short regional
  race; the chart showing it grow is the point.

### Filling team attribution PCS omits (bikeraceinfo)

`scrape_bikeraceinfo_teams.py` → `patch_classics_teams.py` fill rider→team where
PCS has none. **4,370 teams filled** across 1946–1989:

| decade | before | after |
|---|---|---|
| 1940s | 2% | **31%** |
| 1950s | 32% | **53%** |
| 1960s | 31% | **74%** |
| 1970s | 72% | **88%** |
| 1980s | 96% | 97% |

**bikeraceinfo is plain-HTTP scriptable — no Cloudflare, unlike PCS.** So this is
an ordinary Python script with an on-disk page cache; no browser, no snippet, no
data through the conversation. Be polite (`BRI_DELAY`, default 1s).

What it has, and doesn't:

- **Full fields only for the five Monuments** (Milan–San Remo, Flanders,
  Paris–Roubaix, Liège, Lombardia). Omloop, Gent–Wevelgem, Flèche, Amstel and
  San Sebastián are **summary-only stubs** pre-1990 — winner and distance, no
  results list. That is the whole reason the gains above stop short of 100%.
- Year pages are **discovered from each race's index**, never assembled from a
  guessed pattern: the year is a suffix (`pr1955`), an infix
  (`1966-Amstel-Gold-Race`) or a prefix (`1955-liege-bastogne-liege`).
- Founding years it exposes **independently confirm the ones derived from PCS
  500s** — Amstel 1966, San Sebastián 1981 — and it goes back further than we
  ingest (Liège 1892, Roubaix 1896, Lombardia 1905).

Three traps found the hard way, all of which would have corrupted data silently:

1. **One `<li>` can hold SEVERAL riders.** A group finishing together is packed
   into a single item — Il Lombardia 1949 item 20 is five riders — so list
   position is NOT rank, and using it shifts every rank after the packed item.
   `split_entries()` splits on the time terminator (`s.t.`, `@ 5min 43sec`).
2. **Match on NAME, never on rank.** Even split correctly, the two sources order
   an `s.t.` bunch differently (PCS has Pagliazzi 20th at Lombardia 1949,
   bikeraceinfo 24th — both honest). Rank-matching mismatches across every tied
   group. Names are compared accent-folded, order-insensitive, and allow a
   strict subset (nicknames, dropped middle names) but nothing looser.
3. **`?` is a placeholder team**, and would otherwise create a DB team named
   "?". Filtered exactly — several REAL teams of this era have very short names
   (**Z**, Greg LeMond's squad; RM; BP), so any filter-by-length heuristic
   would discard genuine data.

Only 1 ambiguity survived 383 race-years: Milan–San Remo 1966 Gilbert Desmet,
where bikeraceinfo spells one team both "Romeo-Smiths" and "Romeo-Smoths".
Skipped rather than guessed.

### Filling times PCS omits

`classics_bri_times.json` (bikeraceinfo.com) + `patch_classics_times.py` fill a
race-year where PCS publishes no Time column. Applied to **Gent–Wevelgem 2005**:
79 of 80 finishers, winner 4:53:07 over 208 km, which recomputes to **42.577 km/h**
against bikeraceinfo's published 42.577 — an independent check that the
transcription is right.

The script's design is the point, because aligning two sources is where data gets
silently corrupted:

- **Every rank is verified by name before anything is written**, and a single
  mismatch aborts the whole race. bikeraceinfo prints "Firstname Lastname", PCS
  stores "Lastname Firstname", so matching is by accent-folded token *set*.
- **Spelling differences are explicit reviewed `aliases`, not fuzzy matching** —
  dropped Spanish second surnames (`Yus Querejeta`→`Yus`), `Krauß`/`Kraus`,
  `Jeff`/`Jeffry`, and a bikeraceinfo typo (`Speybrock`/`Speybroeck`). A fuzzy
  matcher would have swallowed the real conflict below.
- **`disputed` ranks are skipped, never guessed** — and `corrections` records where
  a third source later settled one. Gent–Wevelgem 2005 rank 33 is the worked
  example: bikeraceinfo named Bram Tankink @31sec while PCS had Guido Trenti (both
  Quick Step, PCS listing Tankink as DNF). **cyclingflash.com resolved it** —
  `33 Guido Trenti Quick Step - Innergetic + 31`, no Tankink anywhere — so
  bikeraceinfo simply had the wrong name against the right gap, which all three
  sources agree is 31sec. Two sources against one; Eric confirmed. All 80
  finishers now have times.
  **cyclingflash.com is a useful third source for classics results**, though it
  sits behind a Cloudflare bot check the in-app browser does not clear (real
  Chrome does).
- Only rank 1 gets an absolute time; **nothing already holding a time is
  overwritten**, keyed on `finish_time_seconds` alone (`gap_seconds` is 0 for every
  winner by construction and is not evidence of a recorded time).

### Known-open

- **Duplicate ranks in 13 race-years** — PCS itself prints one position twice
  (verified directly on the 2021 Paris–Roubaix page: rank 83 for both Stannard and
  Sajnok). **Every 2021 race has one**, which looks systematic. Same class as the 36
  two-rank-1 stages: how to model it is Eric's call, do not guess.
- **Same-team bib collisions in 13 race-years** (Amstel 2022 bib 176, Strade Bianche
  2013 bib 96, …), clustered in 2013–2018. Each is two teammates sharing a bib, both
  DNF, so no rank or time is affected. Not the name-swap artifact: there the bib
  stays put and the *name* moves, whereas here the bib itself is duplicated.
  Upstream PCS collisions; never rename.
- **UCI points deductions** render inside the points cell across embedded newlines
  (Paris–Roubaix 2023, Rex Laurenz: `160 … -25`), splitting a row mid-record.
  `parse_classics_bundle.py` joins continuation lines; ingest keeps the awarded
  figure and ignores the annotation rather than guessing the net.
- Coverage is 1892–2026 (the full history of every race). Going further back is a scrape-scope decision, not a code
  change (Liège dates to 1892, Roubaix 1896), but re-check the column-shape and
  completeness assumptions above first — 1970–1989 held up well, older editions may
  not.
- `classics/riders_index.json` is **1.56 MB (391 KB gzipped)** — larger than the three
  Grand Tour indexes combined, because it carries every rider's per-race breakdown.
  It is lazy-loaded, so first paint is unaffected, but `drawRiderDetail` awaits all
  four indexes in parallel. Dropping the redundant team index from each constituent
  entry saved 87 KB gzipped; further shrinking would mean restructuring `m`.
  **At 1892–2026 it is 2.93 MB / 719 KB gzipped** — bigger than the three Grand
  Tour indexes COMBINED (554 KB), and a rider-detail page pulls all four. This is
  now the clearest cost of extending coverage and the first thing to revisit if it
  grows again.

---

## Derived elevation for the Paris finales (August 2026)

PCS genuinely leaves `Vertical meters` **blank** on most Tour finales into Paris — the
stage page shows an empty field, alongside an empty Parcours type / ProfileScore and
`Distance: 0 km`. Those NULLs are faithful; there is nothing to scrape and no public GPX
exists. **2001–2010 are now filled by reconstruction** via
`patch_paris_finale_elevation.py`, every value recorded as `SOURCE_DERIVED` so a future
bulk re-scrape can tell them from scraped data. ~25 stages since 1990 still lack elevation.

| year | stage | km | m | m/km |    | year | stage | km | m | m/km |
|---|---|---|---|---|---|---|---|---|---|---|
| 2001 | 20 | 160.5 | 980 | 6.1 |  | 2006 | 20 | 154.5 | 1090 | 7.1 |
| 2002 | 20 | 140.0 | 585 | 4.2 |  | 2007 | 20 | 146.0 | 885 | 6.1 |
| 2003 | 20 | 152.0 | 730 | 4.8 |  | 2008 | 21 | 143.0 | 900 | 6.3 |
| 2004 | 20 | 163.0 | 725 | 4.4 |  | 2009 | 21 | 164.0 | 650 | 4.0 |
| 2005 | **21** | 144.0 | 855 | 5.9 |  | 2010 | 20 | 102.5 | 660 | 6.4 |

### Method

1. Trace the ASO road-book map onto OSM roads with **BRouter**, using the towns and spot
   altitudes printed on the ASO profile as control points. Geocode town names through
   Nominatim rather than hand-guessing coordinates.
2. Sample **EU-DEM 25 m every 50 m** along the routed line (opentopodata).
3. Sum positive deltas after a **250 m moving average**. Calibrated against 2010 stage 19
   (Bordeaux–Pauillac ITT), the nearest stage with a PCS elevation and an unambiguous
   route: it reproduces PCS's 167 m as 173 m (ratio 1.04). Raw unfiltered sums overshoot
   by ~70%.
4. Add the Champs-Élysées circuit **separately** — it cannot be measured from the DEM,
   because central Paris is a *surface* model that puts Étoile at 66–74 m against a true
   ~62 m. Anchor it on **2011 stage 21**, whose 436 m is known: steps 1–3 on its run-in
   give 266 m, leaving 170 m for its eight laps, ≈**22 m per lap**.

Expressing each stage as `436 + (its run-in − 266)` cancels most systematic bias, since
the laps are common to every stage. Residual uncertainty ≈ ±5% where the profile anchors
well, worse where it does not.

### Traps, all found the hard way

- **Use FEW waypoints.** Too many make BRouter zigzag and inflate distance 15–20%.
  Bordeaux–Pauillac routed from 2 points came out 49.8 km (actual 52); from 13 points,
  73.5 km.
- **Never assume eight laps.** Read the count *and length* off each profile's passage
  marks. 2002 ran **ten** (first "Haut des Champs" at km 81 of 144); 2003 ran **nine**
  plus a one-off 29 km centenary loop via the Hôtel de Ville and Place de la Nation;
  2004 and 2011 ran eight *shorter* 6.125 km laps. At ~22 m each, a miscount is worth
  20–90 m.
- **Check the stage number.** The finale is s20 some years, s21 others. 2005 s20 is a
  *different* stage already carrying a real PCS 806 m.
- **Check the start altitude against the DEM.** ASO's printed town altitudes are loose
  (Longjumeau 70 m vs a real 48 m; Concorde 45 m vs 34 m). Worse, several starts print a
  *plateau* altitude while the town sits in a valley — Montereau 118/120 m vs a town at
  53 m (2004 and 2009), Étampes 133 m vs 80 m. Routing from the town centre then invents
  a 70–80 m climb that was never ridden. Fix by clipping the route so the distance to the
  first named anchor matches ASO's km; for 2009 that landed at 118.9 m against the
  printed 118, confirming the clip.
- **Match waypoints to the profile's altitudes, not just its town names.** In hilly
  terrain a town-centre geocode can sit 100 m below where the route passed (2006 prints
  Orsay 164 m and Gif 176 m; the valley towns are ~68 m and ~78 m). Relocate to the
  printed altitude — but constrain the search geographically, since matching on altitude
  alone can teleport a waypoint kilometres away.
- **Do NOT digitise the profile artwork.** Its *labels* (km marks, spot altitudes) are
  reliable and are the whole basis of this method; its *drawn silhouette* is decorative.
  2011's terrain occupies **nine vertical pixels** for a stage with 436 m of real
  climbing, and integrating it yields anywhere between 177 m and 499 m depending only on
  the smoothing window.

### Validation

Two checks worth repeating on any new year:

- **Shared final approach.** 2006–2010 all finish through Saclay → Verrières →
  Châtenay-Malabry → Meudon → Paris. Measuring that identical 23.5 km section gave
  **224 / 224 / 223 m** across three independent reconstructions — a cheap reproducibility
  test.
- **m/km against comparable stages.** The series separates cleanly by terrain: **4.0–4.8**
  for flat Brie/Marne run-ins (2002, 2003, 2004, 2009) and **5.9–7.1** for the
  Chevreuse/Hurepoix hills (2001, 2005–2008, 2010). 2011's known 436 m sits at 4.6, inside
  the flat band. A value outside 4–8 m/km for a Paris finale is a bug, not a discovery.

### ERR LOW (Eric's rule, 2026-08-09)

Where a stage is uncertain, store the **low end** of the plausible range, not the
midpoint. An understated figure mildly understates a stage's difficulty; an overstated one
invents climbing that was never ridden and shows up as a bogus outlier in the Race
Overview charts. In practice: when the reconstruction falls short of the ASO distance and
the missing kilometres are **flat** (typically the run into Paris along the Seine), add
them at ~3 m/km rather than scaling the whole route up — uniform scaling multiplies the
hilly sections too. Where a doubt has a known size, subtract it rather than splitting the
difference. Round down. 2006 (1150→1090) and 2007 (955→885) were revised under this rule.

`patch_paris_finale_elevation.py` is idempotent and re-runnable: it skips stages already
populated from any other source, and revises **only** values it derived itself (matched on
provenance source + script name). It also treats a stored `0` as missing — 2006 s20 was
the only TDF stage carrying `vertical_meters = 0` / `profile_score = 0`, a blank PCS field
parsed as zero, and its bogus `profile_score` is nulled rather than left in place.

**Known-open:** 2001 is the weakest of the set (±10%) — its profile names only three
places across 108 km of run-in, leaving a 30 km unanchored approach, and it prints no
start altitude. Separately, **2002's stored `distance_km` is 140.0 but its ASO profile is
titled 144 km** and its axis runs to 144; the elevation used the profile's internal
structure and the distance field was left untouched. Worth reconciling.

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
│       ├── main.ts                   # Orchestration only (init/wireControls/loadDataset/applyHash) — split
│       │                             #   from a 2,900-line monolith 2026-08-01; see architecture.md's
│       │                             #   "Frontend module map" for the full file-by-file breakdown
│       ├── raceRegistry.ts           # RaceId/RACES config — single source of truth for per-race identity
│       ├── state.ts                  # Shared mutable app state (one object; see architecture.md for why)
│       ├── views/                    # One file per view: overview, allRaces, stageChart, riders, riderDetail
│       ├── types.ts                  # TypeScript interfaces
│       ├── style.css                 # All styles
│       └── data/                     # Generated JSON — one per year + summary
│           ├── gc_by_stage_1903.json  # TDF files live at top level
│           ├── ...
│           ├── gc_by_stage_2026.json  # 113 TDF files total (lazy-loaded, one chunk each)
│           ├── giro/                  # Giro d'Italia files in subdirectory
│           │   ├── gc_by_stage_YEAR.json  # 42 years with data (1980–2026)
│           │   ├── all_races_summary.json # Giro cross-year aggregate (built by export_race_summary.py --race giro)
│           │   └── riders_index.json      # Giro rider index (2,775 riders / 446 teams)
│           ├── vuelta/                # Vuelta a España files in subdirectory
│           │   ├── gc_by_stage_2025.json  # 1 year with data (2025)
│           │   ├── all_races_summary.json # Vuelta cross-year aggregate (91 years 1935–2025, 1 with data)
│           │   └── riders_index.json      # Vuelta rider index (184 riders / 23 teams)
│           ├── all_races_summary.json # Cross-year aggregate data for All Races view (TDF only currently)
│           └── riders_index.json      # Compact cross-year TDF rider index (lazy-loaded by Riders view)
└── pipeline/                         # Data pipeline — not deployed
    ├── cycling.db                    # SQLite DB (gitignored, ~140MB, NOT regenerable — back up with db_backup.py)
    ├── db_backup.py                  # Rotating DB backups → db_backups/ (auto-run by add_stages.py before deletes)
    ├── export_gc.py                  # Main exporter: cycling.db + JSON supplements → src/data/
    │                                 #   --year N for single year, --race giro|tdf to select race
    ├── race_common.py                # Shared pipeline helpers, two groups:
    │                                 #   - Giro/Vuelta ingest: parse_time_to_seconds, parse_int, parse_bonus_seconds,
    │                                 #     detect_route_type, parse_year_args, COUNTRY_NAMES, and the RACES:
    │                                 #     {giro, vuelta} -> RaceInfo registry (db name/country, scrapes dirname,
    │                                 #     legacy flat-2026-fallback flag). Used by ingest_race.py and
    │                                 #     build_vuelta_gc_standings.py.
    │                                 #   - Export scripts (all 3 races): resolve_race_arg(), a
    │                                 #     {tdf,giro,vuelta} -> (db_name, data_subdir) lookup. Used by
    │                                 #     export_riders_index.py and export_race_summary.py.
    ├── export_riders_index.py --race {tdf,giro,vuelta}  # Builds <slug>/riders_index.json from the exported
    │                                 #   per-year files (default tdf). Youth/white-jersey years come from
    │                                 #   cycling.db's classification_standings — TDF only, see hasYouth.
    ├── export_all_races_summary.py   # Builds all_races_summary.json from cycling.db + supplements. TDF only —
    │                                 #   NOT the same as export_race_summary.py --race {giro,vuelta} below;
    │                                 #   writes to the top-level data/ dir, not data/tour/ (legacy, unmerged)
    ├── add_pre1960.py                # The actual tool for adding ANY TDF year additively (name is historical)
    ├── add_stages.py                 # Automated TDF stage addition: scrape files → JSON updates → DB → exports
    ├── scrape_stage_template.js      # JS snippets for extracting stage data from PCS in a browser
    ├── scrapes/                      # Per-stage TDF scrape output files (stage_N.json)
    ├── schema.sql                    # DB schema reference
    │
    │   # Giro d'Italia pipeline
    ├── scrape_giro.py                # Background scraper: downloads multiple years from PCS into giro_scrapes/YEAR/
    │                                 #   Usage: python3 scrape_giro.py 1970-1979  (range or individual years)
    │                                 #   Saves per-stage JSON: giro_scrapes/YEAR/stage_N.json
    ├── ingest_race.py --race giro    # Reads giro_scrapes/YEAR/stage_N.json → inserts into cycling.db
    │                                 #   Creates race "Giro d'Italia" (race_id=2) if not present
    │                                 #   Auto-runs fix_giro_rider_names.py at end of non-dry-run
    │                                 #   (merged from old ingest_giro.py/ingest_vuelta.py 2026-07-18; see
    │                                 #   "Pipeline consolidation" note above)
    ├── build_giro_points.py          # Extracts sprint/KOM points from giro_scrapes/ → giro_*_points.json
    ├── fix_giro_rider_names.py       # Fixes single-word rider names in the Giro data by reconstructing
    │                                 #   "LASTNAME Firstname" from the rider slug (e.g. rider/fausto-coppi → "Coppi Fausto")
    │                                 #   Strips disambiguation digits (rider/pozzi2 → pozzi). Auto-run by ingest_race.py --race giro.
    ├── export_race_summary.py --race giro  # Builds data/giro/all_races_summary.json from cycling.db (Giro only)
    │                                 #   Merges giro_races_summary_overrides.json after computing DB defaults
    ├── export_riders_index.py --race giro   # Builds data/giro/riders_index.json from exported Giro gc_by_stage files
    ├── giro_scrapes/                 # Per-stage Giro scrape output files
    │   ├── YEAR/stage_N.json         # Historical years organized by subdirectory (e.g. giro_scrapes/1980/stage_1.json)
    │   ├── stage_N.json              # 2026 files at flat level (legacy layout — 2026 was scraped before year dirs existed)
    │   └── save_server.py            # Local HTTP server (localhost:8765) for saving stage JSON via POST
    ├── giro_sprint_points.json       # Giro sprint points per rider per stage (same format as tour_sprint_points.json)
    ├── giro_kom_points.json          # Giro KOM points per rider per stage (same format as tour_kom_points.json)
    ├── giro_races_summary_overrides.json # Per-year field overrides for export_race_summary.py --race giro
    │                                 #   Contains 88 entries with correct gcWinnerTimeSeconds/slowestFinisherTimeSeconds
    │                                 #   sourced from PCS GC standings pages (DB summed stage times were unreliable)
    ├── check_giro_gc_times.py        # Fetches PCS GC standings page for each Giro year, extracts winner time,
    │                                 #   compares to DB; writes mismatches to giro_gc_time_corrections.json
    ├── apply_giro_gc_corrections.py  # Reads giro_gc_time_corrections.json, merges into giro_races_summary_overrides.json
    │
    │   # Vuelta a España pipeline
    ├── scrape_vuelta.py              # Background scraper: downloads years from PCS into vuelta_scrapes/YEAR/
    │                                 #   Usage: python3 scrape_vuelta.py 2025  (same pattern as scrape_giro.py)
    │                                 #   PCS base URL: /race/vuelta-a-espana/YEAR/
    ├── build_vuelta_points.py        # Extracts sprint/KOM points from vuelta_scrapes/ → vuelta_*_points.json
    ├── ingest_race.py --race vuelta  # Reads vuelta_scrapes/YEAR/stage_N.json → inserts into cycling.db
    │                                 #   Creates race "Vuelta a España" (race_id=3) if not present
    │                                 #   No auto-run of fix_giro_rider_names (modern PCS format, names are correct)
    ├── scrape_vuelta_stage_info.py    # Fetches vertical_meters + profile_score for Vuelta stages from PCS
    │                                  #   Must be run separately after ingest — scrape_vuelta.py does NOT capture these
    │                                  #   URL: /race/vuelta-a-espana/YEAR/stage-N/result/result
    │                                  #   Updates cycling.db stages table directly (same pattern as scrape_giro_stage_info.py)
    ├── export_race_summary.py --race vuelta # Builds data/vuelta/all_races_summary.json (FIRST_YEAR=1935, 91 years)
    │                                  #   Merges vuelta_races_summary_overrides.json after computing DB defaults
    ├── export_riders_index.py --race vuelta  # Builds data/vuelta/riders_index.json from exported Vuelta gc_by_stage files
    ├── vuelta_scrapes/               # Per-stage Vuelta scrape output files
    │   └── YEAR/stage_N.json         # Organized by year subdirectory (e.g. vuelta_scrapes/2025/stage_1.json)
    ├── vuelta_sprint_points.json     # Vuelta sprint points per rider per stage
    ├── vuelta_kom_points.json        # Vuelta KOM points per rider per stage
    ├── scrape_vuelta_gc_pages.py     # Fetches PCS per-stage GC pages ({slug}-gc) → {race}_scrapes/YEAR/gc_pages/
    │                                 #   Saves per-day: info, profile_icon, full result_rows, gc_rows (GC standings
    │                                 #   table top-N). Also writes _slugs.json (true race-day list incl. prologue)
    │                                 #   Takes --race giro (as do the two scripts below) — Giro uses giro_scrapes/
    ├── make_missing_vuelta_days.py   # Diffs gc_pages/_slugs.json vs stage files; creates stage_0.json (n=0)
    │                                 #   for missing prologues (1979–1987 all had one) or inserts+renumbers a
    │                                 #   missing mid-race day. Run before build_vuelta_gc_standings.py
    ├── build_vuelta_gc_standings.py  # Derives per-stage GC for every rider → {race}_scrapes/YEAR/gc_standings.json
    │                                 #   (real PCS per-stage GC + validated cumulative time chains; see
    │                                 #   "Vuelta & Giro per-stage GC standings" below). Consumed by ingest_race.py.
    ├── check_vuelta_gc_times.py      # Fetches PCS GC standings for all 80 Vuelta years, extracts winner time,
    │                                 #   compares to DB; writes vuelta_gc_winner_times.json (all years) and
    │                                 #   vuelta_gc_time_corrections.json (mismatched years only)
    ├── apply_vuelta_gc_corrections.py # Reads vuelta_gc_time_corrections.json, merges into vuelta_races_summary_overrides.json
    ├── vuelta_gc_winner_times.json   # PCS-sourced GC winner time in seconds for all 80 Vuelta years (used by export_gc.py)
    ├── vuelta_gc_time_corrections.json # Years where DB sum differed from PCS by >60s (78 of 80 years had mismatches)
    ├── giro_gc_winner_times.json     # PCS-sourced GC winner time for 88 Giro years (derived from giro_races_summary_overrides)
    └── vuelta_races_summary_overrides.json # Per-year field overrides for export_race_summary.py --race vuelta
                                      #   Contains 78 entries with correct gcWinnerTimeSeconds/slowestFinisherTimeSeconds
                                      #   sourced from PCS GC standings pages (DB summed stage times were unreliable)
    │
    │   # TDF supplemental data files (all in git)
    ├── tour_sprint_points.json       # Green jersey points per rider per stage (1953–2025)
    ├── tour_kom_points.json          # KOM points per rider per stage (raw PCS scrape)
    ├── tour_kom_points_reconciled.json # KOM points after Wikipedia patching (authoritative)
    ├── kom_totals.json               # Final KOM totals from Wikipedia + bikeraceinfo
    ├── kom_reconcile_report.json     # Year-by-year reconciliation results
    ├── profile_icons.json            # Raw PCS profile-icon code per stage (p1–p5 — see warning below)
    ├── bri_stages.json               # Per-stage results from bikeraceinfo (1960–2005)
    ├── tour_gc_winner_times.json     # Official GC winner total time per year from Wikipedia
    ├── gc_all_times.json             # Official GC times for top ~10 riders per year from Wikipedia
    ├── wiki_race_distances.json      # Official total race distance per year from Wikipedia infobox
    ├── tour_all_races_summary_overrides.json # Per-year field overrides for export_all_races_summary.py
    │                                   #   (e.g. full-planned-route elevation for an in-progress year)
    │
    │   # Scraping scripts
    ├── tdf_YEAR_full.json            # Raw PCS scrape files — ALL tracked in git (as are scrapes/, giro_scrapes/, vuelta_scrapes/)
    ├── scrape_kom_points.py          # Scrapes KOM points from PCS stage -kom pages
    ├── scrape_kom_totals.py          # Scrapes final KOM totals from Wikipedia + bikeraceinfo
    ├── scrape_bri_stages.py          # Scrapes per-stage results from bikeraceinfo
    ├── scrape_gc_winner_times.py     # Scrapes GC winner total time from Wikipedia GC table
    ├── scrape_gc_all_times.py        # Scrapes GC times for all top-10 riders from Wikipedia
    ├── scrape_pcs_stages.py          # Scrapes stage data from PCS
    ├── scrape_pcs_kom_finals.py      # Scrapes final KOM standings from PCS
    ├── scrape_sprint_finals.py       # Scrapes final sprint standings
    │
    │   # Patch / fix scripts
    ├── patch_kom_wikipedia.py        # Patches KOM data from Wikipedia (years 1933–1938 top 10)
    ├── patch_missing_distances.py    # Patches zero/null stage distances from PCS result pages
    ├── patch_bri_distances.py        # Patches distances from bikeraceinfo; reports conflicts
    ├── patch_route_types_wikipedia.py # Patches stage route types from Wikipedia
    ├── patch_paris_finale_elevation.py # Reconstructed vertical_meters for Paris finales
    │                                   #   PCS leaves blank (2001–2010), SOURCE_DERIVED.
    │                                   #   Idempotent; revises only its own values.
    │                                   #   See "Derived elevation for the Paris finales"
    │
    │   # Validation scripts
    ├── reconcile_kom.py              # Reconciles PCS KOM data against Wikipedia/BRI references
    ├── validate_exports.py           # CI gate: checks all gc_by_stage_*.json for data integrity
    │                                 #   (decreasing cumulatives, bad structure — hard error; duplicate
    │                                 #   ranks, KOM reference drift — warnings). Runs in deploy.yml.
    ├── validate_kom.py               # Validates KOM totals vs Wikipedia and bikeraceinfo
    └── validate_gc.py               # Validates per-stage GC leaders/gaps vs bikeraceinfo
```

> **Critical:** `cycling.db` is gitignored and must be kept locally at `pipeline/cycling.db`. It is **not regenerable** — most historical years' raw scrape files no longer exist. Back it up with `python3 pipeline/db_backup.py` (rotating snapshots in `pipeline/db_backups/`, newest 5 kept; `add_stages.py` snapshots automatically before its destructive delete step). All raw scraped data (`tdf_*_full.json`, `scrapes/`, `giro_scrapes/`, `vuelta_scrapes/`) IS tracked in git.

> **`add_pre1960.py` is the tool for adding a TDF year**, despite its pre-1960-sounding name — it reads a CLI year argument (`python3 add_pre1960.py 2026`), writes additively to the real `pipeline/cycling.db`, and skips (never wipes) any year already present. (The old `build_db.py` was deleted — it was stale and dangerous.) See "Adding a New Year" below.

---

## Data Pipeline

### Tour de France pipeline
```
PCS website  →  tdf_YEAR_full.json  (scraped via a real browser — see note below)
                       ↓
                add_pre1960.py  →  cycling.db
                                      │
              ┌───────────────────────┴──────────────────────────────┐
              │  supplemental JSON files:                             │
              │  tour_sprint_points.json  (green jersey pts)          │
              │  tour_kom_points_reconciled.json (KOM pts)            │
              │  profile_icons.json       (raw PCS icon codes)        │
              │  gc_all_times.json        (official rider times)      │
              │  tour_gc_winner_times.json (official winner times)    │
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
PCS website  →  giro_scrapes/YEAR/stage_N.json  (via scrape_giro.py for historical years)
                       ↓
               build_giro_points.py  →  giro_sprint_points.json + giro_kom_points.json
                       ↓
               ingest_race.py --race giro  →  cycling.db  (race_id=2, "Giro d'Italia")
                  └─ auto-runs fix_giro_rider_names.py to correct single-word names
                       ↓
               export_gc.py --race giro
                       ↓
              data/giro/gc_by_stage_YEAR.json
                       ↓
               export_race_summary.py --race giro  →  data/giro/all_races_summary.json
               export_riders_index.py --race giro   →  data/giro/riders_index.json
```

**Full pipeline command sequence for each decade of historical Giro data:**
```bash
cd pipeline
python3 scrape_giro.py 1970-1979         # background-friendly; saves to giro_scrapes/YEAR/
python3 build_giro_points.py
python3 ingest_race.py --race giro 1970-1979  # also accepts individual years or --all
python3 export_gc.py --race giro
python3 export_race_summary.py --race giro
python3 export_riders_index.py --race giro
```

### Vuelta a España pipeline
```
PCS website  →  vuelta_scrapes/YEAR/stage_N.json  (via scrape_vuelta.py)
                       ↓
               build_vuelta_points.py  →  vuelta_sprint_points.json + vuelta_kom_points.json
                       ↓
               ingest_race.py --race vuelta  →  cycling.db  (race_id=3, "Vuelta a España")
                       ↓
               export_gc.py --race vuelta
                       ↓
              data/vuelta/gc_by_stage_YEAR.json
                       ↓
               export_race_summary.py --race vuelta  →  data/vuelta/all_races_summary.json
               export_riders_index.py --race vuelta   →  data/vuelta/riders_index.json
```

**Full pipeline command sequence for adding Vuelta data:**
```bash
cd pipeline
python3 scrape_vuelta.py 2024         # saves to vuelta_scrapes/2024/
python3 build_vuelta_points.py
python3 ingest_race.py --race vuelta 2024
python3 export_gc.py --race vuelta
python3 export_race_summary.py --race vuelta
python3 export_riders_index.py --race vuelta
```

All three pipelines feed into the same `cycling.db` (the `races` table distinguishes them: race_id=1 = TDF, race_id=2 = Giro, race_id=3 = Vuelta). The Giro and Vuelta pipelines are similar — both store sprint/KOM points inside each stage scrape file. `export_gc.py --race vuelta` picks up `vuelta_sprint_points.json` and `vuelta_kom_points.json` and outputs to `data/vuelta/`. The Vuelta pipeline has no `fix_rider_names` equivalent — modern PCS format names are correct.

```
                               vite build  →  build/  →  GitHub Pages
```

> **Scraping PCS in 2025+:** plain `curl`/`urllib` requests get a Cloudflare "Just a moment…" 403 challenge page — `scrape_pcs_stages.py` (urllib-based) no longer works against the live site. Use a real browser (e.g. the Chrome MCP tools) to load each stage page and extract the results table via injected JavaScript instead. See "Scraping a live/in-progress Tour" below for the exact DOM structure and a working extraction pattern.

### Key data files

**`cycling.db`** — SQLite database. Tables:
- `races` — (race_id, name, country, race_type) — race_id=1 "Tour de France", race_id=2 "Giro d'Italia", race_id=3 "Vuelta a España"
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

**`tour_sprint_points.json`** — Green jersey points per stage per rider.
```json
{ "2025": [ {}, {"rider/jonathan-milan": 12, ...}, ... ] }
```
Array index = stage position in DB ordering (matches `stages` table order). Each dict maps `rider/rider-slug` → points earned that stage from intermediate sprints + stage finish only (KOM sprint points excluded). Data starts at 1953. **Golf scoring 1953–1958**: lower cumulative points = better rank (Schär system).

**`tour_kom_points_reconciled.json`** — KOM points, same structure as sprint_points. For 1933–1938, Wikipedia top-10 data was merged via `patch_kom_wikipedia.py` because PCS only had top 3–5. This is the authoritative source; `tour_kom_points.json` is the raw PCS scrape.

**`tour_gc_winner_times.json`** — `{"1903": 340380, "1904": 345955, ...}` — official total race time in seconds for the GC winner, scraped from Wikipedia's General Classification table. 103 of 112 years. Missing: 1905–1912 (points-system era, no times) and 1904 (non-standard table). 2000–2005 uses Armstrong's time (DSQ in 2012 but fastest in the race).

**`{race}_gc_winner_times.json` is authoritative for BOTH exporters.** `export_gc.py`
always preferred it; `export_race_summary.py` did not, and computed
`gcWinnerTimeSeconds` by summing the winner's per-stage `finish_time_seconds`
instead. That sum silently understates any edition where some stages lack a
winner time, and nothing distinguishes a short sum from a short race: **Vuelta
1968 had times for 12 of its 20 stages and reported 18:33:54 against a real
78:29:00**, sitting between neighbours of 76:38 and 73:18 on the All Years
chart. Both exporters now read the file first and fall back to the stage sum
only when the year is absent. **Adding the missing year to that file is the fix
for this class of bug**; fixed so far: Vuelta 1968 (Gimondi 78:29:00), Giro 1959
(Gaul 101:50:26) and Giro 1977 (107:27:16), each verified on PCS's own GC page.

**Detect these, don't wait to be told.** A year missing from the curated file is
invisible — the fallback produces a plausible-looking number. Compare each
year's winner time against the median of years within ±6 and flag anything below
70% of it:

```
tour   103 curated / 103 years   clean
giro    90 curated /  90 years   clean (was 88 — 1959 and 1977 were missing)
vuelta  79 curated /  79 years   clean
```

**13 Giro years were filled from PCS's GC pages** (1928, 1930, 1931, 1950, 1952,
1961, 1963–68, 1978), taking the Giro from 90 to 103 years with a winner time.
Every winner name was checked against the historical record and every time
**speed-checked against the stored distance** — all landed at 26.9–36.7 km/h
with a sensible era progression.

Two deliberate omissions:
- **Giro 1946 (Bartali, PCS says 65:32:20)** — that is 46.5 km/h over 3,050 km,
  impossible for the first post-war Giro, and looks like a partial sum. Left
  missing rather than written.
- **Giro 1909–1913** have no time GC at all: the early Giro used a POINTS
  classification, exactly like the Tour before 1913. Nothing to fill.

**Vuelta 1995 (Jalabert, 95:30:33)** was the same story — absent from the file,
and its stage times too sparse for the fallback (584 rows with a time against
2,292 in 1994 and 3,100 in 1996), so it produced nothing at all rather than a
short number.

Final state — every remaining gap is explained, none is a defect:

| race | years with a time | missing |
|---|---|---|
| tour | 104 | 1904–1912 (points era, no times exist) — nothing else |
| giro | 103 | 1909–13 (points era) + 1946 (PCS value fails its speed check) |
| vuelta | 80 | none |

**A second gate hid behind the first.** The curated lookup originally sat inside
`if winner_row:` — i.e. it only ran once a `gc_rank=1` row was found on the
final stage. 19 Giro editions have no such row (the sparse-final-stage case
`validate_db` warns about), so adding their figures to the file changed nothing
until the lookup was moved ahead of the winner lookup. It identifies the TIME
and never needed the rider.

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
Generated by `export_all_races_summary.py`, which merges in `tour_all_races_summary_overrides.json` (`{"2026": {"totalElevationM": 53707}}`-shaped — any field there overwrites the DB-computed default for that year) after computing the defaults. **It is currently empty (`{}`)** — its one entry pinned 2026's elevation to the planned-route total while the Tour was in progress, and was removed once all 21 stages were in (see "Finalizing a completed year"). Keep it that way: an override left behind after the real data lands silently outranks it forever.

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

This is the most important script. It reads cycling.db + all supplemental JSON files and produces the per-year JSON files. Supports `--race giro`, `--race vuelta` (or `--race tdf`, the default) to select which race to export.

**`--year YYYY` scopes the export to a single year** — pass it as its own flag, not a bare positional (`export_gc.py --race vuelta --year 2020`, not `export_gc.py --race vuelta 2020`). A bare positional used to be silently dropped, falling back to a full all-years export; as of 2026-07-25 the script rejects any unrecognized argument with an error instead. Use `--year` whenever fixing/re-scraping a single existing year's data — otherwise every year for that race gets rewritten (harmless if nothing else changed, but it bloats the diff and makes review hard).

`export_riders_index.py` and `export_race_summary.py` have **no** `--year` flag and never will need one: each produces a single combined cross-year file (`riders_index.json`, `all_races_summary.json`) by globbing/looping over every year, so there's no meaningful "just this year" output — the whole point of the file is the merge. Both run in a couple seconds even across 80 Vuelta years, so this isn't a performance problem worth solving. Expect every year's entry to be touched in the diff when either of these runs, even for a single-year data fix — that's normal, not a bug. When `--race giro` is used, it reads `giro_sprint_points.json` / `giro_kom_points.json` and outputs to `data/giro/`. When `--race vuelta` is used, it reads `vuelta_sprint_points.json` / `vuelta_kom_points.json` and outputs to `data/vuelta/`. The TDF `gc_all_times.json` supplement is not used for Giro or Vuelta. For non-TDF races, it auto-detects a `{race}_gc_winner_times.json` file (e.g. `giro_gc_winner_times.json`, `vuelta_gc_winner_times.json`) and uses `winner_time + gc_gap_seconds` for `totalTimeSeconds` — which is far more accurate than the per-stage sum fallback for historical years.

**`totalTimeSeconds` priority** (per rider):
1. `gc_all_times.json` — Wikipedia official time (top ~10 per year)
2. `tour_gc_winner_times.json + gc_gap_seconds` — winner time + rider's gap at last stage
3. Sum of `finish_time_seconds` across stages — legacy fallback (often incomplete)

**Sprint rank computation**: Pre-computed per-stage before the rider loop using running cumulative totals. `GOLF_SPRINT_YEARS = set(range(1953, 1959))` controls ascending vs descending sort. Stored as `sprintRank` in each `byStage` entry.

**KOM rank computation**: Same approach as sprint, always descending (higher points = better). Stored as `komRank`.

**DNF tail catch-up**: After the per-stage loop for a rider, if they DNF'd before the last stage, their cumulative points are topped up with any points stored in later stage slots (some sources store final totals in the last stage entry). Their final `sprintRank`/`komRank` is also set from the pre-computed final-stage rank tables.

**`finalRank`**: Derived from each rider's last `byStage` entry's `gc_rank`, not from the last stage's result row. This ensures DNF'd KOM/sprint leaders still get correct classification ranks.

**gc_rank=999**: Used by PCS for disqualified riders in early years (1904, 1905). These are set to NULL in the DB so the y-axis doesn't extend to 999. These riders get `finalRank=9999` and appear at the bottom of the legend.

---

## Frontend — cycling-app/src/*.ts

Chart logic is split across `cycling-app/src/*.ts` and `views/*.ts` (split 2026-08-01 from a
2,900-line `main.ts` monolith — see `architecture.md`'s "Frontend module map" for the
file-by-file layout, the shared-mutable-state pattern, and the riders↔riderDetail circular
import). `raceRegistry.ts` holds the **`RACES` registry** — the single source of truth for
per-race config (see "Race registry" below). The function-level behavior described here is
unchanged by the split, just physically relocated; check architecture.md if you need to know
which file a given function now lives in. Key functions:

- **`loadDataset(year)`** — **async**; awaits `getDataset(year)` (lazy chunk fetch + LRU), updates UI state, triggers chart redraw. Callers that depend on the result (year-select change, career-dot click-through) must handle the promise — the career-dot click does `loadDataset(...).then(() => switchView("stage"))` to avoid rendering the previously-loaded year.
- **`getDataset(year)`** — resolves a year's dataset from a 6-entry LRU (`DATASET_CACHE`, keyed by `race:year`); on miss it `fetch()`es the year's JSON asset (URL from `URLS_BY_RACE[currentRace]`) and `JSON.parse`s it. Re-visiting an evicted year re-fetches from the browser HTTP cache (no network, only re-parse).
- **`drawChart()`** — renders the bump chart for the current year/metric. Calls `buildRankMapsFromField()` to extract rank series per rider. Each metric has an optional "points" display mode toggled via a y-axis button: GC Time (ascending hours), Sprint Points (ascending cumulative), KOM Points (ascending cumulative).
- **`buildRankMapsFromField(getRank, getCumPts)`** — takes accessor functions, builds `rankAtStage` and `cumulativeAtStage` maps. Reads `sprintRank`/`komRank` fields directly (never re-derives them). `finalRank` is built only from riders who reached the final stage — DNF riders keep their mid-race rank in `rankAtStage` (so their lines still draw) but are excluded from `finalRank` (so they don't pollute Top N selection or legend ordering).
- **`setHighlight(id)`** — O(1) hover path: restyles only the previous and new highlighted rider's elements (line + dot + label) via `restyleRider()`, instead of sweeping all ~180 riders. `updateLineClasses()` still exists for full-sweep scenarios (selection changes, presets, filters).
- **`drawOverview()`** — renders the Race Overview bar charts
- **`drawAllRacesOverview()`** — renders the 4-panel All Races Overview. Uses `ALL_RACES` (imported from `all_races_summary.json`) and a shared `crosshairLines[]` array for the synchronized hover line
- **`drawRidersPage()`** — **async**; awaits `ensureRiderIndex()` (shows "Loading riders…" on first open) then renders the search/filter grid, filtered to `currentRace`. `drawRiderDetail(id)` renders a rider's cross-race career chart (see below) — it is not filtered to `currentRace`.
- **`ensureRiderIndexFor(race)`** — idempotent per race (tracked via `riderIndexBuilt: Record<RaceId, boolean>`); `fetch()`es that race's `riders_index.json` once (URL via `RIDERS_INDEX_URL[race]`, a `?url` import) and builds `riderIndexByRace[race]` (Map) + `allTeamsSortedByRace[race]`. Lazy so it never weighs down first paint. `ensureRiderIndex()` is a thin convenience wrapper calling `ensureRiderIndexFor(currentRace)` — the Riders grid only needs the current race's index, but `drawRiderDetail` awaits all three in parallel (`Promise.all(RACE_IDS.map(ensureRiderIndexFor))`) since a rider's cross-race chart needs every race's data regardless of which one is currently selected. The index file is `{ teams: [names], riders: { slug: {...} } }`: rider keys are slugs (the `rider/` prefix is re-added on load) and teams are integer indexes into the shared `teams` string table (`-1` = no team) — both shrink the payload versus inlining strings. Year-tuples are `[gcRank, teamIdx]` (no points rankings that year) or `[gcRank, teamIdx, sprintRank, komRank]` with `0` = absent rank; normalized to `9999` sentinels on load.
- **`switchView(view)`** — handles "stage" | "overview" | "allraces" | "riders" transitions; calls `updateHash()` at the end
- **`wireControls()`** — attaches all event listeners (year select, metric select, sidebar buttons, view buttons, Team/Nation filter dropdowns)
- **`buildStageFilters()`** — rebuilds the Team/Nation dropdown checkbox lists for the current year's dataset; prunes `stageFilterTeams`/`stageFilterNations` to only values that still exist (carrying filter state across a year change), reapplies the filter if anything survived, or forces an empty selection if a filter was active but nothing carried over
- **`applyStageTeamNationFilter()`** — recomputes `selected` from `stageFilterTeams`/`stageFilterNations` (OR within a facet, AND across facets); no-ops if both are empty so it never fights with the quick-select buttons

**Hash routing (deep links)**: every view is URL-addressable and race-aware. An optional leading race segment selects the race: `#giro/2026/stage/gc`, `#vuelta/allraces`, `#giro/riders/fausto-coppi`. No race segment means `tour` (backward compatible with all pre-multi-race links). Patterns: `#[race/]<year>/stage/<metric>` (metric: `gc`|`gc-time`|`points`|`sprint-points`|`kom`|`kom-points`), `#[race/]<year>/overview`, `#[race/]allraces`, `#[race/]riders`, `#[race/]riders/<rider-slug>` (slug = rider id minus the `rider/` prefix). `computeHash()` emits the race prefix for non-tour races only, keeping tour hashes canonical and stable. The `-time`/`-points` suffixes select the alternate y-axis display mode for that metric. `computeHash()` derives the hash from state; `updateHash()` writes it via `location.hash` (pushes a history entry, so back/forward walk app states); `applyHash()` parses `location.hash` back onto state (async — awaits `loadDataset` for stage/overview routes, or `drawRiderDetail` for a rider route, which itself awaits all three races' `ensureRiderIndexFor`). Loop protection: `applyHash` no-ops when the hash already equals `computeHash()` (our own write), and the `applyingHash` flag suppresses `updateHash` during an apply so intermediate draws don't push partial states. `init()` applies the initial hash, falling back to defaults + `history.replaceState` seed when the hash is empty/unrecognized; after applying, it loads the default dataset whenever none is in memory — this covers riders/allraces deep links (so stage/overview work on later navigation) AND deep links that exactly match the default state, which `applyHash()` short-circuits as "already in sync" without loading anything. When adding new app state that should be shareable, extend `computeHash` + `applyHash` together.

**No-data overlays**: If `currentMetric === "points"` and `year < 1953`, or `currentMetric === "kom"` and `year < 1933`, the chart area shows an explanatory text message instead of chart elements.

**Race registry (`RACES`)**: `RaceId` is `"tour" | "giro" | "vuelta"` — the slug doubles as the data subdirectory name and the hash segment. A single `RACES: Record<RaceId, RaceConfig>` object in raceRegistry.ts is the source of truth for per-race display name, career-chart colors, jersey icon colors (solid vs polka-dot KOM), jersey tooltip labels, war bands, and `hasYouth`. All per-race `Record` maps (`URLS_BY_RACE`, `ALL_RACES_BY_RACE`, `riderIndexByRace`, `RIDERS_INDEX_URL`, etc.) are derived from `RACE_IDS` via `emptyPerRace()`, and the race dropdown options are generated from the registry (index.html has an empty `<select>`). **Adding a race = one `RACES` entry + data files in `src/data/<slug>/`** — the wildcard globs (`./data/*/gc_by_stage_*.json`, `./data/*/all_races_summary.json`, `./data/*/riders_index.json`) discover them automatically.

**War bands by race** (shaded regions on All Races Overview) live in each race's `RACES` entry (`warBands`): TDF has WWI 1914–1918 + WWII 1939–1946, Giro has WWI + WWII 1940–1945, Vuelta has "Civil War / WWII" 1935–1944 (Vuelta started 1935).

**Data loading (performance-critical)**: Per-year files are discovered with **one eager wildcard `?url` glob** — `./data/*/gc_by_stage_*.json` — which puts only the hashed asset *URLs* in the main bundle via `URLS_BY_RACE` (a `Record<RaceId, Record<string, string>>`, keyed by the directory slug); the data itself is emitted as raw `.json` assets and loaded via `fetch()` + `JSON.parse` on demand. `currentRace` selects which URL map to use; `setRace()` rebuilds `YEARS` and the year dropdown. Do **not** switch back to module imports (plain glob / dynamic `import()`): the browser's ES-module registry pins every imported module for the page's lifetime, so LRU eviction would no longer free memory, and parsing JSON-as-JS is slower than `JSON.parse`. Adding a new race is: add a `RACES` entry and drop files in `data/<slug>/` — no glob or dropdown changes needed. The Riders page's cross-year `riders_index.json` URLs come from a matching wildcard glob (`./data/*/riders_index.json?url`). Only the tiny `all_races_summary.json` files are eagerly bundled. d3 is imported as modular submodules (`d3-selection`, `d3-scale`, `d3-axis`, `d3-shape`, `d3-array`) via a small `d3` shim object, not the full `d3` meta-package. Net result: initial download for the default stage view is ~76 KB gzipped, and only LRU-cached years (max 6) stay in memory.

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
python3 export_race_summary.py --race giro            # rebuilds data/giro/all_races_summary.json
python3 export_riders_index.py --race giro             # rebuilds data/giro/riders_index.json
# Vuelta exports
python3 export_gc.py --race vuelta              # all Vuelta years → src/data/vuelta/
python3 export_gc.py --race vuelta --year 2025  # single Vuelta year
python3 export_race_summary.py --race vuelta          # rebuilds data/vuelta/all_races_summary.json
python3 export_riders_index.py --race vuelta           # rebuilds data/vuelta/riders_index.json
# TDF shared exports
python3 export_riders_index.py       # rebuilds riders_index.json (TDF Riders page cross-year index)
python3 export_all_races_summary.py  # rebuilds all_races_summary.json (All Races Overview data — TDF only currently)
python3 validate_exports.py          # check ALL races' exported files (tour+giro+vuelta; 0 errors = good; warnings = informational)
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

2. **Add to DB with `add_pre1960.py`:**
   ```bash
   cd pipeline
   python3 add_pre1960.py 2026 --dry-run   # sanity check first
   python3 add_pre1960.py 2026             # real insert — additive, never wipes existing data
   ```
   This only works if `2026` is **not already** in `race_editions` — see "Adding stages to an in-progress year" below for what to do once it is.

3. **Add sprint points** for the year to `tour_sprint_points.json`. Key = year string, value = array of dicts (one per stage, same order as DB stages) mapping `rider/slug` → points earned that stage from sprints + stage finish (exclude KOM sprint points). See "Scraping a live/in-progress Tour" for how to extract these from PCS's `-points` page.

4. **Add profile icons** for the year to `profile_icons.json` — an array of **raw PCS icon codes** (`p1`–`p5`), one per stage, in DB stage order. For a TTT/ITT stage, also make sure that stage's `info["Won how"]` in `tdf_2026_full.json` contains "team time trial"/"time trial" text (see the `profile_icons.json` warning above) — the icon code alone won't classify it correctly.

5. **Add KOM points** for the year to `tour_kom_points_reconciled.json`. Same structure as tour_sprint_points.json — see "Scraping a live/in-progress Tour" for extraction.

6. **Scrape Wikipedia GC times** (only meaningful once the race has an official classification — skip for an in-progress year):
   ```bash
   python3 scrape_gc_all_times.py 2026    # appends to gc_all_times.json + tour_gc_winner_times.json
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
   If the same PCS route page also gives a full-route vertical-meters total and the year is still in progress, add it to `tour_all_races_summary_overrides.json` too (see below) so elevation doesn't undercount to just the stages raced so far. **Both of those are temporary** — see "Finalizing a completed year" for what to undo once the race ends.

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

1. **Scrape each new stage** from PCS via the browser. Use the streamlined `EXTRACT_ALL`
   flow (one JS injection per stage, POSTs straight to a local save server) — see "Scraping
   a live/in-progress race from PCS" below for the full step-by-step, including the
   two-page `EXTRACT_RESULTS`/`EXTRACT_POINTS` manual fallback if the save server isn't
   running.

2. **Run `add_stages.py`** — this handles everything else automatically:
   ```bash
   cd pipeline
   python3 add_stages.py 10 11        # stage numbers to add
   python3 add_stages.py 10 --dry-run # preview without writing
   ```
   First it runs `detect_name_swaps.py`'s bib-consistency check against the *entire*
   on-disk year (not just the new stages) and **aborts with no changes if any bib maps to
   more than one rider identity anywhere** — this is a hard gate added 2026-07-25, not
   optional, and it will refuse to add a new stage while an older stage still has an
   unresolved swap. Fix the flagged scrape file(s) (swap `name`/`slug`/`nat` back using
   `race_common.swap_identity()`) and re-run. Only after that passes does it update
   `tdf_2026_full.json`, `tour_sprint_points.json`, `tour_kom_points_reconciled.json`,
   `profile_icons.json`, delete/re-insert the year in `cycling.db`, run all three exports,
   and validate.

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
Each row is parsed via `race_common.StageRow.from_list()` (added 2026-07-25) rather than
raw positional indexing — a row that isn't exactly 15 fields raises a clear error instead
of silently corrupting or dropping data (this caught a real bug: a malformed 14-field row
had silently dropped a rider from one stage for a while before the switch to `StageRow`).

**Key notes:**
- `add_stages.py` safely replaces stages that already exist in the data files (idempotent)
- The scrape files persist in `pipeline/scrapes/` so stages don't need re-scraping
- `--scrapes-only` flag updates just the JSON files without touching the DB or running exports
- `add_pre1960.py` is still the underlying DB inserter; `add_stages.py` orchestrates around it
- `fix_2026_name_swaps.py`'s SWAPS list (stages 1-15) is stale/already-applied — do not run
  it without `--dry-run` first, it isn't idempotent and would swap correct riders back to wrong

> **Never pre-fill or estimate time gaps.** Even flat sprint stages produce real time gaps — crashes and incidents can leave riders at the back losing 3–7+ minutes, and riders can DNS/DNF on any stage type. Every `gap_txt` value in a scrape file must come from actual PCS data. Do not write stage files until the real PCS results page has been scraped.

### Manual fallback (if add_stages.py isn't suitable)

`add_pre1960.py`'s `insert_edition()` skips the entire year if it already exists in `race_editions`. The manual process is: delete the edition from all DB tables (no `ON DELETE CASCADE`), re-run `add_pre1960.py`, and manually update the supplemental JSON files. See `add_stages.py` source for the exact delete SQL.

### Finalizing a completed year

Adding the last stage does **not** finish a year. Two things stay wrong until they
are done by hand, and neither one fails a validator — they just show up as a blank
or a stale number in the UI. Done for 2026 on 2026-08-15:

1. **Add the official GC winner time** to `tour_gc_winner_times.json`
   (`"2026": 266186` for Pogačar's 73:56:26). This is the single highest-leverage
   entry in the whole finalization: `export_all_races_summary.py` reads it directly
   for `gcWinnerTimeSeconds`, and `export_gc.py`'s `resolve_total_time()` uses it as
   the base for **every** rider's `totalTimeSeconds` (`winner_time + last-stage gap`),
   which outranks the sum-of-stage-times fallback. Until it exists, all 158 finishers
   carry the fallback, and the fallback is bad: summed stage times missed the real
   figure by **−67 min (2021), −63 (2022), +8 (2023), −72 (2024), +4 (2025), +24
   (2026)**. Wikipedia's scraper (`scrape_gc_all_times.py 2026`) writes this file when
   it has the year; entering the PCS figure by hand is equally valid and lands to the
   second rather than Wikipedia's rounded-to-the-minute values.

2. **Empty the in-progress overrides** in `tour_all_races_summary_overrides.json`.
   2026's `totalElevationM: 53707` was the PCS *planned-route* total, pinned so
   elevation didn't undercount to the stages raced so far. With all 21 stages in, the
   real per-stage sum is **52,988 m**, and leaving the override in place would have
   kept displaying the planned figure permanently. An override that outlives its
   reason is invisible — nothing warns about it.

3. **Replace the planned distance with the official one** in `wiki_race_distances.json`.
   2026 held **3321.2**, the PCS route page's pre-race total (step 7 of "Adding a New
   Year" says to use it while a Tour is running); Wikipedia's infobox for the finished
   race says **3,245 km**, matching the DB's 21 summed stages to the decimal. This is
   the one in-progress placeholder that *does* announce itself — it was sitting at a
   −2.3% divergence in `export_all_races_summary.py`'s reconciliation report, just
   under the 3% threshold that would have flagged it. It also mattered for plausibility
   checks: at 3321.2 km the 2026 winning speed computes to 44.9 km/h, an implausible
   +3.4% jump on 2025; at the true 3245 km it is **43.9 km/h**, right next to 2025's 43.5.

`slowestFinisherTimeSeconds` needs nothing: it is `gcWinnerTimeSeconds + MAX(gc_gap_seconds)`
at the final stage, so it appears on its own the moment (1) is done. For 2026 the DB's
own max gap (Cees Bol, 22,928 s) reproduced the published +6:22:08 exactly — a free
cross-check that the winner time and the stage data agree.

Then re-export and validate:
```bash
python3 export_gc.py --race tdf --year 2026
python3 export_riders_index.py
python3 export_all_races_summary.py
python3 validate_exports.py --year 2026
```
(Note `--race tdf`, not `tour` — `export_gc.py` still uses the legacy race key even
though every path it writes is `data/tour/`.)

---

## Adding Giro d'Italia stages

The Giro pipeline is separate from the TDF pipeline (different scripts, different scrape directory, different supplemental files), but uses the same DB schema and export format.

### Historical Giro data — decade-by-decade scraping

Historical Giro editions (pre-2026) are added decade by decade using `scrape_giro.py`, which scrapes PCS in the background (no browser required — uses urllib with delays to avoid Cloudflare blocks). It saves to `giro_scrapes/YEAR/stage_N.json` subdirectory layout.

```bash
# Start scraper in background (run from pipeline/ directory)
python3 scrape_giro.py 1970-1979 > /tmp/giro_1970s.log 2>&1 &
echo "PID: $!"

# Monitor progress
tail -f /tmp/giro_1970s.log

# After scraper finishes, run the full pipeline:
python3 build_giro_points.py
python3 ingest_race.py --race giro 1970-1979
python3 export_gc.py --race giro
python3 export_race_summary.py --race giro
python3 export_riders_index.py --race giro
```

**Progress as of 2026-07-17:** COMPLETE — all 109 editions with data, 1909–2026 (~4,700 riders / ~700 teams).

### Rider name quality and fix script

PCS stage result pages for historical Giro years can produce single-word names (first name only) due to two page formats:
1. `<span>LASTNAME</span> Firstname` — newer format, correctly extracted by `scrape_giro.py`'s anchor-based td_text extraction
2. `<img flag/> Firstname` — older format, only the first name appears even with the correct extraction

`fix_giro_rider_names.py` handles case 2 by reconstructing `"LASTNAME Firstname"` from the rider's slug (e.g. `rider/fausto-coppi` → `"Coppi Fausto"`). It:
- Finds all Giro riders in the DB with a single-word `full_name`
- Identifies which slug parts are the first name (by fuzzy-matching against the current scraped name, preserving accent characters)
- Builds the corrected name with last name uppercased + original first name
- Strips disambiguation suffixes (e.g. `rider/pozzi2` → last name `Pozzi`, `rider/sierra-1` → drops the `1`)

`ingest_race.py --race giro` automatically runs this script at the end of every non-dry-run ingest. Run it standalone with `python3 fix_giro_rider_names.py [--dry-run]`.

**`INSERT OR IGNORE` name precedence:** The `riders` table uses `INSERT OR IGNORE`, so the **first insert wins**. TDF-sourced rider names (which came from TDF scraping) take precedence over Giro-scraped names for any rider who raced both.

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

# 1. NOTE: ingest_race.py --race giro deletes and re-creates any edition it touches (atomically,
#    preserving vertical_meters/profile_score). No manual delete needed. It refuses
#    a bare no-arg run (which would rebuild every year) without --all.
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
python3 ingest_race.py --race giro

# 4. Export to frontend
python3 export_gc.py --race giro --year 2026

# 5. Validate
python3 validate_exports.py --year 2026
```

> **Note:** Unlike the TDF pipeline which has `add_stages.py` for incremental stage addition, the Giro pipeline currently requires a full delete-and-reimport cycle when adding new stages. This is simpler but means all `giro_scrapes/stage_N.json` files must be present for a reimport.

After ingesting, also run:
```bash
python3 export_race_summary.py --race giro   # updates data/giro/all_races_summary.json
python3 export_riders_index.py --race giro    # updates data/giro/riders_index.json
```

---

## Adding Vuelta a España data

The Vuelta pipeline mirrors the Giro pipeline exactly (same scrape format, same DB schema, same export flow), differing only in:
- PCS base URL: `/race/vuelta-a-espana/YEAR/` (vs `giro-d-italia`)
- Scrape directory: `vuelta_scrapes/YEAR/stage_N.json`
- race_id = 3, race_name = "Vuelta a España"
- No `fix_rider_names` step (modern PCS format, names are reliable)
- First year: 1935 (vs 1909 for Giro)
- War band: Spanish Civil War / WWII gap 1936–1944

**Current status (as of 2026-07-17):** 80 editions with data, 1935–2025 (~4,400 riders / ~570 teams).

### Adding historical Vuelta years

```bash
cd pipeline
python3 scrape_vuelta.py 2020-2024          # saves to vuelta_scrapes/YEAR/ (use SCRAPE_DELAY=4.0 for recent years)
python3 build_vuelta_points.py
python3 ingest_race.py --race vuelta 2020-2024   # ALWAYS pass a year range — see warning below
python3 export_gc.py --race vuelta
python3 export_race_summary.py --race vuelta
python3 export_riders_index.py --race vuelta
python3 scrape_vuelta_stage_info.py 2020-2024   # only the newly ingested years
python3 export_gc.py --race vuelta              # re-export to pick up elevation
python3 export_race_summary.py --race vuelta
```

> **Note on re-ingesting.** `ingest_race.py --race {vuelta,giro}` **deletes and re-creates** any edition it touches, but does so atomically (a failed insert rolls the delete back) and **preserves `vertical_meters`/`profile_score`** from the existing edition, so re-ingesting no longer wipes elevation data. A bare no-arg run (which would rebuild every year found in the scrapes directory) is refused unless you pass `--all`. Still prefer passing the specific range you changed (e.g. `ingest_race.py --race vuelta 1970-1989`). `scrape_vuelta_stage_info.py` only needs to run for years that never had elevation scraped.

**PCS rate limiting:** Use `SCRAPE_DELAY=4.0` for recent years (2015+). Older years can often use `2.0`. The scraper handles 429 with a 30s backoff.

### Adding elevation data for a Vuelta year

`scrape_vuelta.py` does NOT capture `vertical_meters` or `profile_score` — these must be fetched separately after ingestion using `scrape_vuelta_stage_info.py`:

```bash
cd pipeline
python3 scrape_vuelta_stage_info.py 2024          # single year
python3 scrape_vuelta_stage_info.py 2020-2024     # range
python3 scrape_vuelta_stage_info.py 2024 --dry-run  # preview
```

It fetches `/race/vuelta-a-espana/YEAR/stage-N/result/result` and extracts `vertical_meters` and `profile_score` directly from the HTML, then writes them to the `stages` table in `cycling.db`. Re-export after running it:

```bash
python3 export_gc.py --race vuelta --year 2024
python3 export_race_summary.py --race vuelta   # picks up new totalElevationM
```

This is exactly the same pattern as `scrape_giro_stage_info.py` — if you forget this step, the Race Overview page shows no elevation bars and the All Races Overview shows null elevation for that year. Use `SCRAPE_DELAY` env var if hitting 429s (default 3.0s).

**Total elevation for all_races_summary.json** is computed by summing `vertical_meters` from the DB stages (done automatically by `export_race_summary.py --race vuelta`). If PCS's per-stage numbers differ slightly from the official route total, use `vuelta_races_summary_overrides.json` to pin the authoritative value:
```json
{"2025": {"totalElevationM": 53914}}
```

### Jersey filter buttons on the Riders page

The Riders page shows GC / Sprint / KOM / Youth jersey filter buttons for **all three races**. Youth wins are not tracked for Giro or Vuelta (the pipeline captures sprint and KOM winners but not youth), so the youth button is hidden on non-TDF:

```typescript
if (category === "youth" && !raceConfig().hasYouth) btn.style.display = "none";
```

The button group itself is always rendered — only the youth button is hidden per-category. The AND semantics (selecting multiple jerseys narrows to riders who've won every selected category) apply on all races.

`jerseyIconSvg(category)` reads jersey colors from `raceConfig().jersey` (solid fill, or white-with-dots when the config uses `{ dots: color }`).

**If you add a new race:** set `hasYouth` in its `RACES` entry according to whether youth wins are tracked in its pipeline.

### Rider detail chart: cross-race, with race + classification toggles (`drawRiderDetail`)

`drawRiderDetail(riderId)` is **async and cross-race** — it is not filtered to `currentRace`. It awaits all three races' rider indexes in parallel (`Promise.all(RACE_IDS.map(ensureRiderIndexFor))`), builds a `Map<RaceId, RiderEntry>` of every race the rider appears in (`byRace`), and returns early if the rider is in none. The header/meta line (`"7 TDF · Best #1, 8 Giro · Best #1, 1 Vuelta · Best #1"`) is built from `byRace` directly — no nationality text (the flag next to the name + its hover tooltip already convey it).

**Toggle bar**, above the chart: race buttons (T/G/V, one per race in `RACE_IDS`) then a `|` divider then classification buttons (GC/Sprint/KOM). Both toggle groups behave the same way — clicking toggles membership in a `Set` (`activeRaces` / `activeClassifs`), refusing to deactivate the last remaining member so the chart is never empty; a `BADGE: Record<RaceId, {bg, text, label}>` constant (not `RACES[race].chart`, for reliable hex values in SVG `stroke`/`fill` attributes) drives each race button's color and letter. A race button is disabled (`.no-data`) if the rider has no entry for that race at all.

**Overlapping-year dot offset:** when a rider raced two+ active races in the same year, their dots would otherwise land on identical x-coordinates. `xPos(race, year)` looks up which active races have data for that year and offsets each by `±(DOT_R*2+1)` px (currently 11px, for `DOT_R=5`) around the shared center, so same-year dots from different races sit side-by-side, touching, instead of stacking.

**Classifications:** GC draws a solid line (in `RACES[race].chart.gc`), Sprint a `4,3`-dashed line (`chart.sprint`), KOM a `2,3`-dotted line (`chart.kom`) — all three independently toggleable per race via the classification buttons; the y-axis (`"Rank"`) and its domain expand to cover whichever classifications are active. The DNF/DNS zone below the main chart only appears when GC is active.

**Legend** (top-right, above the chart, up to 3 rows): row 1 is one column per active race (name + solid line, in that race's GC color); rows 2/3 (only if Sprint/KOM are active) repeat under each race's column ("Sprint"/"KOM", dashed/dotted, in that race's sprint/kom color) — columns are left-aligned to a fixed per-column x so "Tour"/"Sprint"/"KOM" (and same for Giro/Vuelta) line up vertically.

**Click a dot** to jump to that race/year's stage chart at the matching metric (`gc`, `points` for Sprint, or `kom` for KOM) — `setRace()` + `loadDataset()` + `switchView("stage")`.

**If you add a new race:** its `RACES` entry's `chart` colors and `name` are used automatically for the cross-race chart and legend; add a `BADGE` entry too (hex color, not a CSS var) for its toggle button and DNF-dot outline.

---

## Scraping a live/in-progress race from PCS

> **The `CF_CLEARANCE` cookie route is DEAD as of 2026-08-13.** `scrape_vuelta.py` and
> `scrape_giro.py` still document it, and their docstrings are now wrong for every year,
> not just live races. Verified: with a cookie minted minutes earlier in Eric's own
> Chrome **and** that browser's exact User-Agent (`Chrome/150.0.0.0`), PCS returns
> `HTTP 403` with `cf-mitigated: challenge` and `cType: 'managed'` — i.e. it issues a
> *fresh* challenge and ignores the clearance entirely. The cookie is bound to the
> **TLS fingerprint** of the client that solved it, and curl/urllib cannot present
> Chrome's. Making them do so means a TLS-impersonation library (`curl_cffi`,
> `curl-impersonate`), which exists solely to defeat bot detection — **do not go
> there.** A managed challenge is PCS stating they don't want automated collection;
> keep volumes modest and prefer the browser routes below.
>
> Two further blocks discovered the same day, both of which sound like they should
> work and don't:
> - **A PCS page cannot POST to a local save server.** In the in-app browser it's
>   blocked as mixed content; in real Chrome it's blocked by **Private Network
>   Access**, even with the server returning `Access-Control-Allow-Private-Network:
>   true`. This is why the Grand Tour save-server methodology below no longer works
>   as written. (`pipeline/classics_scrapes/save_server.py` has the PNA header and a
>   `/relay` page anyway — neither is sufficient; treat that file as a record of
>   what was tried.)
> - **Programmatic downloads** (`Blob` + `<a download>`) are silently dropped in the
>   in-app browser and need a real user gesture in Chrome.
>
> **What works, and is now the default for any bulk scrape:** hand Eric a
> self-contained **DevTools console snippet** that fetches every race/year
> same-origin, extracts compactly, and downloads **one combined `.txt`**. He pastes
> it once (all years in a single run — it does not need to be repeated per year) and
> the file lands in `~/Downloads`. Costs zero context and has no transcription risk.
> Relaying page data back through the conversation instead measures at **~23K chars
> per race** (~340K tokens for a 57-race scrape) and is error-prone — a hand-relayed
> gzip payload failed its CRC on the first attempt. If data must pass through
> context, verify it: hash in-page with `crypto.subtle.digest` and compare against
> `shasum -a 256`. See `parse_classics_bundle.py` for the bundle format and parser.

For a live/in-progress race, use a real browser, navigate to each stage's PCS page, and extract data via injected JavaScript. The page structure below applies identically to both the Tour de France and Giro d'Italia — only the URL path differs (`tour-de-france` vs `giro-d-italia`).

### Efficient multi-stage scraping methodology

**The core constraint is Cloudflare rate-limiting:** after ~2-5 same-origin `fetch()` requests from a page, PCS starts returning Cloudflare challenge pages instead of real content. Navigating to a page in the browser (which passes Cloudflare's JS challenge) resets this counter. The optimal strategy uses a **local save server** + a **self-contained extraction JS snippet** to minimize both Cloudflare blocks and token/context usage.

#### Step 1: Start a local save server

`pipeline/giro_scrapes/save_server.py` and `pipeline/scrapes/save_server.py` (TDF; ported 2026-07-25) are identical scripts, one per race's scrape directory. Each runs on `localhost:8765` and accepts POSTed JSON, saving each stage to `stage_N.json` in its own directory (only run one at a time — they share a port).

```bash
cd pipeline/scrapes       # TDF; use pipeline/giro_scrapes or pipeline/vuelta_scrapes for those races
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

**For TDF**, `pipeline/scrape_stage_template.js`'s `EXTRACT_ALL` is exactly this — inject it via `javascript_tool` on `.../stage-N`, it does steps 1-3 itself (points only, no separate KOM sub-page for TDF — see below) and returns a JSON status summary (row count, whether the points fetch succeeded, and any same-stage duplicate-bib warnings). `EXTRACT_RESULTS`/`EXTRACT_POINTS` in the same file are the older two-page, dump-to-`<pre>` fallback for when the save server isn't running.

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
python3 ingest_race.py --race giro
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
- **Adjacent-row name-swap artifact**: On certain PCS stage pages, the anchor tag for a rider's name renders one row out of position in the HTML (likely a PCS-side rowspan/colspan rendering quirk). The EXTRACT_RESULTS script extracts `tds[7].querySelector('a')`, which then grabs the anchor from the adjacent row — swapping the `name`, `slug`, and `nationality` between two adjacent riders while leaving their bib, team, GC rank, and times intact on the correct row. **Sanity check after every stage scrape:** for each row, verify that the rider's slug matches the expected bib and team (a rider should not change team between stages). If you see a rider with an obviously wrong bib or team for a single stage (e.g. a GC leader suddenly riding for a domestic team), the swap artifact has occurred. Fix by swapping indices 5, 6, and 7 (name, slug, nat) between the two affected rows in the scrape file and in `tdf_YEAR_full.json`. This was found in 2026 TDF stage 5 (Quinn↔Van Asbroeck) and stage 10 (Quinn↔Castrillo). A quick automated check after scraping: `python3 -c "import json; d=json.load(open('stage_N.json')); bibs={}; [bibs.setdefault(r[3], r[6]) or print('CONFLICT', r[3], bibs[r[3]], r[6]) for r in d['rows'] if r[3].isdigit() and bibs.get(r[3]) not in (None, r[6])]"` — any bib appearing twice with different slugs signals a swap.

**TTT stage** (e.g. 2026 stage 1) — PCS renders it as ~20+ small per-team tables (unhelpful), **plus one large table with PCS's own pre-computed individual ranks/gaps** — found by checking every `document.querySelectorAll('table')` for one with header `Rnk | BIB | H2H | Specialty | Age | Rider | Team | UCI | (blank) | Time | Time won/lost` (no `GC` column, since it's stage 1). This table exists on both `.../stage-N` and `.../stage-N-gc` — the two are identical, so either page confirms the other. No team-grouped offset arithmetic is needed; just extract this table like a normal stage (rank 1's `Time` cell is absolute, everyone else's is their gap) and leave `gc_pos`/`gc_lag` blank (the stage-1 carry-forward fallback in `add_pre1960.py` fills them in).

**Points classification** (`.../stage-N-points`) — look for `<h4>` headings whose text starts with `"Sprint |"` or equals exactly `"Points at finish"`; the table immediately following each such heading has a `Pnt` column and a `Rider` column with the same anchor structure as above. Sum `Pnt` per rider **across all matching headings on the page** (a rider can score at both an intermediate sprint and the finish) — this sum is that stage's entry in `tour_sprint_points.json`. Ignore any `<h4>KOM Sprint...</h4>` headings on this page — those belong to the KOM classification, not points.

**KOM classification** (`.../stage-N-kom`) — same page layout, but now sum the `Pnt` column under every `<h4>KOM Sprint...</h4>` or `<h4>GPM Sprint...</h4>` heading (there's one per categorized climb on the stage) — this sum is that stage's entry in `tour_kom_points_reconciled.json`. A flat/TTT stage with no climbs has no such headings at all → empty `{}` for that stage index in both files.

### Lessons learned from Giro 2026 scraping

1. **Always verify the save server's target directory** before scraping. The server uses `__file__`-relative paths, but if started from the wrong context (e.g. a temp directory from a previous Claude session), all POSTed data silently goes to the wrong place. A test POST + `ls` check takes 5 seconds and prevents losing 21 stages of work.

2. **Cloudflare rate limits vary by session.** Sometimes you get 5 extra fetches per navigation, sometimes only 1-2. Don't assume a fixed batch size — check for `"Just a moment"` in every fetch response and fall back to navigate-per-stage when blocked.

3. **The save server approach is far more token-efficient than returning data through the conversation.** Each stage's JSON is ~28KB. With 21 stages, that's ~588KB of data that would otherwise flow through context. The save server reduces each stage to a 2-tool-call round trip (navigate + JS extraction with POST) with only a one-line confirmation in the response.

4. **Stage 21 (final stage) often has 0 sprint and 0 KOM points** — this is normal for a processional/criterium-style final stage, not a scraping error.

5. **Adjacent-row name swaps in EXTRACT_RESULTS** (TDF `scrape_stage_template.js` method): On some PCS pages, a rider's name anchor renders one row off in the HTML, causing two adjacent rows to have their name/slug/nationality silently swapped while their bib, team, GC rank, and times stay on the correct row. Found in 2026 TDF stages 5 and 10 — discovered only when a user noticed a GC rank jump (Quinn went from #2 → #147 for one stage). Detection: after scraping, spot-check any rider whose GC rank jumps by 50+ positions in a single stage, or check for bib/team inconsistencies across stages. Fix: swap indices 5, 6, 7 (name, slug, nat) between the two affected rows in the scrape file and in `tdf_YEAR_full.json`, then re-run `add_pre1960.py YEAR` and exports. See "Adjacent-row name-swap artifact" in the PCS page structure section above for a one-liner to detect bib conflicts automatically.

6. **Positional stage-numbering bug in `scrape_vuelta.py`/`scrape_giro.py` (found + fixed 2026-07-25).** Both scripts' `scrape_year()` used to assign `stage_num = i + 1` from the rider's position in the list of *successfully scraped* stages, not from the actual PCS slug (`stage-12` → 12). Because `discover_stages()` silently drops any stage whose probe fails without leaving a placeholder, a single failed fetch mid-scrape (Cloudflare hiccup, timeout, etc.) silently shifted every later stage's file down by one — producing wrong-but-plausible-looking data with no visible error. This is exactly how the 2020 Vuelta lost Stage 12 (the Alto de l'Angliru summit finish): stages 13–18 had been saved as `stage_12.json`–`stage_17.json` for as long as that data existed, until a user cross-referenced the stage count against the real 2020 calendar and noticed the race was one stage short. Both scripts now derive `stage_num` from the slug via regex and print a warning if there's a gap in the saved stage numbers. **This fix only prevents recurrence — it does not retroactively validate other already-scraped years.**

**Historical audit (2026-08-01):** ran a full scan of all 118 scraped Giro years and 80 Vuelta years for the two structural signatures of this bug — gaps in saved stage-file numbering, and stage counts dipping below the local era's norm. Found 10 years with a gap in file numbering; cross-checked each against the live PCS page before assuming it was a bug. **4 were legitimately cancelled stages, not corruption** (Giro 1912 stage 4, Giro 2001 stage 18, Giro 2011 stage 4 — the Wouter Weylandt tribute stage — and Giro 2013 stage 19, cancelled for snow): PCS shows "Race/stage is cancelled" with no results table, so there's nothing to scrape. The other 7 (Giro 1946/14, 1956/12, 1969/21, 2011/20, 2011/21; Vuelta 1948/3, 1968/17) were real gaps and got backfilled by navigating a real browser to each stage (Cloudflare blocks `urllib`/`curl` for historical years too, not just the live/in-progress race — even a fresh `curl` to a 1912 stage page gets the "Just a moment…" 403 challenge) and feeding the captured HTML through the *existing* `find_results_table`/`parse_rows`/`parse_info`/`parse_points_page` functions from `scrape_giro.py`/`scrape_vuelta.py` (imported directly, not reimplemented) — this reuses every already-validated parsing quirk (text-duplication dedup, era-appropriate column detection, etc.) without writing new parsing logic per era. Row counts were cross-checked against the immediately adjacent (already-correct) stage in the same year before accepting each result. The **count-dip heuristic alone was unreliable** — spot-checking against Wikipedia found real historical variation (1990 Giro's 20-stages-plus-one-split, the COVID-shortened 2020 Vuelta) that looked identical to corruption in the raw numbers; only gap-in-numbering was trustworthy without independent verification. The remaining ~25 count-dip-only candidates (mostly pre-1990, where Grand Tour length varied for legitimate historical reasons) were **not** investigated — flagged but deliberately left unaudited.

7. **`scrape_vuelta.py`'s row parser can silently produce blank `gc_pos`/`gc_lag` for an entire stage.** `parse_rows()` only fills those two `StageRow` fields when the results table has a `GC` or `Timelag` header (`scrape_vuelta.py:211-219`); if neither is present, both fields are left as `""` for every rider with no error or warning. Confirmed cause of the 2025 Vuelta Stage 5 gap (a team time trial — Figueres, 24.1km): the TTT results-table layout apparently doesn't expose a `GC`/`Timelag` column the way normal stages do, even though every other field (bib, name, team, points, stage time/gap) scraped correctly. **Not yet fixed at the source** — this session's fix was a manual one-off reconstruction from user-supplied PCS screenshots, matched by bib number against the existing (correct) row data. Team time trials and other atypical stage-page layouts are a plausible recurring blind spot for this parser; worth auditing other TTT stages across scraped years if this comes up again.

8. **Screenshot-based manual data workflow (established 2026-07-25).** For a stage or two of data, asking the user to screenshot the relevant PCS page tabs is often *faster* than fighting a throttling scraper — this isn't just a fallback for when PCS is outright Cloudflare-blocked (`navigate`/`urllib` returning "Just a moment..." for an extended period, sometimes well beyond a single session), it's a legitimate first choice for small data volumes. Don't wait out a block or burn retries before asking; for one or two stages, just ask:
   - **Stage tab** (rank, name, team, time-behind-winner; tick the **BIB** and **+Points** checkboxes at the top of the page for bib numbers and UCI/PCS points columns — easy to miss, ask for these explicitly)
   - **GC tab** (rank, name, team, cumulative gap — same BIB checkbox)
   - **Points tab, "TODAY" toggle** (not "GENERAL"/cumulative) for that stage's sprint-points delta per rider — confirmed by cross-checking against a known-correct existing `sprint_points` dict that this per-stage delta is exactly what `scrape_vuelta.py`'s `parse_points_page()` computes (sum of intermediate-sprint + finish-line points for that stage)
   - **KOM tab, "TODAY" toggle** — same logic for `kom_points`
   - Cross-reference riders against an adjacent already-correct stage file in the same year (e.g. the stage immediately before) to fill in `bib`/`age`/`slug`/`nat`/`team`/`team_slug` — match by **bib number** where available (most reliable), falling back to name matching with accent/diacritic normalization (handle `ł`→`l`, `ø`→`o` manually — Python's `unicodedata` NFKD decomposition doesn't strip these since they're distinct letters, not combining diacritics)
   - DNF/DNS riders for a reconstructed stage can usually be carried forward unchanged from the nearest adjacent correct stage file, rather than asking the user to screenshot a full non-finisher list
   - This produced a complete, correctly-cross-referenced 157-row stage reconstruction (2020 Vuelta Stage 12) and a 179-row GC backfill (2025 Vuelta Stage 5) without any PCS access at all — validate the result before writing by checking rider-count parity between the reconstructed stage and its neighboring stages' rosters, and spot-checking a few well-known riders (e.g. the new GC leader) against real-world race history.

9. **The swap artifact is persistent per-page, not transient.** Confirmed 2026-07-25: re-scraping TDF stage 19 (to test `EXTRACT_ALL`) reproduced the exact same 4 rider swaps (Hindley/Martinez, Evenepoel/del Toro, Braz Afonso/Simmons, Benoot/Cattaneo) that had already been fixed earlier that session — PCS's rendering of that specific page is durably wrong, it doesn't fix itself between requests. Also confirmed: `EXTRACT_ALL`'s same-stage duplicate-bib self-check (`dupWarnings`) reported clean (`[]`) on this same re-scrape, because none of those 4 swaps involve a bib appearing twice in one stage — each bib appears once, just with the wrong rider attached. **A clean same-stage self-check does not mean a stage is swap-free.** The only check that reliably catches this class of swap is the cross-stage bib-consistency gate in `detect_name_swaps.py` (wired into `add_stages.py`) — always run the full pipeline (which invokes it) rather than trusting a single stage's extraction output in isolation.

---

## Key Implementation Notes

### Giro GC winner time overrides

`export_race_summary.py --race giro` computes `gcWinnerTimeSeconds` by summing `finish_time_seconds` per stage. For historical Giro editions this is unreliable — many stages have NULL times, or PCS stored cumulative totals instead of per-stage deltas. As a result, 88 of 109 Giro editions had wrong times.

The fix: `giro_races_summary_overrides.json` contains 88 year entries with correct `gcWinnerTimeSeconds` and `slowestFinisherTimeSeconds`, sourced from PCS GC standings pages (`/race/giro-d-italia/YEAR/gc/result/result`). These overrides are applied after DB-computed defaults in `export_race_summary.py --race giro`.

To update/check GC times:
```bash
# Check all years and write corrections
python3 check_giro_gc_times.py        # → giro_gc_time_corrections.json
python3 apply_giro_gc_corrections.py  # → merges into giro_races_summary_overrides.json
python3 export_race_summary.py --race giro  # → regenerates all_races_summary.json
```

The PCS GC page extraction uses regex `r'(?<!\+)(?<!\d)(\d{1,3}:\d{2}:\d{2})(?!\d)'` — finds time strings NOT preceded by `+` (gaps have `+` prefix; the winner's total time does not).

### Vuelta & Giro per-stage GC standings (July 2026 rebuild)

PCS stage-result pages **before 1998** embed GC standings for only ~1–30 riders
per stage (often just the leader; the full field only at the final stage), and
many historical stages list most of the peloton as `DF` ("did finish" — no
recorded position/time; NOT a DNF). The original `ingest_vuelta.py` "carried
forward" the last seen GC values per rider — in lexicographic file order
(stage_1, stage_10, …, stage_2) — which fabricated per-stage GC by replicating
stale/final gaps across stages. All Vuelta years were rebuilt in July 2026:

1. `scrape_vuelta_gc_pages.py 1979-1997` — fetches each race day's `{slug}-gc`
   PCS page into `vuelta_scrapes/YEAR/gc_pages/` (full result table, GC
   standings top-N, info block, true race-day slug list `_slugs.json`).
2. `make_missing_vuelta_days.py` — creates `stage_0.json` (n=0, labeled "P")
   for the prologues the original scraper missed (1979–1987 all had one), or
   inserts+renumbers a missing mid-race day.
3. `build_vuelta_gc_standings.py` — writes `vuelta_scrapes/YEAR/gc_standings.json`:
   - **authoritative entries**: PCS's own per-stage GC (rows' GC columns +
     gc_pages standings tables) — exact, bonus-inclusive;
   - **computed entries**: cumulative sums of scraped per-stage gaps
     ("score", gap-space so day winners' absolute times cancel), tied to real
     GC via a per-day offset estimated from riders present in both, propagated
     forward AND backward so one truncated stage doesn't break a chain;
   - **validation**: any rider whose computed values ever disagree with a PCS
     authoritative entry beyond 5s is dropped from computed output (their
     authoritative entries remain). Old PCS pages don't publish time bonuses,
     so bonus-earning riders fail validation by design — better absent than
     wrong. A rider-stage with no derivable value gets NO entry (nulls in the
     export; the frontend draws line gaps).
   - gc_rank is emitted only when ≥85% of active riders are known that day
     (otherwise rank=null, gap only — the GC Time display mode still shows
     these riders; the GC Position mode shows only truly ranked ones).
4. `ingest_race.py --race vuelta` consumes `gc_standings.json` when present
   (per stage `n`, per rider); the carry-forward is gone. Stage files sort
   numerically. `DF` now ingests as FINISHED with null time/rank.

**Follow-on bug (found + fixed 2026-08-01): `gc_standings.json` was overriding good raw
data, not just filling gaps in it.** `ingest_race.py` originally used `gc_standings.json`
as the *exclusive* GC source for a year whenever the file existed at all — completely
ignoring that stage's own scraped `gc_pos`/`gc_lag` columns even for riders
`gc_standings.json` had no entry for. Since `gc_standings.json` is built to intentionally
leave gaps rather than guess (see "validation" above), any rider it didn't cover lost a
perfectly good raw GC rank for nothing. Surfaced by a user report that the 2026 Giro showed
79 finishers instead of the real 151 (Jonathan Milan — a sprinter with no reason to be
missing — had a raw `gc_pos` of 124 in the scrape file that was being silently discarded).
Checking further: this wasn't 2026-specific — 67 of 109 Giro years and 54 of 80 Vuelta years
had at least one rider losing their final-stage GC rank this way, totaling 1,251 Giro +
711 Vuelta riders (14.9% / 10.0% of all final-stage rows). Fixed by changing the priority
to **raw first, `gc_standings.json` only as fallback when the raw value is missing** —
matches `gc_standings.json`'s own internal source priority (authoritative raw > computed
> drop), and can only recover data, never regress the pre-1998 years the reconstruction was
built for. Full re-ingest + re-export of both races after the fix recovered 1,930 riders'
GC ranks; ~192 remain genuinely missing (no value in either source — old, sparse editions,
not a bug). If you see a suspiciously low finisher count for a Giro/Vuelta year again, check
whether raw `gc_pos` is present in the stage scrape before assuming it's a scraping gap.

Caveats: mid-race computed gaps can omit the leader's accumulated time
bonuses on days where the only authoritative anchor is the leader (uniform
shift; rank order unaffected). 1986 and 1988-style years where PCS lists only
~top-10 per stage stay sparse — that's all the data PCS has.

**`build_vuelta_points.py` numeric-sort fix**: it used to sort stage files
lexicographically, misaligning sprint/KOM points arrays with DB stage order
for EVERY year with 10+ stages (export_gc.py indexes arrays by stage
position). Rebuilt 2026-07; `build_giro_points.py`/`ingest_race.py --race giro`
got the same fixes.

**Giro (same rebuild, July 2026)**: identical disease, identical cure. All
three scripts take `--race giro` (they live under their `vuelta_` names but
are race-parameterized; scrapes land in `giro_scrapes/YEAR/gc_pages/`).
`ingest_race.py --race giro` consumes `gc_standings.json` the same way. Giro-specific
notes:
- PCS has **full per-day GC tables from 1990 onward** for the Giro (Vuelta
  only from 1998), so 1990–1997 are fully authoritative.
- 1912 was contested as a *team* classification — PCS has no individual GC
  and the rebuild correctly emits nothing for it.
- Missing prologues materialized for 1968/1973/1977–1982/1984–1987; missing
  split-stage halves / dropped days inserted for 1936, 1950, 1960, 1970,
  1988→no-op, 1990, 1991, 1992, 1995.
- `make_missing_vuelta_days.py` matching was hardened during the Giro port:
  one-to-one day matching (1988's 21a/21b share date+finish — key-based
  matching wrongly saw 21b as covered) and insertion positions anchored to
  neighbouring days' actual file numbers (1992's files contain a Genova
  prologue the PCS dropdown omits, shifting file numbers vs slug positions).
- Persistent PCS page failures (server-side): 1912/stage-4, 1946/stage-12,
  1956/stage-9b, 1969/stage-20, 1971/prologue, 1983/prologue; and the 1989
  final-TT `-gc` page is near-empty on PCS itself. All degrade gracefully
  (the stage files still carry the data used).

### Vuelta GC winner time overrides

Same problem as Giro — per-stage time sums from the DB are wildly wrong for historical Vuelta editions. 78 of 80 years had mismatches (some off by hours, e.g. 1982 showed 38h instead of the correct 95h).

The fix mirrors the Giro approach: `vuelta_gc_winner_times.json` contains PCS-sourced winner times for all 80 years; `vuelta_races_summary_overrides.json` contains corrected `gcWinnerTimeSeconds` + `slowestFinisherTimeSeconds` for 78 years; `export_gc.py --race vuelta` picks up `vuelta_gc_winner_times.json` automatically for per-rider `totalTimeSeconds`.

To re-check/update:
```bash
python3 check_vuelta_gc_times.py        # → vuelta_gc_winner_times.json + vuelta_gc_time_corrections.json
python3 apply_vuelta_gc_corrections.py  # → merges into vuelta_races_summary_overrides.json
python3 export_gc.py --race vuelta      # → regenerates all 80 gc_by_stage files
python3 export_race_summary.py --race vuelta  # → regenerates all_races_summary.json
```

### Sprint points scoring system
The green jersey competition existed 1953–present. **1953–1958 used golf scoring** (lower cumulative points = better rank — the Schär system). From 1959 onward, higher = better. The constant `GOLF_SPRINT_YEARS = set(range(1953, 1959))` in `export_gc.py` controls ascending vs descending sort when pre-computing `sprintRank`. The frontend reads the pre-computed rank and never re-derives it, which is critical — re-deriving from points would get 1953–1958 backwards.

### KOM points
KOM competition started 1933. The polka-dot jersey wasn't introduced until 1975. Data for 1933–1938 top-10 was patched from Wikipedia (`patch_kom_wikipedia.py`) because PCS only had top 3–5 for those years.

### 1904 disqualifications
After the race, the top 4 finishers (Garin, Pothier, Cornet-original, Chevalier) were disqualified. Henri Cornet (5th on road) became the official winner. The DB stores DQ'd riders with `gc_rank = NULL` at the last stage (not 999) so the y-axis isn't distorted. Their `finalRank` becomes 9999 in the export, placing them at the bottom of the legend.

### Points-system years (1905–1912)
These Tours were decided by points (fewer = better), not elapsed time. There are no official total elapsed times for these years. `tour_gc_winner_times.json` and `gc_all_times.json` have no entries for 1905–1912. The GC Winner Time and Average Speed panels in All Races Overview show gaps for these years. Wikipedia stage pages only list top-10 per stage, so stage-time summation gives inconsistent results (not used).

### Stage numbering and labels
`stage_number` in the DB matches PCS ordering. Stage 0 = Prologue. Split stages (e.g. 1a/1b) each have their own `stage_number`. Stage labels (`stage_label` in JSON) are computed in `export_gc.py` by grouping stages sharing the same `stage_date`: single stages get sequential numbers, paired stages get "Na"/"Nb" suffixes, prologue gets "P".

### Sprint/KOM point arrays alignment
`tour_sprint_points.json`, `tour_kom_points_reconciled.json`, and `profile_icons.json` all use the same array indexing: index 0 = first stage in DB ordering for that year. This matches the order returned by `SELECT ... FROM stages WHERE edition_id=? ORDER BY stage_number`. The `stage_num_to_idx` dict in `export_gc.py` maps `stage_number → array_index` to handle the alignment.

### DNF riders in classifications
A rider who DNFs before the final stage has their last `byStage` entry used for `finalRank`. Their cumulative points are topped up via a catch-up loop after the main `byStage` loop (some sources store final totals in stage slots after the rider's last actual stage). `sprintRank`/`komRank` at their last entry is also backfilled from the final-stage pre-computed rank tables.

### totalTimeSeconds resolution
Three-tier priority in `export_gc.py` (TDF):
1. Wikipedia official time from `gc_all_times.json` (top ~10 riders per year, all years back to 1903)
2. `tour_gc_winner_times.json[year] + gc_gap_seconds` at last stage — covers all riders in modern years with PCS gap data
3. Sum of `finish_time_seconds` per stage — last resort, often incomplete for pre-1960 non-top-10 riders

For Giro and Vuelta, tier 1 (`gc_all_times.json`) is not used. Instead:
1. `{race}_gc_winner_times.json[year] + gc_gap_seconds` — PCS-sourced winner time + rider's gap (accurate for all years where the file has an entry)
2. Sum of `finish_time_seconds` per stage — fallback for years not in the winner-times file

### Distance data
`wiki_race_distances.json` stores the Wikipedia infobox total distance per year. This is used in `all_races_summary.json` instead of summing DB stage distances, because PCS per-stage distances had 85 errors vs Wikipedia (some 100–200 km off). The per-stage distances in the DB (and shown in the Race Overview) still come from PCS and haven't been individually corrected.

### Difficulty score (Race Overview chart)
Computed client-side: `(vertical_meters² / (distance_km × 1000)) × route_type_multiplier`. Multipliers: P=0.3, TT=0.5, TTT=0.6, F=1.0, H=1.3, M=1.8.

### PCS data notes
- **Sprint points vs. PCS points**: The DB has a `pcs_points` column = PCS prestige ranking system, completely unrelated to the green jersey. Green jersey points come exclusively from `tour_sprint_points.json`.
- **1988 Prelude**: PCS lists 23 entries for 1988 — index 0 is an unofficial "Prélude" stage. The scraper drops index 0 for that year; `profile_icons.json` and `tour_sprint_points.json` do the same.
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
- **Database:** `~/Documents/GitHub/tdf-analytics/pipeline/cycling.db` (gitignored — back up with `pipeline/db_backup.py`)
- **Main site repo** (separate): hosts `www.ericshiflet.com`; TDF app lives at `/tdf-analytics/`
