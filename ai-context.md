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

## Open items as of 2026-08-18

Nothing here is broken-and-unknown; each is a deliberate stop with a reason. Read the linked section before picking one up.

**Landed 2026-08-18** (all on `main`, CI green): the year-aware Riders filters and
multi-select year dropdown (`15cdc9f`), the Riders-page performance work (`d4d2593`),
the smoke-test selector fix (`39033fc`), the doping note (`59e3cb9`), the classics
Sprint/KOM legend removal (`aadb139`), `th.col-stage` min-width (`57711fa`), the
stage-table sticky-column fix (`173ea6e`), and the km/mi toggle on the classics Race
History (`59404b8`). `verify-views.mjs` gained checks for the last of those, replacing
"race history hides the km/mi toggle" — that assertion had become the opposite of
intended behavior.

**Decisions waiting on Eric (do not guess):**
- **Project rename** — analysed and **deferred**; see "Renaming the project". If revived, take the subdomain step first.
- **Landing pages have identical visible body content.** The four `<race>/index.html` pages differ only in `<title>`/meta — the body is the same SPA shell, and the per-race subtitle line was deliberately removed in `58ce75f`. Giving them distinct visible copy would help them rank separately, but it's a UI/content decision.
- **Duplicate ranks + same-team bib collisions** in 13 classics race-years — upstream PCS, how to model it is Eric's call. See "Known-open".
- **More riders may belong on the doping list.** Five are recorded (see "Rider detail chart"). These re-award pairs are visible in the data and were deliberately NOT added without confirmation, since attributing doping to a named rider must not be inferred from a duplicate rank row: **Vuelta 2011** (Froome/Cobo — Cobo *is* listed), **Giro 2009** (Di Luca, Pellizotti, Valjavec), **Vuelta 2010** (Velits/Mosquera), **Vuelta 2022** (Almeida/López). Giro 1913/1932/1948 show the same duplicate pattern from old-data artefacts and are not doping.
- **TDF 2008 KOM has two rank-1 rows** in `classification_standings` — Bernhard Kohl (128 pts, stripped for doping) and Carlos Sastre (80, the re-award). Both therefore show a polka-dot jersey for 2008 on the Riders page. Keeping both is Eric's decision (2026-08-18): the jersey stays, and the rider detail page carries a "Some race results revoked for doping" note beside the name instead (`RIDERS_WITH_REVOKED_RESULTS` in `jerseyIcons.ts`). It is the only such duplicate in the DB. Modelling revocations in the DB itself — a flag on the row, so the app stops depending on a hand-kept list — is still open.

**Known-unfixable / explained, leave alone:**
- **Giro 1946 winner time** — PCS's figure implies 46.5 km/h over 3,050 km. Either the time or the distance is wrong and there's no way to tell which; storing nothing beats storing a number that fails its own check.
- **Tour 1904–1912, Giro 1909–13** — points-classification era, no time GC ever existed.
- **19 editions diverge >3% from Wikipedia on distance** — all investigated, none is a missing stage. See "Distance reconciliation".
- **8 of 19 cancelled stages have no recorded reason.** `validate_db.py` names them under `note` lines. Add a *sourced* reason or leave them; never invent a cause.

**Cost/quality items worth revisiting:**
- ~~**`classics/riders_index.json` is 2.93 MB / 719 KB gzipped**~~ — **addressed 2026-08-22**: re-encoded to 2.08 MB / 547 KB gzipped (-22%) and 24% faster to load. See "riders_index.json re-encoded" under Frontend performance. Still the largest single asset, so still the first thing to look at if coverage grows again.
- ~~**`export_gc.py --race tdf`** while everything else says `tour`~~ — **fixed 2026-08-22**: `--race tour` and `--race tdf` are now the same thing, `export_gc.py` uses the shared `resolve_race_arg()` instead of its own copy of the table, and `--race classics|gravel` names the right exporter instead of saying "unknown race".
- **Social cards are ~1.8 MB committed** across 6 PNGs (gravel added a sixth). Fine for every platform's limit; `pngquant` would roughly halve them.
- ~~**Flatten `byStage` in `gc_by_stage_*.json`**~~ — **measured and REJECTED
  2026-08-22. Do not re-propose without reading this.** Each rider's `byStage`
  is an array of 8-key objects, one per stage (Tour 1987 materialises 5,382 of
  them), and flattening to numeric arrays shrinks the corpus from **131.9 MB to
  41.0 MB raw (-68.9%)**. The size win is real. The runtime win is not worth
  having. Measured in the browser, median of 9 batches of 25, layout forced
  before every batch:

  | | Tour 1987 (692 KB) | classics 2021 (408 KB) |
  |---|---|---|
  | `JSON.parse` | 3.95 -> 1.30 ms (-67%) | 2.17 -> 1.20 ms (-45%) |
  | stageTable pass | 0.57 -> 0.52 ms | 0.44 -> 0.44 ms |
  | stageChart pass | 0.26 -> 0.06 ms | 0.07 -> 0.06 ms |
  | **total** | **4.78 -> 1.88 ms** | **2.69 -> 1.70 ms** |

  **A 3 ms saving on the worst file.** The percentages look excellent and the
  absolute number is imperceptible — for scale, the `riders_index` re-encode
  (PR #10) saved 60 ms, twenty times more. Against that: ~20 call sites in
  `stageChart.ts` and `stageTable.ts`, 469 regenerated files, and a permanent
  readability tax (`f[i+3]` where `sp.status` used to be).

  **The repo-size argument fails too, and fails backwards.** Git keeps the old
  blobs in history, so re-encoding would ADD ~41 MB of new objects to a 151 MB
  `.git` rather than removing 131 MB. It makes the repository bigger.

  Two shortcuts that would have improved the ratio were measured and do not
  work: `stage` cannot be dropped and inferred positionally (67,829 of 91,455
  riders have a sparse `byStage`), and `name` cannot be rebuilt from
  `firstName`/`lastName` (10.2% of riders have neither, and `displayName()`
  falls back to `name`).

  Two measurement traps worth keeping: `performance.now()` is clamped to 0.1 ms,
  so a single pass is 1-9 ticks of noise and the first attempt reported
  meaningless sub-millisecond figures until the work was batched; and
  `performance.memory` could NOT produce a trustworthy retained-size number here
  at any copy count -- 30 copies left the flat encoding below the counter's
  update resolution, 200 copies triggered GC mid-measurement and returned
  negative deltas. The only stable reading was the current encoding at
  359 KB/copy for Tour 1987, with the flat one too small to register.

- **Entering the Riders section costs 438 ms, once per session** — measured
  2026-08-22, and the fix is NOT the manifest I proposed. See "The Riders
  section's 438 ms" below.
- **2026 Vuelta** has not been run yet (last edition with data is 2025). When it finishes, follow "Finalizing a completed year".

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
granularity — `pcs`, `wikipedia`, `bikeraceinfo`, `cyclingflash`, `manual`, `derived`,
`unknown` — with the exact URL in `source_ref`. **Every writer must call
`record_provenance()`,** and the valid set lives in `race_common.VALID_SOURCES` only:
`validate_db.py` reads that frozenset rather than keeping its own copy, because the two
did silently diverge once and the validator rejected a source `record_provenance()` had
already accepted. A source
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
| `scrape_route_overview_elevation.py` | elevation from the race ROUTE page (stage pages omit Paris finales/prologues); `--replace-derived` |
| `patch_cyclingflash_elevation.py` | 2001/2006 s20 from cyclingflash.com; guards on distance before writing |

### State as of 2026-08-11

`validate_db` 0 errors / 3 warnings · `validate_exports` 302 files, 0 errors ·
**142 tests** passing (`python3 -m unittest discover -p 'test_*.py'`, runs in CI).
(**342 as of 2026-08-22**, after the gravel, patch-carry, export and validator suites.)
Every stage has a route, a date, a distance and a confirmed `source_slug`; 0 derived
slugs remain. Every Tour TTT has per-rider results. Elevation was the one field with a
real remaining gap; as of **2026-08-19** it is essentially closed — the race *route* page
carries the Paris finales and prologues that the stage pages omit, so 34 stages are now
scraped rather than NULL or derived (see the next section). **0 `derived` elevation values
remain.** Only 1991 s17 and 1998 s17 are genuinely absent from PCS.

**Known-open, deliberately not fixed:** 36 stages with two rank-1 finishers (doping DQs
where PCS lists both the stripped and the promoted rider — how to model a stripped win is
Eric's call, do not guess); 14 stages with no finishing positions (neutralised or
abandoned mid-race, plus three 1980s TTTs where PCS's rider tables are empty); 17 editions
with a sparse final stage. Test new work with **mutation checks** — substitute the
original bug back and confirm the test fails; that caught two blind spots in this pass.

---

## The Giro and the Vuelta share one scraper now (2026-08-22)

Three pairs of 85–95% identical files became three shared implementations plus
six thin wrappers, 2,006 lines down to 1,259:

| shared | was | overlap |
|---|---|---|
| `scrape_race.py` | `scrape_giro.py` + `scrape_vuelta.py` | 95%, 422 lines |
| `scrape_stage_info.py` | `scrape_{giro,vuelta}_stage_info.py` | 94%, 148 lines |
| `check_gc_times.py` | `check_{giro,vuelta}_gc_times.py` | 85%, 139 lines |

Everything that differed was the PCS URL slug, the output directory and the
words printed. `RaceInfo` gained `pcs_slug` and `cli` to carry the first two.

**The old names still work** — they are wrappers that call the shared module
with `--race` preset, so every recipe in this file is unchanged.

**The real win is test coverage, not line count.** The parsing is fixture-tested
(`test_scrapers.py` against `test_fixtures/`), but the tests imported
`scrape_vuelta`, so the Giro's identical 584 lines were untested and a fix
applied to one copy and not the other would have failed nothing. One
implementation means one suite covers both.

### One inconsistency preserved rather than silently resolved

`check_vuelta_gc_times.py` wrote `vuelta_gc_winner_times.json`; the Giro's
equivalent did not. Merging had to pick one, and either choice changes a
behaviour, so the write is now behind `--write-winner-times`, which the Vuelta
wrapper passes and the Giro's does not. Same behaviour as before, but the
difference is one visible line instead of a divergence buried in 139 duplicated
ones.

**RESOLVED 2026-08-22 — leave the Giro flag off. The file is curated, not
scraped.** Nothing writes `giro_gc_winner_times.json` because it was never a
script's output. Traced through git:

| commit | date | what it contributed |
|---|---|---|
| `68d585d` | 2026-07-17 | created it with 88 years, derived from `giro_races_summary_overrides.json`, which traces back to `check_giro_gc_times.py` → `giro_gc_time_corrections.json` → `apply_giro_gc_corrections.py` |
| `8e8e2f0` | 2026-08-15 | corrected 1959 and 1977 (they read 41:14:17 and 65:29:01 against local medians of ~106:50), read off PCS's own GC classifications |
| `4f82d99` | 2026-08-15 | filled 13 missing years, each winner name checked against the historical record and each time speed-checked against our stored distance |

The source is PCS throughout — it just arrived in three separate operations
rather than one script, so there was nothing to name as a writer.

**Why the flag must stay off.** `check_gc_times.py --write-winner-times` does
`winner_times[year] = pcs_time` for every year it sweeps, then writes the whole
dict. Running that for the Giro would **reintroduce 1946**, which `4f82d99`
deliberately omitted: PCS gives Bartali 65:32:20, which is 46.5 km/h over
3,050 km — impossible for the first post-war Giro and consistent with a partial
sum. A sweep cannot make that judgement; a person did.

The file now carries a `_README` block recording all of this, following the
same convention as `stage_notes.json` and `patched_values.json`. Readers that
parse its keys as ints skip `_`-prefixed entries; the rest use `.get(year)` and
are unaffected. Verified by re-running `export_gc.py`, `export_race_summary.py`
and `export_all_races_summary.py`: zero exported files changed.

**Extend it by hand**, verifying each value the way `4f82d99` did.

### `--help` no longer starts a scrape (fixed for all of them, 2026-08-22)

`check_gc_times.py` grew a private `-h/--help` guard after `--help` fell
through to a full run over every year, each one a live PCS fetch. An audit on
2026-08-22 found **17 more networked scripts with the identical hole** — every
`scrape_*` that parses argv by scanning for the flags it knows and ignoring the
rest. They all now call `race_common.exit_on_help(__doc__)` as the first
statement in `main()`, which prints the module docstring (where every one of
them keeps its usage) and exits 0.

`exit_on_help` exits rather than returning a flag on purpose: a caller that
forgets to check a return value is exactly the failure it exists to prevent.
argparse users were already fine and were left alone.

`test_scrapers.py` asserts the guard is in the first three statements of every
`main()` in that list, checked against the source rather than by running them —
running them is the thing being prevented.

**That audit also found a dead script.** `scrape_vuelta_gc_pages.py` imported
`HEADERS, td_text, dedup_time, parse_profile_icon, parse_info, parse_rows,
parse_year_args` from `scrape_vuelta`, which the Giro/Vuelta merge earlier the
same day had reduced to a thin wrapper exporting only `main()`. Every run had
been dying on `ImportError` since. Nothing caught it: the script has no tests
and CI never invokes it. Now imported from `scrape_race`, where the
implementation actually lives, and the same test suite imports all 17 so a
future merge cannot silently orphan one again.

---

## The Riders section's 438 ms (measured 2026-08-22)

Measured in the browser against the real app, MutationObserver-timed from hash
change to rendered chart, cold document:

| | |
|---|---|
| first open of a rider detail | **438 ms** to header, 457 ms to chart |
| of which network (5 fetches, parallel) | **48 ms** |
| of which parse + build | **387 ms** |
| every subsequent rider open | **86 ms** (median of 6) |

**It is CPU-bound, not network-bound.** 4,560 KB decoded, but the five fetches
overlap and finish in 48 ms; the other 387 ms is `JSON.parse` plus building
30,122 `RiderEntry` objects with their Maps and Sets. Sequential total 457.7 ms
against 438 ms measured in parallel — **parallelism buys ~4%**, which is the
clearest proof it is CPU-bound.

> **Per-race timings measured in a sequential loop are worthless — see
> "Where the index build time actually goes" below.** An earlier version of
> this section reported classics at 208.5 ms and 46% of the cost. That was an
> artefact of measuring it fourth: whichever race runs last carries the GC cost
> of every entry already on the heap. Measured alone on a fresh page, classics
> is 69 ms and tour is 83 ms.

### The bitmask manifest does not pay off — drop it

A `riderId -> bitmask` manifest (343 KB, measured at **30 ms** to parse and
build) would let a rider-detail open fetch only the indexes that rider appears
in. Applying the measured per-race costs to the real membership distribution:

| rider appears in | riders | mean cost |
|---|---|---|
| 1 race | 10,793 (60.9%) | 156 ms |
| 2 races | 3,254 (18.3%) | 301 ms |
| 3 races | 1,966 (11.1%) | 378 ms |
| 4 races | 1,692 (9.5%) | 453 ms |
| 5 races | 31 (0.2%) | 488 ms |

Mean 236 ms against 438 today. Three things kill it:

1. **The grid already needs all five, legitimately.** `selectedRacesForRiders()`
   returns every race when `state.ridersFilterRaces` is empty, which is the
   default — so opening the Riders LIST loads all five for the grid itself. The
   common path (Riders -> click a rider) has already paid the 438 ms before the
   detail view is reached, and no manifest changes that. It would only help a
   deep link straight to `#riders/<slug>`.
2. **The heaviest riders get SLOWER.** Anyone in 4 or 5 races pays 453-488 ms
   against 438 today, because the manifest is pure addition for them. Those are
   the riders whose pages are most worth visiting.
3. **It serialises a round trip.** The manifest must land before the index
   fetches can start. On localhost that hop is 7 ms; at a 200 ms RTT the mean
   goes to 436 ms and the entire win is gone.

### Progressive render — DONE 2026-08-22

`drawRiderDetail` no longer awaits `Promise.all` before drawing. It renders on
the first index containing the rider and folds each later one in.

| | before | after |
|---|---|---|
| name, meta line, toggles | 438 ms | **45-82 ms** |
| chart | 457 ms | 315-471 ms (unchanged, see below) |
| expected time to first content, all riders | 458 ms | **238 ms mean** |

**The chart is not faster, and cannot be.** The five index builds are
synchronous main-thread work that runs back to back, so a deferred chart draw
is starved until they finish. What changed is that the panel is no longer BLANK
for the whole wait — a deep link to `#riders/<slug>` used to show nothing at
all, with not even the "Loading riders…" message the grid has.

Consecutive arrivals coalesce: the deferred draw's timer is cancelled and
re-armed, so a rider in five races pays one chart render, not five.

**Three invariants, all of which broke or nearly broke in the first version:**

1. **Order.** `byRace` now fills in ARRIVAL order, i.e. network timing.
   Everything user-visible reads it back through `racesWithData()` /
   `racesToDraw()`, which re-sort into `RACE_IDS` order. The first version
   shipped "…, 1 Gravel, 16 Classics" one load and "…, 16 Classics, 1 Gravel"
   the next.
2. **Toggle state.** The bar is rebuilt on every arrival, so it reads
   `activeRaces` rather than assuming active — a race the user switched off
   must stay off.
3. **The guard needs the VIEW, not just the rider.** Switching views leaves
   `state.currentRiderId` set, so checking the id alone let a late index build
   a detail header inside the panel the user had already left. Under the old
   `Promise.all` there was one render and one chance to get this wrong; there
   are now five.

**The smoke harness could not have caught any of this**, and that mattered more
than the code. `verify-views.mjs` reads every file with `fs.readFileSync`
behind an already-resolved `Response`, so all five indexes arrive in `RACE_IDS`
order every run — the one thing that can go wrong is the one thing it could not
produce. It now has `bootProgressive(hash, delays, midLoad)`: per-race
artificial latency plus a hook that acts on the half-rendered view. Two traps
found building it — Vite hashes the asset filenames, so the delay map matches
on byte size against the source files (the first version matched nothing and
passed for the wrong reason), and switching off the only active race is refused
by design, so the scenario has to stagger two arrivals before it clicks.

Seven mutations, all caught.

### Build scheduling — DONE 2026-08-22, and the predicted win was the wrong one

Fetches still run in parallel; the BUILDS now go through a queue in
`riderIndexData.ts`. Clean A/B on an idle machine, cold document, 5-race rider:

| | before | after |
|---|---|---|
| name, meta, toggles | 110 ms | **48 ms** |
| **first chart** | **462 ms** | **60 ms** |
| chart appears in | 1 step, at the end | 5 steps (60/113/184/268/483 ms) |
| fully settled | 462 ms | 483 ms |

**Cheapest-first ordering, the thing this was proposed for, contributed almost
none of that: -5% mean and -0% median.** The prediction (238 -> 213 mean,
215 -> 102 median) assumed the queue picks the first build. It does not — the
first build is whichever fetch lands first, because nothing can be ordered
before there is more than one thing to order. Ordering only governs builds two
through five, which is worth little.

Two other parts of the same change did all the work:

1. **The parse moved inside the scheduled slot.** `fetchJson()` calls
   `res.json()`, so ~100 ms of `JSON.parse` — half an index's cost, and 52 ms
   for classics alone — ran eagerly for all five before any build started. The
   loader now fetches TEXT and parses in the slot, which also keeps peak heap
   to one parsed index instead of five.
2. **The yield between builds is a MessageChannel, not a timer.**
   `setTimeout(0)` is clamped to 4 ms once nested and throttled hard in a
   background tab — measured here returning after 318 ms and 1000 ms. Chaining
   five builds through it makes load time depend on whether the tab is focused.
   MessageChannel hops measured 0.1 ms.

Together those are why the chart draws five times instead of once: the
progressive rider detail could always update its header early, but its chart
draw is deferred a tick and five synchronous builds never let that tick happen.

Settling is ~20 ms later, which is the yielding paid for honestly.

> **Do not benchmark this on a busy machine.** The same all-five load measured
> 263 ms and 486 ms in consecutive runs while a 5,000-rider PCS scrape was
> running in the background. Pause the other work first — the scrape is
> cache-resumable, so pausing costs nothing.

---

## Rider names: "Vermeulen Alexey" and the 5,265 like it (2026-08-22)

**The symptom.** A rider shows as `Lastname Firstname` — Eric spotted
"Vermeulen Alexey" on the gravel pages. `displayName()` in `riderDisplay.ts`
returns `firstName + " " + lastName` when BOTH are present and otherwise falls
back to `full_name`, which for any PCS-sourced rider is stored in PCS's own
`Lastname Firstname` order. So the bug is never a wrong name — it is a rider
whose `first_name`/`last_name` are NULL.

**The real scope, measured.** It is not a gravel problem:

| race | riders | missing a split | |
|---|---|---|---|
| **classics** | 11,934 | **5,250** | **44%** |
| stage races | 8,996 | 27 | 0.3% |
| gravel | 3,569 | 28 -> **1** | fixed |

Gravel was where it was NOTICED because gravel riders are 99% Athlinks-sourced
and already `Firstname Lastname`, so the 28 PCS crossovers stood out. In the
classics nearly half are wrong, which reads as consistent rather than broken.

**The fix is a scrape, not a derivation.** `scrape_rider_details.py` reads
PCS's `<h1>`, which gives `Firstname Lastname` directly. A slug-based
derivation was tried first (`rider/alexey-vermeulen` + "Vermeulen Alexey" is
enough to split it) and validated against the 12,444 riders whose split is
already known: it reproduced 67%, disagreed on 195, and while most of those
disagreements were cases where the DERIVATION was the better answer ("Pérez
Francés José" is stored as `José Pérez` / `Francés`), it also fails whenever
the slug omits a middle name the full name carries — `rider/francisco-rodriguez`
against "Rodriguez José Francisco". Guessing there is exactly the thing
"never fabricate" rules out. The cache simply predates the classics and gravel
expansions: 5,260 of the 5,265 were never fetched.

### Applied 2026-08-22 — 4,505 names filled, 771 classics riders left

| race | before | after |
|---|---|---|
| classics | 5,250 missing (44%) | **771 (6.5%)** |
| stage races | 27 | 17 |
| gravel | 28 | 1 |

**4,505 NULL-fills, 0 overwrites** — nothing that already had a value was
touched. Verified in the app: "Alexey Vermeulen", "Alfons Schepers", "Edvald
Boasson Hagen" all render first-name-first.

The remaining 771 are simply not fetched yet; the scrape was still running when
this was applied, and the apply is incremental and idempotent. Finish it with:

```bash
cd pipeline
SCRAPE_DELAY=0.8 python3 scrape_rider_details.py --missing --race classics --dry-run
python3 scrape_rider_details.py --missing --dry-run     # sweeps up the stage races too
python3 db_backup.py && python3 scrape_rider_details.py --db-only
python3 export_classics.py && python3 export_gravel.py
for r in tour giro vuelta; do python3 export_gc.py --race $r; python3 export_riders_index.py --race $r; done
python3 validate_db.py && python3 validate_exports.py
```

Run `--db-only` WITHOUT `--missing`, as above: that re-applies every cached
rider, which is how the 39,031 `entity='riders'` provenance rows got
backfilled for riders whose names were already correct.

**A first name of `"A."` or `"."` is faithful, not a bug.** PCS itself records
many pre-war starters as "Bardella A." or "Van Muyten .", so the split puts the
initial where the first name goes. It reads oddly and it is what the source
says; a nicer rendering is a frontend decision, not a data one.

### DANGER: PCS answers an unknown rider with HTTP 200

`https://www.procyclingstats.com/rider/kvalsten` returns **200** and a
"Page not found" body. `parse_page()` took its `<h1>` as the rider's name, so a
dry run over 28 riders produced `first_name='Page not'`, `last_name='found'`.
Over the 5,260 still to fetch, every dead slug would have written that.

The word "born" appears in the error body too, so the birthday is no help in
telling them apart — the title/h1 is the only signal. `parse_page()` now
returns `display_name=None` for it, which makes every downstream step skip the
rider, and `test_scrapers.py` has eight cases covering it. **This was caught
only because the run was a `--dry-run` first.**

### The scraper is now scoped, and defaults are still dangerous

A bare `python3 scrape_rider_details.py` walks every rider in the DB — with the
cache as stale as it is, that is thousands of live PCS requests. Added:

```bash
python3 scrape_rider_details.py --missing --race gravel --dry-run   # read first
python3 scrape_rider_details.py --missing --race gravel --db-only   # then apply
```

`--missing` selects only riders whose first/last is NULL, `--race` narrows to
one race set (`classics`/`gravel`, or a `races.name`), `--limit N` caps the
run, and `--dry-run` fetches and caches but writes nothing, printing the change
table with NULL-fills separated from overwrites. A dry run still populates the
cache, so the follow-up `--db-only` needs no second fetch.

### Done and not done

- **Gravel: fixed.** 27 riders filled from PCS, 0 overwrites. The 28th,
  `rider/kvalsten`, has no PCS page at all — it keeps `last_name='Kvalsten'`
  and no first name, which is what the sources actually support.
- **Classics: 5,250 riders outstanding**, about 75 minutes at
  `SCRAPE_DELAY=0.8`. Not started — it is a long live-scrape and Eric's call.
- ~~**`riders` has no provenance at all**~~ — **fixed 2026-08-22.**
  `scrape_rider_details.py` now records `entity='riders'` provenance for every
  name field it writes, sourced `pcs` with the rider page as `source_ref`. The
  key question resolved itself: `entity_id` is declared INTEGER while
  `rider_id` is TEXT, and SQLite's type affinity leaves a non-numeric string
  alone, so the id round-trips and stays joinable to the table it describes —
  which a surrogate integer never would. `validate_db.check_provenance()` has
  an orphan check for it that compares as TEXT (a `CAST` would silently match
  nothing). A birthday the page did not supply is deliberately NOT claimed,
  since `update_rider()` COALESCEs it.

---

## Where the index build time actually goes (2026-08-22)

Investigated because the section above blamed the classics index. **It was
wrong, and the way it was wrong is the lesson.**

### Per-race timings from a sequential loop are an artefact

Timing `ensureRiderIndexFor` for each race in turn produced classics 208.5 ms
against tour 67.5 ms, and I reported classics as 46% of the cost. Measured
ALONE on a fresh page, the same two are:

| race | alone, fresh page | when run 5th | riders | year-entries |
|---|---|---|---|---|
| classics | **69 ms** | 246 ms | 11,934 | 44,105 |
| tour | **83 ms** | 59 ms | 5,471 | 16,380 |

Classics is 2.2x tour's riders and 2.7x its year-entries, and is **faster per
rider than tour** — it is the biggest, not the worst. Whichever race runs last
pays the GC cost of every entry already on the heap, and whichever runs first
pays the JIT warm-up for `buildRiderIndexFor`. Neither is a property of the
race.

**The cost is allocation volume, not any one index.** All five together
materialise 30,122 `RiderEntry` objects, 30,122 `Map`s, 30,122 `Set`s and
91,455 per-year objects — roughly 180,000 allocations. Classics is 40% of the
year-entries, which is exactly its share of the data.

### The obvious win is not safe: `teams` cannot be derived

`RiderEntry.teams` is a `Set<string>` built for all 30,122 riders on every
load, for a filter most sessions never touch, and every year already carries
its team. Removing it and deriving from `years` measured **565 -> 461 ms
(-18%)**.

**It is wrong, and the team filter caught it: 8 riders became 2.**

`mergedRidersForSelectedRaces()` keeps the FIRST entry for each (rider, year)
in `RACE_IDS` order. A rider who rode the Tour AND a classic in 1933 keeps the
Tour's 1933 entry, so the classics team for that year is unreachable from the
merged `years` map — the per-rider `Set` is the only thing that carries it.
Measured on the real data: 40 riders carry "Alcyon - Dunlop" only through that
Set, and 6 of the 8 for "La Française-Dunlop" are shadowed by a Tour entry in
the same season.

**This is a design constraint, not a latent bug.** The merged `years` is read
only for PRESENCE (`e.years.has(year)`, the year filter); the jersey filter and
the rider detail both read `riderIndexByRace[race]` per race, so nothing
displayed depends on which race won a shadowed year. `teams` being a separate
union is the deliberate compensation for a map that can hold one team per year.

So: reverted. If the ~18% is ever wanted, the shape that works is keying the
merged map on (race, year) rather than year — a much larger change.

### What the test suite gained

The team filter had never been APPLIED by a test — only "the dropdown is
populated" was checked, which is why an 8-to-2 regression could pass. It is now
checked against an **independent oracle**: the source `riders_index.json` files
are decoded directly, by hand, and the grid's count compared against them.
Checking the grid against the filter's own logic would only restate it.

Two teams are exercised, chosen from the data rather than hardcoded (a name can
be renamed by a re-ingest, a fixed index can land on an empty roster):

- the team with the most riders reachable ONLY through the per-rider set, which
  is what makes the derivation shortcut fail
- the team with the largest roster, which is Grand-Tour-heavy and covers the
  `y` branch of the build — dropping `teams.add()` there survived an otherwise
  passing suite when only the first team was tested

> **Two tooling traps, both of which produced false results before being
> noticed.** `verify-views.mjs` boots the BUILT bundle, so a mutation test must
> `npm run build` after editing source AND after restoring it — restoring
> without rebuilding leaves the previous mutant in `build/` and the next run
> tests the wrong code. And a mutation script writing to one shared backup path
> is not safe against a second sweep running in the background: two of them
> overlapped here and restored `riders.ts`'s contents into `riderIndexData.ts`.
> Use a unique backup path per invocation, and do not start a sweep while
> another is running.

---

## The validators have tests now (2026-08-22)

`test_validators.py`, 97 tests over the four `validate_*.py` scripts. They had
none, which was backwards: **`validate_db.py` cannot run in CI at all** (see the
pre-push section below), so it is the one guard whose correctness nothing else
was checking. Its behaviour had been established exactly once, by hand, by
replaying the damaged 2026-08-21 database through it.

**Fixtures are built from `schema.sql`**, not from a copy of it. An inlined
`CREATE TABLE` block is how `route_type` once went missing from the schema file
while the real DB had it. Foreign keys are ON, which caught two fixtures that
were quietly nonsense.

**What the tests are actually pinning** is the set of distinctions that look
like clutter and are not. Each of these was written for a specific incident and
each would be easy to "simplify" into a regression:

| distinction | what collapsing it costs |
|---|---|
| count DROP errors, RISE only notes | every run that adds a race-year fails |
| an exactly equal count says NOTHING | "rose from 1 to 1" on every clean run, and nobody reads the notes any more |
| orphan provenance: ERROR on `stages`, WARN on `stage_results` | loss vs litter — one is a destroyed value, one is a dead row |
| no-GC check scoped by INCLUSION (`race_type='stage_race'`) | excluding `'one_day'` stopped covering anything the day `'gravel'` arrived |
| phantom split day exempts a slug ending in a letter | Giro 1956 st9b and Vuelta 1978 st19b are genuine cancelled halves |
| phantom split day is scoped to CANCELLED stages | the same rule on every stage produced 33 false errors on correct data |
| duplicate-stage key includes the slug | Giro 1972's 12a/12b are one circuit twice, not one stage duplicated |
| carried-distance warning needs all four filters | 38 editions repeat a distance; only six are the Paris-finale bug |
| `validate_gc.name_match` has a last-name fallback, `validate_kom.name_match` does not | the GC references print initials; the KOM ones print full names, where a lone surname pairs up teammates |

**Verified by mutation** rather than by passing: 34 deliberate breaks were
introduced one at a time and all 34 failed a test. Six survived the first pass
and got tests written for them — two of those were real gaps in
`build_sequential_map`'s slow path, where the 10% distance tolerance and the
forward-only search could both be deleted with every test still green.

> **Trap when mutation-testing Python.** A mutation that keeps the file the same
> LENGTH (`>= 5` -> `>= 2`) and is reverted inside the same mtime second leaves a
> stale `__pycache__` entry that Python reuses, because invalidation keys on
> (mtime, size). It reads as a surviving mutant, or as a restored file that still
> fails. `rm -rf __pycache__` between runs.

**Still untested**, deliberately: the network-fetching halves of
`validate_kom.py` (`fetch_wikipedia_kom`, `fetch_bri_kom`) and
`validate_gc.load_our_gc`, which want HTML fixtures rather than unit tests.

---

## Pre-push hook (2026-08-22)

Work goes straight to main here — 305 of the repo's first 316 commits did — so
CI only ever reports breakage after the fact: the commit is already pushed, main
is already red, and the fix has to go forward. `scripts/pre-push` runs the same
checks first.

**Install** (hooks are not version-controlled, so a fresh clone needs this):

```bash
ln -sf ../../scripts/pre-push .git/hooks/pre-push
```

**Bypass** with `git push --no-verify`. It is a guard, not a gate.

It is **not redundant with CI**: `validate_db.py` cannot run there at all, since
`cycling.db` is gitignored and not regenerable in CI, so a DB-level regression
has no other automated guard anywhere.

Checks are scoped to what changed, because the smoke tests dominate the cost:

| check | cost | runs when |
|---|---|---|
| unit tests | 0.5s | `pipeline/` changed |
| `validate_exports.py` | 1.6s | `pipeline/` or `src/data/` changed |
| `validate_db.py` | 1.3s | as above, and the DB exists locally |
| `npm run build` | 1.3s | `cycling-app/` changed |
| smoke tests | 12.7s | `cycling-app/` changed |

A pipeline-only push costs ~3s rather than ~17s; a docs-only push runs nothing.

---

## DANGER: re-running ingest_classics.py reverts every DB-only patch (2026-08-21)

Found the hard way while refactoring. `ingest_classics.py` rebuilds each
race-year from `classics_scrapes/`, and **several corrections live only in the
database, never in those scrape files**. A full re-ingest silently discards
them and leaves no error behind:

| what is lost | restored by |
|---|---|
| Milan-San Remo 2013 distance (246 km, `wikipedia`) reverts to PCS's wrong 121.0 | `patch_msr_2013_distance.py` |
| ~1,900 team attributions filled from bikeraceinfo (84,800 -> 82,916) | `patch_classics_teams.py` |
| anything else patched post-ingest | its own `patch_*.py` |

The re-ingest itself is atomic and correct — that is the trap. Nothing fails,
counts stay identical (102,261 results either way), and the loss shows only if
you go looking at a specific value. It was caught here by checksumming the
results table before and after, then diffing against a backup.

**PREVENTED since 2026-08-21 (B2).** The ingests now carry patches across the
rebuild themselves. `capture_patches()` reads every patched value out of
`data_provenance` before the edition is deleted and `restore_patches()` hands it
back afterwards, keyed on stage_number and rider_id — never on stage_id or
result_id, both of which the rebuild re-issues. It is generic: anything that
recorded provenance travels, so no registry of patch scripts needs maintaining.
Wired into all three ingests (`ingest_classics.py`, `ingest_gravel.py`,
`ingest_race.py`). A full classics re-ingest is now byte-identical in its
exports, carrying 841 values.

Each carry is REPORTED, never silent, and a patch whose source has since caught
up is called out as retirable. A patch with nowhere to land — its stage or rider
gone from the rebuilt edition — is reported too rather than dropped.

The rule this depends on: **a patch must call `record_provenance()` for EVERY
column it writes.** `patch_classics_times.py` wrote `finish_time_seconds` and
`gap_seconds` but recorded only the first, so the carry-over restored half of it
and left 79 Gent-Wevelgem 2005 riders with a time and a NULL gap. Fixed, and the
missing rows backfilled.

**Still guarded too**, as a backstop for anything the carry-over cannot reach:
`validate_db.py` fails loudly on
a `patched_values.json` manifest of the 25 stage-field patches, value-count
invariants for the team/time patches, and a contradiction check. Replaying the
damaged DB through it produced three errors naming each loss. So the rule below
is still the rule — but forgetting it is now noisy rather than silent.

**Before any full `ingest_classics.py` run: back the DB up, and afterwards
re-run the patch scripts.** They are guarded — `patch_msr_2013_distance.py`
refuses to run unless it finds exactly the broken 121.0 — so re-applying is
safe and a no-op when unnecessary.

The same applies in principle to `ingest_race.py` for the Grand Tours, which
have far more patch scripts behind them.

`ingest_gravel.py` is currently exempt: every correction it makes lives in the
scrape files or `_course_map.json`, so a rebuild reproduces them. Keep it that
way — the moment a gravel value is patched into the DB alone, it joins this
table.

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
- **PCS can print a distance that contradicts its own average speed.**
  Milan–San Remo **2013** — the snow edition, neutralised at Ovada and restarted
  at Cogoleto — shows `Distance: 121 km` and `Avg. speed winner: 43.577 km/h`
  side by side on the same page. With the winner's 5h37m20s those disagree by a
  factor of two (121 km gives 21.5 km/h; PCS's speed implies 245 km), and 121 is
  most likely just the sector ridden before the stop. We scraped 121 faithfully,
  so it charted as a 21.5 km/h spike at half its neighbours' speed. Now stored
  as **246 km, `SOURCE_WIKIPEDIA`** (`patch_msr_2013_distance.py`) — a directly
  published distance rather than one back-computed from PCS's speed; the cost is
  that our 43.76 km/h reads 0.4% above PCS's 43.577, because PCS internally used
  245. **The lesson: `distance_km` from PCS is not self-validating.** Where a
  race carries a winner's time, distance/time is a free cross-check, and it is
  the only thing that catches this class of error.
  An audit of all 966 classics editions against each race's own 15-year median
  found no other edition beyond 25% off; the 1919 and 1945 Paris–Roubaix
  outliers (~24%) are war-damaged roads, not data errors.
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
- `classics/riders_index.json` is **2.08 MB / 547 KB gzipped** (re-encoded
  2026-08-22, PR #10 — was 2.93 MB / 719 KB). Still the largest single asset the
  app ships, because it carries every rider's per-race breakdown, and still bigger
  than the three Grand Tour indexes combined. It is lazy-loaded, so first paint is
  unaffected. The old advice here — "further shrinking would mean restructuring
  `m`" — is spent: `m` is gone, merged into `ym` by that re-encode.
  **The live cost is now the fan-out, not this one file.** `drawRiderDetail`
  (`riderDetail.ts:28`) awaits `Promise.all(RACE_IDS.map(...))` over all **five**
  indexes — 4,559 KB — on every rider-detail open, regardless of which rider.
  Measured 2026-08-22: 10,793 of 17,736 riders (61%) appear in exactly ONE race,
  and an ideal per-rider fetch would average 2,053 KB. A `riderId -> bitmask`
  manifest costs 343 KB raw / 110 KB gzipped and would cut the average to
  ~2,396 KB (-47%) on paper. **Measured 2026-08-22 and dropped** — the grid
  already loads all five legitimately, riders in 4+ races get slower, and the
  extra round trip erases the mean win. See "The Riders section's 438 ms".

---

## Gravel — the Life Time off-road races (August 2026)

Six American gravel and mountain-bike races, **1994–2026**, added 2026-08-21. In the
DB they are **6 independent races** (`races.race_type='gravel'`, one stage per
edition); the frontend shows **one** race, `gravel` — "Gravel" — whose
"stages" are those races. Same aggregation as the classics, done at export time
by `export_gravel.py`.

| slug | display | short | discipline | | slug | display | short | discipline |
|---|---|---|---|---|---|---|---|---|
| `sea-otter` | Sea Otter Classic | SO | mtb→gravel | | `chequamegon` | Chequamegon MTB Festival | CQ | mtb |
| `unbound` | Unbound Gravel | UB | gravel | | `little-sugar` | Little Sugar MTB | LS | mtb |
| `leadville` | Leadville Trail 100 MTB | LV | mtb | | `big-sugar` | Big Sugar Gravel | BS | gravel |

**89 race-years · 7,607 results · 3,569 riders · 93 of them already in the DB from their road careers.**

These six are today's Life Time Grand Prix line-up, but **the archive is
deliberately wider than that series**. The Grand Prix began in 2022; Leadville
has run since 1994 and Chequamegon since 1999 (on Athlinks — the race itself
dates to 1983). A season before 2021 therefore holds fewer than six races, the
same way a classics season before 1907 holds fewer than eleven. Nothing
special-cases it: ordering by `stage_date` renders it correctly for free.

**Men's fields only, for now.** These races run co-equal men's and women's
series and the women's half is a deliberate gap, not an oversight — `riders`
has no gender column, so adding it is a schema change and a second pass.

### PCS has nothing here — do not reach for it

Verified, not assumed: searching PCS for "unbound" returns zero results while
"gravel" returns plenty. No rider slugs, no team attribution, no ProfileScore,
no `won_how`. Every instinct the rest of this pipeline has about where data
comes from is wrong for these six races.

### The source: Athlinks, which Life Time owns

Life Time owns Athlinks, so for its own events this is the timer's own data
rather than a third-party aggregation. Three public, unauthenticated endpoints,
wrapped in `athlinks_api.py`:

| endpoint | gives |
|---|---|
| `alaska.athlinks.com/MasterEvents/Api/{masterId}` | every edition of a race: date, eventId, result count |
| `reignite-api.athlinks.com/event/{eventId}/metadata` | courses, distances in metres, **division names**, split intervals |
| `reignite-api.athlinks.com/event/{e}/race/{course}/results` | the field, paginated |
| `…/race/{course}/division/{d}/results` | one class inside a mass-start race |

Two things that are not obvious and cost real time:

1. **`reignite-api` 403s a default User-Agent.** It sits behind CloudFront. A
   browser UA plus a `www.athlinks.com` Referer returns 200. No key, no cookie.
2. **Page size is not fixed.** Results carry each rider's splits as
   Elasticsearch inner hits, so a course with many splits 400s
   ("Inner result window is too large") at a page size another course serves
   happily. `results()` starts at 100 and halves on failure.

### Which course is the race? — `_course_map.json`

This is the load-bearing decision of the whole pipeline and it gets its own
reviewed artifact, written by `resolve_gravel_courses.py`.

Athlinks addresses everything by numeric id and renames courses constantly
("DK 200" → "UNBOUND 200" → "Elite Men - 200 MILE"; "Chequamegon 40" →
"Pro/Elite Chequamegon 40"), and one edition can carry a dozen courses of the
same distance differing only by tandem/single-speed/relay. **A heuristic that
picks the wrong one does not fail — it produces a plausible, entirely fictional
race.** So: resolve once, write it down, review the table, then fetch by id.
Exactly the discipline `source_slug` enforces for PCS.

Three selection rules come out of it, and they are not interchangeable:

| rule | what it means | field kept |
|---|---|---|
| `elite_course` | the edition ran a separate top-level men's race | all of it |
| `elite_division` | one mass start, pro/elite class scored as a division inside it | that division |
| `open_field` | no pro class existed — the pros started with everyone | **top 100 men** |

`open_field` is the honest-but-lossy one. Before roughly 2016 these races had no
pro class at all: the eventual winner started alongside 1,800 people riding for
a buckle, scored as one list. There is no line in the data between "elite" and
"everyone else" because there was no line in the race, so **any cutoff is ours,
not the sport's**. `FIELD_CAP = 100` sits comfortably outside the competitive
front of every one of these races (the pro fields that DO exist run 36–143
riders) while keeping the archive to a size the Riders page can carry. Each
scrape file records `field_size_source` alongside `field_size_selected` so the
window is always visible as a window. **Editions with a pro class are never
truncated.**

Preference order matters: `Pro/Elite Men` outranks `Grand Prix Male`. The Grand
Prix is a 25-rider invitational inside the pro race; the pro race is the field
this archive is about, and Vermeulen and Stetina appear in the former only some
years and the latter always.

### Sea Otter is a festival, not a race

Athlinks models each Sea Otter discipline-day as its own **event**, with age
groups as "courses" and no distances. There is no lineage to pattern-match, so
`SEA_OTTER` in `resolve_gravel_courses.py` names the endurance round outright,
year by year:

| year | course | note |
|---|---|---|
| 2022 | Fuego XC 80k, "MEN OPEN" | the 2022 Grand Prix opener; **not** the bigger Fuego XC 40k event held the same week |
| 2023 | MTB Endurance – Fuego XL 67M | not La Gravilla, the gravel race that week |
| 2024 | Fuego XL | |
| 2025 | Sea Otter Gravel Men Elite/Pro | the round moved from MTB to gravel |
| 2026 | Sea Otter Gravel Men Elite | |

**Sea Otter before 2022 is deliberately absent.** Athlinks holds only
category-by-category XC results (Cat 1/2/3, no pro class) with no distances,
and no endurance race of this lineage existed. Calling the Cat 1 XC race the
same event would be a fabricated continuity. Also note the year-picking rule:
for every other race the edition is the Athlinks event with the most results;
for Sea Otter it is the *named* event, because the endurance race is never the
biggest one that week.

### Traps found the hard way

1. **A DNF's time is not a finish.** Athlinks fills `gunTime`/`chipTime` for a
   DNF from their last recorded split, so Leadville 2025 shows Tsgabu Grmay at
   1h33 for a 100-miler. Sorted by time, the DNFs win the race. Only a finisher
   keeps a time, and only a finisher keeps a rank — Athlinks numbers some DNFs
   anyway (it ranks one 21st in the 2025 Grand Prix division).

2. **Pre-2016 editions carry no `status` field at all.** Defaulting those to DNF
   marked all 100 riders of every early edition as non-finishers, nulled their
   ranks and threw away their times — and the files still looked perfectly
   well-formed. `row_status()` infers: a row with both a time and a finishing
   position is a finisher.

3. **`age: 0` means "not recorded".** Every Dirty Kanza 2012 and 2013 row has
   it. Stored as-is it becomes a rider born the year they raced.

4. **The plain course response usually omits `divisions` per rider.** Filtering
   client-side for the pro class silently returns nothing for most editions.
   Use the `/division/{id}/results` endpoint. Consequence: **`elite_division`
   editions carry no DNF rows** — a division counts its DNFs in
   `totalAthletes` but never serves them.

5. **A correctly-named elite course can be EMPTY.** Leadville 2025 publishes
   "Leadville 100 MTB - Elite Men" with zero athletes while the real pro field
   sits in the mass-start course tagged `Pro/Elite Men`. The resolver probes
   every candidate's athlete count before committing.

6. **Mojibake and inconsistent case, both upstream.** Athlinks serves Andrew
   L'Esperance's apostrophe as UTF-8 read through MacRoman, and its case is
   per-event, not per-name — Sea Otter 2026 ships "bradyn lange" while
   Leadville 2026 ships "Bradyn Lange". Left alone, the same rider becomes two.
   `clean_name()` repairs both; it title-cases only strings that arrive all-one-
   case, so "McElveen" survives by not being touched.

7. **Distance is per-course and occasionally nonsense** (2024's "Circuit Race"
   and 2026's "Dual Slalom" are both listed at exactly 100.00 km). The
   resolver's km band is the guard. Note Leadville's own figure moved from
   160.93 km (the nominal 100 miles) to 169.43 km in 2025 — the race has always
   been about 104 miles, and that is a measurement change, not an error.

### Rider identity — the crossover, and what protects it

The point of having these races in the same app as the Tour is that Peter
Stetina rode seven Tours and then went gravel, and Alexey Vermeulen, Lachlan
Morton, Alex Howes, Ian Boswell, Laurens ten Dam, Petr Vakoč, Greg Van
Avermaet, Niki Terpstra, Thomas De Gendt, Taylor Phinney, David Millar and
Floyd Landis all cross the same line. If the ingest minted a second identity
for them, the Riders detail page would show two half-careers and the crossover
would be invisible.

PCS has no id to join on, so names are all there is — and a name match is a
claim about a person. `link_gravel_riders.py` makes that claim explicitly,
records its evidence, and writes `_rider_ids.json` for review. A **wrong merge
is the expensive error**: it fuses two careers and nothing downstream can tell.
So a match requires *all* of:

* exactly one existing rider with the same folded name **token set** (the DB
  stores PCS's "Vermeulen Alexey", Athlinks ships "Alexey Vermeulen")
* at least two name tokens
* **career plausibility** — the road results within `CAREER_SPAN` (30) years of
  the gravel result. This does most of the work: it is what stops a 2014
  Leadville amateur from being merged into a 1930s Tour rider of the same name.
* birth years within 2, when both sides know one

Anything else mints `rider/<slug>` — or `<slug>-gvl` when that slug belongs to
someone the rule just declined to match, so the merge cannot come back in
through the door.

**Known limitation: homonyms *inside* the gravel corpus are not split.**
Identity there is by name, the same basis PCS uses, and Athlinks gives nothing
better (`racerId` is null on most rows). `_rider_ids.json` flags
`homonym_suspect` where one name's implied birth years disagree by more than
three, but flagging is all it does — and deliberately. The signal is not
conclusive in either direction: Lachlan Morton's Dirty Kanza 2019 row records
his age as 19 when he was 27, so that spread is one upstream typo rather than
two riders, while Ryan Sellner's 1967 and 2003 in the same Minnesota town
really do look like a father and a son. Splitting automatically would fracture
the real crossover riders to fix a handful of amateur collisions.

`birth_year_approx` is the **median** of the implied years, not the mean, so one
mistyped age cannot drag it.

### What is NOT stored, and why

| field | why |
|---|---|
| `vertical_meters` | Athlinks publishes no elevation; PCS has nothing. Published figures disagree wildly — 11,586 ft and 14,517 ft for the same Leadville course, from two RideWithGPS traces. A NULL is a gap; a guess would be a claim. The Race Overview hides its elevation and difficulty metrics automatically (`hasElevationData`). |
| `profile_score` | PCS's metric, and PCS has nothing here. |
| `team_id` | Athlinks records no team. lifetimegrandprix.com does — but only ONE team per athlete, their current one, so attaching it to a 2022 result would be fiction. |
| season points | Life Time's own 30-to-1 Grand Prix scale exists, but it scores a 25-rider invitational, not the race. `hasSeasonPoints: false`; the bump chart plots finishing position, as the classics' does. |
| women's fields | Deliberate, and the next thing to do here. |

`route_type` carries **`G` (gravel) / `X` (mountain bike)** rather than F/H/M.
These are not points on the climbing scale — with no elevation there is no
honest way to grade them — they encode **surface**, which is what actually
distinguishes these races. Leaving the column NULL was the alternative, and
that paints Unbound flat green in the Race Overview, which is a claim rather
than a gap. `SOURCE_DERIVED`, from the discipline.

`nationality_code` for a gravel-only rider is Athlinks' **registered location
country**, not necessarily nationality — Torbjørn Andre Røed races as Norwegian
out of Grand Junction, Colorado. It is stored because it is right for the
overwhelming majority, and it is **never** allowed to overwrite a nationality
that came from PCS.

### Pipeline

```
resolve_gravel_courses.py   → gravel_scrapes/_course_map.json   (REVIEW THIS)
       ↓  scrape_athlinks.py
gravel_scrapes/<race>/<year>.json        (tracked in git; _raw/ is not)
       ↓  link_gravel_riders.py          → gravel_scrapes/_rider_ids.json
       ↓  ingest_gravel.py               (--dry-run; atomic per race-year)
   cycling.db                            (6 races, race_type='gravel')
       ↓  export_gravel.py               → cycling-app/src/data/gravel/
       ↓  export_classics_history.py --set gravel
```

`gravel_scrapes/_raw/` is a **gitignored local cache** of raw API responses.
It exists because the selection logic needed several corrections after the
fetch, and re-deriving from cache takes seconds where re-fetching 90 editions
takes half an hour. Delete it to force a true refetch.

### Cross-source validation: `crosscheck_ltgp.py`

Athlinks cannot check the course map — the wrong course returns a perfectly
well-formed race. But Life Time publishes each Grand Prix athlete's finishing
**place and time** for every round, on `lifetimegrandprix.com/athlete/<slug>/`,
server-rendered and parseable with a plain fetch. That is an independent oracle
for the riskiest decision in the pipeline, and if a course pick were wrong every
rider on it would mismatch at once.

It covers 2022–2026 and Grand Prix athletes only, so it verifies the modern
editions and says nothing about Leadville 1994 — which is still the half where
the course structure changes most.

Its last run: **385 results agree with Life Time on both place and time.** The 92
that do not are grouped by edition, and every one is a systematic difference
between two sources rather than a wrong course:

| edition | agree | what differs |
|---|---|---|
| Leadville 2022 | 0 | **every** time +60s. Two clocks, not sixty defects |
| Sea Otter 2026 | 53 | 19 times, median +19s — Life Time publishes chip, the division was scored on gun |
| Unbound 2026 | 7 | 33 places, median +3 — the two sources count a different field |
| Leadville 2024 | 9 | one rider (Vermeulen: Life Time says 113th, we say 57th — overall place vs place among pros) |

**None of those place gaps is an error — all three are Life Time answering a
different question**, and it is worth writing down which, because the next
person to read that table will assume the worst:

| gap | why |
|---|---|
| Leadville 2022, Roberge 54 vs 59 | The "LT100 Pro" course is MIXED — 79 men, 35 women. We rank among men; Life Time ranks the mixed field. Five women finished ahead of him, and **54 + 5 = 59** exactly. Only one rider of the twelve checked differs because the rest are far enough forward that no woman is ahead of them. |
| Leadville 2024, Vermeulen 57 vs 113 | 57th of the 70 in the Pro Male division; 113th in the whole 1,738-rider mass start. |
| Unbound 2026, median +3 | We classify 91 finishers of 117 elite men, having downgraded 18 rows Athlinks flagged CONF with checkpoint times. Life Time evidently excludes a few more of the same, so its numbers run ~3 lower. |

The archive's rank always means **position among men in the top-level field**,
applied identically to all 89 editions. For a men-only elite course — most of
them — that is the same number the source publishes.

### Adding a new season, or a new race

```bash
cd pipeline
python3 resolve_gravel_courses.py --race leadville     # then READ the table
python3 resolve_gravel_courses.py --report             # or re-read it later, offline
python3 scrape_athlinks.py --race leadville --year 2027
python3 link_gravel_riders.py                          # idempotent; re-run after ANY scrape
python3 ingest_gravel.py --dry-run                     # then without --dry-run
python3 export_gravel.py                               # no --year: the index is cross-year
python3 export_classics_history.py --set gravel
python3 validate_db.py && python3 validate_exports.py
python3 crosscheck_ltgp.py                             # 2022+ only
```

A new race needs a `GRAVEL` entry in `race_common.py` (with its Athlinks
masterEventId), a `HEADLINE` pattern and km band in
`resolve_gravel_courses.py`, and nothing else — the frontend discovers the data
by glob.

**`scrape_athlinks.py --force` re-derives from the raw cache without refetching.**
Every selection rule in this pipeline has needed correcting after the fact; that
is what the cache is for.

### Decisions taken (2026-08-21) — all five closed

Every judgement call this build had to make is now Eric's, not mine. They are
kept here rather than deleted because each one is a live knob: the reasoning is
what a future change has to argue against.

1. **Name: "Gravel"** (slug `gravel`). Not "Life Time Grand Prix" — the archive
   starts in 1994 and that series began in 2022 — and not "Gravel & MTB":
   three of the six are mountain-bike races and say so in their own names
   (Leadville Trail 100 MTB, Chequamegon MTB Festival, Little Sugar MTB), so
   the set label does not need to.
2. **Six races, not eight.** Crusher in the Tushar (Grand Prix 2022–2024) and
   The Rad (2023–2024) stay out. Consequence to remember: the Grand Prix's own
   2022–2024 standings cannot be reconciled against this archive, because two
   of those seasons' rounds are missing by choice. Adding one later is a
   `GRAVEL` entry plus a `HEADLINE` pattern and nothing else.
3. **`FIELD_CAP = 100` stands.** The only invented number here — it decides how
   much of a pre-2016 mass-start field the archive keeps, and any cutoff is
   ours rather than the sport's, because those races had no pro class to draw
   the line at. Change the constant and re-run `scrape_athlinks.py --force`;
   the raw cache makes that seconds, and every scrape file records
   `field_size_men` beside `field_size_selected` so the window stays visible as
   a window.
4. **Leadville 2022 keeps Athlinks' clock.** Every 2022 Leadville time is
   uniformly 60s later than Life Time's published figure. Eric's call was
   conditional on the finishing ORDER being unaffected — it is, since a
   constant offset applied to every rider cannot reorder them, and the one
   apparent counter-example (Roberge 54 vs 59) is the mixed-field arithmetic in
   the table above, not the clock.

5. **Sea Otter starts in 2022, and stays there.** Closed 2026-08-21 after
   actually checking, which corrected an earlier claim in this file: the
   pre-2022 data is *not* simply "Cat 1/2/3 with no pro class".

   What the check of all 180 Sea Otter events in the Athlinks master found:

   - **The Fuego XL does not exist before 2022 in any form.** There is nothing
     to extend back to under that name. The 2022 Grand Prix round was the
     *Fuego XC 80k*; "Fuego XL" first appears in 2023.
   - A pro XC class **does** exist in about eight scattered years — 2007, 2008,
     2010, 2011, 2012, 2015, 2017, 2019 — under names like "XC Men Pro",
     "XC Men ProXCT Pro", "Men Elite - Cross-country Olympic". So the earlier
     "no pro class" note here was wrong.
   - But 2009, 2013, 2014, 2016 and 2018 have no identifiable pro class, and
     2020–2021 have no XC endurance event at all.
   - **Every pre-2022 XC course carries distance 0.0.** No distances anywhere,
     which removes both winning speed and the distance bar — the two metrics
     that make Leadville's thirty years worth looking at. It would plot as a
     row of dots with no y-value.
   - It is a ~90-minute Olympic-format lap race, not a 3–4 hour endurance
     event. Splicing it onto the Fuego XL lineage would make one series mean
     two incompatible things, and its speed trend would show a step change
     meaning only "we changed which race we are measuring".

   Eric's point that the Fuego XL was ridden by gravel racers despite being an
   officially MTB race is correct, and is already the organising principle of
   the whole set: these six are grouped by FIELD, not by surface, which is the
   same reason Leadville and Chequamegon sit in a race called "Gravel".
   `route_type` carries the surface per edition (Sea Otter is `X` for 2022–2024
   and `G` from 2025) so the set can say "this is the gravel scene" while the
   data still says what each race was ridden on.

   **One alternative was considered and rejected.** The Fuego XL still runs
   under its own name — 106.22 km with a Men Elite division, 39 riders in both
   2025 and 2026 — so "the Fuego XL, 2023–2026" would be a cleaner single
   identity than the round-following lineage that changes race in 2025. But
   from 2025 the top-level men's field moved to the Gravel 90; the Fuego XL's
   39 is now the second-tier race (Alex Wild won it in 2025, not Swenson).
   Since this archive is defined as *the top-level men's field*, following the
   round is the consistent choice and following the Fuego XL would mean
   deliberately tracking the weaker race for the two most recent years.

   Worth stating plainly so it is not re-investigated: **Sea Otter is the one
   race in this set with no deep history to find.** Leadville reaches 1994,
   Chequamegon 1999, Unbound 2007 — but Sea Otter's endurance race is simply
   new. That is a fact about the race, not a gap in the archive.

   If it is ever wanted anyway, the clean shape is a SEVENTH race, "Sea Otter
   XC", kept separate so its identity never collides with the endurance round —
   and it would land with no speeds and no distances.


---

## Paris-finale elevation: the route page, and the reconstruction it replaced (August 2026)

> **Corrected 2026-08-19. The premise of this section was wrong.** PCS *does* publish
> these figures. It leaves `Vertical meters` blank on the **stage** page — which is all
> any scraper here had ever read — but carries the same numbers on the **race route**
> page, `/race/tour-de-france/<year>/route/stages`. Nothing needed deriving. The
> reconstruction below has been **withdrawn from the database** and is kept only as
> history and as the method for the two stages PCS genuinely lacks.

`scrape_route_overview_elevation.py` reads that page: one request per edition instead of
one per stage, matched on each row's own `source_slug`, stamped `SOURCE_PCS`. It fills
NULLs only, **except** under `--replace-derived`, which also overwrites values this repo
computed itself — a scraped figure always beats a reconstruction. It never touches `pcs`,
`wikipedia`, `bikeraceinfo`, `manual` or `unknown` provenance.

**Parse only the "Stages" table.** The page's second table, "Hardest stages", links the
same stage URLs but its last cell is the ProfileScore — parsing the whole page reads 395
as Alpe d'Huez's vertical metres, and every figure comes out wrong-but-plausible.

The 1990 Tour is what exposed this: it charted 38,940 m, the lowest total on record, which
turned out to be PCS's own 40,225 m minus a Paris finale nobody could read.

### What is now stored (all `SOURCE_PCS`, scraped 2026-08-19)

24 stages were filled from NULL (Paris finales 1990–2000, prologues through 2012). The ten
2001–2010 finales then **replaced** the derived values, Eric having approved the swap:

| year | stage | km | derived → **PCS** | m/km |    | year | stage | km | derived → **PCS** | m/km |
|---|---|---|---|---|---|---|---|---|---|---|
| 2001 | 20 | 160.5 | 980 → 1873 → **1791** ᶜ | 11.2 |  | 2006 | 20 | 154.5 | 1090 → 376 → **1012** ᶜ | 6.6 |
| 2002 | 20 | 140.0 | 585 → **1423** | 10.2 |  | 2007 | 20 | 146.0 | 885 → **796** | 5.5 |
| 2003 | 20 | 152.0 | 730 → **757** | 5.0 |  | 2008 | 21 | 143.0 | 900 → **807** | 5.6 |
| 2004 | 20 | 163.0 | 725 → **1453** | 8.9 |  | 2009 | 21 | 164.0 | 650 → **521** | 3.2 |
| 2005 | **21** | 144.0 | 855 → **851** | 5.9 |  | 2010 | 20 | 102.5 | 660 → **481** | 4.7 |

ᶜ **2001 s20 and 2006 s20 are `SOURCE_CYCLINGFLASH`, not PCS** (`patch_cyclingflash_elevation.py`,
2026-08-19). PCS's route-page figures for these two were the only outliers in the set —
376 m (2.4 m/km) and 1873 m (11.7 m/km) — and cyclingflash.com's "Elevation gain" gives
1012 and 1791 instead. Eric supplied both, with distances (154.5 / 160.5 km) that match
this DB exactly, which is what confirms both sites mean the same stage. **Not
independently verified:** cyclingflash.com sits behind Cloudflare bot detection and
refuses automated fetches, so the rows carry the citing URL and say so. The 2006
correction is the significant one — 376 → 1012 moves it from below every modern finale
into the normal band. 2001 barely moves (1873 → 1791), which is itself a result: a second
source broadly agreeing means 2001 really was an unusually hilly run-in, not a PCS error.

**How badly the reconstruction did:** 2005/2003/2007/2008 landed within 1–11%, but 2001
and 2002 came in at roughly *half* the real figure, 2004 at half, and 2006 ran **2.9x
over**. The method's own validation had called those four its most confident results. Read
that as the cost of deriving anything at all — not as a tuning problem.

**The "4–8 m/km is a sanity band" rule is falsified** and must not be reapplied. It was
calibrated on the derived set. Real values run 4.7 to 11.2 across 2001–2010, and the
scraped 2011+ finales reach 11.6 (2026) and 8.5 (2025) — so the band's *ceiling* is
simply wrong. Its floor did useful work, though: it is what flagged 2006's 2.4 m/km as
worth a second source, and that one turned out to be a genuine bad figure. Treat a
reading outside 4–8 as a prompt to go find another source, never as licence to adjust
the number.

**Genuinely absent from PCS everywhere** — stage page *and* route page — and still the
only two stages needing reconstruction: **1991 s17** Gap→Alpe d'Huez and **1998 s17**
Albertville→Aix-les-Bains.

**Deliberately NOT changed:** 2005 s14 and 2006 stages 4/5/6/10/13, where the route page
runs 0.3–5% *under* our stored stage-page values (all `unknown` provenance, old scrape).
Likely a PCS re-measurement. Eric chose to leave these and investigate separately — the
right shape for that is a mode auditing route-page vs stored across *every* edition, not
just ones with gaps.

### The lesson

This is the case where the scrape-from-PCS rule looked inapplicable but wasn't. The
field was blank on the page we checked, so "PCS doesn't have it" felt like an observation
rather than an assumption. **Before deriving anything, check every PCS page that could
carry the field** — the route page, not just the stage page.

---

## The reconstruction method (withdrawn from the DB; kept for 1991 s17 and 1998 s17)

Retained because two stages still need it, and because the traps below cost real time to
find. Values produced this way are `SOURCE_DERIVED` and are always second-best to a scrape.

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
provenance source + script name). That last property is why the withdrawal was safe — and
why re-running it today is a no-op: it will not overwrite the `pcs` values that replaced
its own. It also treats a stored `0` as missing — 2006 s20 was the only TDF stage carrying
`vertical_meters = 0` / `profile_score = 0`, a blank PCS field parsed as zero, and its
bogus `profile_score` is nulled rather than left in place.

**Still open, and unaffected by the correction:** **2002's stored `distance_km` is 140.0
but its ASO profile is titled 144 km** and its axis runs to 144. The elevation used the
profile's internal structure and the distance field was left untouched. Worth reconciling.

---

## Repository Structure

```
tdf-analytics/
├── .github/workflows/deploy.yml      # GitHub Actions: builds + deploys on push to main
├── ai-context.md                     # This file
├── cycling-app/                      # Vite web application
│   ├── index.html                    # App shell (nav buttons, sidebar, chart area) + the root page's
│   │                                 #   canonical/og/twitter/schema tags — the TEMPLATE the landing
│   │                                 #   pages are generated from, so renaming a meta tag here now
│   │                                 #   fails the generator loudly instead of silently
│   ├── vite.config.ts                # base: "/tdf-analytics/" — required for GitHub Pages.
│   │                                 #   rollupOptions.input is DERIVED from race-page-meta.mjs
│   ├── race-page-meta.mjs            # Data-only: SITE (canonical host) + per-race title/description/
│   │                                 #   image/alt. Read by BOTH the generator and vite.config.ts
│   ├── generate-race-pages.mjs       # prebuild/predev: writes <race>/index.html, public/sitemap.xml
│   │                                 #   and public/robots.txt. Throws if a rewrite matched nothing
│   ├── og-image.html                 # Social-card template — iframes the live SPA and hides chrome.
│   │                                 #   NOT in vite input, so it never ships
│   ├── scripts/render-og-images.sh   # Screenshots the 6 og-*.png cards with headless Chrome against
│   │                                 #   a running dev server. Run by hand; never in npm run build
│   ├── public/og-*.png               # The 6 rendered 1200×630 social cards (committed)
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
│       └── data/                     # Generated JSON — one directory per race, one file per year.
│           │                         #   NOTHING lives at data/ root any more: the TDF files moved
│           │                         #   into tour/. Both loaders glob per-race — raceRegistry.ts
│           │                         #   globs data/*/all_races_summary.json, classicsHistory.ts
│           │                         #   globs data/*/race_history.json — so a race is wired up by
│           │                         #   the FILES IT HAS, and the two summary files are exclusive:
│           │                         #   stage races get all_races_summary, aggregate sets get
│           │                         #   race_history. Counts below verified 2026-08-22.
│           ├── tour/                 # Tour de France — 113 years, 1903–2026
│           │   ├── gc_by_stage_YEAR.json  # One per year, lazy-loaded, one chunk each
│           │   ├── all_races_summary.json # Cross-year aggregate for the All Years view
│           │   └── riders_index.json      # 5,471 riders / 633 teams — 787 KB
│           ├── giro/                 # Giro d'Italia — 109 years, 1909–2026
│           │   ├── gc_by_stage_YEAR.json
│           │   ├── all_races_summary.json # built by export_race_summary.py --race giro
│           │   └── riders_index.json      # 4,718 riders / 712 teams — 666 KB
│           ├── vuelta/               # Vuelta a España — 80 years, 1935–2025 (2026 not run yet)
│           │   ├── gc_by_stage_YEAR.json
│           │   ├── all_races_summary.json
│           │   └── riders_index.json      # 4,430 riders / 581 teams — 593 KB
│           ├── classics/             # One-day classics — 134 years, 1892–2026
│           │   ├── gc_by_stage_YEAR.json  # An aggregate "season": N races ordered by stage_date,
│           │   │                          #   NOT stages of one race. See "by-Stage Table for an
│           │   │                          #   aggregate race"
│           │   ├── race_history.json      # Per-race small multiples. No all_races_summary.json
│           │   └── riders_index.json      # 11,934 riders / 1,637 teams — 2,078 KB, the largest
│           │                              #   single asset the app ships
│           └── gravel/               # Life Time off-road races — 33 years, 1994–2026
│               ├── gc_by_stage_YEAR.json  # Aggregate season, same shape as classics
│               ├── race_history.json      # No all_races_summary.json — this set awards no points
│               └── riders_index.json      # 3,569 riders / 0 teams (no team data off-road) — 436 KB
└── pipeline/                         # Data pipeline — not deployed
    ├── cycling.db                    # SQLite DB (gitignored, ~140MB, NOT regenerable — back up with db_backup.py)
    ├── db_backup.py                  # Rotating DB backups → db_backups/ (auto-run by add_stages.py before deletes)
    ├── export_gc.py                  # Main exporter: cycling.db + JSON supplements → src/data/
    │                                 #   --year N for single year, --race {tour,giro,vuelta}.
    │                                 #   "tdf" is accepted as an alias for "tour" (historical)
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
    │                                 #   13 entries as of 2026-08-18, all of which CHANGE the computed value:
    │                                 #   13 slowestFinisherTimeSeconds corrections. The 5 totalElevationM nulls
    │                                 #   left after 2026-08-15 became no-ops once the exporter suppressed sparse
    │                                 #   elevation by rule — see "Cancelled stages and sparse elevation" below.
    │                                 #   Was 88 entries — the other 70 pinned what the exporter already computed
    │                                 #   (see "No-op overrides" below; audit_summary_overrides.py finds them)
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
    ├── audit_summary_overrides.py    # Finds override fields that pin what the exporter already computes.
    │                                 #   --strip removes them and verifies the shipped JSON is unchanged
    ├── scrape_wiki_distances.py      # Builds {giro,vuelta}_race_distances.json from Wikipedia infoboxes
    │                                 #   via the MediaWiki API (50 titles/request, no bot challenge)
    ├── giro_race_distances.json      # Official Giro distance per year (109/109) — reconciliation only, not exported
    ├── vuelta_race_distances.json    # Official Vuelta distance per year (80/80) — reconciliation only, not exported
    ├── distance_divergence_baseline.json # Already-investigated >3% divergences per race, with a reason each.
    │                                 #   Only NEW divergences warn; --strict fails on new ones only
    ├── stage_notes.json              # Why a cancelled stage legitimately has no results, so it isn't
    │                                 #   re-scraped forever. Keyed by DB stage_number, NOT the PCS slug
    │                                 #   number (they diverge after a split day). Loaded by
    │                                 #   race_common.load_stage_notes(); validate_db.py reports gaps
    └── vuelta_races_summary_overrides.json # Per-year field overrides for export_race_summary.py --race vuelta
                                      #   4 entries as of 2026-08-15 (1978, 1982, 1984, 1994), all
                                      #   slowestFinisherTimeSeconds. Was 78 — see "No-op overrides" below
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
    ├── scrape_route_overview_elevation.py # vertical_meters from the RACE ROUTE page, which
    │                                   #   carries the finales/prologues the stage pages leave
    │                                   #   blank. Fills NULLs; --replace-derived also supersedes
    │                                   #   this repo's own reconstructions. Parse ONLY the
    │                                   #   "Stages" table — see the Paris-finale section.
    ├── patch_paris_finale_elevation.py # SUPERSEDED 2026-08-19 for 2001-2010 (PCS had the
    │                                   #   figures all along). Reconstructed vertical_meters
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

### Distance reconciliation (all three races as of 2026-08-15)

`totalDistanceKm` is checked against Wikipedia's published route total for **every** race now, not just the TDF. A summed stage distance always looks plausible, so an edition missing whole stages produces a total that is merely small — there is nothing in the number itself to notice, which is how the 2010 Vuelta sat two stages short until a human spotted it in the UI.

- **Sources**: `wiki_race_distances.json` (TDF, pre-existing), plus `giro_race_distances.json` and `vuelta_race_distances.json` built by **`scrape_wiki_distances.py --race {giro,vuelta}`**. It reads the MediaWiki API rather than rendered pages — raw wikitext means the infobox is a literal `| distance = 3467.0` instead of prose to regex out of HTML, and 50 titles fit in one request, so all 189 editions take ~4 calls. Wikipedia has no bot challenge, unlike PCS. Coverage came out **109/109 Giro and 80/80 Vuelta**.
- **The DB sum is still what gets exported for Giro/Vuelta**; Wikipedia is only the check. The TDF displays Wikipedia's figure because its PCS stage sums had errors 100–200 km wide — not the case here, where the median disagreement is **0.13% (Giro) / 0.23% (Vuelta)** and 186 of 189 editions sit under 1%. Displaying the DB also keeps a defect visible in the UI instead of masking it behind a correct-looking total only the console mentions.
- **`distance_divergence_baseline.json`** is what makes the check usable. 18 editions disagree by >3% for reasons that are not defects (20 until Vuelta 1957 and 1968 turned out to be the cancelled-stage bug — see "Cancelled stages and sparse elevation"), and a warning that prints the same rows forever is one nobody reads — worse, `--strict` could never pass, so nothing would ever gate on it. Baselined years print as a one-line count; only a **new** divergence gets the table, and `--strict` fails on new ones only. Every entry needs a real reason (a test enforces non-empty ones) — silencing a year without recording why is the failure the file exists to prevent.

**No missing stages were found.** Every divergent edition has contiguous stage numbering and a full stage count. Two carry a stage stored as `0.0` km with no results — the convention for a stage that produced no classification — of which **Giro 2011 stage 4** is the interesting one: Quarto dei Mille → Livorno was ridden as a neutralized procession after Wouter Weylandt's death on stage 3, so a real ~216 km is simply absent from the sum. That alone accounts for its −4.9%. See `stage_notes.json` below.

### stage_notes.json — why a stage legitimately has no results (2026-08-15)

**A cancelled stage with zero results is byte-identical to a stage nobody has scraped yet.** Nothing in the row distinguishes "finished, correct, nothing to find" from "still to do", so the same handful get rediscovered and re-investigated on every audit — Giro 2011 stage 4 has now been chased at least three times (the 2026-08-01 historical audit, `insert_cancelled_stages.py`, and the distance reconciliation above).

`stage_notes.json` records the reason. **10 of the 18 cancelled stages are documented**; `validate_db.py` prints the rest by name under `note` lines so a reason gets *added* rather than invented, and it never affects the exit code — these describe data that is correct and finished.

Two design points worth keeping:

- **It lives outside the DB on purpose.** `ingest_race.py` deletes and re-inserts a whole edition, and only a fixed tuple of columns survives that (`vertical_meters`, `profile_score`, distance, `cancelled`, `source_slug`). A note in a `stages` column would be wiped by the next re-ingest with nothing to say it had gone.
- **Keys are the DB's `stage_number`, never the PCS slug number.** The two diverge after any split day — Giro 1946 DB stage 14 is PCS `stage-12`, Giro 1969 DB stage 21 is PCS `stage-20`. A note keyed the wrong way explains nothing and silences nothing, it just sits there looking done, so `validate_db.py` warns about any note that doesn't match a cancelled stage. Entries for stages where the two numbers differ carry `official_stage_number` so the note can be read without decoding the offset.

### Giro 1969 stage 20 — a wrong date on a cancelled stage (fixed 2026-08-15)

The cancelled Trento → Marmolada stage was stored as **1969-06-04**, duplicating stage 19's date; the real date is **1969-06-05** (bikeraceinfo: *"Thursday, June 5: Stage 20, Trento - Marmolada. Stage 20 canceled because of bad weather"*). It came in that way from `insert_cancelled_stages.py`, which parses the date off a PCS page that, for a cancelled stage, is nearly empty.

**Nothing noticed for months, because the row has no results and nobody reads it.** But `compute_stage_labels()` treats two stages sharing a date as a split day, so:

| | before | after |
|---|---|---|
| Trento → Marmolada | `19b` | **`20`** |
| Rocca Pietore → Cavalese | `20` | `21` |
| finale, Folgarida → Milano | `22` | **`23`** |

Every label from stage 19 on was one low, and a 23-stage Giro appeared to have 22. The fix went into `giro_scrapes/1969/stage_21.json`, not just the DB — a DB-only edit is undone by the next re-ingest. Re-ingesting reproduced all 564 results with an identical non-date fingerprint, so exactly one field moved.

`validate_db.py`'s `check_phantom_split_days()` guards it now. **It is scoped to cancelled stages, and that scope is the entire check** — PCS letters split days in some editions and numbers them sequentially in others (TDF 1986 `stage-1`/`stage-2` are one real split day), so the same rule applied to all stages produced **33 false errors on correct data**. Within cancelled stages the letter suffix still separates the genuine cases: Giro 1956 `stage-9b` and Vuelta 1978 `stage-19b` are real cancelled second halves and are not flagged.

The Giro 2011 entry is the fullest, and is the one to read first if the −4.9% distance gap ever comes up again.

### No-op overrides (cleaned up 2026-08-15)

The Giro and Vuelta override files had the same disease at scale. `giro_races_summary_overrides.json` held **88 years / 181 pinned fields** and `vuelta_races_summary_overrides.json` **78 / 156** — but only **18 and 4 fields respectively changed anything**. The other **315 pinned exactly what `export_race_summary.py` already computed**.

They were not wrong when written; they were *outgrown*. Two changes made them redundant without making them visible:

- `{race}_gc_winner_times.json` was **derived from these override files** (see the tree entry for `giro_gc_winner_times.json`), so every `gcWinnerTimeSeconds` pin had an identical twin in the file the exporter reads first. Each one was a **second copy of the truth that outranks the first** — fix a winner time in `giro_gc_winner_times.json` and the stale override would silently win.
- Moving the curated winner-time lookup ahead of the `winner_row` gate (commit `8e8e2f0`) let the exporter derive `slowestFinisherTimeSeconds` correctly on its own for most years, retiring those pins too.

`audit_summary_overrides.py` finds them by rendering the **real exporter** twice — once with the real overrides file, once with an empty one, both via the `--out`/`--overrides` flags into temp files — and diffing field by field. It deliberately does not reimplement the priority logic: a checker that duplicates the logic it checks agrees with the bug. `--strip` removes the no-ops and then asserts the shipped JSON is byte-identical, which is the only claim that matters.

What survives is worth reading, because it documents where the DB genuinely can't be trusted: 13 Giro + 3 Vuelta `slowestFinisherTimeSeconds` corrections where the computed winner+max-gap runs high, and Vuelta 1978 supplying a value the DB can't produce at all. The 5 Giro `totalElevationM: null` pins that also survived the strip are **gone as of 2026-08-18** — the exporter now suppresses sparse elevation by rule, so they became no-ops and `audit_summary_overrides.py --strip` removed them. See "Cancelled stages and sparse elevation" below.

Re-run the audit after any change to a `{race}_gc_winner_times.json` or a batch of GC corrections — that is when new no-ops appear.

### Cancelled stages and sparse elevation (2026-08-18)

`totalElevationM` is `SUM(stages.vertical_meters)`, and SQL's `SUM` ignores NULLs. An edition where **one stage of 23** carries a figure therefore exported that one stage as the whole race's climbing. On the Giro's All Years Summary this drew **1994 at 212 m** (its Bologna opener) and **1998 at 11 m** (the Nice prologue) as real points beside genuine 45,000 m years — visibly wrong, and wrong in the direction that looks like a data point rather than a gap.

Five Giro years with the same shape (1992, 1995, 1996, 1997, 1999) had already been pinned to `null` by hand in `giro_races_summary_overrides.json`. **That list missed 1994 and 1998**, which is the argument against curating it: the years are found by eye, and the eye is what missed two of seven.

The rule now lives in **`total_elevation()` in `export_race_summary.py`**, used by both that exporter and `export_all_races_summary.py`, so all three races behave alike:

- Null unless at least **`ELEVATION_MIN_COVERAGE` (50%)** of the edition's stages carry a figure. Coverage across all 302 editions splits cleanly — every sparse edition sits at or below **18%**, the least-covered plausible one (TDF 1998) at **86%** — so 50% is the wide middle of a gap, not a tuned edge. Only Giro 1994 and 1998 changed; the other five sparse years were already null via the hand pins.
- Every suppression **prints** (`Elevation: N edition(s) exported as null …`) with the sum it would have produced. Silence would just relocate the invisibility.

**A cancelled stage counts toward nothing.** `cancelled=1` means the stage produced no classification — no GC time, no points — so it contributes neither distance nor ascent to the year's total. `total_distance()` sits beside `total_elevation()` and applies the same filter, because counting a stage in one total and not the other is how distance and elevation end up describing two different races. Four figures moved:

| | | |
|---|---|---|
| TDF 1982 stage 5 | −556 m | ridden, then annulled after the Orchies blockade (it still has 160 results) |
| Vuelta 1991 stage 12 | −3,015 m | Andorra→Pla de Beret, no results |
| Vuelta 1957 stage 4 | −136 km | the only two cancelled stages stored with a real distance |
| Vuelta 1968 stage 17 | −204 km | (the other nine are already 0.0 km, so the rule just makes that convention explicit) |

**Wikipedia independently confirms the distance half.** Both Vuelta editions had sat in `distance_divergence_baseline.json` since 2026-08-15 as ">3% out, source disagreement". Dropping the cancelled stage moved **1957 to +0.27%** and **1968 to −0.36%** — Wikipedia's published route totals exclude those stages too, and what had been filed as unexplainable disagreement was this bug all along. Both baseline entries are **removed**: a baselined year that no longer diverges is a silencer with nothing left to silence.

`test_exports.py::TestElevationCoverage` locks all of it, distance and ascent.

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

**Abandoned riders leave the classifications** (fixed 2026-08-18): a rider is ranked only for stages *before* the one their last result row abandons on (DNF/DNS/OTL/DSQ). They keep the points they scored — they just stop being ranked against riders still racing. Without this, whoever led a classification when they climbed off held that lead to Paris: Roger De Vlaeminck abandoned stage 12 of the 1969 Tour on 61 sprint points and still outranked Merckx's eventual 59 on stage 25, which cost Merckx his green jersey in the riders index and broke the famous 1969 triple. **Only riders whose last row is an abandonment are dropped** — a rider whose results merely stop is a data gap (old PCS pages omit legitimate finishers, see the `finalRank` fallback), not an exit, and stays in.

**DNF tail catch-up**: After the per-stage loop for a rider, if they DNF'd before the last stage, their cumulative points are topped up with any points stored in later stage slots (some sources store final totals in the last stage entry). Their final `sprintRank`/`komRank` is also set from the pre-computed final-stage rank tables — which now returns nothing for a genuine abandonment, by design.

**The riders index does not use these ranks where the DB has the real ones** (2026-08-18): `export_riders_index.py` takes `sprintRank`/`komRank` from `classification_standings` for every year that table covers (TDF 1960–2025), and falls back to the derived cumulative-points order outside it (pre-1960, 2026, and all Giro/Vuelta years — that table has no points/kom rows for them). The two are not interchangeable: the derived order is "who led on reconstructed points after the last stage", the DB is the official final standing. Before this, 16 of 66 TDF points years and 7 of 66 KOM years named the wrong rider on the Riders page (1972 green, 2014 and 2015 polka dot among them). The abandonment fix above closed 4 of them; the rest only agree because the scraped standings now win.

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

**The path is normalized away on load (2026-08-15).** `normalizeUrl()` (formerly `seedHashFromPath`) rewrites the URL to `<base>/#<race>/<view>` whenever the page is served from a per-race landing path. The landing pages carry no hash, so one is seeded from the path — but the path then has to go, because **nothing ever updates it again**. Switching race only touches the hash, so landing on `/vuelta/` and clicking through to the Tour's All Years Summary produced `/vuelta/#allraces`: a path saying Vuelta and a hash saying Tour, with the hash being the one that's true. The landing pages still exist and are still crawled; they just stop leaking into the URL after boot. The hash is the single description of app state.

**Canonical host (2026-08-15).** The site serves from **`https://www.ericshiflet.com/tdf-analytics/`** — a GitHub Pages *project* site inheriting the custom domain from the `eshiflet.github.io` user site, which is why the repo name is a path segment. `eshiflet.github.io/tdf-analytics/` and the apex `ericshiflet.com` both **301** there, so exactly one URL returns 200. Every canonical/`og:url`/schema/sitemap/robots reference used to point at the redirecting `github.io` URL; they now point at the serving host. The sitemap mattered most: **a sitemap only covers URLs on its own host**, so one served from `www.ericshiflet.com` listing `github.io` entries was being ignored wholesale. `SITE` in `race-page-meta.mjs` is the single definition.

**Social cards are rendered from the real charts (2026-08-15).** `public/og-*.png` are 1200×630 Open Graph images — one per landing page, so a shared link previews the race it actually points at. They are NOT mockups: `og-image.html` iframes the live SPA at a deep link, hides the chrome (topbar, sidebar, `rider-end-label`s, unit toggles), and scales the chart to fill, so the card is the same D3 render a visitor gets and cannot drift from it. `scripts/render-og-images.sh` screenshots the six variants with headless Chrome against a running dev server.

Deliberately **not** part of `npm run build` — it needs a browser binary, and CI must stay install-free. Re-run it by hand after a palette or chart change. `og-image.html` is absent from `vite.config.ts`'s input, so it never ships. `twitter:card` is `summary_large_image`; the previous `summary` cropped everything to a small square and wasted the chart.

**`generate-race-pages.mjs` fails loudly now.** Every metadata rewrite goes through `sub()`, which throws if its pattern matched nothing. `String.replace` on a non-matching regex is a silent no-op, and that is how the script rotted: it kept rewriting a `<p class="subtitle">` that commit `58ce75f` had deleted from index.html, so the per-race subtitle copy silently did nothing for months. The dead `subtitle` field is gone. It also generates `public/sitemap.xml` and `public/robots.txt`, so the race list and the host each live in exactly one place.

**Static landing pages must be listed in TWO places, and now aren't.** `generate-race-pages.mjs` writes `<race>/index.html` from `race-page-meta.mjs`'s `RACES`, and `vite.config.ts` needs each one in `rollupOptions.input` or it never reaches `build/`. `classics/` was generated but not listed, so `/classics/` 404'd on the live site **while working perfectly in dev**, where Vite serves the file straight off disk. (The cross-race footer links that surfaced that 404 were removed 2026-08-19 as redundant with the race dropdown. The URLs are still built and still in `sitemap.xml`, so the failure mode is unchanged — it would just surface via the sitemap now rather than a click, which is slower to notice.) `vite.config.ts` now derives its input map from the same `RACES` object. `race-page-meta.mjs` is data-only for exactly this reason — importing the generator would run its file writes every time the Vite config loads.

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

**Hosting topology (verified live 2026-08-15).** This is a GitHub Pages **project** site that inherits its custom domain from the `eshiflet.github.io` **user** site, which is why the repo name is a path segment:

| URL | response |
|---|---|
| `https://www.ericshiflet.com/tdf-analytics/` | **200** — the only URL that serves |
| `https://eshiflet.github.io/tdf-analytics/` | 301 → www.ericshiflet.com |
| `https://ericshiflet.com/tdf-analytics/` | 301 → www.ericshiflet.com |

`www.ericshiflet.com/` itself is Eric's separate personal site, not this app. `SITE` in `race-page-meta.mjs` holds the serving host and is the single definition used by canonical tags, `og:`/`twitter:` URLs, sitemap and robots.

**The social cards are not rebuilt by CI.** `scripts/render-og-images.sh` needs headless Chrome and a running dev server, so `public/og-*.png` are committed artifacts. Re-run it by hand after a palette or chart change, or the cards quietly keep showing the old design.

---

## Renaming the project (analysed 2026-08-15 — DEFERRED, Eric's call)

"tdf-analytics" now covers the Giro, the Vuelta and 11 one-day classics, so the name is wrong. Eric looked at the cost and **decided not to rename for now** ("it sounds a bit invasive"). Don't re-derive this; the analysis is below.

**There are two independent renames. Conflating them makes a small job look enormous.**

### A. The public name `tdf-analytics` — 40 occurrences, 17 files

`vite.config.ts` base (1) · `index.html` canonical/og/schema (7) · `sitemap.xml` (5) · `robots.txt` (1) · `race-page-meta.mjs` SITE (1) · `verify.mjs`/`verify-views.mjs` base-stripping regexes (6) · 8 Python scrapers' User-Agent strings · `ai-context.md` (8) + `architecture.md` (1). **`.github/workflows/deploy.yml` needs no change** — it references `cycling-app/`, not the repo name.

The code is an afternoon. **The cost is entirely in URLs**: renaming the repo changes the Pages path, so every bookmark and shared deep link under `/tdf-analytics/` stops resolving. Git remotes redirect automatically; the Pages path does not, so it needs a redirect shell at the old location that preserves the hash (all app state lives in the hash). Search ranking also resets for the new path.

**The option that makes this free:** give the project its own custom domain (e.g. `cycling.ericshiflet.com`). A project repo can hold its own domain and is then served at that domain's *root* — `base` becomes `/`, the repo name never appears in a URL again, and renaming becomes a purely internal decision. Costs a DNS record, a `CNAME` in `public/`, and a redirect for existing `/tdf-analytics/` links. **If the rename is ever revived, do this first** so URLs churn once instead of twice.

### B. The internal `tdf` → `tour` legacy — zero user impact

The July 2026 pass migrated TDF's *supplemental* files to the `tour_` prefix but left the rest:

- **`export_gc.py --race tdf` and `validate_db.py --race tdf`** while every path they write is `data/tour/`. This is a **live trip hazard, not a cosmetic one** — `export_gc.py --race tour` errors out, and it was hit during this very session. Unifying the race key is the highest-value, lowest-risk piece of the whole rename discussion: small, invisible to users, touches no URLs.
- 47 `tdf_YYYY_full.json` raw scrape files and 16 Python files referencing them, plus `reingest_tdf_stage.py`. Pure consistency, no functional gain — do last, or never.

### Suggested sequencing if revived

1. Unify the `tdf`/`tour` race key (do this regardless — it's a bug magnet).
2. Move to a dedicated subdomain, making the repo name invisible.
3. Rename the repo, which is then free.
4. Rename the `tdf_*_full.json` files last, or never.

Names considered: `grand-tour-analytics` is **already too narrow** (the classics aren't grand tours). Prefer race-agnostic — `cycling-analytics`, `procycling-analytics`, `peloton-analytics`.

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

### Riders page filters (rewritten 2026-08-18)

**Jersey buttons are per-race and driven by capability flags, not by hardcoded
exceptions.** `jerseyCategoriesForRace(race)` in `jerseyIcons.ts` is the single
place that decides which jerseys a race offers: `hasYouth` gates the white
jersey (TDF only), `hasSprintKom` gates green and polka dot. The one-day
classics therefore show exactly **one** gray jersey, and because a one-day race
has no running general classification its tooltip reads **"One-day Classics -
Winner"** rather than "GC" (`jerseyIconTitle()` swaps the word wherever
`hasCumulativeGc` is false). The same two helpers drive both the filter buttons
and the per-rider icons in the grid, so the two can't drift apart.

**The year filter is a multi-select, and it scopes the jersey filters.** Years
live in `state.ridersFilterYears: Set<number>` and are OR'd — "2021, 2023" means
either year. With no year selected a jersey filter asks the career-wide question
("won this at least once, ever"). With years selected it asks about those years
specifically: the rider must have won **every** selected jersey within a
**single** one of them. So "yellow + 2021, 2023" is the two riders who actually
wore yellow in one of those years, and "yellow + green" is one rider who took
both in the same season rather than one in each of two years a decade apart.
Applied across races, that same rule asks for a Giro/Tour double in one season.
`matchesJerseyFilter()` in `views/riders.ts` is the whole rule.

Before 2026-08-18 the two filters were independent: "2026 + yellow jersey"
returned Bernal, Pogačar and Vingegaard, because it meant "rode the 2026 Tour
AND has ever won yellow". The grid's jersey icons are year-scoped too, so a 2019
winner shows no jersey while the grid is filtered to 2026 — otherwise the icons
contradict the filter.

**Test hooks.** The team and nationality selects carry `#riders-team-filter` and
`#riders-nationality-filter`. `verify-views.mjs` used to find the team select by
position among `.riders-filter-select`, which silently retargeted the
nationality select the moment the year filter stopped being a plain `<select>` —
the check kept its name, measured 70 nationalities against a "> 600 teams"
threshold, and failed. Query these ids; never index that NodeList.

**If you add a new race:** set `hasYouth`, `hasSprintKom` and `hasCumulativeGc`
in its `RACES` entry — the jersey buttons, the grid icons and the tooltip
wording all follow from those three, with no per-race code.

### Rider detail chart: cross-race, with race + classification toggles (`drawRiderDetail`)

`drawRiderDetail(riderId)` is **async and cross-race** — it is not filtered to `currentRace`. It awaits all four races' rider indexes in parallel (`Promise.all(RACE_IDS.map(ensureRiderIndexFor))`), builds a `Map<RaceId, RiderEntry>` of every race the rider appears in (`byRace`), and returns early if the rider is in none. The header/meta line (`"7 TDF · Best #1, 8 Giro · Best #1, 1 Vuelta · Best #1"`) is built from `byRace` directly — no nationality text (the flag next to the name + its hover tooltip already convey it).

**Toggle bar**, above the chart: race buttons (T/G/V, one per race in `RACE_IDS`) then a `|` divider then classification buttons (GC/Sprint/KOM). Both toggle groups behave the same way — clicking toggles membership in a `Set` (`activeRaces` / `activeClassifs`), refusing to deactivate the last remaining member so the chart is never empty; a `BADGE: Record<RaceId, {bg, text, label}>` constant (not `RACES[race].chart`, for reliable hex values in SVG `stroke`/`fill` attributes) drives each race button's color and letter. A race button is disabled (`.no-data`) if the rider has no entry for that race at all.

**Overlapping-year dot offset:** when a rider raced two+ active races in the same year, their dots would otherwise land on identical x-coordinates. `xPos(race, year)` looks up which active races have data for that year and offsets each by `±(DOT_R*2+1)` px (currently 11px, for `DOT_R=5`) around the shared center, so same-year dots from different races sit side-by-side, touching, instead of stacking.

**Classifications:** GC draws a solid line (in `RACES[race].chart.gc`), Sprint a `4,3`-dashed line (`chart.sprint`), KOM a `2,3`-dotted line (`chart.kom`) — all three independently toggleable per race via the classification buttons; the y-axis (`"Rank"`) and its domain expand to cover whichever classifications are active. The DNF/DNS zone below the main chart only appears when GC is active.

**Legend** (top-right, above the chart, up to 3 rows): row 1 is one column per active race (name + solid line, in that race's GC color); rows 2/3 (only if Sprint/KOM are active) repeat under each race's column ("Sprint"/"KOM", dashed/dotted, in that race's sprint/kom color) — columns are left-aligned to a fixed per-column x so "Tour"/"Sprint"/"KOM" (and same for Giro/Vuelta) line up vertically.

The Sprint/KOM rows list only races with `hasSprintKom` (2026-08-18): the classics award neither jersey and no such line is ever drawn for them, so listing them promised two series that cannot exist. Their column is not widened to fit a label it never renders either, and when *no* active race contests them the two rows disappear entirely rather than leaving reserved empty space — deselect the Grand Tours on a rider who also has classics results to exercise that path.

**Doping note.** Riders in `RIDERS_WITH_REVOKED_RESULTS` (`jerseyIcons.ts`) get "Some race results revoked for doping" immediately right of the name, dimmed italic, wrapping to its own line on narrow screens. Five riders as of 2026-08-18: Armstrong (seven Tours), Landis (2006 Tour), Contador (2010 Tour, 2011 Giro), Kohl (2008 Tour KOM), Cobo (2011 Vuelta). Membership means a governing body actually **removed a result** — not a suspension, and never inferred from the data. Duplicate ranks hint that a re-award happened but are not evidence: the same duplicates arise from PCS artefacts (Giro 1913/1932/1948). Note `rider/juan-jose-cobo` is not `rider/ivan-cobo-cayon`, a different rider in the same data.

**Dead code warning:** `DOPING_GC_NOTES` and `jerseyIconsWithYearsEl()` in `jerseyIcons.ts` are **not called by anything** — the per-jersey-year doping annotation they implement has never rendered. Don't cite them as precedent for how the app displays anything; the name-level note above is the only live one.

**Click a dot** to jump to that race/year's stage chart at the matching metric (`gc`, `points` for Sprint, or `kom` for KOM) — `setRace()` + `loadDataset()` + `switchView("stage")`.

**If you add a new race:** its `RACES` entry's `chart` colors and `name` are used automatically for the cross-race chart and legend; add a `BADGE` entry too (hex color, not a CSS var) for its toggle button and DNF-dot outline.

---

## Frontend performance — Riders page (measured 2026-08-18)

Numbers below are from a local dev build, all four races selected (14,260 rider
buttons). They are here so the next person optimizes the thing that is actually
slow rather than the thing that looks slow.

**Where a grid rebuild goes** (per filter change, before the fixes):

| Phase | ms |
|---|---|
| filter + merge + sort | ~40 |
| `displayName` + text node | ~33 |
| `nationalityFlagEl` | ~85 |
| `jerseyIconsElMultiRace` | ~190 |
| button create + title + data-id | ~82 |
| attach + forced layout | ~157 |

Sorting 14,260 names with `localeCompare` is 14ms and clearing the old nodes is
4ms — neither is worth touching. `Intl.Collator` is *not* faster here (16ms).

**Index load** (the ~2.7s first paint of the Riders page is mostly this):

| Race | Riders | Size | Parse | Build |
|---|---|---|---|---|
| tour | 5,471 | 0.77 MB | 10ms | 48ms |
| giro | 4,718 | 0.65 MB | 15ms | 61ms |
| vuelta | 4,430 | 0.58 MB | 11ms | 60ms |
| **classics** | **11,934** | **2.79 MB** | **132ms** | **379ms** |

### What was done

- **`jerseyYearsWon` memoized** on a `WeakMap` keyed by the entry object. The
  grid called it once per rider PER RACE — 57,000 calls per rebuild, each
  allocating and sorting four arrays over data that never changes after load.
- **`jerseyCategoriesForRace` memoized per race.** It returned a freshly
  filtered array on every one of those 57,000 calls. 190ms → 132ms.
- **Flag elements cloned, not rebuilt.** One prototype `<span>` per nationality,
  `cloneNode` thereafter; it was redoing attribute writes, emoji codepoint
  arithmetic and (for the two historical flags) an SVG `innerHTML` parse 14,260
  times. 85ms → 30ms.
- **`setAttribute("data-id")` instead of `btn.dataset.id`**, and `displayName`
  called once per rider instead of twice. 82ms → 66ms.
- **`content-visibility: auto` on `.rider-name-btn`** — 157ms → 46ms. See the
  trap below before touching this.
- **`constituents` built lazily** — see the trap below.
- **In-flight promise dedupe in `ensureRiderIndexFor`.** `riderIndexBuilt[race]`
  only flips after fetch AND build finish, so two concurrent callers both passed
  the guard and both downloaded and rebuilt the same index. `drawRidersPage` and
  `drawRiderDetail` both call it for every race, so opening a rider from a link
  did exactly that: two 2.8 MB classics fetches and two ~500ms rebuilds racing
  to populate the same Map. Callers now share the promise; it clears on settle
  so a failed load can still be retried.

### Traps

**Measuring layout.** `content-visibility` was measured, declared a no-op, and
reverted — wrongly. The A/B ran against a rebuild that deferred layout past the
end of the measurement window, so both arms timed everything *except* the thing
the property affects, and both read 416ms. Re-measured with a forced synchronous
layout (`getBoundingClientRect()` straight after appending the fragment) it is a
clean 157ms → 46ms → 156ms across three toggles each way. **Any re-test of this
must force layout.** A synthetic benchmark also lied in the other direction
(357ms → 58ms on a probe div in a different layout context); trust only the live
grid.

**`constituents` is a non-enumerable lazy getter.** The classics index carries a
per-race breakdown for 11,934 riders, ~380ms of the ~510ms that index takes to
build, for data only the career chart reads one rider at a time. It is now
defined by `defineLazyConstituents()` as a memoizing getter — and deliberately
**non-enumerable**, because `mergedRidersForSelectedRaces()` clones entries with
a spread and an enumerable getter would fire for all 11,934 and hand back
exactly the eager cost being avoided. That merge copies the property's
*descriptor* (`getOwnPropertyDescriptor`, which does not invoke the getter) so
the clone stays lazy and shares the memo. Make it enumerable, or replace the
descriptor copy with a value copy, and the optimization silently evaporates.

**Search is accent-folded, and folding is cached.** `foldForSearch()` in
`riderDisplay.ts` NFD-normalizes, strips `\p{Diacritic}`, then hand-maps the
letters that don't decompose because they aren't accented forms of anything
(ø ł đ ð þ ß æ œ ı — 28 riders with ø, 20 with ł, 4 with ß, one Đ).
`searchHaystack()` additionally keeps an umlaut-expanded spelling, so both
"zulle" and "zuelle" find Zülle (113 riders carry an umlaut). Folding 14,260
names per keystroke would undo the work above, so the haystack is computed once
per rider into a `WeakMap`. Both search boxes (Riders grid, stage-chart "Find a
rider") go through it.

### Still open

The ~415ms JS half of a rebuild is now ~305ms; the remainder is spread across
the per-rider helpers and has not been attributed further. The bigger prize is
the ~2.7s first paint — deferring the classics index until a classics filter is
touched, or streaming the grid after the first index resolves, is worth more
than anything left in the rebuild loop.

---

## riders_index.json re-encoded for the aggregate races (2026-08-22)

The classics index is the single largest thing the app downloads, fetched
whenever the Riders page opens. It shrank **703 KB -> 547 KB gzipped (-22%)**
and got **24% faster to load**, which was not the trade this was expected to be.

### The encoding

Aggregate sets (classics, gravel) now carry ONE map per rider-year:

```
ym: { "2021": [teamIdx, raceIdx, rank, raceIdx, rank, ...] }
```

replacing a `y` of `[finalRank, teamIdx]` plus a parallel `m` of
`[[raceIdx, rank], ...]`. Those stored every year key **twice**, and finalRank
is `min()` of the ranks already in `m` — derivable, not data. The Grand Tour
indexes keep their own `y` shape (they have no constituent races), so the
loader branches on which key is present.

### Measured, because the risk was real

Deriving finalRank means touching `m`-shaped data at load, which is what
`defineLazyConstituents()` exists to avoid — the note in this file calls that
getter load-bearing and worth ~380ms when eager. Measured in the browser on the
real 11,934-rider file, median of 7, forcing layout each iteration:

| | old | new |
|---|---|---|
| gzipped | 703 KB | **547 KB** |
| parse + build | 250.1 ms | **189.9 ms** |

**Both improve.** The 380ms that getter avoids was materialising 11,934
`ConstituentResult` objects — not iterating numbers. A `min()` over a flat
numeric array costs ~1.5ms, while parsing 156 KB less JSON saves far more. The
getter is still lazy and now reads the same `ym` array.

### What to re-check if this is touched again

`validate_exports.py`'s staleness check re-derives finalRank from `ym` rather
than reading a stored value, so a broken derivation fails the validator rather
than a stale copy of a correct one. It caught this change immediately — 44,105
"inconsistent rider-years" on the classics — before it was taught the new shape,
which is exactly what that check is for.

---

## The rider detail page stopped loading all five indexes (2026-08-22)

The rider detail page is cross-race by design — it shows every race a rider has
results in — and the only way it could find out *which* races those were was to
download and build **all five** `riders_index.json` files. That is **1,185 KB
gzipped** plus five synchronous index builds on the main thread, for every
rider page opened.

Almost all of it was spent proving a negative. Of **17,736 riders** across the
five sets, **10,793 (61%) appear in exactly one** and **31 appear in all five**:

| sets a rider appears in | riders |
|---|---|
| 1 | 10,793 |
| 2 | 3,254 |
| 3 | 1,966 |
| 4 | 1,692 |
| 5 | 31 |

### The stamp

`link_rider_race_sets.py` writes the answer into the file the page has to load
anyway. Each index gains:

```
"xr": ["giro", "vuelta", ...]              # the OTHER sets this file reaches
riders: { "<slug>": { ..., "x": 5 } }      # bitmask over xr; omitted when 0
```

**Each file names its own bit order.** The two exporters —
`export_riders_index.py` for the Grand Tours, `race_set_export.py` for the
aggregate sets — do not know about each other, and a fixed bit order duplicated
across Python and TypeScript is exactly the pair that drifts. The frontend
validates each slug against the race registry and maps anything unrecognised to
`undefined` *without shifting the remaining bits*, so an index stamped before a
new race set existed stays readable rather than being misread.

### Measured

Over every (race, rider) pair:

| | before | after |
|---|---|---|
| payload per rider page | 1,185 KB gz | **705 KB mean / 737 KB median** (−41% / −38%) |
| cost of the stamp itself | — | **+25 KB gz** across all five files |

Verified in the browser on a cold deep link: `#riders/achiel-de-smet`
(Tour only) fetches **one** index; `#riders/aad-van-den-hoek` (Tour, Vuelta,
Classics) fetches **three** and skips Giro and gravel.

### The deep link was loading them all a second way

`switchView("riders")` draws the Riders **grid**, and an unfiltered grid loads
every race. So `#riders/<slug>` fetched all five through the grid before
`drawRiderDetail` ever ran — the grid's own bail-out discarded that work, but
only after the fetches were in flight. `switchView` now takes `{ draw: false }`,
used by exactly that one caller. Without this the bitmask saves nothing on the
path it was built for.

### The exporters restore it themselves

Rewriting an index drops the stamp, so `export_riders_index.py` and
`race_set_export.py` (via `export_classics.py` / `export_gravel.py`) call
`stamp(quiet=True)` after writing one. There is no step to remember. Proven
live: `export_riders_index.py --race giro` writes 666 KB without the stamp,
re-stamps to 694 KB, and leaves the working tree **byte-identical** to what was
committed. Same for `export_gravel.py` on the aggregate path.

Membership is symmetric, so stamping one index can legitimately rewrite the
others — a rider newly appearing in the Giro changes the classics file's mask
for that rider too. Only files whose bytes actually change are written, so a
no-op export produces a clean `git diff`.

`validate_exports.py` still checks it, and that is now the **backstop** — for a
hand-edited file, or a new writer that forgets:

```
ERROR cross-race rider membership is stale. Run: python3 link_rider_race_sets.py
```

Run it by hand only after some other writer touches a `riders_index.json`.
`test_exports.py` asserts both exporters still make the call, because a
refactor that drops one would otherwise surface as a failed pre-push much later.

A **stale** bit is worse than a missing one: the page trusts it to decide which
indexes to skip, so a rider who left a set would have that race silently dropped
from their career chart rather than merely loading slowly. `apply_membership()`
clears old stamps before writing, and only rewrites a file whose bytes actually
changed — these are 6 MB of JSON and a stamp that always reported "changed"
would churn every diff.

`crossRaceFor()` returns **null**, not an empty list, when no built index has
heard of the rider: those mean opposite things ("ask again later" versus "this
rider races nowhere else"), and the page falls back to loading everything on
null rather than concluding the rider raced nowhere.

---

## Payload budget (2026-08-22)

```bash
cd cycling-app
node check-payload.mjs             # compare against the committed baseline
node check-payload.mjs --update    # re-baseline, deliberately
```

Every payload win in this repo was measured once, by hand, and then had nothing
holding it in place — the compact JSON separators (−10%), the `riders_index`
re-encode (−22% gzipped), the cross-race bitmask. An exporter change could undo
any of them and the only symptom would be a slower site: no test fails, no
validator complains, and the diff on a 2 MB minified JSON file tells you
nothing.

So the sizes are committed. `payload-baseline.json` holds the **gzipped** byte
count of 13 tracked payloads and the run fails when one grows more than 2%:

```
REGRESSED riders_index:classics  462.4 KB -> 578.0 KB  +25.0%
```

**What it tracks, and why not simply every file.** `entry:main.js` /
`entry:main.css` (main.js also carries the three `all_races_summary.json` files,
which raceRegistry.ts imports as data rather than by URL, so they are bundled
into it and never appear as their own asset); each race's `riders_index.json`
individually, because those are the biggest single downloads and the ones that
get re-encoded; each race's per-year files as one **bucket** total, because
there are 440 of them, they are fetched one at a time, and 440 baseline lines
would be noise nobody acts on; and `total:assets`, so a new category cannot slip
in below the radar.

**Attribution.** The build flattens every race's data into one `assets/`
directory, so `gc_by_stage_1987.json` could belong to any of four races and all
five races have a `riders_index.json`. Vite copies these verbatim, so the file
is matched back to its race on `basename:rawBytes` — no hashing of 131 MB of
source. A genuinely ambiguous file is split evenly across its candidates: the
per-race bucket goes approximate, the total stays exact.

**Growth is expected and is not a regression.** Adding a year makes the archive
bigger, which is why this compares against a committed baseline with a tolerance
rather than a hardcoded ceiling. Re-baseline in the commit that causes the
growth — the diff on `payload-baseline.json` is then the actual record of what
grew and why. The failure is only what makes you look.

Wired into `scripts/pre-push` and the CI workflow, both reusing the build they
already ran, so it costs only the gzipping (~1.6s for 474 files). A new or
removed asset is reported but does **not** fail: adding a race set is normal
work, and failing it would only teach people to pass `--update` reflexively,
which is the one habit that makes this useless.

---

## Dev-loop traps (2026-08-18)

**Vite HMR serves stale modules more often than you'd think.** Three separate
times in one session an edit appeared to have no effect: the dev server was
serving the new source (verified by `fetch()`ing the module and grepping it) but
the page kept executing a cached copy. A plain reload was not always enough — a
cache-busting query param on the page URL (`/tdf-analytics/?cb=123#riders`) was.
Before debugging "my change didn't work", confirm the running page actually has
it.

**The by-Stage TABLE's row filters (August 2026) are aggregate-only.** The Top 10
/ Top 20 / All / Nation cluster to the LEFT of the table renders only when
`raceConfig().stagesAreRaces` — i.e. the one-day classics. The reason is
semantic, not cosmetic: for an aggregate season each column IS a separate race,
so `gcRank` is a finishing position and "at least one top-10 result" means what
it says; on a Grand Tour the same field is the *running GC position*, where the
identical button would be claiming something entirely different. Three things
worth knowing before touching it:

- **They do not reuse the sidebar's controls, deliberately.** The sidebar's
  Top 10/20 and Nation rewrite `state.selected` — the user's hand-picked set of
  chart lines — and `main.ts` re-queries `.button-row button` to clear `.active`
  on every year change. Reusing either the state or the class names would let a
  year change silently strip the table's buttons, so these carry their own
  `state.stageTableTopFilter` / `stageTableFilterNations` and their own
  `table-filter-*` classes. The table's filters only hide rows; they never
  touch the graph.
- **The colour ramp stays anchored to the WHOLE field.** Column colours are
  built from every rider, not the visible subset — otherwise filtering to the
  top 10 re-spreads the scale across a field that is now all winners and
  repaints their wins from green to red. `verify-views.mjs` pins this.
- **The cluster lives outside `.stage-table-wrap`.** That element is the scroll
  container; an absolutely-positioned child would scroll away with the 600+
  rows a classics season carries. `#stage-table` is a flex row instead, with
  the controls as its FIRST child — they sit where the sidebar does in graph
  mode (`main.ts` hides the sidebar in table mode), so switching sub-views
  doesn't throw the controls across the screen.
- **Top 10 / Top 20 / All are a radio, not toggles**, matching the graph's
  Quick select: exactly one is lit, re-clicking the lit one does nothing, and
  All is the only way back. `null` IS the All state, so there is no fourth
  value to keep in sync. All also clears the Nation filter — otherwise a lit
  "All" would claim the whole field while a nation still hid most of it (the
  graph's All clears team/nation for the same reason). The Nation panel's own
  Clear drops nations without touching the limit.
- **Nation ANDs with the active limit; it does not override it.** This is a
  deliberate divergence from the graph, where `applyStageTeamNationFilter()`
  *replaces* `state.selected` outright and unlights the preset buttons. That
  behaviour falls out of both controls writing to one selection set, which the
  table doesn't share — and "Belgium riders with a top-10 finish" is worth
  being able to ask.

The row count under the cluster always renders — `"670 riders"` unfiltered,
`"59 of 635"` filtered — so the season's field size is readable without having
to filter first, and the cluster doesn't change height when a filter goes on.

Nationality selections are pruned to the nations present when the year changes
(carried over otherwise), so a filter left on from 2026 cannot silently empty
1913.

**The stage table's sticky columns depend on fixed widths.** `.col-rider` pins
itself with `left: 74px` (22px team + 52px bib) and the other three combinations
are spelled out in `style.css`. `.col-bib` had no width, so it sized itself from
its content at ~44px; sticky then shifted the rider column 8px right of where it
belonged and, being opaque with a z-index, painted over the left edge of the
stage-1 column — which read as "column 1 is narrower than the others". Both
sticky columns are now pinned (`width`/`min-width`/`max-width`) precisely so
those offsets stay true. If either is ever allowed to size itself from content
again, every offset goes stale with it.

Separately, `th.col-stage` carries `min-width: 46px` because the table sizes
columns to content and a stage whose values are short rendered narrower — worst
in Sprint/KOM, where totals start in single digits (31.5px against 44.4px). It
is a minimum, not a fixed width: GC-time cells are wider and grow together.

**The km/mi toggle serves two views.** `all-races-unit-toggle` now drives both
the Grand Tours' All Years Summary and the classics Race History, sharing
`state.allRacesUnit` so a preference for miles carries across. On Race History
it converts speed (km/h → mph) as well as distance, and hides itself for the
Finishers metric, which is a unit-less count — so the button appears and
disappears as the metric switch changes, not only on entering the view
(`raceHistoryUsesDistanceUnits()`). `classicsHistory.ts` imports
`updateUnitToggle` from `main.ts`, a cycle that is safe for the same reason
`riders.ts`'s is: the call happens inside an event handler, never at
module-evaluation time.

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
A rider who DNFs before the final stage has their last `byStage` entry used for `finalRank`. Their cumulative points are topped up via a catch-up loop after the main `byStage` loop (some sources store final totals in stage slots after the rider's last actual stage).

**They are NOT ranked past the stage they abandon on** (2026-08-18). The per-stage sprint/KOM ranking excludes any rider whose last result row is an abandonment, from that stage onward — see "Abandoned riders leave the classifications" under "export_gc.py — Key Logic". The final-stage backfill on their last entry still runs but now finds nothing for a genuine abandonment, which is the point: a rider who climbed off leading the points classification must not still hold it in Paris.

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

# Unit tests — 162 as of 2026-08-18
python3 -m unittest discover -p "test_*.py"

# Exported-JSON checks (run after any export). 436 files, 0 errors and
# 90 warnings is the expected clean result as of 2026-08-18 — compare the
# COUNT against that baseline rather than expecting zero.
python3 validate_exports.py
python3 validate_db.py               # 0 errors, 3 warnings expected

# Cross-race rider membership — the `x` bitmask the rider detail page uses to
# decide which indexes it can skip. The exporters re-stamp it themselves; this
# only needs running by hand after some OTHER writer touches a riders_index.json.
python3 link_rider_race_sets.py --check     # report drift, write nothing
```

### coverage.py — what is missing, and where (2026-08-22)

```bash
python3 coverage.py                    # every race set, worst gaps first
python3 coverage.py --race tour        # tour/giro/vuelta/classics/gravel
python3 coverage.py --field vertical_meters   # one field, every year lacking it
python3 coverage.py --years            # full per-year table, not just the gaps
python3 coverage.py --csv              # machine-readable
```

**Not a validator.** Every other check here answers "is this value wrong?".
This one answers the question that actually picks the next scrape target: for
every race and year, which fields are simply *not there yet*. It never fails a
build and never claims a value is wrong.

The whole difficulty is honest denominators — a gap that cannot be filled is
noise, and noise is what made the per-field audits hard to read side by side:

| excluded | why |
|---|---|
| cancelled stages | never raced, so a NULL distance is the correct value — the same rule the race totals use |
| `finish_time_seconds` / `gc_rank` for a **DNF** | no finishing time or GC standing exists; counting the whole startlist reported ~60% missing on years that are complete. Biggest single source of noise |
| gravel: elevation, profile score, route type, teams, source slugs | PCS has no gravel or MTB coverage at all — verified, not assumed, so there is nothing to scrape from |
| one-day: profile score, route type | a one-day race is not classified flat/hilly/mountain |

Gaps rank by **values missing**, not by percentage: a year at 40% of 180 is a
bigger afternoon than one at 0% of 3. As of 2026-08-22 the top of the list is
per-stage `gc_rank` for the 1980s Giro and Vuelta and `finish_time_seconds` for
the 1950s Tour, with 3,618 stage elevations outstanding across 340 race-years.

`test_coverage.py` pins each exclusion above, because each one is a case where
a naive `COUNT` reported a gap that does not exist.

`validate_kom.py` / `validate_gc.py` need external reference data that isn't in
the repo; without it they report `0 ok / 0 mismatch` or `no_data` for every year
and prove nothing. `validate_exports.py`, `validate_db.py` and the unittest
suite are the ones that actually gate a change.

**Tests worth knowing about** (`pipeline/test_exports.py`): `TestAbandonedRidersLeaveTheClassifications`
builds a scratch DB where one rider leads the sprint classification and then
abandons, and asserts the finisher takes the final standings — that is the 1969
De Vlaeminck/Merckx bug in miniature. `TestRidersIndex` covers the official-
standings override, including that a rider absent from those standings ends up
unranked rather than keeping a derived rank.

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
