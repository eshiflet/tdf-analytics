# Cycling Analytics — AI Context

Interactive cycling analytics app covering **21 races in five sets**: the **Tour de France** (all 113 editions, 1903–2026), the **Giro d'Italia** (109 editions with data), the **Vuelta a España** (81 editions, back to 1935), **11 one-day classics** (1892–2026) and **7 off-road races** (gravel and MTB, 1994–2026). The 2026 Tour de France is **complete** — all 21 stages are in the DB, Pogačar won in **73:56:26** and the slowest finisher was Cees Bol at **+6:22:08** (finalized 2026-08-15; see "Finalizing a completed year" below for what changed). Live at **[ericshiflet.com/tdf-analytics/](https://ericshiflet.com/tdf-analytics/)**.

**Riders, as of 2026-09-19**: **18,037**, and `riders` holds exactly that many — 17 gravel riders were merged and one split on 2026-09-19 (see "Athlinks' racerId"), taking it from 18,054 — the 826 rows that carried no results were deleted on 2026-09-14 and `validate_db` now reports any that reappear. (18,050 before the 2026 Vuelta landed that evening; it introduced 4 riders new to the whole archive.) On the 18,050 snapshot, 11,095 appeared in exactly one race set and 36 in all five. The classics contribute the most exclusive riders (5,225, 28.9%) and gravel the highest *rate* — 3,775 of its 3,885 riders, 97%, race nowhere else. Only 110 riders in the whole archive have both a gravel and a road result, which is what `link_gravel_riders.py` exists to protect.

---

**Where the data comes from: [DATA_SOURCES.md](DATA_SOURCES.md)** — every source, its URLs, how to reach it (cyclingflash needs the Claude in Chrome extension), and where each one stops being useful.

## Project Overview

The app visualizes per-rider performance across every stage of multiple Grand Tour races. Users select a **race** (Tour de France, Giro d'Italia, or Vuelta a España) and **year** via dropdowns, then pick a metric and see a bump chart of every rider's ranking after each stage, with a sidebar legend and hover tooltips.

**Tech stack:**
- Frontend: Vite + TypeScript + D3.js (static site, no framework)
- Data: SQLite → Python export → JSON files bundled by Vite
- Hosting: GitHub Pages, deployed via GitHub Actions on push to `main`

**Multi-race support:** Each race SET has a canonical **slug** — `tour`, `giro`, `vuelta`, `classics`, `gravel` — used consistently for the data subdirectory (`src/data/<slug>/gc_by_stage_*.json`), the frontend `RaceId` type, the race dropdown value, and the URL hash segment. The frontend race dropdown is populated from the `RACES` registry in raceRegistry.ts (see "Race registry" below); every view (stage chart, Race Overview, All Races Overview, Riders) works for all three races, and deep links are race-aware (`#giro/2026/stage/gc`). The DB schema is multi-race via the `races` table (race_id=1 TDF, race_id=2 Giro, race_id=3 Vuelta). Editions with data: TDF 113 (1903–2026), Giro 109 (~4,700 riders), Vuelta 81 (1935–2026, ~4,500 riders).

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

## Open items as of 2026-09-14

Nothing here is broken-and-unknown; each is a deliberate stop with a reason.

**Decisions waiting on Eric (do not guess):**
- **Project rename** — analysed and **deferred**; see "Renaming the project". If revived, take the subdomain step first.
- **Landing pages have identical visible body content.** The five `<race>/index.html` pages differ only in `<title>`/meta. Distinct copy would help them rank separately, but it is a UI/content decision.
- **Duplicate ranks + same-team bib collisions** in 13 classics race-years — upstream PCS, how to model it is Eric's call. See "Known-open".
- **More riders may belong on the doping list.** Five are recorded. Re-award pairs visible in the data were deliberately NOT added without confirmation: **Vuelta 2011** (Froome/Cobo), **Vuelta 2010** (Velits/Mosquera), **Vuelta 2022** (Almeida/López). Giro 1913/1932/1948 show the same pattern from old-data artefacts and are not doping. ~~**Giro 2009** (Di Luca, Pellizotti, Valjavec)~~ — **SETTLED 2026-09-11**: the disqualification sweep found PCS striking all three through itself, so they are confirmed by the source rather than inferred from a re-award pair, and carry `disqualified=1` with provenance. Confirmed with Eric.
- **TDF 2008 KOM has two rank-1 rows** — Kohl (stripped) and Sastre (re-award). Keeping both is Eric's decision (2026-08-18); the jersey stays and the rider page carries a revoked-results note. Modelling revocations in the DB is still open.
- **The white jersey for the Giro and Vuelta.** Their youth standings are in `classification_standings` as of 2026-09-09, but `yw` is still exported for the Tour alone and `hasYouth` is still false for the other two. Turning it on is a display decision, not a data gap.

**Closed 2026-09-13/14 — rider identity and the mobile layout:**
- **There IS a mobile layout now**, built behind `@media (max-width: 767px)` in `style.css`. Additive only, so the desktop rendering is untouched BY CONSTRUCTION — a max-width query cannot apply above its breakpoint, which makes "desktop unchanged" structural rather than something to re-verify. The rider sidebar becomes a sheet behind a `#sheet-toggle` button (created lazily by `mobile.ts`, gated on `window.matchMedia`, hidden on views with no sidebar — the `[hidden]` attribute needs an ID selector to beat the UA rule). Every control is at least 36px in both axes. Verified at 375px across all five races, four routes, both stage views and the rider detail page: zero horizontal page scroll.
- **Names sort through one shared `Intl.Collator`** (`riderDisplay.ts`, `ignorePunctuation`). A bare `.sort()` compares UTF-16 code units, which put `Île-de-France` at position 1949 of 1950 in the team filter; a plain `localeCompare` gives leading punctuation full weight, which put Albert `'t Jolyn` ahead of Abdoujaparov at the top of 14,000 riders. Used everywhere names or teams are ordered.
- **The Traka source rule is conditional** — see "The Traka: PCS does not automatically win". 2023 recovered 21 -> 101 results, 2024 87 -> 102.
- **Rider identity has four files and they know about each other** — see "Rider identity: four files outside the database". ~100 merges, 2 splits, 11 recorded non-merges, 38 tandem entries excluded.
- **The 826 orphan rider rows are deleted** (2026-09-14). Litter from re-sourcing The Traka on 2026-08-24: created from the timers' full field and stranded when each edition's results were replaced from PCS. Verified unreferenced before deleting — 0 rows in `stage_results` or `classification_standings`, 0 reachable through `_rider_ids.json`, 0 present in any export — and a full gravel re-ingest afterwards re-created none. `riders` is now **18,050**, which is exactly what the app lists; the two numbers had diverged for three weeks. Nothing in the exports changed, because an unreferenced rider was never exported — which is why nothing noticed. **`validate_db.check_orphan_riders()` now reports them**, naming the script and date range that stranded them, so the next occurrence is a line of output rather than an afternoon reading `data_provenance` by hand.
- **`birth_year_approx` was wrong for 481 gravel riders** (set-median bug) and **`link_gravel_riders`'s country/era guard only fired in one direction**, which had fused a 43-year-old American David Martin into a Spanish road rider whose only result is Milan-San Remo 2023. Both fixed.

**Closed 2026-09-12:**
- **The disqualification sweep is complete** across all 113 Tour, 109 Giro and 81 Vuelta editions: **1,509 results, 69 riders**. `disqualified=1` survives a re-ingest, exports carry it, and the frontend renders it. The Vuelta count said 80 and the rider count 67 until 2026-09-19; both had gone stale, which is why `TestAiContextHeadlineCounts` now derives all four from the database.
  **Re-verified 2026-09-19 by re-reading the pages rather than trusting the sweep's own report**: 481 rows across the 1,305 stored PCS pages carry a struck-through rank, and all but two are already flagged (see the open item below). **Vuelta 2026 has no disqualifications** — its 21 pages hold zero struck ranks and its 3,292 stored results zero `DSQ` statuses. That is a real negative, not a silent one: the marker survives in the same directory and the same file format 481 times over, so a zero there means PCS published nothing to strike. **PCS strikes a result when the sanction lands, often years after the race**, so this is true as of the 2026-09-15 scrape and is not a permanent answer — re-read the pages, do not re-derive it from the database. See "PCS strikes through a disqualified rank".
- **37 impossible gravel times** — a confirmed finisher timed faster than the winner he finished behind, Athlinks asserting both. `ingest_gravel` now clears the time AND the derived `gap_seconds`, since a -9754s gap is the same claim in another column. 37 -> 0 on both counts, all 8,142 gravel results kept.
- **5,759 stale `data_provenance` rows** purged (it was 34 in the morning; the day's re-ingests and merges grew it).
- **23 typo-variant rider ids merged**, 2 merges reversed after research, 3 pairs recorded as deliberately separate. Audit reads SAME 0, REVIEW 0.

**Open work, ready to pick up:**
- **171 duplicate-rider candidates remain open** after the 2026-09-14 sweep, and the sweep classifies them so nobody re-derives the triage: 139 have no birth year on one or both sides and nothing this archive knows can decide them, 26 have conflicting nationalities and are probably two people, 6 disagree on birth year by more than rounding. Re-run the pairwise scan from "Rider identity"; the audit now prints each candidate's home towns, which is the signal most likely to settle one.
- **A tandem has no representation in this schema.** 38 two-person entries are excluded at ingest (`tandem_entries.json`) and two of them held a real finish — a tandem really did place 30th and 70th at Unbound 2016. Dropping them says the schema cannot express a two-person entry, not that the rides did not happen. Modelling them is open.
- **Four riders keep a sponsor glued to their stored name** (`jeff-hall-herbalife`, `brian-laiho-specialized` and their two partners). They are *not* the clean-named rider — the birth years say two different people — so renaming them would put two visually identical riders on the page while leaving them separate. A display decision, not a data bug.
- ~~**THE BIG ONE: the Riders grid builds 18,114 buttons eagerly and costs 628 ms**~~ — **DONE 2026-09-11. 628 ms -> 48 ms** by virtualising the grid; see "The grid is the last second".
- ~~**11 time trials have no times**~~ and ~~**1960-2025 has no local scrape files**~~ — both **CLOSED 2026-09-11**, see "The 1960-2025 Tour backfill". All 66 editions are scraped and 64 are ingested; 1978 and 1982 refuse, each holding a stage PCS never classified, and both want a decision rather than a fix.
- ~~**41 stages typed ITT hold 4,040 riders on the winner's exact time**~~ — **CLOSED 2026-09-11, applied and the warning is gone.** Each stage was fetched by its own `source_slug` and read: a non-winner whose `Time` cell matches `^[-+]?0:00$` has no published time, and all 4,040 are that. None is a mislabelled mass-start (Giro 1985 stage-8a was the genuine one, already fixed via `route_type_overrides.json`, which is why it is not in the set). NULL is the honest value; `null_itt_filler_times.py` wrote it. `ingest_race` now refuses to recreate them, so a re-ingest is safe. See "Times that no race produced".
- **54 finishers carry a 0-second finish time** across 10 stages (was 99 across 11; the ITT fix took Tour 1937 stage-17b out of the set). Do NOT reach for a re-ingest: today's code reads the same pages' `+0:00` filler and would credit all of them with the winner's time, trading one defect for the other. NULL is the honest value, and that is **still a decision waiting on Eric**.
- **Vuelta 2026 stage 8 is 10.0 km shorter on PCS (161.0) than on lavuelta.es (171.0)** and nothing found explains why. **Decided 2026-09-15: keep PCS's figure**, unexplained. Its neighbour, stage 2, turned out to be a pre-start route trim — planned 214.3, raced 202.1 — so the same is likely here, but that is inference, not evidence. Only the road book would settle it. Worth 0.3% of the race total.
- **Should Leadville 2016+ store the pro division at all?** `stages.field_definition` now RECORDS which slice each edition holds, so nothing is misleading any more — but it does not answer whether the slice is the right one. 1994-2015 hold the top 100 of the whole men's field; 2016-2025 hold a pro category of 18-79. Both are defensible and they are not comparable: a rank series across 2015/2016 changes quantity mid-chart, and the archive's deepest Leadville history is the part that would be discarded if the modern years were re-cut to match. Re-cutting them the other way (top 100 of the whole course, as before) needs a re-resolve and a re-fetch — Athlinks serves the division and the course from different endpoints, and only the division is in `_raw/`. **Eric's call**; the five closed scope questions do not cover it.
- **241 GC positions are held by riders whose gaps disagree.** A GC rank IS a position on aggregate time, so riders sharing one share the gap that produced it; rows that share a rank and disagree about the gap are self-contradictory and nothing can say which number is wrong. Found 2026-09-19 and now reported by `validate_db.check_gc_rank_gap_consistency()`. **A shared rank alone is ordinary** — Tour 1948 stage 1 has ten riders sharing 3rd on one time — which is why checking for duplicate ranks reports 1,025 groups that are almost all correct, and only the disagreeing gap is a fault. At **rank 1** it is the annulment shape (PCS lists the stripped and the promoted rider together, the promoted one keeping his gap to the man ahead) and is a NOTE, not a warning: 5 groups, 4 already flagged disqualified. **Below rank 1 it is not explained that way** — 241 groups, only 14 holding a disqualified row, median disagreement 23s, worst Tour 1904 st6 rank 2 at 388s against 18,945s. Concentrated in 1970-1995. Deciding which of two gaps is right needs the source page, not a rule. **The tie is the narrow view of a wider defect** — see the next bullet — but it is not contained by it: a tie whose two gaps both fall inside the surrounding ranks' window keeps the ladder ascending, so **14 of these 49 stages are invisible to the monotonicity check**. Both checks are needed.
- **The 5 editions a re-ingest cannot reach are fixed without one.** `fix_stage1_gc.py` applies the ingest's stage-1 rule to a single stage, so the archive is consistent: **149 rows**, 0 duplicated stage-1 GC ranks in all five. **The orphan guard was right to refuse them and `--allow-drop` would have been vandalism**: Vuelta 1941/1942/1968 number their stages by expanding PCS's split days while the scrape files are named for PCS's numbering, so Vuelta 1942 has **20 stages against 17 files** and `stage_15.json` (14 July) is our stage 18. Rebuilding it would have produced 17 stages and destroyed 62 result rows. Tour 1978 st13 is the Valence d'Agen strike stage (99 rows, held as `stage-12a`); Tour 1982 st5 is cancelled and holds nothing.
  **Vuelta 1968 GAINED 88 real GC positions** from `gc_standings` where it had invented ones; Tour 1978 and 1982 needed no change at all. **Verified by round trip**: restoring the 1996 Vuelta's stage 1 to its pre-fix state and running this reproduces the re-ingest's output on **180 of 180 rows**. That test is what caught the one real difference — the ingest keeps `gc_standings`' GAP even when its rank is `None`, and filtering those out disagreed on 100 rows.

- **53 stages hold a GC ladder that runs backwards** (342 before PCS's time marker, 111 before the stage-1 fallback fix), reported by `validate_db.check_gc_gap_monotonicity()` and triaged by **`audit_gc_ladders.py`** (offline, read-only). The GC *is* the ranking of aggregate time, so a later rank stored closer to the leader is arithmetically impossible — Tour 1919 st3 has rank 23 at 30,667s and rank 24 at 1s. Found 2026-09-19 when the 241 tie-groups turned out to live in only 49 stages while 293 more were corrupt without anything colliding.
  **The offline repair was tried and rejected, and the reason is the useful part.** *Rank is not recoverable from gap*: riders on equal aggregate time take DIFFERENT ranks, split by a tiebreak (sum of placings) we do not store — deriving rank from gap alone moves **71,806 rows, 18% of the archive**. Gap is not recoverable from rank for the same reason reversed. So the ladder proves a row is wrong without saying which value is right, and an offline "fix" would be fabrication.
  What the ladder CAN do is name the row and bound it, which is the triage: **18 ONE ROW** (removing exactly one of the step's two rows makes the ladder monotone, so that row is the suspect and its true gap is bounded by its neighbours — `rider/lucien-didier`, Tour 1978 st8, stores 4s where the ladder needs 289-304s), **14 PAIR** (either row would explain it; the evidence does not choose), **21 LADDER** (several steps, or neither removal is enough — re-fetch the classification whole). **24 stages hold TWO interleaved classifications**, one with `gc_rank` copied from `stage_rank`: Tour 1987 st1 stores ranks 13-18 twice, once at a flat 23s and once at the real prologue gaps. That is a ladder to REMOVE, not a value to correct.
  Concentrated in 1970-1995 (246 of 342) and on **stage 1** (54). A hypothesis worth not repeating: 441 of the 617 backwards steps look like `mm:ss` parsed as seconds, which would have been one parser bug — but asking whether x60 also stays UNDER the next gap leaves 23, so it was an artifact of the one-sided test.
  **RESOLVED 2026-09-19: most of these are PCS's own and our values are right.** PCS prints an asterisk on a rider whose recorded time was **AWARDED rather than raced** — credited with a group's time after a crash inside the final kilometres, most often — while he keeps the place he actually finished in. Primož Roglič is **34th on the road at Vuelta 2022 st16 with a gap of 0**. His time then no longer places him where he stands, which is exactly this shape. Whole groups get it at once: 28 riders share one stage time on Tour 1996 st7.
  **IT IS NOT A RELEGATION**, which is what I called it for an hour and shipped in a column name. The reading came from a Penalties & Fines tab on the Giro 2024 st11 page naming Tim Merlier — but **Merlier carries no marker**, while four sprinters around him do. PCS does not publish what each mark is for, so the column records only that the mark is there, never a reason. The evidence it does give, stated in the one direction it actually holds: **all 332 backwards steps across every stored GC page sit on marked rows, and NONE of the 227,820 unmarked rows is out of order.** 385 of the 717 marked rows are in order, so the mark is **necessary for a backwards step, not sufficient** — which is exactly what an exemption needs. The first measurement said "100% against 0.00%" and was wrong: it carried a running MAXIMUM down the ladder, so one corrupt cell (Tour 1996 st21 rank 43 reads `743:02:43`) condemned all 86 rows below it. **Compare each row with the one directly above it, never with a maximum.**
  **FIXED 2026-09-19.** `stage_results.time_adjusted` records it; `gc_source.py` reads the page (with the alignment gate); `backfill_time_adjusted.py` flagged **2,249 rows across 387 stages** from files already on disk; `ingest_race.py` sets the same flag from the same helper, so a rebuild recreates it; and both GC checks exempt a marked row. **342 -> 111 -> 71 -> 54 -> 53**, with **18 ONE ROW, 14 PAIR, 21 LADDER** left (the 54th was Nibali's placeholder rank; see "A GC position of 1000"). The app shows PCS's own asterisk beside the rider in the GC legend — deliberately NOT the strikethrough a disqualification gets, because nothing was taken away from him — carried to the frontend as `adj: [stage numbers]` on 768 riders in 79 editions. Verified: re-ingesting Giro 1984 into a copy reproduced all 21 flags with **0 rows changed, 0 lost, 0 new**, and the same re-ingest with the ingest change reverted dropped all 21. **NO RANK AND NO GAP WAS WRITTEN**, and the 72 re-exported data files differ from their predecessors by the added key and nothing else.
  **All THREE artifact families are read** — the stage file's own rows, the verified `gc_pages` tables, and the stored `classification_scrapes` HTML. The HTML was refused for weeks because a mark could not be attributed to a table; `scrape_classifications.tab_blocks()` solves that, keying each table by the page's own nav, and it added **810 marks** (532 Giro, 278 Vuelta). **Only the STAGE and GC tabs are read**: marks fall in STAGE (226), YOUTH (112), GC (84) and TEAMS (8) and **never in POINTS or KOM**, whose columns are points — the clearest evidence available that the asterisk annotates a TIME. TEAMS is excluded because its time is a team's, YOUTH because it is the GC time filtered to young riders.
  **The HTML needs its own alignment gate and 167 of its 1,023 files fail it** — Giro 1935-1937 among them, the split-day expansion again. Third artifact family, third time the same trap: gate on the STAGE tab's own winner and row count against the stage file.
  Coverage is still a FLOOR: Roglič at Vuelta 2022 st16 stays unflagged — that year has no `gc_pages` file, his stage row carries a bare `+0:00`, and no HTML page is stored for it.
- **The 1992 Giro's GC is CORRECT — the claim that it was a stage stale was wrong** (asserted and retracted 2026-09-19, within the hour). Its `gc_pages/*.json` files are misnamed: each holds the NEXT stage's page, all 20 of them. Comparing our stage N against `gc_pages/stage-N` therefore compared it against the wrong stage and produced a tidy, convincing 100%-agrees-with-the-previous-page result. **The lesson is the reusable part: never compare against a stored page without first proving it is that stage's page.** The gate is the page's own `result_rows` — same winner, same field size as the `stage_N.json` beside it. Do NOT gate on the date string: the same page is dated `18 July 1926` in one file and `1926-07-18` in the other, which silently rejected 1,000 good pages on the first attempt. Only Giro 1992 (20 files) is affected, plus one split-day file each in Giro 1956 and Vuelta 1990.
- **83 backwards GC ladders have no explanation yet**, the remainder after PCS's time marker (342 -> 111) and the `+0:00` zero filler (28 more). They are heterogeneous and mostly small: **165 steps, median drop 18s, 62 of them 10s or less, 18 of them 1-2s**, and 59 of the 83 stages hold exactly one. Spread across all three races and every decade from the 1920s on, with stage 1 the most common at 19. **Two hypotheses tested and rejected** — do not re-run them: *time bonifications* (drop sizes scatter across 1,3,4,5,6,7,8,11,12,18,20,21 rather than clustering on 10/6/4 or 20/12/8, and only **4 of 104** small steps involve a rider with any `bonus_seconds`), and *`mm:ss` parsed as seconds* (see above). `audit_gc_ladders.py` names the row and bounds it for the 29 where one can be; the rest need their source pages.
- ~~**The stage-1 GC fallback invents a classification**~~ — **FIXED AND APPLIED 2026-09-19.** `ingest_race` gave a stage-1 rider his STAGE placing as a GC position whenever PCS left him out of the classification; it now does that only where the stage has **no other source** — nobody with a published `gc_pos`, and no `gc_standings` entry. **212 editions re-ingested** (5 refused by the orphan guard; **they are now fixed the other way** — see the next bullet).
  **No second source could have saved the removed values, which was checked first.** `gc_all_times.json` is final-GC totals with no per-stage dimension; `bri_stages.json` (bikeraceinfo, Tour only, 1960-2025) carries `gc_top10` and is deeper than PCS on **0 of the 29** affected Tour editions; `gc_standings.json` for Vuelta 1996 st1 holds 103 riders with **100 of them ranked `None`**. PCS publishes three positions after that stage and so does every other source we hold.
  **The provenance was the real problem and is now honest.** Those rows were recorded as `results` / `source=pcs` — a claim that the page reports a classification it does not, live on 254 stage-1 stages. A stage whose GC really is the finishing order now also carries `field='gc_from_stage_order'`, `source='derived'` (28 stages).
  **What it cost and what it bought.** 3,358 fabricated `gc_rank` and 2,339 `gc_gap_seconds` removed; 3,438 riders lose a stage-1 GC in the exports. Nothing outside stage 1 moved. In return: **backwards GC ladders 111 -> 71**, **tie contradictions 241 -> 32**, **zero-gap fillers 1,095 -> 6**, **0-second finish times 54 -> 3**, and duplicated stage-1 GC ranks 748 -> 454 — all 454 remaining being PCS's own duplicates (20 team time trials where it ranks by team, plus stages where its own stage ranks repeat).
  **Three regressions the re-ingest caused, all caught by comparing against a backup rather than trusting it.** (1) 729 stages lost their start and finish: PCS labels them `Departure`/`Arrival` on 866 stage files and `Start`/`Finish` on 5,367, and the ingest only knew the second pair — Tour 1903 st1 went from Montgeron-Lyon to None. `stage_endpoint()` now reads either, and all 163 remaining NULLs match the backup exactly. (2) 312 rows lost a `team_id`; the carry-over cannot rescue `derived` values by design, and re-running `backfill_bib_numbers --field team_id` restored 439 teams and 3,742 bibs. (3) 51 `time_adjusted` flags were dropped because the ingest read the marker from a different file than the backfill did — both now read all three copies and agree exactly (868 -> 1,439).
  **A re-ingest is now a no-op**: re-running two editions changes 0 rows. 746 tests.
- ~~**718 NULL `gc_gap_seconds` can be filled from pages already on disk**~~ — **APPLIED 2026-09-19**, 718 gaps across 44 stages in 17 editions (Tour 1923 alone held 300). `backfill_gc_gaps.py` fills NULLs only and refuses to overwrite, so nothing hand-researched could be destroyed; re-running it now reports 0 rows. **The downstream effect was the part worth checking**: 321 riders' `totalTimeSeconds` CHANGED rather than filled, because `export_gc.resolve_total_time` prefers `winner + last-stage gap` over a sum of stage times and those riders had no last-stage gap until now. The new values are better by that function's own priority order, and **21 of them had been faster than their race's winner** — which is what a partial sum looks like. None is now. One new contradiction surfaced too (Tour 1919 st15 puts two riders at GC rank 8 with gaps 8,510s apart) and it is PCS's: both our values match the page exactly. A NULL cannot contradict anything; a value can.
  **The first count was 896 and was wrong, which is the part worth keeping.** PCS's time column is not always gaps: where it has no time for the leader it prints its `-0:00` filler in his cell and **ABSOLUTE times** below. Tour 2006 stage 11 offered 164 rows of ~49 hours to write into a gap column, and beside the genuine multi-hour gaps of the 1910s they look ordinary. `gc_source.gc_gaps()` now refuses such a page **whole** on two guards — the leader's cell must be a real elapsed time, and no gap may reach it, since a rider cannot be further behind than the leader has been racing. 54 pages fail that; 1,355 more simply hold fewer than two GC rows and are counted APART, because reporting them together would claim the dangerous kind is twenty-five times as common as it is. The largest honest gap-to-leader ratio on an accepted page is **0.749** (Tour 1903 st2), so the line at 1.0 is well clear of real data.
- **Four GC rows disagree with their own source page, and in all four WE ARE RIGHT.** Resolved 2026-09-19 by reading the neighbouring stages. **Tour 1957 st24**: the page puts `nino-defilippis` 6th at 1,563s and `gastone-nencini` 7th at 1,677s — but stages **22 and 23 agree with us**, Nencini 6th at 1,563s, on the page as well as in the database, and neither rider gained a second on the final stage. **Tour 1926 st17** is the same shape: stages 15 and 16 have `albert-dejonghe` 6th and `leon-parmentier2` 7th, both riders gain ~29s into st17, and only the st17 GC page swaps them. **PCS contradicts itself** — the stage result page's own GC columns match our stored values, its classification page for the same stage does not. Nothing to fix here, and a future "correction from the source" would INTRODUCE the error. `backfill_gc_gaps.py` refuses to touch them by design.
  The headline: across **2,733 stages** whose page is verified and in gap form, the archive's GC agrees with PCS on every row except these four, where PCS disagrees with itself.
- **15 editions publish a "Slowest Finisher" that is really about 10th place.** The All Races view charts `slowestFinisherTimeSeconds` as a red speed line. For the 17 editions with no `gc_rank=1` on their final stage that number is the slowest of the few riders stored, not the lanterne rouge — and the missing rank 1 is a PROOF, not a symptom: the overall leader is necessarily in a complete final classification, so those editions demonstrably do not hold the whole field. Measured 2026-09-19: mostly old Giro years whose final stage holds 7–28 riders (Giro 1966 stores ten, at GC positions 11, 13, 17, 20 …), 15 of the 17 still publish a value. **The house fix is to research the real figure, not to suppress it** — four Vuelta years already carry one in `vuelta_races_summary_overrides.json` — so `validate_db` now NAMES the editions rather than counting them. Suppressing instead would be a policy change and is Eric's call.
- **Valjavec's 2009 results are now flagged; Carretero's are deliberately not.** Applied 2026-09-19 at Eric's instruction, **22 rows**: all 21 of `rider/tadej-valjavec`'s Vuelta 2009 rows and the one Giro 2009 row (st21) that completes an edition already 18/21 flagged.
  **The Vuelta rows rest on CAS, not on PCS, and that is a first for this column.** The Court of Arbitration for Sport set aside his exoneration on 2011-04-22 and disqualified **all his results between 19 April and 30 September 2009**; the Vuelta ran 29 Aug – 20 Sep. **PCS has NOT struck his Vuelta GC** — it strikes him at 39 in the MOUNTAINS classification (that table is led by David Moncoutié, which is how it was identified), while the GC table led by Valverde leaves him alone at 30. So these 21 rows are recorded with provenance source `wikipedia`, not `pcs`, and the `source_ref` carries the ruling and its dates. The Giro row is `pcs` — PCS does strike his GC rank 7 there.
  **Giro 2009 stages 1 and 2 remain unflagged** (19/21). CAS covers them, PCS does not strike stage 1 and we hold no page for stage 2. Left as the narrower claim.
  **`rider/ramon-carretero`, Giro 2015 st1 — still DO NOT APPLY.** The struck row reads `18 Carretero Ramón Southeast` with no time and no gap, and that stage was a TEAM TIME TRIAL whose page carries a team table beside the rider one; our database has him 197th there and DNS on stage 2. Wikipedia confirms he is suspended but gives neither the window nor the annulled results.
  **The trap was already solved in this repo and I did not know it.** `scrape_classifications.tab_blocks(html)` returns `{TAB LABEL: inner html}` keyed by the page's own `<ul class="tabs tabnav resultTabs">` nav, and its docstring documents the same trap from 2026-09-09. **No committed code has the flaw** — `audit_disqualifications` scopes to the first `<table class="results">` (the stage table), `gc_source` reads named JSON keys, `scrape_classifications` uses `tab_blocks`. All three mistakes were in throwaway analysis scripts of mine, and none reached the data. Run through `tab_blocks`, both cases settle: **Valjavec's strike is in the KOM tab** (so PCS really has not struck his GC, and the CAS basis is the right one) and **Carretero's is in the STAGE tab** — but on a team time trial, where the structured scrape file shows him 197th at +3:53 while his eight teammates share 121-136 at +0:52, so the struck `18` is Southeast's team position and not his result. **Use `tab_blocks` before reading a rank off one of these pages.**
  **The recurring trap, hit three times in one day: a PCS results page stacks several classifications**, and a struck rank means nothing until you know which table it is in. Identify the table by its leader, then check the rank against what we store.
- **9 team time trials hold 536 fewer riders than the stage after them.** Measured: only 1 of the original 10 was recoverable (Vuelta 2003 st1, done). On the rest PCS has no more riders than we store — Tour 1954 st4a really is 10 riders. Coverage report, not a worklist.
- ~~**2026 Vuelta** has not been run~~ — **DONE 2026-09-14**, the day after it finished. 81 editions now, 1935-2026. Enric Mas won in **73:52:55**; van Aert took the points jersey, Buitrago the mountains, Onley the youth. **Stage 3 was cancelled mid-race** and is stored as such. Three parser defects surfaced while adding it — see "The 2026 Vuelta, and the three defects it exposed".
- **20 Tour team time trials have no rider times**, 1954-1982, and none is safely fillable — see "Team time trials with no rider times".
- **26 editions list a rider under two teams** — PCS's own data, not a defect: Alfredo Irusta rides for `deportpublic-1994` on stages 1-6 of the Vuelta and `castellblanch-1994` on 7-21. Never rewrite these; the guard in `backfill_bib_numbers --field team_id` skips their editions, which is why 4,223 Giro/Vuelta team fills are still unapplied.
- **Giro 2011 and 2013** hold a stage with no scrape file, the same shape as the 1982 Tour. 2013's stage 2 has a corrected TTT file waiting on that decision.
- **Gravel elevation.** `coverage.py` now reports these gaps honestly, and `scrape_pcs_gravel.py` reads `Vertical meters`/`ProfileScore` where PCS publishes them — The Traka 2023-2025 remain unmeasured by PCS itself.

**Known-unfixable / explained, leave alone:**
- **Giro 1946 winner time** — PCS's figure implies 46.5 km/h over 3,050 km. Storing nothing beats storing a number that fails its own check.
- **Tour 1904–1912, Giro 1909–13** — points-classification era, no time GC ever existed.
- **19 editions diverge >3% from Wikipedia on distance** — all investigated, none is a missing stage.
- **8 of 19 cancelled stages have no recorded reason.** Add a *sourced* reason or leave them; never invent a cause.
- **10 duplicate-bib collisions in TDF 1931/1932** — upstream PCS, both riders and both results correct. The repair tools ignore them by design. NOT to be confused with a rider holding TWO bibs in one edition, which is a name swap: six such riders in 1931 and 1933 blocked `backfill_bib_numbers` entirely until the swaps behind them were repaired on 2026-09-11.

**Cost/quality items worth revisiting:**
- ~~**Social cards are ~1.8 MB committed** across 6 PNGs; `pngquant` would roughly halve them.~~ — **ALREADY DONE and this line was stale (corrected 2026-09-19).** `render-og-images.sh` has quantised every card since 2026-09-11; the six total **714 KB** (730,884 bytes), not 1.8 MB. The 1.8 MB figure is the pre-quantisation size the script's own comment quotes, read here as if it were current.
- ~~**Flatten `byStage`**~~ — **measured and REJECTED 2026-08-22.** Saves 68.9% of the corpus and 3 ms on the worst file, costs ~20 call sites and a permanent readability tax, and ADDS ~41 MB to `.git` because the old blobs stay in history. Do not re-propose without reading that section.
- ~~**Entering the Riders section costs 438 ms**~~ — largely addressed 2026-08-22; see "The Riders section's 438 ms".

## Three editions were serving data the database had already repaired (2026-09-19)

`validate_exports.py` never opened `cycling.db`. Every check in it asks whether
an exported file is internally consistent — which a stale file happily is — so
**a DB repair followed by a forgotten re-export was invisible to everything.**

A one-off sweep of all 303 exported stage-race years against the database found
**three stale files**, none of them touched this session:

| file | rows disagreeing |
|---|---|
| `vuelta/1968` | 88 |
| `vuelta/1942` | 32 |
| `vuelta/1941` | 29 |

**Every difference is on stage 1**, which dates them exactly: the September
stage-1 GC work removed an invented classification from the database, and these
three files kept serving it. They are the residue of "the five editions a
re-ingest cannot reach" — repaired in the DB directly, never re-exported.

`vuelta/1968` was showing readers:

| rider | the file said | the database says |
|---|---|---|
| Rudi Altig | 2nd | **75th** |
| Domingo Perurena | 3rd | **17th** |
| Dino Zandegu | 5th | **15th** |

Re-exported; all three now agree with the database on every row, and only stage
1 moved.

**`check_exports_match_db()` makes it permanent.** It compares `gc_rank` and
`gc_gap_seconds` for the three stage races — what the last month's repairs have
actually moved, and what the chart plots — 680,000 rows against 303 files in
under two seconds. Reported as an ERROR naming the fix, in the style of the
cross-race membership and alias-map checks, because a stale export is not a
judgement call but a step somebody did not run:

```
ERROR exported year is stale: vuelta/1968: 88 row(s) disagree with the
database — run: python3 export_gc.py --race vuelta --year 1968
```

Four tests, including that a missing database and a missing export are both
silent, and a mutant that never reports staleness fails the one check that
matters.

## 18 backwards-ladder stages are 12 defects, and one of them is 7 (2026-09-19)

`audit_gc_ladders.py` reported 18 ONE ROW stages as eighteen lines. They are
**12 distinct rider-editions**, and one accounts for seven of them:

```
Those 18 ONE ROW stages are 12 distinct rider-edition(s); 1 of them spans more than one stage.
  Tour de France 1966 rider/herman-van-springel: stages [4, 5, 6, 7, 8, 9, 10],
  stored [46, 62], every one short by exactly 1s
```

**A run with a single shortfall across all of it is one carried-forward number,
not seven daily failures.** Van Springel holds 46s where his rank needs 47s on
stages 4-7 and 62s where it needs 63s on 8-10 — and everyone around him at
ranks 13-19 holds the group time exactly. He is one second ahead of a group he
is ranked behind, for a week.

**Where it enters:** his gap is 47s at stage 1 and 46s from stage 3, which is a
SPLIT DAY — stage 4's `source_slug` is `stage-3b`. The second is lost there and
carried.

**Not repairable from disk, and not guessed.** PCS's stored `gc_pages` for
those stages hold **15 rows**, top-15 only, and he is 16th — so the source that
would settle it does not cover him. Whether the gap is wrong or the rank is
wrong remains exactly the open question [[project_gc_ladder_integrity]]
describes, and `backfill_gc_gaps.py` already reports only 4 disagreements
archive-wide, none of them here.

`group_one_row_runs()` is extracted and tested rather than inline: grouping on
the rider ALONE would fuse two unrelated editions, and a mutant that does
exactly that fails both tests.

## A script that rewrote the database by being imported (2026-09-19)

`patch_giro_2026_elevation.py` had no `if __name__ == "__main__"` guard. Its
`sqlite3.connect`, its `UPDATE stages`, and its `conn.commit()` all sat at
module top level, so **importing it wrote to `cycling.db`**. Reading
`STAGE_DATA` out of it cost twenty-one rows.

**Demonstrated, not inferred.** The pre-fix file was pointed at a copy of the
database and imported — nothing else:

```
BEFORE import: [(8, 1804), (21, 1709)]
AFTER  import: [(8, 2500), (21, 500)]
```

Stage 8 went from the scraped 1,804 m back to this file's 2,500 m estimate.

**It is the only one.** An AST sweep of every unguarded module in `pipeline/`
found three with SQL keywords at top level; the other two (`gc_source.py`,
`race_set_ingest.py`) only define query strings and make no call.

**`test_no_pipeline_module_writes_to_the_db_at_import` now asserts it**, by
PARSING rather than importing — importing to find out whether importing is safe
is the bug. It matters most in that exact file:
`test_every_networked_script_still_imports` imports scripts by design, so a
suite that mutates the data it validates is the worst place for this to hide.
Restoring the old file fails it with the offending lines named.

### Two more things were wrong with it

- **It wrote 21 stages with no `record_provenance()` call at all**, against the
  rule that every writer records its source. It records both columns now, as
  `manual` — giroitalialive.com is not one of `VALID_SOURCES` and inventing a
  name for a one-off would make the registry meaningless — with the site in
  `source_ref`.
- **Running it is not idempotent, it is destructive.** 16 of its 21 values have
  since been superseded by scraped PCS figures, so it now defaults to a dry run
  and prints what it would replace:

```
 st   stored  this file  route
  6      680        500  H -> F
  8     1804       2500  H -> H
 21     1709        500  F -> F
```

Only stages 1-5 still match it.

### Elevation provenance: 2,964 unproven -> 0 (2026-09-19)

**Every elevation value in the archive now has a recorded source.** It was
found, not assigned: the stage scrape files carry `"Vertical meters"` in their
own `info` block, and it matches the database exactly for **2,879 of the 2,964**
values that had no provenance row.

That is the standard `backfill_provenance.py` already applied to `distance_km`
— claim PCS only where the artifact on disk still says so — extended to a field
its docstring had written off as *"genuinely unknowable retroactively"*. It is
not unknowable; nobody had looked in the file.

| | |
|---|---|
| proven `pcs` from the stage file | **3,342** (97.3%) |
| `unknown`, with the reason recorded | 86 (2.5%) |
| `manual` / `cyclingflash` | 6 |
| **with no provenance row at all** | **0** (was 2,964) |

**The gate matters as much as the match.** A stage file is named
`stage_<n>.json`, and a stage number is not a stable key — a split day makes
PCS's slug diverge from ours, which is the bug that put this repo on notice in
the first place. So a figure is never believed on the filename: the file's own
Distance or Date has to agree with the row first. Either suffices, because 128
stages had their distance re-sourced from Wikipedia or bikeraceinfo while the
date still pins the file down; **2,751 of the 2,879 agree on both**.

**The 86 that stay `unknown` each say why**, which is the point of recording
them at all:
- **77** — no figure on the stage page. 76 of those are the edition's FINAL
  stage, because PCS serves an empty stage page for the Paris/Madrid finale and
  publishes the number on the ROUTE page instead.
- **8** — the DB disagrees with its own scrape file, and the row now names both
  numbers: Tour 2005 st14 (file 4,175 / db 4,188), Tour 2006 st4/5/6/10/13,
  Tour 2016 st13, Vuelta 2019 st21 (file says **0**).
- **1** — no scrape file on disk.

### Then the route page settled 78 of those 86 (2026-09-19, networked)

`scrape_route_overview_elevation.py --verify-unknown` fetched **81 editions**,
one request each, and compared the ROUTE page against the values already
stored. **78 matched exactly** and are now `pcs` with the route URL as their
ref. Elevation provenance is **99.59% pcs, 8 unknown, 0 missing**.

**The mode had to be added.** The script only ever looked at stages whose value
is NULL or `derived`, so it skipped all 86 of these on sight. `--verify-unknown`
targets the opposite — a value that EXISTS whose origin was never established —
and records provenance without writing a value.

**The 7 that still disagree are the interesting ones.** The route page gives
the same figure as the stage page, so the stored value matches **neither PCS
surface**:

| | stored | both PCS pages |
|---|---|---|
| Tour 2005 st14 | 4,188 | 4,175 |
| Tour 2006 st4 | 1,736 | 1,662 |
| Tour 2006 st10 | 3,595 | 3,509 |
| Tour 2016 st13 | 752 | 685 |

Something overwrote six 2006 stages and two others with figures PCS does not
publish, and left no record. Unchanged and still `unknown`; that is a research
question, not a repair. Vuelta 2019 st21 — whose stage file says `0` — was
confirmed by the route page and is now `pcs`. The eighth remaining unknown is
Tour 1982 st5, which has no artifact at all.

**A write I did not intend, reported because it happened.** The first
`--verify-unknown --apply` run also filled **Vuelta 2020 st18 (NULL -> 1,492 m,
the Madrid finale)**, because the ordinary fill loop still ran beneath the new
mode — and the verify report's early `return` skipped the FILLED section, so it
was never printed. The value is correct and properly sourced, so it stays. The
mode is now single-purpose and a test asserts both the fill loop and the
mismatch scan are gated on the flag; ungating either fails it. **A mode that
writes silently is worse than one that writes too much.**

### The summary exports were stale, and the new staleness check cannot see them

Re-exporting for that one stage revealed that **`all_races_summary.json` had
been stale since this morning** for the Tour (15 values) and the Giro (1): the
718 GC gap fills moved 330 riders' `totalTimeSeconds`, and
`slowestFinisherTimeSeconds` is derived from those. The year files were
re-exported at the time; the summaries were not.

`check_exports_match_db()` compares `gc_by_stage` files only, so this class is
outside it. A summary is a DERIVED-from-derived file and checking it against the
DB would mean restating the exporter's own rules — including the sparse-elevation
cut-off, which is exactly the kind of subtlety a second implementation gets
wrong. **The rule is procedural for now: after any DB change, re-run
`export_race_summary.py` for each race and `export_all_races_summary.py`, not
just `export_gc.py`.**

### The Tour had been invisible to this script all along

`SCRAPE_DIRS` mapped the Giro and the Vuelta and **not the Tour**, on a comment
saying its scrapes *"live in tdf_YEAR_full.json and aren't per-stage"*. That
stopped being true when `convert_tdf_layout.py` moved them: there are **2,423
`tour_scrapes/<year>/stage_<n>.json` files across 113 years** and **not one
`tdf_*_full.json` left**. The comment outlived the layout, so
`load_stage_file()` returned nothing for every Tour stage and all 1,570 were
recorded `unknown` for results, distance, route type, slug AND elevation — on
the grounds that a file it could not find did not exist. Three tests now assert
the mapping, that each mapped directory really holds `stage_*.json`, and that
no `tdf_*_full.json` comes back.

**`--upgrade-unknown`**, opt-in, then replaced the 51 elevation rows (and 272
others) that the blind spot had already stamped `unknown` back on 2026-08-08.
`unknown` is this script's own to-do marker, not evidence, so completing it is
not discarding anything — but it is still a write, so the flag only ever moves
`unknown` -> proven. Verified across all 143,331 provenance rows: the only
transitions were **231 `unknown -> pcs`** and **92 `unknown -> derived`**, with
**0 rows moving away from a real source** and **0 stage values changed**.

The per-field breakdown in the output exists for the same reason: one total
cannot be checked against anything, and `vertical_meters pcs 2,879 / unknown 85`
was confirmed against an independent sweep written separately.

## Four single-race helpers the multi-race migration left behind (2026-09-19)

An audit of every exported name in `cycling-app/src` — 134 of them — against
every other module found four functions nothing calls. They are not random
dead code: each reads the CURRENT race out of global state, and each has a
replacement that takes the race explicitly. They are the residue of the
multi-race work.

| removed | the live replacement |
|---|---|
| `jerseyIconsEl(entry)` | `jerseyIconsElMultiRace(entry, races, years)` |
| `jerseyIconSvg(category)` | `jerseyIconSvgForRace(category, race)` |
| `ensureRiderIndex()` | `ensureRiderIndexFor(race)` |

`jerseyIconSvg` only became unreachable once `jerseyIconsEl` went — the one
caller was the other dead function, which is why a single pass over exports
found both.

**This saves 1 byte.** Vite was already tree-shaking all of it; the point is
that the source no longer offers a next reader two ways to do the same thing,
one of which silently assumes a single race. No payload claim attaches to it.

**Most of the other 16 "unused" exports are not dead** — they are used inside
their own module and merely over-exported (`ROUTE_MULTIPLIER`,
`isoToFlagEmoji`, `jerseySvg`). Dropping the keyword is churn with no reader
benefit, so they were left.

### The twenty tooltip strings nobody saw are gone (Eric's call, 2026-09-19)

`jerseyTooltipLabel()` was the fourth dead function, and the last reader of
`RaceConfig.jerseyTooltips` — five races x four strings that nothing showed.
**Removed**, along with the config field, all five blocks, and
`JerseyCategoryId`, which existed only to type them and duplicated
`JerseyCategory`.

**Keeping them would have been worse than it looked.** Their copy named the
jersey COLOUR — *"Yellow jersey — GC winner"*, *"Pink jersey — GC winner"* —
which says nothing about WHICH race once the riders grid merges five of them.
And for two race sets they were not copy at all: the classics block is
`"Classics win"` four times over and gravel is `"Off-road win"` four times, so
they could not even distinguish a GC from a KOM.

`jerseyIconTitle()` composes the race instead, and a correction to an earlier
note in this file: it renders **"Tour de France - GC"**, not "TDF - GC".
`RACE_ABBR` holds full names despite its name — `RACE_SHORT_LABEL` is the one
with the short forms.

**−131 bytes gzipped**, which unlike the dead functions is real: a string in a
live config object is not tree-shaken. Three checks in `verify-views.mjs`
assert every jersey icon names its race and its classification, and that none
carries the removed colour copy; they search for Merckx first, because the grid
is virtualised and its first alphabetical window contains nobody who has won
anything. A mutant that drops the race from the title reports
`GC | Sprint | KOM | Winner` and fails.

## A GC position of 1000, in a field of 198 (2026-09-19)

Vuelta 2015 st2 is the stage Nibali was thrown off the race for holding a team
car. PCS publishes `"1000"` in the GC-position column of his DSQ row, and the
ingest stored it as a rank. **The only `gc_rank >= 500` in 790,373 rows**, and
**the only literal `"1000"` in a rank column across 10,800 scrape files** — a
placeholder, not a convention worth modelling. 339 of the other 344 DSQ rows
store NULL.

It was also one of the 54 backwards ladders, since rank 1000 sat 98s behind a
leader that rank 194 was 1,763s behind. **54 -> 53.** One cell changed,
`gc_rank 1000 -> NULL`, verified by full-column diff against a snapshot; status
stays DSQ and the 98s gap stays.

### Two wrong rules, before the right one

This is the part worth keeping. The obvious test — **a position cannot exceed
the field it is a position in** — sounds like arithmetic and is wrong:

| rule | rows it flags | why it is wrong |
|---|---|---|
| `gc_rank > COUNT(*)` | **663** | `COUNT(*)` is what the stage's PAGE published, not the classification behind it. Vuelta 1988 st21 stores ten finishers and ranks one 113th — correctly. |
| `gc_rank > 2 * COUNT(*)` | **9** | Still catches Vuelta 1980 st1 (ranks 107-110 of 53 stored rows) and 1989 st23 (139-142 of 69). |
| **top rank > 2x the next, on a classification of 50+** | **1** | The shape of the RANK SET, which does not depend on how much of the page we kept. |

The archive's next-worst top-rank jump is **75** (Giro 1969 st2, 95 after 20) on
a 21-rider remnant, against Nibali's **806**. Both a ratio test and a bare-gap
test would have caught that good row; the size floor is what excludes it.

**The ingest fix had to be a POST-PASS for the same reason.** No row-local test
is sound, because the row loop does not know the classification yet. It now
reads the stage's rank set back after inserting it, applies the same rule, and
prints what it dropped.

**Proved against a real re-ingest, not asserted.** Vuelta 2015 was re-ingested
into a copy of the pre-fix database — the copy that still held 1000 — and the
run printed `Stage 2: dropped GC position 1000 (next is 194 of 195)` and left
NULL behind. A re-scrape will not undo this repair
([[project_name_swap_repair]] is the cautionary case).

**Six tests, three mutants, all caught** — and mutant 1 IS the first wrong rule
above, failing exactly the tests that stand for the 663 false positives.

## 718 GC gaps filled from pages already on disk (2026-09-19)

`backfill_gc_gaps.py` was written but never run. It is offline, reads only
`<race>_scrapes/<year>/gc_pages/`, and **fills NULLs only** — it refuses to
overwrite a stored value, which is what makes it safe: every write lands where
there was nothing, so nothing hand-researched can be destroyed.

**718 rows across 44 stages**, almost all pre-1931: Tour 1923 (300), 1903 (71),
1919 (49), 1914 (42), 1924 (35), and eleven more Tour years, plus Giro 1924
(12) and 1914 (3).

**Checked three ways before applying.** The dry-run table first; then an
INDEPENDENT parse of the 1923 pages that did not go through `gc_source` at all,
which agreed on all 300 fills **and found that the 620 rows already holding a
value all match the page, with zero disagreements**; then a full-column diff of
every one of the 790,373 `stage_results` rows against a pre-apply snapshot.
That diff is the real evidence: **718 cells changed, all of them
`gc_gap_seconds`, all NULL→value, 0 overwrites**, no row added or removed, no
other table touched, +44 provenance rows.

### The export changed 330 totals too, and that is the point

`export_gc.py` resolves `totalTimeSeconds` in tiers: winner time + the rider's
gap at the last stage, falling back to a SUM of per-stage finish times "often
incomplete for pre-1960 non-top-10 riders". 330 riders had no gap at the final
stage and were therefore showing the incomplete sum. They now resolve on the
accurate tier. Arithmetic, on the Giro 1924 winner's 517,417s:

| rider | was (partial sum) | now (winner + gap) |
|---|---|---|
| Scrivanti | 358,244 | 517,417 + 62,367 = **579,784** |
| Montanari | 229,442 | 517,417 + 66,644 = **584,061** |
| Garino | 269,450 | 517,417 + 75,082 = **592,499** |

Montanari's old figure was **4 days short**. This is the same defect shape as
the 74 seasons that showed a partial elevation sum as a total — a partial
presented as a whole — and it was found only by diffing the exported JSON by
parsed CONTENT ([[feedback_scoped_run_may_rewrite_whole_file]]). A line diff
would have shown 330 changed numbers and no reason to look twice.

### One new warning, and it is a true one

`check_gc_rank_gap_consistency` went **32 -> 33**. The new row is Tour 1919
st15 rank 8, where Duboc and Van Daele are BOTH stored at rank 8 — and before
the fill both held a NULL gap, so the check had nothing to compare and said
nothing. **The fill did not create the defect, it made it visible.** The stored
PCS page is itself the source of it:

```
7   Lucotti      16:01:12
8   Duboc        16:01:12     <- same time as rank 7
8   Van Daele    18:23:02     <- same rank as Duboc
```

Backwards ladders stayed at **54** — the fills introduced none.

**Not applied, and deliberately:** 4 rows whose stored value DISAGREES with the
page, which are two transposed PAIRS (Tour 1926 st17 Parmentier/Dejonghe, Tour
1957 st24 Nencini/Defilippis — each pair holds the other's number). Choosing
between us and PCS there is a different job with a different risk.

**A trap worth naming:** `check-payload.mjs` reported `other 1.8 KB -> 182.8 KB
(+10,249%)` and failed. That was a stale `build/` accumulating hashed assets
across the session's repeated builds, not a regression — `rm -rf build` and it
passes at +2.4 KB. Clear the build directory before believing a payload number,
the same way [[feedback_verify_what_you_claim_to_have_verified]] says to clear
`__pycache__`.

## The chart's end labels were a smear, and had always been clipped (2026-09-19)

The bump chart writes each rider's surname at the end of his line, at his
finishing rank. On the **default view** — latest Tour, Top 20 — twenty riders
share ranks 1-20 on an axis spanning 1 to 180, which put the labels **2.9px
apart in a 10px font**. There was no de-collision of any kind. The first thing
anyone saw on opening the app was an unreadable vertical smear at the right
edge of the chart.

`layoutEndLabels()` spreads them: push each label down until it clears the one
above, then push back up from the bottom if that overran. Order is preserved,
so reading order still matches finishing order.

**Fixing it exposed a second defect that the smear had been hiding.**
`margin.right` was the constant `36`, leaving **30px** after the label's 6px
offset — while the widest surname in that field renders at **70px** and the
median at 39. Every label past about five characters had always been cut off by
the SVG's edge; nobody could see it because they overlapped anyway. The margin
is now measured: `endLabelMargin()` picks the longest label **by character
count** (plain string work, no layout), measures only THAT one with
`getComputedTextLength`, pads it, and clamps the result to a sixth of the chart
so one freak name cannot eat the plot. One text measurement per draw, not 200.

**When they cannot all fit, the ones that fit are drawn from the best rank
down.** The classics need this: a season standing ties dozens of riders on
equal points, so "Top 20" there selects **136 riders**, wanting 1,496px of a
732px chart. A first version hid ALL labels past the threshold, and that put
the entire classics race set over a cliff edge — 73 selected at "Top 10", 66
of which fit, and all 73 disappeared. Caught by driving the real app, not by a
test.

| view | selected | labelled | overlaps | clipped |
|---|---|---|---|---|
| Tour 2026, Top 20 (default) | 20 | 20 | 0 | 0 |
| Tour 2026, All | 184 | 66 | 0 | 0 |
| Classics 2024, Top 10 | 73 | 66 | 0 | 0 |
| Giro 1998 KOM, Top 20 | 20 | 20 | 0 | 0 |

**Idempotent by construction.** Each label records the y it WANTS in
`data-y0`, and every pass re-spreads from those rather than from wherever the
last pass left it. Verified by cycling Top 10 / All / Top 20 five times in the
live app and diffing every label's position: identical.

**Not wired into the hover path.** `setHighlight()` restyles exactly two
elements to stay O(1) across ~200 riders, and re-spreading the field on every
mouseover would hand that back. A hovered rider's label can sit under a spread
one while the pointer rests there.

**Three tests, three mutants, each caught by exactly one of them** — and they
read the `y` ATTRIBUTES rather than measuring pixels, because jsdom implements
neither `getBBox` nor `getComputedTextLength`. Removing the spread reports
"closest pair 2.9px apart"; restoring the constant margin reports "30px of room
for ~73px of text"; spreading from the current y instead of `data-y0` reports
"positions moved". The failure messages are the defect, quantified.

## "Pujol ?" is not a man's name (2026-09-19)

PCS writes a first name nobody recorded as a placeholder and we store the
string it prints: **"Pujol ?", "Lecrenier ???", "Van Muyten ."**. Every view
rendered it verbatim, so a reader saw the source's punctuation as part of a
man's name.

`displayName()` — the one funnel every view's rider name goes through, in the
chart legend, the results table, the riders grid and the rider page — now
returns the bare surname whenever that is all we know:

```ts
if (r.firstName && r.lastName) return `${r.firstName} ${r.lastName}`;
return r.lastName || r.name;      // was: return r.name;
```

**Exactly 16 riders change and nobody else**, checked against all 18,038 before
writing the line. 59 riders have a surname and no first name; for 43 of them
`full_name` IS the surname and the render is unchanged, and the other 16 are
the whole placeholder set — eleven `?`/`??`/`???` and three `.`, plus Belli and
Rolin. The DB keeps PCS's string, and the Riders search still matches on it, so
nothing became unfindable.

**Two of the three checks needed a second pass.** A legend row's text ends in a
flag emoji, so the field-wide assertion was written end-anchored and **passed
against the very placeholder it existed to catch** — found by mutation, not by
reading it. It now looks for a `?` anywhere in the row. All three fail with
`displayName()` reverted.

### The `?` that is NOT a placeholder — 2 riders, 1 since merged

Two names carry a `?` inside a word: **`S?ren Nissen`** (Leadville 2015) and
**`Vojt?ch Marvan`** (Unbound 2024). That is mojibake, not a placeholder, and
**the rider ids were minted from the corrupt string** — `rider/s-ren-nissen`,
`rider/vojt-ch-marvan`. A third id, `rider/.-van-muyten`, is minted from a
placeholder dot the same way.

**It is upstream.** `gravel_scrapes/_raw/470827_701199.json`, the raw Athlinks
response, already says `"S?ren Nissen"` — our parser did not break it.

**MERGED 2026-09-19, on Eric's decision** — and the merge, not a rename, is
what removed the corruption. `rider/s-ren-nissen` is absorbed into
`rider/soren-nissen`, whose Athlinks record for Unbound 2018 spells him
`Soren`. The surviving id carries no `?` in either the slug or the name, so the
defect is gone without anyone having to choose between `Søren` and `Sören`.

**The ages settled it, not the names.** A name match is what created the
problem; matching on it again would only compound it. Athlinks gives **age 30
at Leadville 2015** and **age 33 at Unbound 2018** — three years apart across a
three-year gap. Both rows are male, they share no stage (the test that would
have disproved it), and `racerId` is **0** on all three raw records, so
Athlinks offers no identity link of its own. The nationalities disagree, `us`
against `lu`, and `lu` is right: Nissen is Luxembourgish, and Leadville records
where a rider registered from.

He now holds both results — Leadville 2015 (5th) and Unbound 2018 (39th). One
rider row gone, one result re-pointed, and **nothing else in 790,373 rows
moved**. `rider_aliases.json` carries the evidence and is read at ingest, so a
rebuild cannot recreate the id; the redirect map went **142 -> 143**, so the
dead `/rider/s-ren-nissen` link now resolves instead of dying.

**Marvan stays, and is now the only row the check reports.** He has no clean
twin to merge into, and renaming him would pick a letter no source states —
`Vojtěch` is near-certain for a Czech name of that shape, which is not the same
as published. [[feedback_no_fabricated_data]].

`validate_db.check_corrupt_rider_names()` reports them, so they stay a standing
worklist item rather than something someone noticed once. **It draws the line
deliberately**: a `?` between two letters is reported, a `?`, `??`, `???` or `.`
standing alone after a surname is not. Reporting both would bury the real
defects under 16 rows that are working as intended. It also PROVES the minted
id rather than inferring it from the shape — `slugify("S?ren Nissen")` is
literally `s-ren-nissen` — because a hyphen is not evidence; every two-word
name has one. Five tests, and both mutants (report every `?`; require a letter
on both sides) fail the check that exists to catch them.

`validate_db` is now **0 errors / 12 warnings**, up from 11 by this one.

## Every rider shipped his name twice (2026-09-19)

The rider indexes carried three names per rider: `n` as PCS prints it
("Houa Léon"), plus the split `fn`/`ln` that the name pass added in August. For
**26,161 of 30,503 riders `n` is exactly `ln + " " + fn`** — a third name
spelling nothing the other two do not.

`race_common.compact_rider_names()` drops those and `rawName()` in
`riderIndexData.ts` rebuilds them on load. **145 KB gzipped, 11.7% of the
rider-index payload**, for +27 bytes of JS:

| index | before | after | |
|---|---|---|---|
| classics | 579.0k | 511.8k | -11.6% |
| tour | 204.8k | 175.6k | -14.3% |
| vuelta | 166.5k | 142.5k | -14.5% |
| giro | 179.9k | 155.4k | -13.6% |
| gravel | 108.7k | 108.2k | -0.4% |

**It is NOT a blanket omission, and the gravel row is why.** Gravel's `n` is
"First Last" — the same string the frontend renders anyway — so deriving
`"Stamstad John"` for it would not restore a value, it would INVENT one. The
Riders search matches on `${entry.name}\n${displayName(entry)}`, two orderings
in one haystack, so a derived reversal there would silently widen what the box
matches. Only the exact PCS ordering is reconstructible, so only it is dropped;
the other 4,342 riders keep a literal `n`, including the 43 surname-only ones
and the handful whose name is `"Pujol ?"`.

**Verified by content, not by line** ([[feedback_scoped_run_may_rewrite_whole_file]]):
all five indexes were re-exported and compared as parsed objects against a
backup — 26,161 `n` keys gone, every one rebuilding byte for byte, **0 other
differences** in any field of any rider. `validate_exports.py` still reports 470
files / 0 errors / 84 warnings and the cross-race stamp is unchanged.

**Both halves are tested, and both mutants were caught.** `verify-views.mjs`
types into the real search box and asserts a rider is found by BOTH orderings;
stubbing `rawName()` to `""` fails the reversed check alone and leaves the other
two passing. `TestCompactRiderNames` asserts the exporter never drops a name the
browser could not put back, and that both `build_index` functions call it — an
exporter that forgets the call ships the field again, and the only symptom is a
bigger file.

**Rejected while measuring:** a nation string table on top of this saves a
further 7 KB gzipped, which does not pay for a new table in the format.

**Noticed in passing:** `export_riders_index.py --help` does not print help — it
parses `--help` as an unknown `--race` value, falls through to the default and
exports the Tour. Harmless (no network, idempotent), and out of scope for the
guard pass that fixed the 18 networked scripts, but it is the same shape.

## A networked audit now says how long it will take (2026-09-19)

`audit_elevation.py` fetches every stage from PCS by its own `source_slug`, and
printed only its work SET before starting: *"Auditing 1671 Tour de France
stage(s)"*. That reads like a status line. At the 2.0s of politeness it owes PCS
it is **56 minutes of network** before the first summary — and an unscoped run
started by accident is indistinguishable from a deliberate one until it is still
going an hour later. It now prints `~55m at 2.0s between fetches, at least`, and
when nothing scoped the run, the three flags that would.

The estimate is deliberately a **floor** and says so: it counts the delay
between requests and not the requests themselves. An estimate that may read low
is worth more than none; one that reads high gets ignored.

**The script was not at fault and neither were its guards** — `--race`,
`--limit` and `--split-only` all exist, and writes are already behind
`--apply-provenance`, so the aborted run wrote nothing. I started it with no
scope while looking at something else, and piped it through `tail -6`, which
buffered away the very line that would have told me. Both mistakes were mine;
the missing runtime is the one thing that would have caught either.

## The Vuelta landing page advertised the wrong decade-end (2026-09-19)

`race-page-meta.mjs` holds the hand-maintained SEO copy for the five static
landing pages — the `<title>`, the description, the og:image alt — and nothing
connected it to the archive it describes. **The 2026 Vuelta landed on 2026-09-14
and the page went on advertising "(1935–2025)"**: the one string a search engine
indexes, and a reader's first impression of how current the site is, a year
behind the data sitting beside it. The other four races were correct, which is
why it went unnoticed.

Fixed, and `test_exports.TestLandingPageYearRanges` now compares every
advertised range against the years actually exported. It parses the module
rather than importing it (the module is JavaScript), and **a parse that finds
nothing FAILS** — a silent no-op would reproduce exactly the gap it closes.

**The card was stale too, and is now re-rendered.** `og-vuelta.png` showed the
2025 general classification because `scripts/render-og-images.sh` is a manual
step that nobody re-ran when 2026 arrived — the failure its own documentation
predicts. Re-rendered from the real 2026 chart; the alt text moved to 2026 in
the same commit, because it describes the picture and the picture changed.

**The script takes a card name now:** `./scripts/render-og-images.sh og-vuelta`.
A card goes stale on its own schedule, and re-rendering the other five to fix
one rewrites five committed binaries whose content did not change — Chrome's
antialiasing and pngquant's palette search are not bit-reproducible, so they
would land in the diff as noise indistinguishable from a real design change.

**Gravel deliberately still renders 2025.** Its 2026 season holds 4 races
against 2025's 7, and a card is a picture of the archive at its best, not its
most recent. That is a choice, not an oversight.

**Two tests hold this together.** `TestSocialCardAltMatchesTheCard` compares the
season each card is screenshotted from against the season its alt text claims —
two hand-maintained files, neither importing the other, that were correct only
by coincidence. Alt text that misdescribes its image is worse than none: it is
the only description a screen-reader user gets and they cannot notice it is
wrong. Only the three Grand Tour alts name a year; the classics and gravel alts
describe their card generically, which is a better alt AND cannot rot.

## A season-level bib stopped moving on its own (2026-09-19)

`race_set_export.build_year()` took a rider's bib and team from whichever of
their rows it saw FIRST, over a query with no `ORDER BY`. SQLite returned them
in rowid order, so **re-ingesting any race in a season shuffled the rowids and
changed both fields** — every `gc_by_stage_*.json` in the set churned with no
data change behind it, and anyone diffing an export had to establish that by
hand before trusting the rest of the diff.

A stage race never hits this: one bib per rider per edition. An aggregate season
is a dozen SEPARATE races and a rider has a different number in each — Mattia De
Marchi rode 2022 as bib 110 at The Traka and 2399 at Unbound, and both are
correct.

The rows are now walked in **calendar order**, so "first seen" means "the
rider's first race of the season". One-time correction of **14,142 bibs and 181
teams**, and then it stops: verified by re-ingesting a race and re-exporting,
which churns **0 files**.

**Which bib an aggregate season ought to show at all is still open.** A
season-level bib is lossy however it is picked, and showing none may be the
better answer. But a stable wrong answer beats an unstable one, and this stops
the churn either way.

The test inserts its rows in REVERSE calendar order on purpose — that is what
makes "first row returned" and "first race of the season" different answers.
Without it the test passes whether or not the sort exists.

## 74 seasons showed a partial elevation sum as a total (2026-09-19)

The Race Overview header printed **Total Elevation** whenever *any* stage of the
season carried a figure. The classics in 1950 know the elevation of **one race in
eight**, so the header stated that race's 2,003 m as the season's total —
understating it roughly eightfold while looking authoritative. Gravel 2026 was
the case that surfaced it: The Traka's **4,198 m** presented as the total for a
season that also ran Leadville, Unbound and Sea Otter.

**74 race-seasons** were doing this: the classics from 1911 to 2011 almost
continuously, eight Giro years (1992–1999, as low as 1 stage in 23), and gravel
2026.

The overview now applies the pipeline's own threshold —
`export_race_summary.ELEVATION_MIN_COVERAGE`, 50% of ridden stages — and shows
`—` below it. **Two places showing a season's elevation under two different
rules would be worse than either.** A suppressed value carries the count in its
`title` ("Elevation is known for 1 of 8 — too few to total"), because a bare dash
says *unknown* where the truth is *known for some*. A season with nothing at all
keeps the bare dash: there is no count worth offering.

**The old guard was correct when it was written.** Its comment says the off-road
set "carries no elevation at all (Athlinks publishes none)" — true until PCS
gravel elevation landed on 2026-09-09, which turned a sound assumption into this
bug. Worth remembering when writing a guard around what a source does *not*
have.

Three scenarios in `verify-views.mjs`, mutation-checked: reverting to the
any-stage guard, suppressing every total, dropping the count, and showing a
count when nothing is known each fail one.

## A chart that read as a race collapsing (2026-09-19)

The race-history view's third metric was labelled **"Finishers"** for every race
set. For the classics that is what it is — the stored field is the one PCS
publishes. For the off-road set it is not, and the chart said something false:

| Leadville | stored | the field that actually ran |
|---|---|---|
| 2015 (`open_field`) | 100 — the `FIELD_CAP` | **1,289 men** |
| 2016 (`elite_division`) | 43 | all 43 of the pro category |

Plotted side by side under one label, that is a line **falling off a cliff in
2016**, and every reader takes it for a race that collapsed. What changed was
which slice the timer published and which slice we keep — the same thing
`stages.field_definition` exists to record.

The metric is now labelled **"Riders in archive"** for the off-road set only,
with a caveat under the buttons naming both numbers. The classics keep
"Finishers" and get no caveat, because there it would be false.

**The true field size is NOT exported instead, deliberately.** The scrape files
carry `field_size_source`, but that field also changes meaning with the rule —
for a division it is the division's size, 43 — so plotting it would swap one
ambiguous number for another with a bigger cliff. Naming what the number is
beats dressing it up as something it is not.

Four scenarios in `verify-views.mjs`, mutation-checked: relabelling gravel
"Finishers", dropping the caveat, and showing it on the classics each fail one.

## What a rank is a rank OVER (2026-09-19)

An off-road race is a mass start with categories inside it, and which slice the
timer publishes changes from year to year. **Every gravel race but Little Sugar
changes at least once; Leadville changes four times.** So Leadville's rank 3
meant "third man across the line, of the hundred stored" through 2015 and "third
PRO, with other men finishing between them" from 2016 — the same column, two
different quantities, and **nothing in the database said which**.

`stages.field_definition` now records it per edition, from the course map's own
`rule`, through the ingest, the export and into the tooltip:

| value | what a rank means | editions |
|---|---|---|
| `open_field` | place among all men; top `FIELD_CAP` stored | 59 |
| `elite_course` | place in the race, which is elite men | 21 |
| `elite_division` | **place in ONE CATEGORY** of a mass start — others finished between them | 12 |
| `pcs_field` | the field as PCS publishes it (The Traka) | 2 |

`elite_division` is the one that had to be said out loud; the others mean "place
in the field that raced" and are labelled only so the contrast is visible rather
than implied by silence. A cancelled edition stores NULL — `cancelled` is a
course-map *rule*, not a description of a field, and storing the word would make
it look like one more category. Grand Tours and classics store NULL too: one
field, nothing to disambiguate, and `validate_db` errors if a road stage carries
a value.

**The tooltip is where it lands.** Hovering a race's column header:

```
Leadville Trail 100 MTB  08/15/2015 … All men — top 100 stored
Leadville Trail 100 MTB  08/13/2016 … Pro category — others finished between these places
Leadville Trail 100 MTB  08/15/2026 … Elite men's race
```

`formatters.fieldDefinitionLabel()` returns null for a value it does not know
rather than printing the raw enum at a reader — `validate_db.check_field_definition()`
is what fails in that case, and a test asserts every rule the course map uses is
one the frontend can label.

**This did not change a single rider row** — 94 stages gained a key, 0 riders
moved. It is a fix to what the data SAYS, not to what it holds.

**It reaches the rider page too.** That page plots a career across years on one
axis, which is precisely where an off-road rank changes meaning without saying
so, and it reads `riders_index.json` rather than the year files. The aggregate
index therefore carries `fd: {raceIdx: {year: codeIdx}}` with an `fdTable` —
**94 entries, 245 bytes gzipped** — and the career tooltip reads:

```
2024 Leadville Trail 100 MTB · Result #8
Pro category — others finished between these places
```

Emitted only where some edition declares one, so the 2.3 MB classics index
gains nothing rather than two empty containers.

**It also killed a fixture drift.** `test_race_set_export.py` built its DB from a
hand-written 7-table miniature, so adding one column to `schema.sql` made fifteen
tests die on `no such column` — a failure that says nothing about the change that
caused it. It now builds from `schema.sql`, like `test_ingest.py` has since the
`route_type` incident, and its inserts name their columns instead of relying on
column COUNT. Verified by pointing an exporter at a column that does not exist
and watching the fixture reject it.

## A link to a merged rider now redirects (2026-09-19)

Merging deletes a rider id, and every link ever made to it goes dead — a
bookmark, a shared URL, a search result all land on **"No rider matches this
link."** **142 ids have been absorbed.** The bug report that started the
2026-09-18 merge pass was itself a link to `rider/torbj-r`, and that pass
deleted it: the reporter's own URL stopped working *because* they reported it.

`link_rider_race_sets.py` now also writes **`cycling-app/src/data/rider_aliases.json`**
— `{absorbed slug: canonical slug}`, and **not the same file** as
`pipeline/rider_aliases.json`, which holds the evidence for every merge. The
pipeline file is the record; this one is the 1.8 KB lookup the browser reads.
It is written by the linker rather than an exporter because it is the only
GLOBAL output: every `export_*.py` takes one race and the alias map spans all
five, the same reason the cross-race stamp lives there.

- **Only canonicals that exist in an index are exported.** A redirect to a
  rider no index holds would send one dead page to another, which is worse than
  the honest message. Two entries are exactly that and stay out:
  `jorge-padrones` and `damia-palafoix`, whose canonicals are Traka finishers
  below `FIELD_CAP`. 144 aliases in, 142 redirects out.
- **Fetched ONLY on a miss.** `riderAliases.ts` loads the file after the rider
  lookup has already failed, so every link that still resolves costs nothing.
  Measured on the PRODUCTION build: a valid rider triggers no request for it, a
  dead slug triggers exactly one. Dev is not representative and neither is the
  Performance API — Vite's `?url` import fires its own module request in dev
  that the build inlines away, and `performance.getEntriesByType('resource')`
  records neither request, which made a first attempt at this measurement report
  a confident false negative.
- **The redirect REPLACES the history entry** (`replaceHash()`), so Back does
  not land on the dead slug and bounce forward again.
- **One hop only.** An alias may never point at another alias — an invariant
  with a test on the pipeline side and a second asserted against the EXPORTED
  map, because that is what the browser actually reads.
- **`validate_exports.py` errors when the map is stale.** A merge made without
  re-running the linker would otherwise leave the redirect silently missing, and
  a missing redirect is indistinguishable from a rider who never existed.

## Recent structural changes (July 2026) — read before assuming older patterns

A cleanup + multi-race restructuring pass landed 2026-07-17. If you've seen older descriptions of this codebase, these supersede them:

**Data safety (pipeline):**
- All raw scraped data (`pipeline/tour_scrapes/`, `giro_scrapes/`, `vuelta_scrapes/` — one directory per race, `YEAR/stage_N.json` inside each) is now **tracked in git** — it used to be gitignored with the only copy on one machine.
- `cycling.db` is NOT regenerable; back it up with `python3 pipeline/db_backup.py` (rotating snapshots in `pipeline/db_backups/`). `add_stages.py` snapshots automatically before its destructive delete.
- `ingest_race.py --race {tour,giro,vuelta}` (merged from `ingest_giro.py`/`ingest_vuelta.py` 2026-07-18 — see below; the Tour joined 2026-09-10): `--dry-run` is truly read-only (it used to delete the edition!), the rebuild is atomic, `vertical_meters`/`profile_score` are preserved across re-ingest, and a bare no-arg run is refused without `--all`. **The edition ROW is kept, not deleted and re-inserted** — it carries `classification_standings` (no ON DELETE CASCADE, so deleting it raised FOREIGN KEY constraint failed on 254 editions), the ordinal `edition_name` and `uci_classification`; stage incidents are carried across by stage number. **`--all` aborts at the first refusal rather than skipping it**, so a race with any refusal wants a year-by-year loop. Use `preview_reingest.py` first.
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
| `reingest_tdf_stage.py --from-pcs` | replaces one TDF stage's results by fetching the page. Was the only route to 1960+ until 2026-09-11; those years now have scrape files, so `ingest_race.py --race tour YEAR` is the ordinary path and this is for one-off single-stage repairs |
| `derive_ttt_rider_times.py` | team time → each rider, for TTTs where PCS's rider tables are empty |
| `rescrape_ditto_stages.py` | re-scrapes stale-ditto files; rewrites only on strictly fewer violations |
| `fix_doubled_winner_times.py` | the 3,377-row winner repair (arithmetic, no re-scrape) |
| `backfill_stage_metadata.py` | fills NULL route/date from PCS's info panel |
| `scrape_route_overview_elevation.py` | elevation from the race ROUTE page (stage pages omit Paris finales/prologues); `--replace-derived` |
| `repair_mojibake_names.py` | un-corrupts stored names; re-slugs OUR ids minted from them, never an upstream one |
| `resolve_traka_events.py` | picks which event is The Traka 360 each year; `--report`, `--force` |
| `scrape_traka.py` | The Traka → the standard gravel scrape-file shape, men only |
| `backfill_rider_team_provenance.py` | provenance for pre-tracking `riders`/`teams` rows; companion to `backfill_provenance.py` (which covers `stages`) |
| `patch_cyclingflash_elevation.py` | 2001/2006 s20 from cyclingflash.com; guards on distance before writing |
| `null_itt_filler_times.py` | NULLs the 4,040 fabricated ITT finish times; re-run after any re-ingest of those editions |
| `audit_rider_racer_ids.py` | gravel riders stored under >1 id, found via Athlinks' own persistent `racer_id`; never merges, `--json` feeds `merge_rider_duplicates.py` |

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

> **The progressive scenarios must WAIT for their preconditions, never assume
> a wall-clock delay.** The first version fired its mid-load hook at a fixed
> 60ms and threw if the view was not ready. That is a correct thing to check
> and a terrible thing to bet a build on: it passed on the laptop and failed in
> CI, where the runner had rendered one race by then instead of two. The
> settle at the end of `boot()` was a second such assumption — a flat 400ms
> that could not survive a slow machine once artificial fetch delays were in
> play. Both are now conditions polled to a deadline, with one small fixed wait
> left for the deferred chart draw. Making the settle condition assert the
> chart's contents instead would just restate the check below it, and would
> therefore never fail. Verified at normal speed and at 4x the delays.

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

### DONE 2026-08-22 — every rider PCS can name now has one

| race | before | after |
|---|---|---|
| classics | 5,250 missing (**44%**) | **40 (0.34%)** |
| stage races | 27 | 3 |
| gravel | 28 | 1 |

5,252 names filled across two applies, **0 overwrites of an existing value**.
All 5,250 classics riders were fetched, 0 failures.

**The 43 that remain are correct, not a backlog.** Every one has a last name and
no first name because PCS records only a surname for them — `Monin`, `Legaux`,
`Chiesa`, and the `bel-*`/`fra-*` slugs PCS uses for unidentified early
starters. `displayName()` falls back to the surname, which is the honest
output.

**PCS's unknown-name markers are dropped, not stored.** It writes an unrecorded
given name as `?`, `??` or `.` rather than omitting it, and 14 riders came
through with `first_name='?'` — rendering "? Pujol", which is worse than
"Pujol". `split_for()` now maps those to NULL. An INITIAL is kept: "C."
in "C. Terruzzi" is what is known about that rider, not a placeholder for it
(86 riders).

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

### Done

- **All of it, 2026-08-22.** classics 5,250 -> 40, stage races 27 -> 3, gravel
  28 -> 1. 5,252 names filled, 0 overwrites. Every one of the 5,250 classics
  riders was fetched, 0 failures. See the DONE section above for what the 43
  remaining riders are and why they are correct.
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

## Mojibake: "Emil √Öberg", and the ids minted from it (2026-08-23)

The app served a rider called **Emil √Öberg**. `√Ö` is not a name — it is the
bytes `C3 85` (UTF-8 `Å`) rendered through MacRoman. Both upstreams ship this,
and both ship it inside otherwise-clean rows: the same PCS row that carries
`Martens René` correctly also carries `S.E.F.B. Banque d'Ã‰pargne` (cp1252 on
`C3 89` = `É`). Three names were affected in the whole DB.

**`scrape_athlinks.fix_mojibake()` already existed and already missed them**,
for three compounding reasons worth remembering, because each one looks
reasonable on its own:

1. Its trigger was a character class, `[‘’‚„†ÄÅâãïô]`, built from the one
   example anyone had seen (`L‚ÄôEsperance`, `E2 80 99`). It had no `√` —
   MacRoman's rendering of `C3`, the lead byte of *every* accented Latin
   letter in UTF-8. The entire À–ÿ family was outside the guard.
2. Its cleanliness score counted only categories `So/Sk/Co/Cn`. `√` and `∂`
   are `Sm`, so `Lukas L√∂er` scored 0 corrupted and 0 repaired — no
   improvement, no fix.
3. That score's blocklist contained **`Å`**, a real Nordic letter. So the
   correct `Emil Åberg` scored *dirtier* than the mojibake it came from. This
   is the one that made the case unfixable rather than merely untriggered.

The replacement lives in `race_common.py` (both ingests need it) and inverts
the design: **the round trip is its own detector.** Re-encoding a legitimately
accented name almost always yields bytes that are not valid UTF-8 — `Røed`
hits a bare continuation byte, `Vakoč` will not encode into MacRoman at all —
so the codec raises instead of returning a plausible wrong answer. The second
gate counts characters that have no business in a *name* (not letters, marks,
or name punctuation) rather than blocklisting specific ones, so no real letter
can ever be evidence against itself. It is a provable no-op on clean text,
which is what makes it safe to run at ingest.

Audited over **10.3 M strings** — every name in the DB and every string in
every scrape directory — it changes exactly those 3 names and nothing else.

### The ids are the part that outlives the names

Fixing a display name is the surface. The slugs minted *from* the corrupted
string are the actual damage, and the two upstreams need opposite treatment:

| | id | policy |
|---|---|---|
| gravel riders | `rider/emil-oberg`, `rider/lukas-l-er` | **re-slugged** to `rider/emil-aberg`, `rider/lukas-loer` |
| classics team | `team/sefb-banque-d-a-pargne-1987` | **left exactly as PCS spells it** |

The rider ids were minted by *our* `link_gravel_riders.slugify()` from the
corrupted string — these editions came from Athlinks, which publishes no rider
id, so we own them outright. (The reason is Athlinks, not PCS: PCS does cover
some gravel, under `national-race/`, and where it does its slug is preferred —
see commit 2d8cd2f0, "Source The Traka from PCS".) `√Öberg` slugified to `emil-oberg`, which reads as `Ø` and is
wrong twice over.

The team id came out of a **PCS href**. It is PCS's own identifier, generated
from PCS's own corrupted name; renaming it would break the join to the source
and to every scrape file on disk. Same rule as the four upstream PCS bib
collisions: repair the display value, never the upstream key.

`repair_mojibake_names.py` applies both policies and rewrites the 12 affected
scrape files **textually** rather than re-dumping them — they are written by
four scripts in three different `json.dump` styles, and re-dumping would bury
a two-name repair in a 40k-line reformat.

`classics_scrapes/_captures/*.txt` still contain the corruption **and must
keep it**. No script parses them; they are the raw DevTools capture of what
PCS served, and `team/sefb-banque-d-a-pargne-1987=S.E.F.B. Banque d'Ã‰pargne`
sitting in one is the evidence that the mojibake is upstream's and that the
slug was generated from PCS's own broken string. Repairing evidence destroys
it.

### Why the ingest, not the scraper

The scrape files on disk still hold whatever upstream shipped the day they
were fetched, so a rebuild reads the corruption again no matter how good the
scraper is. `fix_mojibake()` is therefore wired into all five writers
(`ingest_race`, `ingest_classics`, `ingest_gravel`,
`reingest_tdf_stage`), and `upsert_team()` additionally heals a row already
stored corrupted — narrowly: only when `fix_mojibake(stored) == repaired`, so
it can un-corrupt a name but never rename a team.
`test_gravel.TestIngestRepairsMojibake` covers both, including that negative.

---

## Provenance: `teams` had none at all (2026-08-23)

Backfilled by `backfill_rider_team_provenance.py` — the companion to
`backfill_provenance.py`, which covers `stages` and never touched these two
tables. `riders` and `teams` are now at 100%
coverage (0 rows without a provenance row, 0 orphans).

**The source is derived from evidence, never assumed.** The script reads every
scrape file on disk, records which ids are actually attested in one, and
assigns:

| evidence | source | rows |
|---|---|---|
| value byte-identical to `_rider_ids.json` | `athlinks` | 16,820 |
| id attested in a road scrape | `pcs` | 28,520 |
| id in no surviving scrape file | `unknown` | 34 riders, 1,303 teams |
| `season_year` parsed from the slug's own tail | `derived` | 4,781 |

Two things that matter more than the totals:

*Attestation only proves what the evidence covers.* A PCS results table
carries a rider's name and nationality, so it is evidence for `full_name` and
`nationality_code` — and for nothing else. A `birth_year_approx` in the same
row came from somewhere the script cannot see, so it gets `unknown`. The
`athlinks` claim is stronger than attestation: all 3,475 gravel-only riders
hold values *byte-identical* to `_rider_ids.json`, checked rather than assumed.

*The 1,303 `unknown` teams are the point, not a failure.* Their ids are
PCS-shaped, so `pcs` would look right and read plausibly forever — but no
scrape file that still exists mentions them, and 718 no longer have a single
result pointing at them. A row that admits the trail is gone is worth more
than a guess nobody can falsify.

### The comment that caused the gap

`ingest_gravel.upsert_rider()` carried a note saying rider provenance was
impossible because `data_provenance.entity_id` is declared `INTEGER` while
`rider_id` is TEXT. **That was false**, and it was the whole reason gravel
riders had no provenance: the table is not `STRICT`, so SQLite's affinity
leaves a non-numeric string alone — 41,171 rows were already doing exactly
this. The docs had resolved it on 2026-08-22; the comment was never updated
and quietly kept a writer from recording anything. There is now a test
(`test_provenance_takes_a_text_slug_as_entity_id`) asserting the behaviour the
comment denied.

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
| payload budget | 1.6s | `cycling-app/` changed |

A pipeline-only push costs ~3s rather than ~19s; a docs-only push runs nothing.

The payload check reuses the build two rows above it, so its cost is only the
gzipping of 474 files — see "Payload budget".

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

## Gravel — the off-road races (August 2026)

Seven gravel and mountain-bike races, **1994–2026**. Six are Life Time's
American events (added 2026-08-21); the seventh, The Traka 360, is Spanish and
was added 2026-08-24. In the DB they are **7 independent races**
(`races.race_type='gravel'`, one stage per edition); the frontend shows **one**
race, `gravel` — "Gravel" — whose "stages" are those races. Same aggregation as
the classics, done at export time by `export_gravel.py`.

| slug | display | short | discipline | timed by | | slug | display | short | discipline | timed by |
|---|---|---|---|---|---|---|---|---|---|---|
| `sea-otter` | Sea Otter Classic | SO | mtb→gravel | athlinks | | `chequamegon` | Chequamegon MTB Festival | CQ | mtb | athlinks |
| `unbound` | Unbound Gravel | UB | gravel | athlinks | | `little-sugar` | Little Sugar MTB | LS | mtb | athlinks |
| `leadville` | Leadville Trail 100 MTB | LV | mtb | athlinks | | `big-sugar` | Big Sugar Gravel | BS | gravel | athlinks |
| `traka` | The Traka 360 | TK | gravel | **pcs** (2023-26) / tretzesports (2021-22) | | | | | | |

**95 race-years · 8,152 results · 3,944 riders · 108 of them with a road career in this DB.**

Six of the seven are today's Life Time Grand Prix line-up, but **the archive is
deliberately wider than that series**. The Grand Prix began in 2022; Leadville
has run since 1994 and Chequamegon since 1999 (on Athlinks — the race itself
dates to 1983). A season before 2021 therefore holds fewer than seven races, the
same way a classics season before 1907 holds fewer than eleven. Nothing
special-cases it: ordering by `stage_date` renders it correctly for free.

The Traka is not a Life Time race and not part of that series at all — it is
here because it is where the European road-to-gravel crossover actually shows
up. Of its 443 riders, **34 also have road results** in this DB: Bram Tankink,
Ide Schelling, Diego Rosa, Tom Leezer, Christian Meier, Joonas Henttala,
Leonardo Basso, Jeremy Hunt, Ruben Zepuntke, Umberto Marengo, Alan Riou.

Be exact about the size of that win, because it is easy to overstate. The
gravel set's cross-race rider count went **93 → 107** when The Traka arrived
from the timers, and **107 → 108** when it moved to PCS. PCS barely finds more
crossovers. What it changes is that they stop being *inferred*: 183 of The
Traka's riders now carry an id PCS published rather than one this repo matched
by name.

**Men's fields only, for now.** These races run co-equal men's and women's
series and the women's half is a deliberate gap, not an oversight — `riders`
has no gender column, so adding it is a schema change and a second pass.

### PCS's gravel coverage — an earlier claim here was WRONG

This section used to say PCS had nothing for gravel, "verified, not assumed".
**It was wrong, and how it was wrong is the part worth keeping.** The check was
a single method: search PCS's own index for "unbound", "traka" and "gravel",
get back only "Gravel and Tar", conclude it is not there. That search **does
not return `national-race/` entries**, which is exactly where PCS files gravel.
One method, written down as verified. Eric found The Traka on PCS afterwards.

Probe by URL, never by search:

```
procyclingstats.com/national-race/<slug>/<year>/result
```

| race | on PCS |
|---|---|
| **The Traka 360** | 2023–2026 — including **2025**, which neither timer ever published |
| The Traka 200 | yes (deliberately out of scope — a different race, not a class of the 360) |
| **Big Sugar Gravel** | 2023–2025 |
| Unbound, Leadville, Sea Otter, Chequamegon, Little Sugar | genuinely absent |

So the old consequences still hold for five of the six Life Time races, and
NOT for The Traka, which now comes from PCS for every year PCS has.

**Big Sugar stays on Athlinks** despite PCS having it, and the reasoning is the
opposite of The Traka's. Athlinks already resolves a real elite men's course
there (`BIG SUGAR PRO MEN`, `… ELITE MEN`), so the field is already the sport's
own pro field rather than a window we invented; it is slightly deeper than PCS
(76/93/102 against 73/84/99); it covers 2021 and 2022, which PCS does not; and
PCS publishes no distance for it at all (`(0km)`). PCS earns its place on The
Traka because it replaces a *guess*; on Big Sugar it would replace something
already better.

That comparison did clear one thing up. **Big Sugar 2025 is stored at 86.91 km
against ~167 km every other year, and that is correct** — Athlinks' own course
name is `BIG SUGAR 50 MILE (Formerly 100)`, every 2025 course is 86.91 km, and
the winner's 39.2 km/h is right for a shorter race. The edition was genuinely
halved. It looks exactly like a course-resolution bug and is not one.

**UCI Gravel World Championships is still unsourced** (asked for 2026-08-24,
deferred). Not on PCS under either namespace; UCI's own dataride is an ASP.NET
`__VIEWSTATE` app that was returning `Exception occured while executing the
controller`; firstcycling sits behind the Cloudflare check that also blocks
cyclingflash.

### The source for the six: Athlinks, which Life Time owns

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

### The Traka: one race, two timing platforms, five names

Not on Athlinks and not on PCS — verified by search, PCS's only gravel race is
"Gravel and Tar" (NZ). Its results live on the two timers Klassmark has used,
and both are plain JSON over GET, gzipped, no key and no browser:

| years | source | how it is addressed |
|---|---|---|
| **2023–2026** | **PCS** | `national-race/the-traka-360/{year}/result` — preferred wherever it exists |
| 2021, 2022 | tretzesports.com | `getCursa.php?idCursa=N` + `getResultats.php?idCursa=N` |
| *(2023, 2024, 2026)* | *sportmaniacs.com* | *still resolved and recorded as `also_seen`, but PCS wins* |

**PCS wins every year it covers**, for one reason that outranks the rest: it
publishes real `rider/<slug>` ids. Identity in the gravel set is otherwise
matched by NAME under a strict rule with its evidence written down, because
Athlinks has no id to join on — a PCS slug turns that claim into a fact. It
also has 2025, which neither timer ever published, and it gives real trade
teams and PCS's own distance figure (independently confirming 360 km for
2023–25 and **325 km for 2026**).

Two things about PCS's rider column shape everything downstream:

| namespace | meaning |
|---|---|
| `rider/<slug>` | a rider PCS tracks. Joins straight to `riders`. 183 of The Traka's riders resolve this way. |
| `national-rider/<slug>` | known to PCS only from national/amateur racing. A **separate namespace** that does not exist in `riders` and must never be stored as if it did — these fall back to name matching like any other gravel-only rider. |

`link_gravel_riders.decide()` checks the PCS slug **first** and returns
`pcs_slug` as the decision; one folded name carrying two different PCS ids is
two people, and returns `new_ambiguous_pcs` rather than picking one.

PCS's time column is its usual one-cell time-and-gap — rank 1 absolute,
everyone below a gap — so the winner's gap is forced to 0 and every other
finisher's absolute time is winner + gap. Reading the winner's cell as both is
the bug that doubled 3,377 winning times across this DB once already.

**Only the 360 km course.** The Traka also runs 50/60/100/200/560 km events on
the same weekend; those are different races, not classes of this one.

`resolve_traka_events.py` decides which event IS the 360 and writes
`_traka_events.json` for review — the same discipline as `_course_map.json`,
and it earns it here, because two things move at once:

- **The name changed in four of five editions**: `TRAKA 360` (2021),
  `THE TRAKA 360` (2022–24), `360 K` (2025), `360 PRO M` (2026). A fixed string
  returns nothing, and nothing looks exactly like "race not held".
- **The distance moved too.** 2026's "360" is **325 km**. A km band tight
  enough to exclude the 200 would have excluded the 2026 race itself.

So the match is on a leading `360` token, then a preference for an explicitly
men's event (2026 splits into PRO M / PRO W / OPEN). Two spellings cost a
silent miss when the pattern is wrong and are now regression-tested: `"THE"` is
optional (2021 is `TRAKA 360`) and there is **no word boundary in `360K`**.

**2021 exists on BOTH platforms** — tretzesports has the real 72-man field,
sportmaniacs an empty `360K` stub. The merge prefers whichever record actually
resolved to results, so file order cannot decide which edition the archive keeps.

**2025 is missing, and that is the source's doing.** All four of that edition's
distances return an empty rankings list, and the only 2025 link on The Traka's
own results page points at a "PNS Hill Climb Challenge" side event which 404s.
The race was held on 2025-04-30. Recorded as a skip with its reason rather than
inferred away — and if the organiser publishes it later, re-running the resolve
step picks it up with no code change.

### Field selection: `pcs_field` for 2023 on, FIELD_CAP before it

| year | source | rule | rows | note |
|---|---|---|---|---|
| 2021 | tretzesports | `open_field` | 72 | under the cap anyway |
| 2022 | tretzesports | `open_field` | **100** | capped from 201 |
| 2023 | pcs | `pcs_field` | 21 | ranks 1–21 |
| 2024 | pcs | `pcs_field` | 87 | ranks run to **147** |
| 2025 | pcs | `pcs_field` | 123 | ranks run to **198** |
| 2026 | pcs | `pcs_field` | 141 | ranks run to 133 |

**`pcs_field` is never truncated, and that is not an exemption.** FIELD_CAP
exists because a mass-start result list has no line in it between elite and
everyone else, so any cutoff is ours. PCS lists only the riders it holds a page
for — that IS a line, drawn by the sport's own record-keeper, exactly as an
`elite_course` is. There is no tail to window.

What PCS publishes is a **sparse subset at TRUE positions**: 87 rows in 2024
whose ranks run to 147. Those holes are real and are preserved. Renumbering
them 1–87 would claim 87 people finished a race that 147 finished, and it would
put a rider who came 147th on the same line as one who came 87th.

The 2022 cap still bites (201 men → 100) because tretzesports publishes the
whole mass-start field and nothing distinguishes the front of it. Where a year
has both, PCS's row count is far smaller than the timer's — 2024 is 87 against
737 — because they are answering different questions: "who does PCS track" and
"who crossed the line".

`KEEP_BEYOND_CAP` still exists in `scrape_traka.py` but no longer fires: it
named riders kept past a window that the PCS-sourced years do not apply. The
move to PCS did not preserve what it was doing, and the difference is worth
recording rather than discovering later:

| rider | under the timers | under PCS |
|---|---|---|
| Leonardo Basso | 2023 139th, 2024 103rd | **2024 only, at rank 100** |
| Jeremy Hunt | 2024 DNF | **absent** |

PCS lists no non-finishers at all for 2023–2025 (2026 has 27), so Hunt's DNF
simply is not in the source. And the two sources disagree on Basso: PCS ranks
him 100th where sportmaniacs had him 103rd among men and 112th overall — three
different numbers for one ride, which is a good reminder that "rank" means
something slightly different in each. PCS's is the one stored, because PCS is
the source of record for that year.

### The Traka's upstream traps

The first and third below applied to sportmaniacs, which no longer sources any
ingested year — kept because the code still resolves it for comparison and
because a future race on that platform will meet them again. The second is
live, for 2021 and 2022:

1. **A sportmaniacs non-finisher carries `officialTime: "00:00:00"`** with an
   empty position. Parsed naively that is a finish in zero seconds, which sorts
   ahead of the winner — 180 of 2024's 737 men are in this state.
2. **tretzesports puts `DNF`/`DNS` in the time field itself** and gives those
   rows `PosicioSexe: "-1"`. Both must become a status, never a rank or a time.
3. **`nationality` arrives in four formats across five editions** — Spanish
   names (2023: `ESPAÑA`, `PAÍSES BAJOS`), ISO-2 (2024), ISO-3 (2026), plus a
   few English names and the upstream typo `Unites States (US)`. All 110
   distinct values are mapped through an explicit reviewed table in
   `scrape_traka.py`; anything not in it stays NULL. The one deliberate
   omission is `UM` (US Minor Outlying Islands) — a real ISO-2 code, so not
   dismissible as junk, but on a Girona start list far likelier a mis-selection
   than a claim. tretzesports publishes no nationality at all, so 2021 and 2022
   have none.

4. **A bib with no name becomes a rider called "Dorsal N"** — *dorsal* is
   Spanish for bib number, and tretzesports emits one wherever it timed an
   entrant it could not name. Twenty-one reached the `riders` table as riders
   in their own right and were **deleted 2026-09-11**: Dorsal 71-79, which
   held one inert `DNS` row each in The Traka 360 2021 (no rank, no time, no
   team — the edition stayed at 57 finishers and went from 72 results to 63),
   and Dorsal 15/44/119/138/158/197/204/211-215, which held no results at all
   and reached no export.

   **The placeholder is upstream, not ours.** The raw tretzesports rows read
   `{"Nom": "DORSAL 71 ", "Temps": "DNS", "PosicioSexe": "-1"}` — the timer
   puts the bib in the *name* field. `scrape_traka.py` only title-cases it.

   **Filtered at ingest since 2026-09-11**, so a rebuild no longer recreates
   them: `ingest_gravel.is_placeholder_name()` matches `^dorsal[\s_-]*\d+\b`
   and the row loop skips the entry. Verified both ways against a scratch copy
   of the DB — re-ingesting 2021 with the filter leaves 0 Dorsal riders and the
   edition at 63 results / 57 finishers; with the filter disabled all 9 come
   straight back.

   The scrape files are deliberately NOT edited — they are the record of what
   the source said — which is exactly why the filter has to sit at the point
   the DB decides what a rider is.

   **The skip is conditional, and that matters.** It only drops a placeholder
   that also carries NO result. Every one seen so far is a DNS with no rank and
   no time, so nothing is lost; but a bib-only row that actually *placed* would
   be a real result we simply cannot name, and dropping it would shrink the
   field and move everyone behind it. Those are kept and reported loudly for a
   human — the same rule as the malformed-row handling in `ingest_race`. Watch
   for it on sportmaniacs, whose index carries
   `Dorsal 0 — CORRE Y MARCHA POR LA ESCLEROSIS LATERAL`, a charity entry that
   matches the pattern and might one day have a time against it.

### Athlinks `SV` is not El Salvador — a malformed location shape (2026-09-11)

Six Leadville 2009 riders were stored as El Salvador. None is Salvadoran.

Athlinks has a location shape where the **country code lands in `region`** and a
junk value lands in `country`. Every instance carries `region: "US "` — the
trailing space is Athlinks's — against real records whose region is a state:

```
Stig Somme      {"country": "SV", "locality": "denver",  "region": "US "}   <- malformed
Lance Armstrong {"country": "US", "locality": "Grand Junction", "region": "CO"}
```

Across **59,060 raw athlete records in 91 files, `region` "US" occurs with
exactly one country value, "SV"** — 32 rows. Their localities are Calgary,
Canmore, Nanaimo (x4), Whitehorse, Carcross, Toronto (x2), Lantzville,
Victoria, Sao Paulo, Saint Genes Champanelle, Perth. Overwhelmingly Canadian,
not one Salvadoran. The locality is real; the country is not.

**The guard tests `region`, never the value "SV", and that is load-bearing.**
SV is a perfectly good code and Athlinks also uses it correctly — Mauricio
Barrientos, locality `San Salvador`, region `SS`, the one SV record in the whole
corpus with a normal region. Rejecting the code would have thrown away the real
record with the corrupt ones. Nor can the guard simply look for country-shaped
region values: `country US / region CA` is **California, 1,311 rows**.

Fixed in `scrape_athlinks.to_row` (`TestMalformedAthlinksLocation`), so no
future scrape reads one as a nationality.

**What the six were set to.** Residence is not nationality and a guess is a
claim, so only one of them got a value:

| rider | to | why |
|---|---|---|
| Stig Somme | `us` | Athlinks itself records `us` in 4 of his 5 Leadville editions, and the official Leadville results list him as Denver, Colorado |
| Sessford, Butt, Brown, Magee, Reed | **NULL** | the corrupt `sv` was the only country value any source gave |

Canmore and Nanaimo make Canada the obvious guess for several, and that is
exactly why it is not stored.

**A related sharp edge in `link_gravel_riders.py`:** where a rider has more than
one country across editions it takes `sorted(countries)[0]`. That is alphabetical
and looks arbitrary, but works as a de-facto "prefer the non-US value", which is
usually the real nationality — `['at','us'] -> at` for Lakata, `['ca','us'] -> ca`
for Roberge, 43 riders in all. It is also why Stig Somme's real `us` lost to the
corrupt `sv`. Left alone: the input was the bug, and changing the rule would
re-decide all 43.

**`club` is captured in the scrape files but not ingested.** sportmaniacs gives
a real per-edition club ("AMERICAN GRAVEL MAFIA", "PAS NORMAL STUDIOS"), which
is better evidence than the one-current-team-per-athlete figure that kept
`team_id` NULL for the Life Time races. It is still left NULL, because storing
clubs for one race of seven would make the column mean something different per
race. The data is in the files if that decision is ever revisited.

### A different flag after a long silence is a namesake

Adding The Traka exposed a hole in `link_gravel_riders.decide()`. Neither Traka
source publishes an age, so `BIRTH_TOLERANCE` — the check the docstring calls
the one that "does most of the work" — **cannot fire at all** for these riders.
`CAREER_SPAN = 30` was then the only guard, and on the first (uncapped) pass it
let through `rider/sean-yates`: the real Sean Yates last raced in 1996, and a
Spanish-registered rider of that name rode the 2024 Traka 28 years later.

The FIELD_CAP window later removed that particular rider from the archive
anyway — he finished well outside the top 100 — so the rule's only LIVE effect
today is the second row below. That does not make it redundant: the hole it
closes is real, it is invisible without a birth year, and the only reason the
Yates case is not in the data is a cap that could be changed by editing one
constant.

A country conflict on its own is NOT evidence and must never be treated as
such — these sources record where someone entered FROM, not their passport, and
22 existing matches are honest conflicts of exactly that kind (Mohorič rides
for Slovenia and enters from Monaco; Woods for Canada from Andorra; Voigt as a
German from the US). Every one of those riders' road careers overlaps or nearly
touches the gravel result.

Combined with a long silence it is different, and the two separate cleanly:

```
STALE_SPAN = 15   # years of silence after which a conflicting flag disqualifies
```

What it rejects, of everything currently in the archive:

| rider | road | gravel | why | live? |
|---|---|---|---|---|
| `rider/dag-selander` | no, one 1981 result | us, 1999 + 2006 | 18-year gap, different flag | **yes** — a pre-existing bad merge the Traka work surfaced |
| `rider/sean-yates` | gb, to 1996 | es, 2024 | 28-year gap, different flag | no — outside the top 100, so not in the archive |

The rejected rider mints a `-gvl` gravel-only identity, which is the cheap
reversible fallback the script was built around. Every long-gap match whose
country *agrees* survives untouched — Carmichael (1986 → 2006-14), Bradley,
Friel.

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
| `vertical_meters` | Athlinks publishes no elevation. PCS does, for the editions it covers, and **as of 2026-09-09 this IS stored** — The Traka 2026 holds 4,198 m. Only the Athlinks races are still NULL by necessity, and there the published figures disagree wildly — 11,586 ft and 14,517 ft for the same Leadville course, from two RideWithGPS traces. A NULL is a gap; a guess would be a claim. The Race Overview hides its elevation and difficulty metrics automatically (`hasElevationData`). |
| `profile_score` | PCS's metric, **stored as of 2026-09-09** for the gravel editions PCS covers (The Traka 2026: 125). A printed 0 next to an unmeasured `-` elevation means unrated, not flat, and is deliberately NOT stored — see `parse_parcours`. Athlinks has no equivalent. |
| `team_id` | Athlinks records no team. lifetimegrandprix.com does — but only ONE team per athlete, their current one, so attaching it to a 2022 result would be fiction. sportmaniacs DOES give a real per-edition club for The Traka; it is captured in the scrape files and still not ingested, because storing clubs for one race of seven would make the column mean something different per race. |
| season points | Life Time's own 30-to-1 Grand Prix scale exists, but it scores a 25-rider invitational, not the race. `hasSeasonPoints: false`; the bump chart plots finishing position, as the classics' does. |
| women's fields | Deliberate, and the next thing to do here. |

`route_type` carries **`G` (gravel) / `X` (mountain bike)** rather than F/H/M.
These are not points on the climbing scale — with no elevation there is no
honest way to grade them — they encode **surface**, which is what actually
distinguishes these races. Leaving the column NULL was the alternative, and
that paints Unbound flat green in the Race Overview, which is a claim rather
than a gap. `SOURCE_DERIVED`, from the discipline.

`nationality_code` for a gravel-only rider is the timer's **registered location
country**, not necessarily nationality — Torbjørn Andre Røed races as Norwegian
out of Grand Junction, Colorado. It is stored because it is right for the
overwhelming majority, and it is **never** allowed to overwrite a nationality
that came from PCS.

### Pipeline

```
resolve_gravel_courses.py   → gravel_scrapes/_course_map.json    (REVIEW THIS)
resolve_traka_events.py     → gravel_scrapes/_traka_events.json  (REVIEW THIS)
       ↓  scrape_athlinks.py   (the six Life Time races)
       ↓  scrape_traka.py      (The Traka, from either platform)
gravel_scrapes/<race>/<year>.json        (tracked in git; _raw/ is not)
       ↓  link_gravel_riders.py          → gravel_scrapes/_rider_ids.json
       ↓  ingest_gravel.py               (--dry-run; atomic per race-year)
   cycling.db                            (7 races, race_type='gravel')
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

Its last run (**2026-09-19**): **390 results agree with Life Time on both place
and time**, against 54 place and 36 time mismatches. Grouped by edition, and
every one is a systematic difference between two sources rather than a wrong
course:

| edition | agree | what differs |
|---|---|---|
| Leadville 2022 | 0 | **every** time +60s. Two clocks, not eleven defects |
| Sea Otter 2026 | 53 | 18 times, median +19s — Life Time publishes chip, the division was scored on gun |
| Unbound 2026 | 8 | 32 places, median +3 — the two sources count a different field |
| Leadville 2024 | 9 | one rider (Vermeulen: Life Time says 113th, we say 57th — overall place vs place among pros) |
| Leadville 2025 | 15 | 9 places, median −2 |
| Big Sugar / Unbound 2022, Sea Otter 2023 | 24 | 6 places, all within 1–10 |

The 385 in the previous revision of this table was from 2026-08; the counts
moved when the 2026 rounds landed and again when the off-road ranks were
repaired on 2026-09-19. **Re-run it before quoting it** — an agreement count is
exactly the kind of number that reads as current long after it stops being so.

**Checked 2026-09-19 that Unbound 2026 is not tie handling.** Our field has nine
tied groups; scoring them densely would put Seewald at 18 where Life Time says
24 and we say 25. The gap grows with depth (+1 by 25th, +2 by 32nd), so we
include one or two riders in the top 32 that Life Time does not count. Which
source is right needs Life Time's own finisher list, not its per-athlete pages.

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
# The Traka is not on Athlinks and has its own pair:
python3 resolve_traka_events.py                        # then READ the table
python3 scrape_traka.py                                # every resolved year
python3 link_gravel_riders.py                          # idempotent; re-run after ANY scrape
python3 ingest_gravel.py --dry-run                     # then without --dry-run
python3 export_gravel.py                               # no --year: the index is cross-year
python3 export_classics_history.py --set gravel
python3 validate_db.py && python3 validate_exports.py   # also errors if a year's export no longer
                              # matches the DB — the only check here that
                              # opens cycling.db
python3 crosscheck_ltgp.py                             # 2022+ only
```

A new **Athlinks** race needs a `GRAVEL` entry in `race_common.py` (with its
masterEventId), a `HEADLINE` pattern and km band in `resolve_gravel_courses.py`,
and nothing else — the frontend discovers the data by glob.

A race on **another timer** needs more: a `GRAVEL` entry with `master_id=None`
and its own `source=`, that source added to `VALID_SOURCES`, and a resolve +
scrape pair that writes the same `{info, cancelled, rows}` file shape. The
Traka pair is the worked example. Everything downstream —
`link_gravel_riders.py`, `ingest_gravel.py`, `export_gravel.py` — needed no
per-race knowledge, only for `ingest_gravel.py` to read `info["source"]`
instead of assuming Athlinks (a file without that key predates the change and
IS Athlinks).

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

## The mobile layout (September 2026)

A static site on GitHub Pages has no server, so there is no user-agent branching
and no separate mobile build. Everything is one stylesheet and one bundle.

**The whole layout lives below one line in `style.css`:**
`@media (max-width: 767px)`. Every rule for small screens sits inside it, which
makes "desktop is unchanged" a structural property rather than a claim to
re-verify — a max-width query cannot apply above its breakpoint. Anything that
must be true on mobile and false on desktop belongs in that block and nowhere
else.

767 and not 768: it is the last width before the common tablet-portrait
breakpoint, so a 768px iPad keeps the desktop layout it renders perfectly well.

**`mobile.ts` is the only JS**, and it is gated on `window.matchMedia` — with a
`typeof window` guard, because the Node smoke tests import the bundle and a bare
`window.matchMedia()` at module scope crashes them. It creates the sheet chrome
lazily (the elements do not exist in the DOM on desktop at all) and listens for
`change` so a rotation or a resize is handled without a reload.

**Two traps worth knowing:**

1. The `#sheet-toggle` button must be hidden on views that have no rider sidebar
   — Riders, Race Overview, All Years. Setting `btn.hidden = true` did nothing,
   because the UA's `[hidden] { display: none }` rule carries almost no
   specificity and the mobile rule has an ID. The selector is
   `body.is-mobile #sheet-toggle:not([hidden])`, which is what makes the DOM
   property mean what it says.
2. The riders grid is virtualised and its row height is read back out of
   `grid-auto-rows` by `gridMetrics()` in `riders.ts`. It used to be a hardcoded
   `const ROW_H = 29` with a "keep in sync" comment; raising the row to 36px for
   thumbs is exactly the edit that comment could not survive. If you change the
   row height, change it in the CSS only.

**Tap targets are 36px minimum in both axes**, set by `min-height`/`min-width`
inside the media block. Short of Apple's 44px deliberately: 44 would add 48px to
a topbar that already takes 170px of an 812px screen. The `y-axis-toggle` is one
element rotated, so a single `min-height` widens it in graph mode and heightens
it in table mode; its graph-mode strip is centred on `left: 20px` so a 36px-wide
strip does not hang off the edge.

**Verified at 375px** across all five races, four routes, both stage views and
the rider detail page: `document.documentElement.scrollWidth` is exactly 375
everywhere, and nothing is clipped-and-unreachable. Rider-name label collisions
on the Gravel and By Stage Graph charts are **pre-existing, not mobile-caused** —
measured at 1440px they are 27 and 1 respectively.

---

## Rider identity: four files outside the database (September 2026)

Road riders arrive with a PCS slug, so identity is solved before the data
reaches us. Gravel riders do not: `link_gravel_riders.py` keys them on the
FOLDED NAME, which means every identity question is decided by a string. Four
files hold the answers, all of them consulted **at ingest** — a decision applied
only to the database is undone by the next rebuild, the same trap the Dorsal
placeholders taught.

| file | claim it records | direction |
|---|---|---|
| `rider_aliases.json` → `aliases` | these two ids are one person | fuses |
| `rider_aliases.json` → `separated` | these two ids are NOT one person | blocks a merge |
| `rider_splits.json` | this ONE id is two people | fissions |
| `tandem_entries.json` | this row is not a rider at all | drops |

Plus one rule rather than a list: `race_common.strip_series_flag()` removes
Leadville's Leadman marker, `(l)` in 2011 and `LM` in 2013, before the identity
key is taken. It is applied in `link_gravel_riders.py` AND `ingest_gravel.py`,
because both look the rider up by name.

**They have to know about each other.** The two halves of a split share a name
exactly and never share a stage, which is the most confident SAME the duplicate
heuristic can produce — so `audit_rider_duplicates.py` and
`merge_rider_duplicates.py` both read `rider_splits.json` and settle such a pair
instead of merging it. Shipping the split without that took one commit to
introduce and the next sweep would have silently undone it.

**Why `tandem_entries.json` is a list and not a rule.** A tandem is two people
on one bib, identified in the raw Athlinks results by a contiguous bib block
where every name is two full names — Unbound 2016 bibs 1135-1146, Unbound 2017
1144-1150, Unbound 2019 2901-2907, Chequamegon 2013 256-261. The scrape file
does not preserve that block; all that survives is the name, and no name-shaped
test separates "Joe Stiller Tina Stiller" from "Juan Carlos Najera Alonso De
Porres" or "Ian Lopez De San Roman". A four-token rule would delete both of
those real riders, and there is a test asserting it does not. 38 entries found,
2 ever reached the database. The ingest additionally WARNS about an unlisted row
joined by `&` or `and`, which is the one tandem spelling a rule can catch safely.

**`merge_rider_duplicates.py` takes an optional per-group `canonical`.** Its last
tie-break is alphabetical, which exists so two runs agree and not because the
first id is better — when research has established which id should survive it has
to be able to say so. The override is validated against the group's members,
because silently ignoring a typo would merge the pair the wrong way round.

---

## What the Athlinks data will and will not tell you (2026-09-12/14)

A whole duplicate pass was argued from names and ages before anyone looked at
what else is in the file. Read this before trusting either.

**`age_at_race` is noise at plus or minus 3 to 5 years.** Lachlan Morton's Dirty
Kanza 2019 row says 19 when he was 27. Measured across the pairs examined,
75% of the ids carrying more than two ages contradict themselves. Consequences:

- A gap of 4 between two ids is NOT evidence they are different people.
- An id whose own rows imply birth years more than ~6 years apart IS a
  conflation — `rider/tom-miller` aged 20 years in 8, `rider/mark-smith` 7 in 14.
  That is the bar `rider_splits.json` uses.
- Do not filter on "an id contradicts itself" without checking what that selects.
  Used as a guard it mostly picks out ids with MORE age data: across 63 pairs it
  cleared, the median id carried zero ages and so could not fail the test.

**`birth_year_approx` was wrong for 481 gravel riders until 2026-09-12.**
`link_gravel_riders.py` accumulated implied birth years into a SET and took the
median of that, so ten readings of 1992 and one of 2000 collapsed to two numbers
and the typo weighed as much as the ten — and with an even count the index picks
the HIGHER one. Fixed to take the median over the observations. The check that
settles it is independent of every age involved: 57 of the corrected values now
match a birthday scraped from a PCS rider page.

**`locality` is the strongest signal in the file, and nothing read it for
months.** It settled two cases outright: Jeff Bradley's 7-Eleven road career and
his three Chequamegon rides both read Davenport, Iowa; Alfred Thresher's three
Leadvilles all read Las Vegas. But it works PAIRWISE, on a candidate something
else proposed — as a bulk homonym flag it catches 256 names and almost none is a
second person, because riders move house. `audit_rider_duplicates.py` now prints
each candidate's towns and the comparison between them.

**`region` is often the RACE's state, not the rider's.** Whenever the locality
string already carries a state, Athlinks puts the event's state in `region`:
Thresher reads CO and NV for one Las Vegas rider because Leadville is in
Colorado. It is also spelt both ways — `CO` and `COLORADO` — frequently for one
rider in different years. Use `normalize_region()`, and prefer the locality.

**Leadville seeds a returning rider with last year's finishing position as this
year's bib.** Measured over the whole Leadville archive: it holds for 75% of
returning top-100 finishers and 8% of those outside 300th, so it is seeding and
not coincidence. That chain is what proved three Threshers were one man —
2010 bib 1451 finishing 29th, 2011 bib 29 finishing 56th, 2012 bib 56. Nobody
entering for the first time is handed bib 29.

**Measure the base rate before trusting a name.** "Mike Johnson" sounds
hopeless; the archive holds 24 riders surnamed Johnson and exactly two called
Mike or Michael. "Sonnesyn" holds two, both halves of one rider. The count is
one query and it changes the answer.

**`rank_overall` is in the scrape files and differs from `stage_rank`**, which
is the men's/division rank. Thresher finished 29th overall and is stored at 28.
The bib chain needs the overall number.

**sportmaniacs and tretzesports publish no location of any kind** — nationality
and club only. Everything above applies to the five Athlinks races, not the Traka.

---

## The Traka: PCS does not automatically win (2026-09-12)

`resolve_traka_events.py` preferred PCS for every year it covered, unconditionally.
For an open mass-start gravel race PCS lists only the riders it has road pages
for: 21 of The Traka 2023's 291 classified men, where this archive's own
`FIELD_CAP` would take 100. The edition was stored at 21 riders and nothing
noticed, because `coverage.py` counts NULLs and a field that SHRANK has none.

The preference is now conditional on `contribution()` — the size of the WINDOW
each source's rule would take, not its raw field size, because `open_field` is
capped and `pcs_field` is not. Ties go to PCS, which is the point of preferring
it: real `rider/<slug>` ids make the crossover to a road career an exact join.
It only loses when it would cost riders.

Effect: 2023 21 -> 101, 2024 87 -> 102, 2025 and 2026 unchanged (sportmaniacs
published no rankings for 2025, and 2026's sportmaniacs event is a 325 km
360 PRO M with 135). Cost: 9 team assignments PCS supplied and the timers do
not, plus 20 PCS rider ids whose results moved to differently-spelled ids —
which is where most of the merge work below came from.

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

### Extended back past 1990 (2026-09-11)

The August pass filled 1990-2012 and stopped, because that was the range the 1990
Tour's missing total had pointed at. The hole was never 1990-specific. Running the
same tool at every earlier year filled **73 more stages**, all NULL-fills, all
`SOURCE_PCS`, nothing overwritten:

| race | stages | years | what they are |
|---|---|---|---|
| Tour | 33 | 1948-1989 | every one a Paris finale |
| Giro | 22 | 1993, 2001-2022 | 21 finales + 2011 st20 Verbania-Sestriere |
| Vuelta | 18 | 1985-2000 | 14 Madrid finales + 4 prologues |

All 33 Tour editions had been storing N-1 of N stages and undercounting their
total by exactly one finale — 1982 charted 45,134 m against PCS's own 47,314 m.
Every total moved up, by 200 m to 2,633 m, one stage each.

**Six values a human should still glance at.** Each was inside the m/km band its
own year's flat stages occupy, which is why they were written; each is also the
kind of coincidence worth knowing about rather than discovering later:

- **Tour 1981 and 1982** both return exactly **2180 m**, over 186.8 and 186.0 km,
  both Fontenay-sous-Bois→Paris. Plausibly the same route twice, but it is the
  repeated-round-number shape `validate_db` flags for distances.
- **Vuelta 1988 and 1989** both **2500 m**; **1998 and 1999** both **944 m**.
- **Three near-zero circuit finales** — Giro 2020 st21 at **3 m**, 2008 st21 at
  12 m, Vuelta 1995 prologue at 19 m. A pan-flat Milan circuit really is near
  zero, and these are not the `0` that means a blank PCS field (see the
  `vertical_meters = 0` trap below) — but 3 m is worth one look.

**Genuinely absent from PCS, checked directly rather than assumed** — the route
page carries no figures at all for any of these, so no scrape will fill them:
the **pre-war Tour**, the **1954-1962 Tour block** (1954, 1955, 1956, 1957,
1959, 1962 — 141 stages), and **Giro 1992-1999** (167 stages across 8
consecutive editions). That is 308 stages that are not work.

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
│   │                                 #   rolldownOptions.input is DERIVED from race-page-meta.mjs
│   │                                 #   (`rollupOptions` pre-Vite-8; the old key still works)
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
│           │   └── riders_index.json      # 5,471 riders / 632 teams — 815 KB
│           ├── giro/                 # Giro d'Italia — 109 years, 1909–2026
│           │   ├── gc_by_stage_YEAR.json
│           │   ├── all_races_summary.json # built by export_race_summary.py --race giro
│           │   └── riders_index.json      # 4,722 riders / 733 teams — 698 KB
│           ├── vuelta/               # Vuelta a España — 81 years, 1935–2026
│           │   ├── gc_by_stage_YEAR.json
│           │   ├── all_races_summary.json
│           │   └── riders_index.json      # 4,491 riders / 601 teams — 637 KB
│           ├── classics/             # One-day classics — 134 years, 1892–2026
│           │   ├── gc_by_stage_YEAR.json  # An aggregate "season": N races ordered by stage_date,
│           │   │                          #   NOT stages of one race. See "by-Stage Table for an
│           │   │                          #   aggregate race"
│           │   ├── race_history.json      # Per-race small multiples. No all_races_summary.json
│           │   └── riders_index.json      # 11,934 riders / 1,637 teams — 2,271 KB, the largest
│           │                              #   single asset the app ships
│           └── gravel/               # Life Time off-road races — 33 years, 1994–2026
│               ├── gc_by_stage_YEAR.json  # Aggregate season, same shape as classics
│               ├── race_history.json      # No all_races_summary.json — this set awards no points
│               └── riders_index.json      # 3,885 riders / 32 teams — 477 KB
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
    ├── ingest_race.py                # Ingests any stage race: --race {tour,giro,vuelta}
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
    │                                 #   Indexes by STAGE NUMBER over a contiguous range, not by file
    │                                 #   order: a cancelled stage has no file but does have a DB row
    ├── derive_missing_stage_points.py # Fills an EMPTY stage's sprint/KOM points from PCS's own
    │                                 #   cumulative classifications: (after stage N) - (after N-1).
    │                                 #   Four guards, each of which caught something real — a baseline is
    │                                 #   mandatory, a rider absent from the baseline is capped by the
    │                                 #   largest verifiable award, non-positive values are never written
    │                                 #   (PCS lists penalised riders on -5), and every write is gated on
    │                                 #   MEASURED improvement vs PCS's published table. Records what it
    │                                 #   derived in derived_stage_points.json. Never overwrites scraped
    │                                 #   data, and never touches a PARTIAL stage
    ├── audit_points_residual.py      # How far our per-stage points are from PCS's published
    │                                 #   classifications, and --localize says WHY: PENALTY / SCALE /
    │                                 #   JITTER / UNEXPLAINED. Built because "the residual is upstream"
    │                                 #   was asserted twice here and was wrong both times
    ├── refresh_stage_points.py       # Re-reads ONLY sprint_points/kom_points into existing scrape files,
    │                                 #   for giro + vuelta. --probe/--dry-run/--apply/--resume, PID-locked.
    │                                 #   Asserts no other key changes before saving, so it can never
    │                                 #   revert a name-swap repair the way a full re-scrape would.
    │                                 #   A stage may LOSE points only if the page was fetched and has no
    │                                 #   points column — a failed fetch is refused, not written as empty
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
    │
    │   # Rider identity — read at INGEST, because a decision applied only to the DB is
    │   # undone by the next rebuild. See "Rider identity: four files outside the database"
    ├── rider_aliases.json            # NOT the same file as cycling-app/src/data/rider_aliases.json, which is
    │                                 #   the browser's redirect lookup exported FROM this one.
    │                                 #   `aliases`: absorbed id -> canonical id, with the evidence for each.
    │                                 #   `separated`: pairs a human ruled DIFFERENT people, so the audit
    │                                 #   stops re-proposing them. 127 and 11 as of 2026-09-14
    ├── rider_splits.json             # The mirror: ONE id that is two people, keyed on
    │                                 #   (rider_id, race, year) because that is what the scrape file
    │                                 #   carries. `rejected` records two candidates that did NOT meet
    │                                 #   the bar, so nobody re-derives them
    ├── tandem_entries.json           # Two people on one bib — not a rider. An explicit list, not a rule:
    │                                 #   the tell is a bib block in the raw results, which the scrape
    │                                 #   file does not preserve. 38 entries, 3 races
    ├── warm_rider_cache.py           # Parallel fetcher into scrape_rider_details.py's cache. Built for a
    │                                 #   6,304-rider birthday scrape that measured out at a 2.5% hit rate
    │                                 #   and was not run; --skip-no-pcs encodes why
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
    ├── tour_scrapes/YEAR/stage_N.json  # Raw PCS scrape files — ALL tracked in git; identical layout for giro_scrapes/ and vuelta_scrapes/
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

> **Critical:** `cycling.db` is gitignored and must be kept locally at `pipeline/cycling.db`. It is **not regenerable** — most historical years' raw scrape files no longer exist. Back it up with `python3 pipeline/db_backup.py` (rotating snapshots in `pipeline/db_backups/`, newest 5 kept; `add_stages.py` snapshots automatically before its destructive delete step). All raw scraped data (`tour_scrapes/`, `giro_scrapes/`, `vuelta_scrapes/`) IS tracked in git.

> **`ingest_race.py --race tour <year>` is the tool for adding a TDF year** (since 2026-09-10; it replaced `add_pre1960.py`, which existed only because the Tour's files were laid out differently). It writes to the real `pipeline/cycling.db` and preserves per-stage elevation and distances that live only there. See "Adding a New Year" below.

---

## Data Pipeline

### Tour de France pipeline
```
PCS website  →  tour_scrapes/YEAR/stage_N.json  (scraped via a real browser — see note below)
                       ↓
         ingest_race.py --race tour  →  cycling.db
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

> **Scraping PCS in 2025+:** plain `curl`/`urllib` requests get a Cloudflare "Just a moment…" 403 challenge page — `scrape_pcs_stages.py` (urllib-based) no longer works against the live site. Use a real browser (e.g. the Chrome MCP tools) to load each stage page and extract the results table via injected JavaScript instead. See "Scraping a live/in-progress race from PCS" below for the exact DOM structure and a working extraction pattern.

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

**`profile_icons.json`** — `{"2025": ["p1", "p3", ...], ...}`. **Raw PCS profile-icon codes** (`p1`–`p5`), NOT decoded route-type letters — a past version of this doc said otherwise; the actual decoding happens in `race_common.detect_route_type(icon, won_how)`:
1. If `won_how` (the stage's "Won how" text, e.g. "Sprint of small group") contains "team time trial"/"ttt" → `route_type = "TTT"`.
2. Else if it contains "time trial" → `"TT"`.
3. Else fall back to `ICON_TO_ROUTE = {"p1": "F", "p2": "H", "p3": "H", "p4": "M", "p5": "M"}`.

This matters when scraping a TTT stage whose PCS page doesn't populate `won_how` with descriptive text (seen on 2026 stage 1) — you must **manually set that stage's `info["Won how"]`** in that stage's `tour_scrapes/YEAR/stage_N.json` to a string containing "team time trial" (or "time trial" for a lone ITT) before running `ingest_race.py --race tour`, or it silently misclassifies as Flat/Hilly/Mountain from the icon alone.

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

**Static landing pages must be listed in TWO places, and now aren't.** `generate-race-pages.mjs` writes `<race>/index.html` from `race-page-meta.mjs`'s `RACES`, and `vite.config.ts` needs each one in `rolldownOptions.input` (named `rollupOptions` before Vite 8; the old key is still honoured) or it never reaches `build/`. `classics/` was generated but not listed, so `/classics/` 404'd on the live site **while working perfectly in dev**, where Vite serves the file straight off disk. (The cross-race footer links that surfaced that 404 were removed 2026-08-19 as redundant with the race dropdown. The URLs are still built and still in `sitemap.xml`, so the failure mode is unchanged — it would just surface via the sitemap now rather than a click, which is slower to notice.) `vite.config.ts` now derives its input map from the same `RACES` object. `race-page-meta.mjs` is data-only for exactly this reason — importing the generator would run its file writes every time the Vite config loads.

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

## Build toolchain (current as of 2026-09-16)

| | version | note |
|---|---|---|
| Node (CI **and** local) | **24** | was pinned to 20 in CI, which is past EOL and a different major from every developer |
| Vite | **8.3** | builds with **rolldown**, not Rollup; Oxc and Lightning CSS, not esbuild |
| `actions/checkout`, `actions/setup-node` | **v7** | |
| `actions/upload-pages-artifact`, `actions/deploy-pages` | **v5** | |
| `npm audit` | **0 vulnerabilities** | |

**Four things here that are easy to get wrong:**

* **`npm audit fix --force` proposed the wrong upgrade.** The only advisory that
  needed a real version bump was `esbuild <=0.24.2`, reachable through Vite, and
  `--force` wanted Vite 8. But **Vite 7 already fixes it** (`esbuild ^0.27 ||
  ^0.28`) *and keeps Rollup*. Taking `--force` would have swapped the bundler
  inside a security patch for no security benefit. Check the MINIMUM version
  that clears an advisory before accepting what `--force` offers.
* **That esbuild advisory is a DEV-SERVER issue** (GHSA-67mh-4wv8-2f99 — a
  website can read responses from the dev server). It does not affect the built
  site, so it never warranted rushing.
* **The rolldown swap barely moved the artifact.** 152 files before and after,
  and only `main.js` (-1,482 B) and `main.css` (-98 B) changed size at all;
  every data JSON, image and HTML byte-identical, payload budget -1.9 KB. If a
  future bundler change moves more than that, it is worth understanding why.
* **`build.rollupOptions` still works on Vite 8.** It is renamed
  `rolldownOptions`, and this repo uses the new name — but the old one emits all
  six entry points and a byte-identical bundle with no deprecation warning
  (verified by building with it, 2026-09-16). A comment in `vite.config.ts` once
  claimed otherwise; do not reinstate that claim.

The two Node runtimes are separate and get confused: the one the ACTIONS run on
(fixed by bumping the action pins) and `node-version:`, the one the SITE is
BUILT with. The Node 20 deprecation warnings were about the first; they went
2 -> 0 with the action bumps alone.

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
4. Rename the `tour_scrapes/` directory last, or never.

Names considered: `grand-tour-analytics` is **already too narrow** (the classics aren't grand tours). Prefer race-agnostic — `cycling-analytics`, `procycling-analytics`, `peloton-analytics`.

---

## Adding a New Year (e.g. 2026)

1. **Scrape PCS data** for the new year into `tour_scrapes/2026/stage_N.json`, one file per stage (`{"n": 1, "info": {...}, "rows": [...]}`) — the same shape the Giro and Vuelta use. For a live/in-progress Tour this must be done via a real browser, which lands the files in the flat `scrapes/` directory for `add_stages.py` to pick up; see "Scraping a live/in-progress race from PCS" below. Each row is `[rnk, gc_pos, gc_lag, bib, age, rider_name, rider_slug, nat, team_name, team_slug, uci_pts, pcs_pts, bonus_txt, abs_time_txt, gap_txt]` — only the stage winner (`rnk == "1"`) needs a real `abs_time_txt`; every other rider needs `gap_txt`, and the winner's `gap_txt` is `+0:00`, never their own time (see the September 2026 rules). `gc_pos`/`gc_lag` blank on stage 1 falls back to the stage rank/gap; it is NOT carried forward beyond that. An edition's final classifications go in `tour_scrapes/2026/classifications.json`.

2. **Add to DB with `ingest_race.py`:**
   ```bash
   cd pipeline
   python3 ingest_race.py --race tour 2026 --dry-run   # sanity check first
   python3 ingest_race.py --race tour 2026            # real insert
   ```
   This only works if `2026` is **not already** in `race_editions` — see "Adding stages to an in-progress year" below for what to do once it is.

3. **Add sprint points** for the year to `tour_sprint_points.json`. Key = year string, value = array of dicts (one per stage, same order as DB stages) mapping `rider/slug` → points earned that stage from sprints + stage finish (exclude KOM sprint points). See "Scraping a live/in-progress race from PCS" for how to extract these from PCS's `-points` page.

4. **Add profile icons** for the year to `profile_icons.json` — an array of **raw PCS icon codes** (`p1`–`p5`), one per stage, in DB stage order. For a TTT/ITT stage, also make sure that stage's `info["Won how"]` in `tdf_2026_full.json` contains "team time trial"/"time trial" text (see the `profile_icons.json` warning above) — the icon code alone won't classify it correctly.

5. **Add KOM points** for the year to `tour_kom_points_reconciled.json`. Same structure as tour_sprint_points.json — see "Scraping a live/in-progress race from PCS" for extraction.

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
- `ingest_race.py --race tour` is the underlying DB inserter; `add_stages.py` orchestrates around it
- `fix_2026_name_swaps.py` was retired 2026-09-10; `fix_name_swaps.py --race tour` covers every year generically
  it without `--dry-run` first, it isn't idempotent and would swap correct riders back to wrong

> **Never pre-fill or estimate time gaps.** Even flat sprint stages produce real time gaps — crashes and incidents can leave riders at the back losing 3–7+ minutes, and riders can DNS/DNF on any stage type. Every `gap_txt` value in a scrape file must come from actual PCS data. Do not write stage files until the real PCS results page has been scraped.

### Manual fallback (if add_stages.py isn't suitable)

`ingest_race.py --race tour` REPLACES an existing edition rather than skipping it, and preserves the per-stage elevation, profile scores and distances that live only in the database (`preserved_by_slug`). The delete-and-rebuild dance the old `add_pre1960.py` needed is gone.

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

**Current status (as of 2026-09-14):** 81 editions with data, 1935–2026 (4,491 riders / 601 teams). The 2026 edition was added the day after it finished — see "The 2026 Vuelta, and the three defects it exposed" for what that pass changed in the shared scraper, and read it before adding another year.

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

### Adding a JUST-FINISHED Vuelta — the full recipe (used for 2026, 2026-09-14)

The block above is the historical-backfill recipe and is missing four steps a
current edition needs. None of the four fails a validator if you skip it; each
shows up as a blank or a stale number. In order:

```bash
cd pipeline
python3 db_backup.py                                   # cycling.db is NOT regenerable

SCRAPE_DELAY=4.0 python3 scrape_vuelta.py 2026         # replays recorded name swaps itself
python3 detect_name_swaps.py --race vuelta --year 2026 # NEW swaps this year; confirm by TEAM first
python3 fix_name_swaps.py --race vuelta --year 2026 --dry-run
python3 fix_name_swaps.py --race vuelta --year 2026 --apply

python3 build_vuelta_points.py
python3 ingest_race.py --race vuelta 2026 --dry-run
python3 ingest_race.py --race vuelta 2026

python3 insert_cancelled_stages.py --dry-run           # (1) any stage the scraper refused
python3 insert_cancelled_stages.py --apply             #     then WRITE THE REASON into stage_notes.json
python3 scrape_vuelta_stage_info.py 2026               # (2) elevation + profile score
python3 scrape_classifications.py --race vuelta --year 2026 --apply   # (3) final points/KOM/youth
python3 check_vuelta_gc_times.py 2026                  # (4) official GC winner time
python3 scrape_wiki_distances.py --race vuelta         # rebuilds the whole file; diff it

python3 export_gc.py --race vuelta --year 2026
python3 export_race_summary.py --race vuelta
python3 export_riders_index.py --race vuelta

python3 validate_exports.py --race vuelta   # expect 0 errors; compare the WARNING COUNT to the baseline
python3 validate_db.py                      # a deliberate row-count rise wants --update-patch-manifest
python3 coverage.py --race vuelta           # the new year should not appear at all
```

**(4) is the highest-leverage step**, exactly as it is for the Tour.
`export_race_summary.py` reads `vuelta_gc_winner_times.json` directly for
`gcWinnerTimeSeconds`, and `export_gc.py` bases every rider's
`totalTimeSeconds` on it. Until it exists, the fallback is a sum of stage
times, which for 2026 was **693 s (11:33) over** PCS's official 73:52:55.
`slowestFinisherTimeSeconds` then appears on its own. `apply_vuelta_gc_corrections.py`
is a LEGACY path — it writes the same figure into
`vuelta_races_summary_overrides.json`, which the exporter no longer needs, and
it iterates over every correction, so running it would add ~79 override entries
to a file that holds 4. Don't.

**Things that will look like problems and are not** (all seen on 2026):

| symptom | what it is |
|---|---|
| a NEW distance divergence >3% | reconcile against PCS's `/route` page total first, then record it in `distance_divergence_baseline.json` with the reason |
| `validate_db` notes row counts rose | new data; `python3 validate_db.py --update-patch-manifest`, then check the PATCHED LIST is unchanged and only the counts moved |
| `build_vuelta_points.py` changes years you never touched | those committed arrays are STALE against their own scrape files. 9 sprint / 13 KOM years on 2026-09-14. Keep your year, restore HEAD for the rest — do not smuggle an unreviewed data change in |
| riders absent from a classification | a rider who abandoned keeps his points but stops being ranked. Correct and deliberate |

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
the per-rider helpers and has not been attributed further.

~~The bigger prize is the ~2.7s first paint~~ — **MEASURED AND CLOSED
2026-09-11.** Streaming the grid after the first index resolves was the other
half of that suggestion and it landed on 2026-08-22; between them the number no
longer exists. On the live site:

| scenario | time to the first grid button |
|---|---|
| warm SPA, switching into Riders | **207 ms** |
| cold page load straight to `#tour/riders` | **1,194 ms** (DOMContentLoaded 50 ms) |

**Deferring the classics index is not the remaining win it looks like.** All
five indexes start fetching at `riders.ts:187`, but first paint only WAITS for
the primary — the rest are parallel, and a cache-bypassing fetch of each on a
10 Mbps / 150 ms-RTT connection costs 179 ms for the 2,271 KB classics index
and 95-248 ms for the others. Deferring it would free bandwidth that is not the
bottleneck, and would cost behaviour: the default grid spans every race, so
11,934 of the 17,736 riders would be missing until someone touched a filter.

What is left of the cold load is JS parse and building 18,114 buttons, not
waiting on data. Anyone attacking it again should start there and should
measure a COLD load — a warm SPA hides the whole cost, and localhost hides it
completely (295 ms there, with every index arriving in under 20 ms).

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

## The Riders grid draws before every index has landed (2026-08-22)

With no race filter set the Riders page shows all five races, and it used to
`await Promise.all` over all five indexes before drawing anything — ~460 ms of
main-thread index builds behind the slowest of five downloads, with only a
"Loading riders…" label on screen throughout.

Every fetch still starts at the same moment. What changed is **which one is
waited for**: the page draws from the current race's index, then folds the rest
in with **one** more rebuild, not one per arrival. Measured on the dev server,
median of 3 cold loads, forcing layout — **unminified, with a second Claude
session competing for the same CPU**, so read the ratio and not the absolute
numbers; production will be faster on both sides:

| | before | after |
|---|---|---|
| time to a usable grid | 1,712 ms | **902 ms** (−47%) |
| time to all 17,736 riders | 1,712 ms | 1,936 ms (+13%) |

**The +13% is real and cannot be designed away.** The early merge and render are
main-thread work, so they push the remaining index builds back. What it *can* be
reduced to is the question — see below.

### The merge had to become incremental

The first version invalidated the merge cache and re-merged from scratch when
the late races landed. That cost more than drawing early saved: full grid ready
went **1,712 ms → 2,511 ms**, a 47% regression on completion for a 47%
improvement on first paint.

`mergedRidersCache` now remembers which races have been **folded in**, not just
which were selected, and folds late arrivals into the existing clones. A race
whose index is still building is simply absent from `folded` and gets merged on
a later call. That took completion from +47% to +13%.

The old cache key could not have expressed this: keyed on the selected race set
alone, the second render looks identical to the first, so it would have been
handed the first render's riders and the late races would never have appeared.

### Why the count label says "loading more…"

A search over a partial grid comes back **empty for a rider who does exist** —
which looks like a data bug, not a loading state. So the count reads
`12,499 riders · loading more…` until every selected race has been folded in,
and drops the suffix when the grid is complete.

### One rebuild, not five

A full grid is 17,736 buttons and costs **141 ms** to rebuild (measured, median
of 7, forcing layout). Rebuilding once per arriving index would spend more than
drawing early saves — the point of drawing early is the first screen, not a
five-step animation of the count going up.

**That 141 ms is wrong, or measures something narrower than a full grid
(re-measured 2026-09-11).** Against the PRODUCTION build served locally, with
layout forced and waiting for all 18,114 buttons rather than the first one,
switching into Riders costs **628 ms** (median of 3: 482, 628, 632). The
conclusion above still holds — one rebuild beats five — but the figure should
not be quoted as the cost of building the grid.

### The grid is the last second, and it is CPU (measured 2026-09-11)

Everything else has been ruled out. On the production build, served locally so
there is no network to blame:

| | |
|---|---|
| all five indexes fetched | **118 ms** |
| `JSON.parse` + Map build, all five | **166 ms** |
| switching into Riders, warm, forcing layout | **628 ms** |
| cold first load to first grid button | **1,147 ms** |

The data is ready at 118 ms and the rest is JavaScript. The cost is building
**18,114 buttons and 44,188 DOM nodes** eagerly, every rider whether or not he
is on screen.

**Virtualised 2026-09-11, and it did what it promised: 628 ms -> 48 ms**
(median of 3, production build, layout forced, five columns). The DOM went from
18,114 buttons and 44,188 nodes to **160 and 207**.

The CSS is what makes it honest rather than approximate: `repeat(N, 1fr)` with
`grid-auto-rows: 29px` means a row's height is fixed and a rider's row is just
`index / columns`. Only the visible rows plus four of overscan are built; the
space above and below is held by two spacers that span whole rows, so
`scrollHeight` comes out at exactly `ceil(riders / cols) * 29` — measured at
104,980 px for 18,097 riders in five columns, to the pixel.

**Two things that will bite whoever touches this next.**

`grid.replaceChildren()` RESETS `scrollTop`. Since the render reads `scrollTop`
to decide which rows to build, not restoring it makes the first scroll snap
back to row 0 and re-render the top, forever. The spacers keep total height
constant across the swap, so putting the offset back is invisible.

**Programmatic `grid.scrollTop = n` fires no scroll event in an automated
browser, and `requestAnimationFrame` does not run while the pane is hidden** —
so the obvious test reports that scrolling is broken when it is fine. Verify
with a real wheel scroll on a visible pane. The first three attempts here all
measured the harness rather than the code.

**The second thing `renderWindow()` has to restore is FOCUS, and that one
shipped broken** (fixed 2026-09-11). `scrollTop` was handled from the start;
focus was not, and it is the half that locks people out. Tabbing down the grid
scrolls each newly focused button into view, which fires the scroll handler,
which lands in `renderWindow` and destroys the very button the user is standing
on — focus falls to `<body>`. A keyboard user could not get past the first
window: every attempt threw them back to the top of the document. Mouse users
saw nothing wrong, which is why it shipped.

Re-focus by `data-id` after the swap, with **`preventScroll: true`** — without
that flag the focus call re-scrolls and undoes the offset restored one line
above. A null lookup means the scroll carried that rider out of the window
entirely (a mouse scroll, not a tab), and losing focus with the element is
correct there.

The regression test for it took two attempts, and the first one is the
cautionary half. It scrolled 58px, which under JSDOM's zero `clientHeight` left
the window index at 0 — `renderWindow` returned early, nothing was replaced,
and the check passed against the *unfixed* build. It asserted nothing. It now
scrolls to 145px, which moves the window by exactly one row while keeping the
target inside it, and fails as it should: `focused rider/dorsal-73 -> <body>`.
**Run every new regression test once against the unfixed code.**

**KNOWN TRADE: the browser's own Ctrl+F no longer finds an off-screen rider**,
because he is not in the DOM. The page's search box covers it and always has —
it filters the whole result set, not the rendered window.

`verify-views.mjs` counted `.rider-name-btn` as a proxy for "how many riders
match", which a window breaks by design. It now reads the count label — what
the user is actually told — and separately asserts the DOM holds a window
rather than the field. The independent source-file oracle for the team filter
is unchanged and still agrees: 98 vs 98, 209 vs 209.

**Measure on the production build.** `npm run dev` serves 250 unbundled modules
and reports 35 SECONDS to first grid; localhost dev is not evidence of
anything. `npx vite preview --outDir build` is.

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

**A passing run now names every payload that MOVED (2026-09-19).** The 2%
tolerance is right and stays, but sub-threshold drift is invisible one commit at
a time and permanent in aggregate. 8.2 KB of real points data landed in the giro
and vuelta year files across commits `e91a0662` and `d0892557` without a
re-baseline — far under 2%, so the run passed and reported only a growing
`+5.8 KB vs baseline` that named nothing. The next person to touch the payload
inherited the question of whether that 5.8 KB was theirs, and answering it meant
diffing 42 files by hand.

The breakdown is keyed on buckets that MOVED, not on the total being non-zero,
because the total is exactly what hides an offsetting pair — one race set growing
5 KB while another shrinks 5 KB nets to a reassuring `+0.0 KB`. It is silent when
nothing moved, which is the state right after a re-baseline and the state this
exists to make normal again. The FAIL path is untouched: it already itemises its
regressions, and the breakdown prints after the exit.

**`test_exports.TestPayloadBreakdown` runs the real script** — the first test in
this repo to shell out to node — against a SYNTHETIC payload rather than the real
build. `check-payload.mjs` resolves `build/assets`, `src/data` and the baseline
relative to its own `import.meta.url`, so a copy of it beside a handful of
invented files exercises measure, attribute, compare and report end to end. Two
reasons not to point it at the real build: it never touches the committed
baseline, which a crashed test would leave mutated and which passes silently when
wrong; and it needs no `npm run build`, so it runs in CI, where the Python suite
executes BEFORE the build step. Against the real 470-asset build the same six
cases gzip 2,800 files and take **9.5s**, against a pre-push hook whose entire
measured unit-test budget is 0.5s; synthetic, they take **0.33s**.

The fixture's filler is **incompressible random hex, not repeated characters** —
a run of `"x"` gzips to a few dozen bytes, and then the 10-40 byte perturbations
these tests make are 20% of a payload and trip the regression guard instead of
exercising the sub-threshold path they exist for. That was a real first draft,
not a hypothetical.

```
6 payload(s) differ from the baseline. None is a regression, but drift that
nobody re-baselines accumulates until an unrelated change trips the 2% guard:
     +4.4 KB    +0.22%   years:giro
     +3.6 KB    +0.21%   years:vuelta
      -322 B    -0.29%   riders_index:gravel
```

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

## The 2026 Vuelta, and the three defects it exposed (2026-09-14)

Added the day after the race ended. The edition itself was routine — 21 stages,
184 starters, 142 finishers, `coverage.py` reports **no gaps on any tracked
field**. What was not routine is that adding one ordinary year surfaced three
separate defects, each of which had been silently wrong for years. All three
have the same shape as every defect in the section below: **something read the
easy thing instead of the right thing, and nothing downstream could tell.**

### 1. PCS 500s the final stage's `-points` page, for every Grand Tour

`scrape_race.scrape_stage` fetches `<slug>-points` and `<slug>-kom` and treated
a missing page as "no points awarded". For stage 21 those URLs return HTTP 500
— verified on the Tour, Giro and Vuelta 2026 and on the Vuelta 2025, so it is
not a one-off — and every Grand Tour finale scraped through this path landed
with **zero sprint and zero KOM points**. The 2025 Vuelta still has that hole.

The fix costs nothing: the stage's OWN result page carries the same
`Sprint | ...`, `Points at finish` and `KOM Sprint` tables, and it is already in
hand. Checked against both dedicated pages on Vuelta 2026 stage 20 — all three
parse to identical dicts. `pts_html or html`.

### 2. The points parser read PCS's "Today" column, not `Pnt`

Much worse, and the reason to distrust a total that merely looks low.
`parse_points_page` took **the last numeric cell in the row** as the points
value. PCS's points tables end with `delta_pnt` ("Today"), so the winner of the
2026 Vuelta's stage 2 was credited with **10 points instead of 30**. And the
error was not even consistent: on a row whose Today cell is blank the fallback
landed back on `pnt` and was right. So the totals came out *low and plausible*
rather than uniformly wrong — Wout van Aert finished that Vuelta credited with
**208 of his real 326 points**, and nothing anywhere said so.

Positions cannot substitute either: a sprint with time bonuses carries a
`result_boni` column and one without it does not, so the same page serves 9-
and 10-column tables side by side. The fix is durable rule 3 — **read the
`data-code`** — via `parse_header_codes`, which already existed in this file and
which `parse_rows` had used all along. The points parser simply never called it.

After the fix the 2026 Vuelta's cumulative sprint points reproduce PCS's
published points classification **exactly** for the whole top six (326 / 273 /
216 / 141 / 116 / 115).

> ~~**Every Giro and Vuelta year still carries the old values.**~~ — **DONE
> 2026-09-15**, all 95 affected editions. See "The points refresh" below: exact
> agreement with PCS's published classifications went from **25.5% to 89.9%**
> across 1,435 rider-classifications. The jersey WINNERS were never affected:
> those come from `classification_standings`, scraped by
> `scrape_classifications.py`, which has always had its own correct parser.

### The points refresh: 95 editions, and two more defects (2026-09-15)

Re-reading the points pages for every Giro and Vuelta year that has them.
`refresh_stage_points.py` does it, and deliberately **is not**
`scrape_race.py --all`: both defects live in how points were READ, so it
rewrites ONLY `sprint_points` and `kom_points` and asserts every other key is
unchanged before saving. A full re-scrape would rewrite every result row to fix
two dictionary keys, reverting name-swap repairs on the way through, and cost
four times the requests against a small site.

**Result, measured against something it could not produce itself** — our
cumulative totals vs PCS's *published* points and KOM classifications, every
listed rider, 10 editions:

| | before | after |
|---|---|---|
| exact agreement | **25.5%** | **89.9%** |

Giro 1993 and 1995 land at **100%** on both classifications. The residual is
PCS disagreeing with itself — see the last note below.

### 4. Old KOM pages have no points column, and we were storing riders' AGES

The worse of the two. On pre-1990 KOM pages PCS lists who crossed each climb
with **no `pnt` column at all**, and the old "last numeric cell in the row"
rule fell through to the **Age** column. Giro 1961 stage 15 stored Bahamontes
on 32 and Taccone on 21 — their ages. Stage 7 stored Delberghe on 25; his Age
cell reads 25. Two independent confirmations: the page's `data-code` list has
no `pnt`, and each stored value equals that rider's Age cell.

This was never "points read from the wrong column". It was fabricated data
sitting in the archive, and the honest replacement is nothing at all.

**The guard that found it, and why it had to be loosened.** The refresher
refused, at first, to let any stage LOSE points — a rate-limit, a Cloudflare
challenge and an honest "no points awarded" all parse to `{}`, and writing the
wrong one deletes real data silently. That rule fired immediately on Giro 1961,
and chasing *why* is what surfaced the ages. The rule is now the distinction
that actually matters: **a drop is allowed when we SAW the page and it has no
points column; refused when the fetch failed.** Removals are counted and
reported separately so they can never be read as ordinary corrections.

### 5. The Giro's Intergiro sprint counts toward the points classification

`parse_points_page` matched `Sprint |` and `Points at finish`. The Giro also
prints **`Intergiro Sprint | ...`**, and PCS counts it. Measured, not assumed:
including it takes the 2024 Giro from **39/110** listed riders matching PCS to
**102/110**, and 1993/1995 to 100%.

It was tempting to exclude it on the history — the Intergiro had its own blue
jersey in the 1990s — and a first check seemed to show it changed nothing for
1990 and 2005. That check was wrong: it compared how many riders MATCHED, not
the values, so it hid a change that moved values without moving the count. The
re-run then altered 1990-1998, exactly the era where wrongly including it would
do damage. What settles it is the direction of the error: with Intergiro in, we
are **LOW where we differ and essentially never HIGH** (2024: high on 2,
low on 6). Over-counting would look the opposite.

### The residual was mostly the MISSING FINALE, not PCS disagreeing with itself

**This section said the opposite and was wrong.** It read: "the points are not
published per-stage at all, so there is nothing to extract and a reconciliation
would be invention." The first half is true and the conclusion does not follow.

Giro 2005 sat at 62% and 2015 at 71%, and summing every heading on every stage
page gives Bettini 152 against a published 162, Nizzolo 164 against 181. What
that actually proves is only that the STAGE PAGES do not have it. PCS publishes
the **cumulative** points and KOM classification on every stage page, so the
finale's award is simply (classification after the last stage) − (classification
after the one before). That is PCS's own data.

41 editions carried points for every stage but the last, because PCS 500s a
finale's `-points` page and for most years the stage page has no tables either.
Nizzolo's missing 17 = **+22 on stage 21, −5 for a jury penalty on stage 16**,
exactly. `derive_missing_stage_points.py` recovers them; see "Recovering a
finale from the classifications" below.

Giro 2005 **62% → 80%**, Giro 2015 **71% → 90%**, overall **89.9% → 93.0%**.

What genuinely IS upstream inconsistency is the remainder — and it is much
smaller than this section used to claim.

### What the points residual actually IS — bounded, 2026-09-16

`audit_points_residual.py` exists so nobody has to guess again. It compares our
summed per-stage points to PCS's published classifications, and `--localize`
walks PCS's stage-by-stage standings to say WHY each rider disagrees.

**First: one number was hiding two different things.**

| | |
|---|---|
| classifications where we HAVE per-stage data | Giro **87.7%**, Vuelta **88.2%** exact |
| classifications where we have NOTHING | 59 Giro + 94 Vuelta, **1,129 riders** |

That second group is old editions where PCS publishes a small final
classification (3-16 riders) and no per-stage points pages at all. Those finals
ARE in the database, via `classification_standings` — they are missing from the
by-stage CHART by necessity, not by defect. Quoting the combined figure (81% /
74%) conflates a real residual with an era that never had per-stage data.

**Second, where the real disagreements come from** (localized, sampled):

| category | what it is |
|---|---|
| **PENALTY** | a jury deduction. PCS applies it to the classification and shows nothing on the stage page, so we read HIGH. The largest single identified cause — 51% of the Giro sample. Giro 2016 lists two riders on **-5**, a penalty exceeding everything they scored. |
| **SCALE** | PCS's classification delta is a consistent multiple of its own stage page's award. The Vuelta 2024's stage 19 gains 30/25/22/19 where the page says 20/17/15/13. PCS disagreeing with PCS; believing either page is a choice, not a fix. |
| **JITTER** | the award is credited to an adjacent stage. |
| **UNEXPLAINED** | Giro 23%, Vuelta 28% of disagreements. **This is the number worth quoting** — not the whole residual. |

Modelling penalties would need negative per-stage values and a DECREASING
cumulative line, which `validate_exports` currently treats as an error. That is
a modelling decision, not a bug fix, and it is deliberately not taken.

### Extending the derivation past the finale was nearly worthless (2026-09-16)

`derive_final_stage_points.py` became `derive_missing_stage_points.py` and now
fills ANY empty stage, not just the last. Measured across the 35 modern
editions that have one (111 stages), **3 editions passed the improvement gate**:

| | | |
|---|---|---|
| Vuelta 2019 POINTS | 7 stages, 58 riders, 475 pts | 22% -> **46%** |
| Giro 2005 KOM | 1 stage, 3 pts | 94% -> 98% |
| Giro 2012 KOM | 1 stage, 6 pts | 97% -> **100%** |

**The gate refused 16 classifications**, six of which would have made things
worse — Vuelta 2000 POINTS **66 -> 26 exact**, Giro 2013 POINTS 80 -> 75,
Vuelta 2013 KOM 48 -> 44. And the four 1990s Vueltas with 12-20 empty stages
each (1990, 1992, 1995, 1999) all came back **0 -> 0**, exactly as the audit
predicted: no usable published classification to derive from.

**So the finale fill had already captured essentially all the recoverable
value.** Record the negative result rather than repeating the sweep.

### Three ways a stage page goes wrong, all seen in the 2019 Vuelta

Worth knowing before diagnosing a thin year, because they look identical in our
data (an empty or short dict) and are not the same problem:

1. **PCS has no points tables at all.** Stage 10, a 36.2 km ITT: the points
   page carries only "Team day classification".
2. **PCS has the tables and the SCALE but no riders.** Stage 17 publishes
   "Intermediate sprint | Atienza" and "Points at finish" with a proper `pnt`
   column reading 25, 20, 16 — and every rider cell is empty
   (`<td class="ridername "><div class="cont"></div></td>`). Our parser is
   right to credit nothing; this was briefly written up here as a parser bug
   and it is not one.
3. **PCS has an intermediate sprint and NO "Points at finish".** Stages 4 and 7
   hold 3 riders / 7 points for a "Sprint of large group" finish. These are
   PARTIAL, not empty, so the derivation skips them by design — **scraped data
   always wins, and replacing it with derived values is a provenance
   downgrade.** Quantified and left alone.

### Scope a networked sweep LOCALLY before running it

The first unscoped run of the generalized tool spent **4.5 hours and emitted
one line**. It was fetching standings for every "empty" stage of the pre-1960
Giro, where no published classification exists to measure against, so every
result was discarded after the fetching — and PCS began timing out, which the
tool (correctly) treats as "no standings", making a slow run's output
indistinguishable from a real absence. The work set was computable from files
already on disk with ZERO fetches: 537 stages, narrowing to 111 once the
no-classification era was excluded. `derive_missing_stage_points.py` now skips
a year with no points era at all. **Count the work locally first; a sweep whose
gaps you cannot tell from real absences is not worth running.**

### Recovering a finale from the classifications (2026-09-15)

`derive_missing_stage_points.py`. Four guards, each of which caught something
real, and the tool is mostly those guards:

1. **A baseline is mandatory.** With no penultimate standings every delta
   becomes the rider's whole-race total. The 1986 Giro publishes none, and the
   first run credited Bontempi with **167 points on the final day** — his
   entire classification. "No baseline" must mean skip, never assume zero.
2. **A rider absent from the previous standings** either scored their first
   points on the finale or the earlier table was truncated, and per rider those
   are indistinguishable. Accept one only up to the largest award observed
   among riders that CAN be verified — a ceiling read from the stage's own
   data, not a magic number.
3. **Never write a non-positive value.** PCS lists riders on a NEGATIVE
   classification total when a penalty exceeds their points (Giro 2016 has two
   on −5). The first version's ceiling test passed those straight through, the
   cumulative curve decreased, and `validate_exports` failed with 2 errors.
   That is the validator doing its job on a defect this doc's author
   introduced.
4. **The write is gated on measured improvement.** For each classification it
   computes agreement with PCS's published table before and after, and writes
   only if it improves. This is not ceremony: it refused **Vuelta 2000 POINTS,
   which would have gone 66 → 26 exact**, plus two KOM regressions. 17
   classifications were dropped as unproven.

Derived editions are recorded in `derived_stage_points.json`, and
`refresh_stage_points.py` reads that file so a later refresh cannot purge them
— to the refresher, a page with no points tables is exactly why they were
derived in the first place. Re-run this after any refresh, like
`fix_name_swaps --replay` after a re-scrape.

### Two operational lessons from the run itself

* **`pgrep -f "python3 <script>"` does not match.** The real command line is
  `.../Python <script>.py`, so the pattern silently matches nothing — which
  reads exactly like "the job finished". A waiter built on it fired instantly
  and launched the next race while the first was still running. Match on the
  script name, or better, check the lock file's PID with `ps -p`.
* **Two copies ran concurrently** before `refresh_stage_points.py` had a lock.
  Nothing corrupted a scrape file (each write is one atomic `os.replace` of a
  value both processes computed identically), but they doubled the request rate
  and interleaved writes to the resume file, whose last writer wins — three
  finished years came back unmarked. It now takes a PID lock and clears a stale
  one from a dead process.

### 3. A year-scoped `check_gc_times.py` run wiped 77 years of corrections

`check_vuelta_gc_times.py 2026` cut `vuelta_gc_time_corrections.json` from 78
entries to 1. `winner_times` was seeded from the file on disk so a scoped run
merged; `discrepancies` started empty and the file was overwritten wholesale.
Both now seed from disk, and a year the run actually examined gets that run's
verdict (including removal once it agrees with PCS again) while every year it
did not look at is carried through untouched.

### Stage 3 was cancelled ON the road, and PCS still serves a full table

The jury stopped the stage on the Col de Mont-Louis for heavy rain and hail. No
winner was declared, and the commissaires additionally cancelled the results of
the intermediate sprint and the mountain sprint.

The existing cancelled-stage guard looks for an EMPTY results table. This page
is not empty: PCS serves **183 rows in which every rank is "NR" and every GC
column is stage 2's, carried forward**. Ingested as results that is 183 people
finishing a stage nobody finished, plus one day's general classification
repeated as the next day's — durable rule 6, broken by accident.

So `scrape_stage` now checks for PCS's cancellation banner BEFORE reading any
table, using `race_common.STAGE_CANCELLED_RE` / `page_says_cancelled()`. That
phrase list used to live in `insert_cancelled_stages.py`; it is now shared, so
the scraper that REFUSES a cancelled page and the script that PLACES the row
afterwards cannot disagree about what "cancelled" looks like. A cancelled stage
is reported as its own outcome rather than as `FAILED`, and it is excluded from
the "re-run to retry them" warning, because there is nothing to retry.

**The points arrays had to learn about the hole too.** `build_*_points.py` built
one array entry per FILE present, and `export_gc.py` indexes it by DB stage
position — where the cancelled stage does have a row. Stage 4's sprint points
would have been credited to stage 3, and stage 21's dropped off the end. Both
builders now range over `min..max` stage number and emit `{}` for a number with
no file. (A prologue is stage 0, which is why the range starts at the lowest
number present rather than at 1.)

### Two numbers that look wrong and are not

* **Total distance 3,035.6 km**, against Wikipedia's 3,310.6 — an 8.3%
  divergence, recorded in `distance_divergence_baseline.json` and decomposed
  against the official race site on 2026-09-15. No stage is missing; see
  "Three sources, three totals" below for the full accounting.
* **Winner's average speed 41.09 km/h**, up on nothing in particular. It sits
  inside the 40.25-42.65 band of 2021-2025. The DB's summed stage times gave
  74:04:28 against PCS's official 73:52:55 — 693 s out, the usual reason the
  curated winner time outranks the sum.

### Three sources, three totals (reconciled 2026-09-15)

2026 is the edition that makes the difference between "planned" and "raced"
impossible to ignore, because **three stages were altered and the sources
updated at different moments.** Per stage:

| source | all 21 | as raced | what it actually is |
|---|---|---|---|
| PCS / our DB | 3,209.6 | **3,035.6** | as-raced; matches PCS's own `/route` page to the decimal |
| official lavuelta.es stage list | 3,231.9 | 3,057.9 | as-raced, and it DID update for the in-race changes |
| Wikipedia stage table | 3,291.2 | — | the pre-race route book, never updated |
| Wikipedia infobox | **3,310.6** | — | does not even match Wikipedia's own table (+19.4) |

**The 275.0 km between Wikipedia's headline and what we display:**

| km | cause |
|---:|---|
| 166.7 | stage 3, cancelled on the road — excluded here, planned length still counted there |
| 71.0 | stage 15, shortened for extreme heat (raced 110.2; Wikipedia still lists 181.2) |
| 28.8 | stages 2 and 8 — planned vs raced (stage 2 confirmed; stage 8 unexplained), see below |
| 19.4 | Wikipedia's infobox exceeding Wikipedia's own stage table |
| −10.9 | net across the other 17 stages, 0.1–5.7 km each |

**Stage 20's landslide reroute contributes nothing**, which is worth knowing
before hunting for it: that change predates both route tables, so Wikipedia's
187.0 and the raced 186.8 already agree to 0.2 km. Only a change made *during*
the race (stage 15, stage 3) splits the sources.

**Beware a third figure for stage 15.** Press coverage gives the original as
189.7 km; Wikipedia's route table says 181.2. Neither is our number and neither
needs to be — we store the 110.2 that was raced — but do not adopt either as
"the planned distance" without a source that says which it is.

### Stages 2 and 8: one resolved, one accepted unexplained (2026-09-15)

`lavuelta.es` lists stage 2 at **214.3 km** and stage 8 at **171.0 km**; PCS
says **202.1** and **161.0**, and those are the figures we store. Every other
stage agrees to within 0.1 km, so this was never general drift — two specific
stages, 22.3 km between them, 0.7% of the race.

**Stage 2 is settled, and PCS is right.** 214.3 km is the distance published in
the race guidebook when the route was unveiled. Roughly 12 km was trimmed from
the day **before the flag dropped**, for late logistical and road-safety
reasons in the South of France; 202.1 km is what the peloton actually rode to
Manosque. So the two numbers are not in conflict at all — they are the planned
and the raced distance, and this archive stores raced. (Established by Eric,
2026-09-15, from the route documentation.) It is the same split as stage 15,
just made an hour earlier, which is why no in-race report mentions it.

**Stage 8 has no explanation and we are keeping PCS's 161.0 anyway** — Eric's
call, 2026-09-15, taken with the absence of a reason understood rather than
assumed away. What was ruled out first:

* **Not a stale official page.** That same list carries stage 15 at the
  shortened 110.2, so it was updated after the race.
* **Not confirmable from PCS.** PCS's stated distance divided by the winner's
  time reproduces PCS's own published average speed exactly — which proves only
  that PCS derived one from the other. **The check is circular; it validates
  nothing.** Do not cite it as corroboration.
* **Not something either page explains.** Neither PCS's "Story of the day" nor
  Wikipedia mentions a change to stage 8; Wikipedia records only stage 3.

Given stage 2, a pre-start trim is the obvious reading — but that is inference
from a neighbour, not evidence, and it is written here as a hypothesis so the
next person does not find it restated as fact. What would settle it is the road
book or a report giving stage 8's competitive distance. The value stays PCS's
because the whole edition came from PCS, and mixing one organiser distance into
it would make the total reproduce neither source.

### What was verified against something it could not produce itself

* Final GC: our top six reproduce PCS's published classification **to the
  second** (Mas 73:52:55, then +135 / +164 / +414 / +525 / +568).
* Points and KOM jersey winners match PCS's own standings.
* Four name swaps (stages 2, 19, 21) were confirmed by TEAM before repair —
  in each the name moved while bib and team stayed, e.g. stage 21 showing
  "116 Brenner Marco | NSN" when Brenner rides bib 171 for Tudor all race.
  The re-scrape after the parser fix reverted all four and the automatic
  `--replay` put them straight back, which is that mechanism working.
* Cancelled stage 3 renders exactly as the Vuelta 1991's does: no distance bar,
  grey elevation and difficulty bars, excluded from both totals.

### Still open, deliberately

**Six riders in each classification disagree with PCS's own published totals**
by 1-10 points, several in offsetting pairs (Bisiaux +10 / Omrzel -10,
Debruyne +5 / Vermaerke -5, Buitrago -4 on KOM). Every stage page was re-read
directly and reproduces our figures, so PCS's per-stage tables and PCS's
classification disagree with each other. Nothing in this source can settle it,
and a reconciliation would be invention. Riders who ABANDON also appear to
"disagree" — Pogačar carries 102 sprint points in our per-stage sums and none
in the standings — but that is correct and deliberate: a classification ranks
only riders still in the race.

---

## The three Grand Tours were unified (September 2026)

A long pass that started as "run a pending backfill" and ended with one code
path per concern. Every defect it found had the same shape: **a tool that
covered some races and not others**, because the Tour's scrape files were laid
out differently and nobody had noticed what that was costing.

### The durable rules

1. **All three stage races share one layout.** `<race>_scrapes/YEAR/stage_N.json`
   plus per-year sidecars. Reach them through `race_common.year_sources()` and
   `load_stage_rows()` — never build the paths yourself, which is how tools ended
   up covering two races out of three.
2. **One row parser: `scrape_race.parse_rows`.** `scrape_pcs_stages` had its own
   copy, and four defects survived for years because a fix landed in one and not
   the other.
3. **Read PCS's `data-code` attributes, not header text or fixed column
   positions.** Header text is not unique (a Tour table prints "Pnt" twice and
   leaves the bonus header empty) and positions shift with the table.
4. **PCS puts the resolved value in `<span class="hide">` next to its visible
   ditto (`,,`).** Read the span. Reading the `<font>` discards the time of every
   rider tied with the row above — it left the 1925 Tour with gaps on 1% of
   finishers instead of 100%.
5. **A winner's gap is `+0:00`, never their own finishing time.** Setting both
   from the one cell is what doubled 3,377 winners' times; ingest computes
   `finish = winner + gap`.
6. **Never carry GC forward across stages.** A gap changes every stage, so
   repeating it is invention. Where a stage publishes no GC, compute it from
   real stage times (`build_vuelta_gc_standings.py`) and validate against the
   authoritative standings.
7. **PCS is not blocking you.** A stub `Mozilla/5.0` gets 403; the full Chrome
   string in `scrape_pcs_gravel.UA` gets 200. Import the UA — never hand-roll a
   fetch and conclude the site is down.
8. **`/race/<race>/<year>/gc` serves the last STAGE's result**, not the general
   classification (`/result` 500s). All six classifications are `resTab` blocks
   on that one page; select by the `resultTabs` nav label, never by table
   position, and read `pnt2` for a classification total — `pnt` and `uci_pnt`
   are the award for placing in it.

### What changed

| area | outcome |
|---|---|
| provenance | `stages` at 100% on all six tracked fields, 0 orphans |
| `coverage.py` | exclusions are per stage and per upstream; two were false and hid ~993 fillable values |
| name swaps | all 27 pairs repaired; 54 rider-editions with two bibs -> 0 |
| bibs | 13,333 filled from the rider's own bib elsewhere in the edition; TTT rows had none |
| Tour layout | `tdf_*_full.json` -> `tour_scrapes/YEAR/stage_N.json`, verified round-trip, originals deleted |
| classifications | Giro and Vuelta got 11,841 rows where they had none; Tour KOM back to 1933, points to 1947 |
| Tour GC | 57,457 values computed from real stage times replacing 66,673 carried-forward ones |
| ingest paths | four became two: `add_pre1960.py` and `fix_2026_name_swaps.py` retired, `ingest_race.py --race tour` enabled |

### Things that look like missing data and are not

* **Sparse gaps in an old edition** — usually the ditto artifact above, or a cap
  applied to an era it does not fit. `MAX_GAP` is now the winner's own time
  rather than a flat 4 hours, because pre-war stages ran 300-400 km and the back
  of the field genuinely finished five hours down.
* **A rider absent from computed GC** — validation drops them only from the
  conflicting day onward, not for the whole race. One mismatch used to erase 31
  stages; in 1937 every conflict lands on the final stage, the only day whose
  authoritative GC covers the field.
* **Rank 999 with a "-" time** — PCS has no time for that stage, NOT an
  abandonment: 25 of 1905 stage 1's 29 ride stage 2 and are classified normally.
  It is the only stage in the database with such rows; letour.fr places all 29
  sixteenth at +5h20'00" and `patch_1905_unranked_finishers.py` records that as
  `manual`, never `pcs`.
* **A classification the frontend does not show** — the Giro and Vuelta have
  youth standings in the database now; `hasYouth: false` is a display choice.

### Verification that actually held

Every claim above was checked against something it could not produce itself.
The scraper reproduces the Tour's pre-existing 2024 and 2010 standings exactly
through a different code path; the computed 1925 GC reproduces PCS's published
final classification to the second; `ingest_race --race tour` on 1949 is
byte-identical to `reingest_edition_results`. **Coverage percentages are the
claim to distrust** — several were wrong because a low number was read as a thin
source rather than a parser dropping data.

---

## Time trials where the whole field shows no gap (audited 2026-09-11)

An individual time trial in which most riders carry `+0:00` is either a stale
scrape or PCS having nothing — and the two look identical in the database. 41
such stages exist across the three races (Tour 1937; Giro 1951-1991, 29 stages;
Vuelta 1971-2006, 11). **Each was fetched and re-parsed to tell them apart, and
only THREE are recoverable:**

| stage | riders with no gap, stored -> re-parsed today |
|---|---|
| Vuelta 2002 stage 1 | 162/206 -> 7/206 |
| Vuelta 2003 stage 1 | 151/197 -> 7/197 |
| Vuelta 2006 stage 1 | 153/189 -> 8/189 |

The other 37 are genuinely sparse at source: the 1989 Giro's stage 10 gives
Breukink 0:25 and Roche 0:33 and then `+0:00` for 161 riders, on PCS, today.
Nothing to fix, and re-scraping them would be a wasted afternoon.

**The detector that found these, and the one that did not.** "Riders sharing an
identical time in a time trial" finds 1,009 groups and means nothing — with
whole-second timing and a compressed field, ties are ordinary, and a 4.6 km
prologue spreads 200 riders across a minute. The signal is riders sharing **the
WINNER's exact time**: 172 of 172 in the 1985 Giro's stage 8, which is a lost
gap rather than a tie. Sharpen a detector until its hits are real before
believing a count.

---

## What the September 2026 repair pass established (2026-09-11)

Eight rules, each bought with a defect. They generalise past the stage that
found them, which is why they are here rather than only in a commit message.

### 1. A dot is part of a slug

`iBanesto.com`, `O.N.C.E.`, `FDJ.fr`, `R.M.O.`, `Vini Caldirola - So.di`. The
slug pattern's class was `[a-z0-9-]`, so on those teams it could not reach the
closing quote and matched **nothing at all** — the row arrived with a team NAME
and no team. 4,118 Tour rows, 3,847 Giro, 3,793 Vuelta. The rider pattern has
the same shape and fails worse: a row whose slug will not parse is dropped
outright.

### 2. A re-scrape silently undoes a name-swap repair

The fix lives in the scrape file and PCS reproduces the transposition on every
request, so re-fetching a repaired stage writes the swap straight back. Every
applied pair is now recorded in `name_swaps_applied.json`, `--replay --apply`
restores any a scrape reverted, and **`scrape_race.py` runs it automatically**
over each year it scrapes. Any OTHER scraper that rewrites a stage file needs
`fix_name_swaps.py --replay --apply` run after it by hand.

### 3. A guard is only where you put it

`implausible_speed` (12-70 km/h, deliberately far wider than any real stage)
has guarded `ingest_race` since 2026-09-10. `derive_ttt_rider_times.py` did not
call it, and duly wrote 130 riders a 1:05:16 time for an 11 km prologue before
the run was reverted from a backup. Both call it now, and so does
`clear_impossible_stage_times.py`, which applied the same rule to 2,115 values
already stored.

### 4. PCS puts a CUMULATIVE time where a stage time belongs

Found in four different places, and it always looks like an impossibly slow
rider: in the Time column of a split-day trial (1962 Tour stage-2b, 10:45:17
for 23 km), in a TTT block (the 1971 prologue, 1:05:16 for 11 km), as a whole
team's time on an ordinary parse (2013 Giro stage 2, 3:20:43 shared by ranks 1
to 5 — five riders on different teams cannot share a stage time, but they can
share a race total), and on the GC tab of a page whose Stage tab has the real
figure. **Ranks 1-5 carrying one identical time is the fastest way to spot it.**

### 5. An impossibly FAST winner is usually a doping annulment

The stripped winner keeps his real time and the promoted rider's row carries
his GAP to the man who was disqualified — read as a finishing time, it makes
the whole field absurd. The 2008 Tour's stage 6 has Riccò at 4:57:52 and
Valverde at "0:01". Ten stages carry this: Riccò, Vinokourov, Landis,
Schumacher, Astarloza, Contador, Zoetemelk. `ingest_race` takes the FIRST
rank-1 row with an absolute time and never overwrites it, so these repair
themselves on re-ingest — the data is not lost, it is two rows down.

### 6. Read "rows gone" before anything else in a change table

`preview_reingest.py --race X [years]` copies the database, ingests into the
copy and diffs, counting NULL-fills, overwrites and clears apart. A rebuild
that loses rows is the one to stop for: the 1982 Tour's `--allow-drop` looked
like a one-stage cleanup and cost 145 real placings on stage 9, where PCS now
serves ten rows for a field of 155. Where rows DO go, account for them —
the 1960-2025 ingest lost 508 and 153 were individual placings on team time
trials, which a team trial does not produce, and 39 were one rider under a
renamed slug.

### 7. A rider carries one number and rides for one team for a whole edition

Both obey the same edition-scoped invariant, so `backfill_bib_numbers.py` fills
either: `--field bib_number` (default) or `--field team_id`. Bib gaps come from
the TTT, whose per-rider cells PCS leaves empty; team gaps come from the GC
sidecar supplying a rider for a stage PCS does not list him on. The guard skips
any edition where the rider holds two values — but check WHY first: two bibs is
a name swap and repairing it removes the block, while two teams is often PCS
itself and must be left alone.

### 8. PCS renames things, and the database does not notice

Team slugs (`kelme-1980` -> `kelme-gios-1980`, `rokado-1972` ->
`rokado-colders-1972`) and rider slugs (`julius-thallmann` ->
`julius-thalmann`). Nothing is wrong with the scrape files — each is internally
consistent, one slug per team per edition — the database is simply behind. A
re-ingest catches it up; a "canonicaliser" would be guessing at something the
file already states. A renamed RIDER leaves the old id holding the editions not
yet rebuilt, so merge the rows and delete the orphan — and clear its
`data_provenance`, which `validate_db` will otherwise report.

**Two things the merge leaves behind, both found 2026-09-11 on that same
`julius-thallmann` -> `julius-thalmann` example:**

- **The exports still point at the dead id.** `classics/gc_by_stage_1983.json`
  carried `rider/julius-thallmann` after the DB had moved on, so the rider link
  on that page went nowhere. **Re-export every race set the rider appears in**,
  not just the one being rebuilt. Now 0 export rows point at a missing rider,
  and `audit_rider_duplicates.py` is the cheap way to keep checking.
- **`first_name`/`last_name` were dropped while their provenance survived**,
  which is the detectable signature: a rider with a `full_name`, no split
  names, and `data_provenance` rows claiming PCS supplied them. Thalmann was
  the only case in 19,002 riders; restored, and the count is now 0.

### `audit_rider_duplicates.py` — typo-variants already in the database

`link_gravel_riders.py` asks whether an INCOMING name belongs to an existing
rider. This asks the other half: which ids already stored are variants of each
other. They arise from partial re-ingests after a PCS rename, and from Athlinks
taking whatever an entrant typed — the same person with and without a middle
initial across years.

**It never merges.** It classifies and prints, because what settles one of
these is usually outside the database. 30 groups today: **23 SAME, 3 REVIEW,
4 DIFFERENT.**

Two suffixes are MEANING and are never treated as typos — collapsing them
would be the expensive error in reverse:
- PCS's numeric disambiguator: `alessandro-fantini` and
  `alessandro-fantini-1` are two different people.
- PCS's roman numerals: `gilbert-desmet-i` and `gilbert-de-smet-ii` are two
  real riders of the same family.

Nationality is what separates the genuine collisions — `camile-leroy` (be,
1919-24) from `camille-leroy` (fr, 1938), `michael-andersson` (se) from
`michael-anderson` (us), `peter-godde` (nl) from `peter-goode` (us). Career
span longer than 25 years separates the rest.

### `audit_rider_racer_ids.py` — the source's own identity, which nothing read

Added 2026-09-18. Its sibling above asks whether two ids LOOK like one person
and must be conservative, because a name is all it has. This asks a better
question: every Athlinks row carries **`racer_id`**, the timer's persistent id
for a human being, and where two of our ids share one, the SOURCE says they are
one person. Stronger than any name, locality or age test we can run.

**It sat unread for months.** `link_gravel_riders.py` dismisses it in a comment
as "null on most rows" — true, and beside the point. It is null on **78%** of
rows and decisive on the rest. The first run found **21 fractured riders**; six
were already aliased, fifteen were merged that day, and the sweep reads **0
today**.

It is the only thing that can pair a TRUNCATED name with its rider. Athlinks
cuts `displayName` at the first non-ASCII byte **per registration**, not per
rider, so `Torbjørn Andre Røed` arrives as `Torbj R` and `Andrew L'Esperance`
as `Andrew L` on some entries while the same season spells them correctly on
others. No name-similarity test can pair `torbj-r` with `torbjorn-andre-roed`.

**Two deliberate differences from the name-based audit:**

- **A nationality clash is REVIEW, not DIFFERENT.** Athlinks' `country` is where
  an entrant LIVES, not their passport. Røed rode as `us` from Grand Junction
  and `no` from Asker; Yuki Ikeda reads `us` for four Leadvilles before `jp`
  appears. Against a mere name match a clash is good evidence of two people;
  against the source's own racer id it is good evidence of a rider who moved.
- **The mirror direction is a lead, never a verdict.** Several racer ids on ONE
  of our ids is where a conflation would show, and 12 ids have that today — but
  a person can hold two Athlinks accounts, and `rider/ryan-petry`'s two are
  84638762 and 84638767, five apart. Printed as REVIEW, never classified, and
  **split into open leads and SETTLED ones** by reading both halves of
  `rider_splits.json`, so a question somebody already answered is not re-asked.
  11 open, 1 settled.

**`jake-pantone` was the first of those leads run down, 2026-09-18.** Three
racer ids — 176052831 (Leadville 2011), 333542089 (Unbound 2018), 165673321
(Unbound 2019 and 2021) — and **one man with three registrations**. The birth
year decides it: ages 30, 37, 38 and 40 in those four years imply **1981 every
time**, zero variance over a decade, where this archive's noise floor is ±3-5.
The localities agree — Eden on three rows and Huntsville on the fourth are two
of the three communities of Ogden Valley, Weber County, Utah, and the `CO`
beside Huntsville is *Leadville's* state, the documented region artefact.
Recorded in `rider_splits.json`'s `rejected`.

**All 12 mirror leads are now run down (2026-09-18).** Ten are one person with
two or three Athlinks registrations and are recorded in `rider_splits.json`'s
`rejected`; one is examined-but-undecided; one is a real split candidate.

| lead | verdict |
|---|---|
| `aaron-campbell` | one man. Its 6-year birth spread sits INSIDE one account — racer 397998872 carries both the 1982-implying and 1976-implying rows — so it cannot be two people. Farmington and Kaysville are neighbouring Davis County, Utah towns. |
| `alex-wild` | one man. **Bib 73 across five different 2024 races** — one Life Time Grand Prix number. Old account replaced in 2021. |
| `ryan-petry` | one man. The two ids are **five integers apart** (84638762/84638767): one person registering twice. Leadville seeding binds it — 11th in 2014, bib 11 in 2015. |
| `nathan-keck` | one man. `57783, SD` is the ZIP for Spearfish, South Dakota, which the other rows spell out. |
| `mark-walker`, `matti-rowe`, `matt-acker`, `mark-currie` | one man each; single implied birth year, one home town, second id appears at a re-registration or a move. |
| `elliot-bach` | one man on thin evidence — two rows, one age. Recorded so the thinness is not re-derived. |
| `sam-benedict` | **examined and deliberately NOT decided.** Two rows, one age. The blocker is our own Leadville coverage, below. |
| `mark-wallace` | **the one real split candidate — see below.** |

**`rider/mark-wallace` holds two men.** Racer 301499916 is five Leadvilles,
2000-2013, every row located Golden, CO, and every one implying **1962 exactly**
— bound internally by an exact seeding hit, 37th in 2004 and bib 37 in 2005.
Racer 367460791 is a single Unbound 2018 row, **Wilmette, Illinois**, implying
**1972**. Ten years and two states from a set that is internally perfect across
thirteen. Not yet split; the Unbound row is the one that would move.

### Leadville's "coverage cliff" is a definition change, and it hides a real bug

**The cliff is not data loss.** 1994-2015 store exactly 100 rows (`FIELD_CAP`);
2016 onward store 43, 18, 37, 55, 53, 79, 78, 70, 66, 67. The cause is visible in
one field of each scrape file's `info`: **every year through 2015 has
`division_id: null`, and every year from 2016 selects a division** — `ProM`,
then `Pro Male`, then `Pro Male, Grand Prix Male`. Leadville began publishing a
pro category on Athlinks in 2016 and the resolver picks it, so the stored field
changed meaning from *the top 100 of the whole men's race* to *the entire pro
division*. 2026 needs no division because its course is already
"Leadville 100 MTB - Elite Men". Deliberate, but a **comparability break nothing
records**: a rank in 2015 and a rank in 2016 are not the same quantity, and the
2016-17 "Pro" division is a registration category, not a performance tier — it
contains 10.9h finishers.

**The real defect is underneath it. `division_rank()` assumes that a row fetched
from `/division/{id}/results` carries its rank IN that division, and Leadville
2016 disproves it.** There, Athlinks' `primary` tracks the OVERALL field, so the
stored classification runs 1, 2, 3, 4, 5, 6, 8, ... 804 **in a 43-rider race** —
Richard La China is recorded as finishing 804th. 2017 is fine on that count
(`primary` really is 1..14 there), which is exactly what makes the bug hard to
see: the same code path is right one year and wrong the next.

Two riders are also placed against their own clock: **Albert Lake** (2016, 7.05h
stored at rank 278, behind 24 slower riders) and **Enrique Saborio** (2017, 6.54h
at rank 15, behind 12 slower). Both carry an `overall` wildly inconsistent with
their time — Lake 1449th on 7.05h — which is the signature of a checkpoint split
kept as a finish, the same class as the impossible times cleared in September.
Measured corpus-wide, only **7 rows in 94 gravel editions** are out of clock
order, so this is a small, nameable set, not a systemic problem.

**`validate_db.check_gravel_rank_integrity()` now reports both symptoms.** It
sorts the oversized editions by RATIO rather than absolute rank, which is what
separates a real defect from a harmless one: Leadville 2016 is **18.7x** its own
field, while The Traka's 1.2-1.6x is just PCS's place in a wider published field
and Unbound 2016's 100-vs-98 is a FIELD_CAP window that later lost a duplicate.
The check does NOT guess which cause applies — it prints the ratio.

**REPAIRED 2026-09-18, in two halves.**

*The places.* `scrape_athlinks.is_a_classification()` now asks whether published
places are places in THIS field: they must be DISTINCT and none past the size of
the listing the timer served. Neither is a judgement call, which is what makes it
safe on every edition. Two details decide whether it misfires:

- It is judged **over finishers only**. Leadville 2021, Sea Otter 2024 and
  Unbound 2022 all publish a flawless classification beside a DNF carrying a
  `999999` sentinel, and judging every row would throw all three away.
- It is bounded by the rows the timer **published**, not the rows that survive
  de-duplication. A division served as 100 rows and deduped to 98 still has a
  real 100th place. This is a bound, not a threshold — no magic number.

When places fail that test the division is renumbered **in `overall` order, not
by the clock**. That is the whole lesson of Sea Otter 2023, where clock ranking
replaced a podium three sources agree on: `overall` is a separate witness and
stays right when the clock does not. Six editions were renumbered; **Leadville
2016 went from 1..804 to a contiguous 1..43**.

*The times.* `ingest_gravel.rows_contradicting_their_rank()` extends the winner
rule to the subtler case — a rider whose clock beats riders ranked ahead of him
while still trailing the winner. It returns the complement of the longest
non-decreasing run of times in rank order: the FEWEST rows that must be wrong
for the rest to agree. Counting disagreeing pairs would call Saborio's one bad
row twelve defects. **6 rows** nulled across 6 editions, placing kept, and the
same majority guard as the winner rule refuses to act when a fifth of the field
disagrees — then the ORDER is the suspect side, not the clocks.

Both halves are re-derived from the gitignored `_raw/` cache with
`scrape_athlinks.py --force`, so the repair cost no network at all.

**`--force` is now idempotent (fixed 2026-09-19).** It used to stamp
`info.fetched_at` with `datetime.now()` on every file it re-derived, so a run
that fetched nothing claimed 88 fresh fetches and buried the six-edition repair
above in timestamp churn — the repair had to be dug back out with a
content-level diff. `info.fetched_at` now comes from
`athlinks_api.cached_at()`, the mtime of the `_raw/` file the rows actually came
from: **`now` after a real fetch and the original date after a re-derive**, so
one expression is right in both directions and no "did we fetch" flag has to be
threaded through `results()`. A field unioned from two divisions takes the
NEWEST, because a file is only as fresh as its most recent input; the cancelled
branch fetches nothing at all and keeps whatever date was already recorded. Two
consecutive `--force` runs now produce byte-identical files, which they did not
before.

`sam-benedict` stays undecidable — the repair fixes the ORDER of Leadville
2016/2017, not the thinness of those fields.

**`ike-pantone` is a different man and must never be merged into him.** Ike rode
Unbound 2021 in 50th at 46,807s; Jake rode the same edition in 42nd at 45,855s.
They share a stage, which is the test that proves two people — Ike is Ogden,
born 1985, twelve miles down the canyon and almost certainly a relative.

**The blind spot is stated in the output, because it cost a find.** A pair whose
rows all lack a racer id is invisible here — Nathan/Nathaniel Spratt is exactly
that, one man on two ids, missed because his 2026 rows carry nothing to join on.
He was found instead by noticing that he and his brother Marcus register together
on ADJACENT bibs (1699/1700, 158/159, 86/87, 108/109). **A clean run does not
mean the corpus is whole**; run `audit_rider_duplicates.py` beside it.

The identity key must be built exactly as `link_gravel_riders` built
`_rider_ids.json` — `fold(strip_series_flag(name))`. Folding alone leaves
Leadville's Leadman marker in the key, the lookup misses, and every `(l)` row in
2011 and `LM` row in 2013 drops out unnoticed; there is a test for it.

```bash
python3 audit_rider_racer_ids.py                    # both directions, classified
python3 audit_rider_racer_ids.py --json out.json    # then READ it
python3 merge_rider_duplicates.py --groups out.json # dry run, then --apply
```

### Canonical spelling is researched, not guessed — and two merges were reversed

The first merge broke ties **alphabetically**, which prefers the shorter string
and therefore the typo. Replaced 2026-09-11 by looking each case up. Of the 11
ties, 4 kept the less plausible spelling; researching those changed three
answers and reversed two merges:

| pair | verdict |
|---|---|
| `aaron-gammel` / `-gammell` | **one rider, canonical CONFIRMED.** Two of his three Unbound registrations spell it GAMMEL (2011, 2012) against one Gammell (2010) — a source majority, not string length. A separate *Jed* Gammell rides Chequamegon with the double L. |
| `greg-follet` / `-follett` | **one rider, canonical RESOLVED** — see below. |
| `ernest-gilioli` / `-gillioli` | **SEPARATED.** Wikipedia's 1926 Tour startlist has Gillioli at number 147 as a *touriste-routier*; its 1909 list has Gilioli at 157 as a *lone rider*. Two entries, two numbers, two categories, and PCS dates Gilioli to 1885 — 41 in 1926. Possible, but nothing asserts one man. |
| `giuseppe-bereta` / `-beretta` | **SEPARATED.** Il Lombardia 1909 and Milan-San Remo 1934: 25 years, two different races, nothing between. Placing 72nd in a professional classic at about 49 is not credible. |

**`greg-follet` resolved 2026-09-11, by counting EVENTS rather than records.**
The raw Athlinks data holds three entries, not two: `Greg Follet` (Leadville
1997), `Greg Follett` (Leadville 1999) and `Greogry C Follet` (Chequamegon
1999 — the "Greogry" is theirs, and a useful reminder of how typo-prone this
source is). Two events spell it **Follet**, one spells it Follett.

The organiser's own *All Time Finishers* PDF carries both his rides —
`FOLLET, GREG` 9:14:34 CO 1997 age 26, and `Follett, Greg` 8:26:54 CO 1999,
both M2 — **at times matching this database to the second**. That confirms the
merge and confirms our data, but it is NOT an independent witness on spelling:
Leadville's results are the same Athlinks feed. No outside source records him
at all.

So the canonical `greg-follet` stands — now on a 2-to-1 majority across two
different events, rather than on an alphabetical tie-break that happened to
land there. The evidence and all four source URLs are in `rider_aliases.json`.

### The 3 REVIEW groups, resolved 2026-09-12 — and one of them inverts the rule

- **`andrew-lesperance` -> `andrew-l-esperance`.** 21 of his 22 gravel
  registrations across 8 races spell it L'Esperance; a single Leadville 2023
  entry drops the apostrophe. PCS's slug agrees and Canadian Cycling Magazine
  confirms one rider from Nova Scotia.
- **`elliott-rodda` -> `elliot-rodda`.** Unbound 2014 and 2016, no shared
  stage, no conflicting nationality — one rider. The registrations split 1-1
  and **no outside source records him at all**, so the canonical is simply the
  side carrying a nationality. Spelling UNRESOLVED, and recorded as such.
- **`mathieu-belanger-barette` -> `mathieu-belanger-barrette`**, which is the
  0-result identity absorbing the 2-result one. **Bélanger-Barrette, double R**,
  per the UCI rider database, Precision Hydration, Cycling Weekly, Velo,
  Reserve Wheels and FirstCycling. PCS spells it `barette` and **PCS is
  wrong**; its slug is what `link_gravel_riders` matched on, which is how the
  typo became our canonical. The correct spelling survived only in the
  sportmaniacs record, which had no results attached.

That last one is worth keeping in mind whenever a canonical is chosen: a
most-results rule would have picked the misspelling, and so would anything that
treated PCS as the arbiter. **Six outside sources beat both.**

Audit now reads **SAME 0, REVIEW 0, DIFFERENT 4, SETTLED 3**, 23 aliases, and
0 stale rider links in any export.

**PCS is the PRIMARY source, not an authoritative one**, and this is where the
difference bites. It carries all four ids as separate rider pages — which is a
signal, not a verdict, since PCS demonstrably makes duplicates. What PCS *is*
authoritative for is the `rider_id` string itself, because our ids are its
slugs by convention. Spelling gets triangulated.

**The default is not to merge.** Where evidence neither joins nor separates
two ids, they stay separate: a merge is a claim, and an unmerged pair is cheap
and reversible where a fused career is neither.

### `rider_aliases.json` — what makes a merge durable

**Consulted at ingest by all three paths** (`ingest_race`, `ingest_gravel`,
`ingest_classics`) via `race_common.load_rider_aliases()`. Without that a
rebuild mints every absorbed id again straight from the scrape files, which
still carry the old spelling — the same failure as the Dorsal placeholders and
the ITT filler times. It lives outside the database for the same reason
`stage_notes.json` does.

20 aliases. Every entry carries its evidence, because a merge is a claim.
`TestRiderAliasesSurviveAReingest` pins the durability, that no alias points at
another alias, and **that neither separated pair is in the file** — if either
were, the next ingest would quietly re-merge riders a human had decided apart.

**The `separated` section is the mirror, and the audit is not clean without
it.** Re-running `audit_rider_duplicates.py` after the merges left three SAME
groups, and all three were pairs a human had ALREADY ruled apart: Gilioli /
Gillioli and Bereta / Beretta, separated after research, plus Desmet i / de
Smet ii, refused by the share-a-stage test. A name heuristic cannot tell them
apart, so it proposes them on every run — and recording only the merges
remembers half the work. The next `--apply` would have quietly re-merged two of
them.

So a separation is recorded like a merge, with its evidence and the date it was
decided. `audit_rider_duplicates.py` reports those as **SETTLED** rather than
SAME, and `merge_rider_duplicates.py` refuses them outright as belt and braces,
since a stale `--groups` file could still carry one. The audit now reads
**SAME 0, REVIEW 3, DIFFERENT 4, SETTLED 3**, and the merge dry run proposes
nothing. `TestSeparationsAreRemembered` pins it, including that no pair is
recorded as both an alias and a separation — the two sections contradict each
other if they ever overlap.

**Resolving a REVIEW takes an outside source, and that is the point.**
`andrew-l-esperance` (21 results, ca) beside `andrew-lesperance` (1 result, no
nationality) reads as ambiguous from inside the data. One search settles it:
Andrew L'Esperance is a single Canadian rider from Nova Scotia and PCS's own
slug for him is `andrew-l-esperance`, so the other is a gravel-registration
variant of the same man. See DATA_SOURCES.md for reaching Wikipedia,
cyclingflash and the rider's PCS page.

---

## Time trials had no times (2026-09-10)

The 2026 Tour held **3,611 results and not one finishing time** — the largest
single gap `coverage.py` has ever reported, and not the one the docs predicted
(they still named the 1950s Tour). Two independent defects, both in a Time cell
that does not look the way the parser assumed.

### A time trial's Time cell is shaped nothing like a road stage's

```
road stage:  <font>3:29:07</font><span class="hide">3:29:07</span>
             <font>,,</font><span class="hide">0:00</span>          <- the ditto
time trial:  32.19<font class="fs10">,33</font><span class="hide"></span>
team TT:     <div class="w25 fs14 bold time">21:47.870</div>
```

PCS times a TT to the hundredth. It prints **MM.SS as bare text** with only the
hundredths inside the `fs10` font, and leaves the hidden span **empty** — so
rule 4 (read the span, never the visible ditto) has nothing to read and falls
through. The old fallback then took the FIRST `<font>` in the cell, which here
is the hundredths: Sobrero's 22:24 in the 2022 Giro's Verona TT parsed as
`",54"`, and `dedup_time` halved that to `"5"`. `parse_time_to_seconds` rejects
that shape, so ingest stored NULL rather than a wrong number — the failure was
silent and total. `parse_hundredths_time` in scrape_race.py now reads the bare
text and drops the fraction; the road-stage path is untouched, and it has to
stay a *fallback* because plenty of time trials (the 2021 Vuelta's opening TT
among them) are rendered exactly like road stages.

A modern TTT prints its fraction differently again — `21:47.870`, one div, dot
separator — and `_TTT_TIME_RE` in race_common.py allowed no fraction at all, so
it matched nothing and all 184 riders on the 2026 Tour's opening TTT took an
empty time.

**Blast radius: 19 time trials, 2021-2026, across all three races.** Not one
had a winner's time or a single gap. Fixed here: the 2026 Tour (both its TTT and
its stage-16 ITT). Still outstanding at the time of writing: 6 Giro and 5
Vuelta stages, listed by
`coverage.py --field finish_time_seconds`; each needs a re-scrape of that
stage plus `ingest_race.py --race {giro,vuelta} YEAR`.

### The 2026 Tour's own rows were also shifted a column

Independently of the above, every 2026 Tour row had been written by an
extractor that never captured `uci_pnt`: UCI points landed in `pcs_points`, PCS
points in `bonus_seconds`, and the bonus in the absolute-time slot. Stage
winners carried a **100-second bonus**. Re-scraping through
`scrape_race.parse_rows` — which asks PCS for the column by `data-code` rather
than counting positions — put all five columns back:

| column | NULL-filled | overwritten | unchanged |
|---|---|---|---|
| `finish_time_seconds` | 3,637 | 0 | 0 |
| `gap_seconds` | 38 | 2,852 | 747 |
| `uci_points` | 297 | 0 | 3,340 |
| `pcs_points` | 3 | 297 | 3,337 |
| `bonus_seconds` | 0 | 300 | 3,337 |

All 3,637 rows matched their existing rider on slug and rank — no identity
moved, and the swap gate passed clean. The re-scrape also brought the sprint
and KOM points pages, which the old 2026 files did not have at all, and PCS's
own profile icon, which corrected stage 5 from `H` to `F` (it had been
`unknown`-provenance).

### What did NOT change, and why that is correct

`gcWinnerTimeSeconds` stayed at 73:56:26. **The sum of per-stage times is not a
GC time and never was** — summing 2026 gives 74:53:52, and even 2023, whose
stage times were already complete, sums 500s over its published GC. Bonuses,
penalties and PCS's own reconciliation live in between. `export_gc.py` takes
tier 2 (`tour_gc_winner_times.json` + `gc_gap_seconds`) for every modern year,
so filling stage times moved no GC total, no summary and no riders index —
`all_races_summary.json` and `riders_index.json` came out byte-identical. The
only export change was 26 abandoning riders gaining a partial `totalTimeSeconds`
from tier 3, which is what 2023 and 2025 already do.

### Tests

`test_scrapers.py` had a fixture for the 2022 Giro's closing ITT and a test
that asked only **who won** — so the parser could return `"5"` for that time and
still pass. It now asserts Sobrero's 22:24 and Affini's +0:22, and two new
fixtures (`tdf_2026_stage_1_ttt`, `tdf_2026_stage_16_itt`) pin both fractional
shapes. 92 scraper tests, 460 in the suite.

---

## Team time trials with no rider times — 20 Tour stages, none safely fixable (2026-09-10)

`derive_ttt_rider_times.py` discovers its own targets now instead of the three
stages it was written for, and finds **20 Tour TTTs where not one rider holds a
finishing time**, 1954 to 1982. It writes to none of them, and the reasons are
worth keeping because each is a different upstream problem wearing the same
shape.

**7 — the published team time is not a stage time.** The winning team's figure
implies 9-10 km/h on every one: 1966 st3 8,370s over 21 km, 1967 st6 6,512s
over 17 km, 1968 st3 8,841s over 22 km, 1969 st2 5,865s over 16 km, 1971
prologue 3,916s over 11 km. That consistency is the tell — these are CUMULATIVE
RACE TIMES after the stage, the same defect as the GC total in a Time cell, one
level up. Either that or the stored distances are wrong; nothing on the page
says which, so the script refuses.

**This was nearly written into the database.** The 1971 prologue passed every
check the script had — 13 teams on both sides, ranks increasing with time,
riders already carrying their team's placing — and 130 fabricated times were
applied before `implausible_speed` was added here and the work reverted from a
backup. A guard is only where you put it: it had been in `ingest_race` since
that morning and this path never called it.

**7 — riders hold individual placings.** 1978 st5 has 106 riders with 106
DISTINCT ranks across 11 teams; 1977 st9, 1979 st4 and st8 likewise. A team
time trial does not produce individual placings, so either the route_type is
wrong or those ranks came from somewhere else. Writing team times on top would
bury the contradiction.

**6 — the team sets disagree.** Mostly PCS renaming a team: `team/rokado-1972`
vs `team/rokado-colders-1972`, `team/rokado-1973` vs
`team/rokado-de-gribaldy-1973`. Those two resolve themselves when 1972 and 1973
are re-ingested, since the change table already shows the slugs updating. 1954
and 1957 are different — PCS lists 11 and 12 national teams against 7 in the
database, on stages holding 10 and 15 riders.

**What is NOT wrong:** 46 further stages flagged by a first pass on the theory
that "database says TTT + file is not is_ttt + one timed row" meant a bad parse.
It does not. PCS publishes the 1927 and 1928 team-format stages as ordinary
result tables with no ttt-results block at all, and **one absolute time in a
field of 142 is the normal shape of a road stage** — the winner has a time,
everyone else has a gap.

---

## The 1960-2025 Tour backfill (2026-09-10/11, DONE — 64 of 66)

66 editions with no local scrape files — the largest structural gap left, and
now closed: **all 66 scraped, 64 ingested.** The tooling existed already
(`scrape_race.py --race tour` since the September unification), and trying it
found four things that had to be fixed first. Each was a tool that could not do
the job it claimed.

**Outcome (2026-09-11):** +3,132 finishing times, +3,533 gaps, and 8,720
carried-forward `gc_rank`s replaced by computed ones. 1978 and 1982 refuse, each
holding a stage PCS never classified. 508 rows went and 48 arrived: 153 of the
192 carrying a placing were individual placings on TEAM time trials, which a
team trial does not produce, and 39 were one rider under a slug PCS renamed.

### 1. `ingest_race.py` could not re-ingest 254 of the editions it serves

It DELETEd the `race_editions` row and inserted a fresh one.
`classification_standings` references `edition_id` with **no ON DELETE
CASCADE**, so from the moment the September standings landed — 86 Tour, 88 Giro
and 80 Vuelta editions — every re-ingest of those years raised `FOREIGN KEY
constraint failed` and rolled back. Nothing was lost; nothing could be rebuilt
either, which is the entire purpose of the script. The verification that this
path matched `reingest_edition_results` on 1949 predates those rows by two
commits, so it was true when written and false by the next morning.

The edition ROW now stays, as `ingest_classics.replace_edition` has always done.
That also keeps what no scrape file carries: the ordinal `edition_name`
("72nd Tour de France", on 1,170 editions) and `uci_classification`, both of
which the re-insert overwrote with a generated "YEAR Race". **Stage incidents**
(1904's disqualifications, the Festina walkout) key on a `stage_id` the
re-ingest replaces, so they are captured and handed back by stage number.

### 2. `discover_stages` never asked PCS for the prologue

It only ever probed `stage-N`. A prologue is slugged `prologue`, never
`stage-0` — 82 in the database, **41 of them the Tour's, 1967-2012**. Those
years would have come up a stage short each; not silently, because the orphan
guard would then refuse the edition, but not usefully either.

### 3. `backfill_bib_numbers.py` refused to write anything, anywhere

Six rider-editions in the 1931 and 1933 Tours hold two bibs each, and the guard
was global. The invariant it protects is per edition: 1931 being ambiguous says
nothing about 1985. Those editions are now skipped and reported. This matters
because **PCS leaves the per-rider cells empty on a team time trial** — no
re-scrape can supply them — and a re-ingest of 1960-2025 clears 7,647 TTT bibs
that only this tool can put back. 48 TTT stages across 44 of those years.

### 4. A winner's time that is not a stage time

See "Refuse a winner's time that no bike race could have ridden" in the log.
PCS puts the GC TOTAL in the Time column on some split-day trials: the 1962
Tour's 23 km stage-2b reads 10:45:17. Ingest bases every other rider on the
winner's time, so one bad cell fabricates a field at 2.1 km/h. Guarded at
12-70 km/h — deliberately far wider than any real stage.

### What the pilot showed

**1985 reproduces the database exactly**: 24 stages, identical slugs, dates,
distances and row counts, prologue and split day included. The change table for
re-ingesting it is 386 fills, **0 overwrites**, 438 clears — and the clears are
right: 130 are carried-forward GC on `stage-18a`, where PCS itself publishes
only 15 GC rows, and 178 are TTT bibs the backfill restores. **1962 ingests to
a byte-for-byte identical edition** once its sidecar exists.

### The per-year recipe (all four steps, in order)

```bash
python3 scrape_race.py --race tour YEAR                  # stage pages (replays swaps itself)
python3 scrape_vuelta_gc_pages.py --race tour YEAR       # per-stage GC pages
python3 build_vuelta_gc_standings.py --race tour YEAR    # the sidecar
python3 fix_name_swaps.py --race tour --year YEAR --dry-run   # any NEW swaps
python3 ingest_race.py --race tour YEAR
python3 backfill_bib_numbers.py --apply                  # once, at the end
```

**A re-scrape undoes a name-swap repair.** The fix lives in the scrape file and
PCS reproduces the transposition on every request, so re-fetching a repaired
stage writes the swap straight back — silently, the file being the source of
truth. `scrape_race.py` therefore runs `fix_name_swaps --replay --apply` over
every year it scrapes before it exits, restoring anything recorded in
`name_swaps_applied.json`; it prints only when it actually restores something,
and `--no-replay` opts out. The dry-run line above is still worth running,
because replay only knows the pairs already recorded — a year scraped for the
first time may hold new ones. Any scraper OTHER than `scrape_race.py` that
rewrites a stage file needs `python3 fix_name_swaps.py --replay --apply` run
after it by hand.

Before the ingest step, see what it would do:

```bash
python3 preview_reingest.py --race tour 1960-2025        # the change table
python3 preview_reingest.py --race tour 1985 --verbose   # with example values
```

It copies the database, ingests into the copy and diffs — the real one is only
ever read. NULL-fills, overwrites and clears are counted separately because
they carry different risk, and a year the ingest refuses is reported as refused
rather than counted, since nothing moves when the edition rolls back.

**Never ingest a year before its `gc_standings.json` exists.** Old PCS stage
pages carry GC for ~15 riders; the rest of the field reaches the database only
through the sidecar. 1962 without it loses 130 rows on one stage; with it, the
edition is identical.

### Two editions the orphan guard will refuse, and should

1978 and 1982 each contain a stage PCS never classified — stage-12a, abandoned
to the Valence d'Agen riders' strike, and the 1982 team trial annulled after
the farmers' protest. PCS labels both "Race/stage is cancelled", exactly as it
labels the 1991 Vuelta's weather-cancelled stage, so the scraper writes no file
and the orphan guard refuses the edition. That is correct: a stage file would
land them in the database as raced days nobody finished. Both need a decision,
not a flag — `insert_cancelled_stages.py` places such stages with
`cancelled=1`.

**And the database is wrong about one of them today**: TDF 1978 stage 13
(`stage-12a`) is stored as `cancelled=0` with 99 GC-only rows, contradicting
PCS. 1982 stage 5 is already `cancelled=1`. Not repaired here — it wants the
same decision.

### What a re-ingest changes, and why

Expect `gc_rank` and `gc_gap_seconds` to move on most pre-1998 years. Those are
carried-forward values being replaced by ones computed from real stage gaps and
validated against PCS's published standings — the same swap the September pass
made for 1903-1959, where 57,457 computed values replaced 66,673 carried ones.
Neither the old nor the new figure is PCS-published for a mid-pack rider in
1963: PCS publishes 15. The difference is that one is repeated and one is
derived from that rider's own racing.

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

# Unit tests — 769 as of 2026-09-19
python3 -m unittest discover -p "test_*.py"

# Exported-JSON checks (run after any export). 470 files, 0 errors and
# 84 warnings is the expected clean result as of 2026-09-16 (the 470th is
# the 2026 Vuelta) — compare the COUNT against that baseline rather than
# expecting zero.
python3 validate_exports.py
python3 validate_db.py               # 0 errors, 12 warnings expected (2026-09-19)
                                     # Warnings are a standing worklist, not noise —
                                     # read them. Two were added 2026-09-11 and name
                                     # 4,310 rows that are still wrong; see
                                     # "Times that no race produced" below. The
                                     # count is the baseline to compare against,
                                     # so a check that ADDS a warning updates it
                                     # in its own commit — it read 9 for five days
                                     # after two checks had already taken it to 11.

# Cross-race rider membership — the `x` bitmask the rider detail page uses to
# decide which indexes it can skip. The exporters re-stamp it themselves; this
# only needs running by hand after some OTHER writer touches a riders_index.json.
python3 link_rider_race_sets.py --check     # report drift, write nothing
```

### coverage.py — what is missing, and where (re-run 2026-09-11)

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
| `gc_rank` for a one-day or gravel race | structural: a race of one stage has no general classification. 0 of 72,911 and 0 of 7,891 |
| `route_type` anywhere it is computed; a gravel `source_slug` | derived or assigned at ingest, never fetched, so no scrape fills them. `route_type` fills exactly when its input does |
| elevation, profile score and teams **only for the gravel editions Athlinks or tretzesports timed** | those are timing platforms: a finish list, no parcours, no trade team. **Corrected 2026-09-09** — this row used to exclude the whole gravel set because "PCS has no gravel or MTB coverage at all — verified, not assumed", and the one-day row excluded profile score because "a one-day race is not classified flat/hilly/mountain". Both were false and together hid ~993 fillable values. The reasoning is in this table and in coverage.py's own docstring. |

Gaps rank by **values missing**, not by percentage: a year at 40% of 180 is a
bigger afternoon than one at 0% of 3. Distrust a low number either way — it
usually means the parser is dropping data, not that the source is thin.

**Re-run 2026-09-11**, after the September 10-11 repair pass (the Tour's
1960-2025, every Giro edition, 79 of 80 Vuelta ones). 469 race-years, 7,268
stages, 786,858 results; 1,308 race-year/field combinations incomplete,
169,434 values:

| field | outstanding | where it is worst |
|---|---|---|
| `gc_rank` | 87,852 across 214 race-years | the 1980s Giro and Vuelta — Giro 1989 is 563 of 3,977 (14%), and the next five are the same era |
| `vertical_meters` | 3,334 across 343 race-years | the pre-war Tour, whole editions at zero (1937, 1938) |
| `finish_time_seconds` | 149 race-years incomplete | the late-40s/early-50s Giro — 1951 is 179 of 1,611 (11%), 1947 and 1948 under 7% |
| `birthday` | 6,326 of 19,023 riders | — |

**The `gc_rank` line is not a worklist, and this is the trap in the table.** It
is the biggest number here and the least actionable one: PCS embeds per-stage
GC standings for only about 1-30 riders before 1998, and the July 2026 rebuild
deliberately emits a rank only where at least 85% of the active field is known
that day. The rest are null *because* the alternative was the carry-forward
that fabricated them. So the 87,852 are mostly values that cannot honestly
exist, not values nobody has fetched yet — see "Vuelta & Giro per-stage GC
standings" above before planning anything against this row.

That also means the usual "distrust a low number" reflex cuts the other way
here. It is the one field in this table where a low number is the correct
answer, and two repair passes have not moved it for exactly that reason.
The late-40s Giro's `finish_time_seconds` is the row with real fetchable work
behind it.

**`vertical_meters` was also on that line until 2026-09-11, and the correction is
worth keeping.** It does have fetchable work — but 73 values of 3,334, and *not*
where this table points. The years named above as worst (the pre-war Tour, whole
editions at zero) are exactly the ones PCS has nothing for at all. The 73 that
could be filled were Paris/Milan/Madrid finales scattered through years that
already looked almost complete, and so never surfaced as a "worst gap" at all.
See "Extended back past 1990". The general lesson: this table ranks by *count*,
and a field's biggest gap and its fetchable gap can be disjoint sets.

`test_coverage.py` pins each exclusion above, because each one is a case where
a naive `COUNT` reported a gap that does not exist.

`validate_exports.py`, `validate_db.py` and the unittest suite are the ones
that gate a change.

**`validate_kom.py` / `validate_gc.py` were NOT short of reference data, and
the note here saying so was wrong (corrected 2026-09-11).** `bri_stages.json`
is in the repo, covering 1960-2025, and the bikeraceinfo fetch works. Both
validators pointed `DATA_DIR` at `cycling-app/src/data/`, and the Tour's
exports moved to `data/tour/` in the **2026-07-31 per-race restructuring**.
`load_our_*` therefore returned `[]` for every year, both printed `no_data`
for everything, and the silence was read as "no reference data" for six weeks.

`validate_gc.py` carried a second bug behind the first: `SELECT year FROM
race_editions` with no race filter, so it walked all 1,365 editions of every
race and printed each Tour year's verdict once per race sharing that year —
"1365 years total" for a 113-edition race. This is exactly the year-only
lookup the July pass fixed everywhere else; it was missed here because nobody
reads empty output.

After both fixes: `validate_gc.py` reports **113 years, 40 ok, 2 mismatch**,
and `validate_kom.py` 1998 goes from `no_data` to **90% match**.

**Aligned on DATE since 2026-09-11, and both earlier "mismatches" were
artifacts of the old alignment.** `build_date_map()` matches BRI stages to
ours by `stage_date`; `build_sequential_map()` survives only as a fallback for
years where one side has no usable dates.

The old positional/label matching was wrong wherever the two sources disagree
on stage count, and it failed loudly enough to look like a data defect. For
1998, BRI lists 20 stages against our 22, so "Stage 8" matched our stage 13,
"Stage 9" our 16, "Stage 10" our 18 — every leader compared belonged to a
different day, reported as a 54% mismatch on a year whose GC is correct. A
date is the one thing both sides agree on and neither renumbers; BRI's stage
numbers are not our `source_slug`s and the two diverge after every split day,
which is the trap that governs the rest of this pipeline. Split days put two
stages on one date and are handed out in order.

**The date field is not one shape, and assuming it was cost a second pass.**
1998 gives a bare `"Sunday, July 12"`; 2005 gives `"Saturday, July 2: 19 km"`
and, for its stage 20, the date followed by a paragraph of race preview. An
end-anchored pattern matched 1998 and failed all 18 of 2005's, silently
dropping that year back to positional. The parser now scans for the first
`<word> <number>` whose word is a real month.

Result: **113 years, 42 ok, 0 mismatch** (was 40 ok / 2 mismatch / 1,365
"years"), and `validate_kom.py` 1998 goes from `no_data` to a 90% match.

**Two distance disagreements survive alignment and are therefore real** — the
route names match on both sides, so these are the same stage:

| stage | bikeraceinfo | ours |
|---|---|---|
| 2004 stage 14 | 292.5 km | 192.5 km — differ by exactly 100, so one side has a digit wrong |
| 2005 stage 14 Agde - Ax-3 Domaines | 220.5 km | 174.0 km |

Neither is resolved. `distance_divergence_baseline.json` is the place for them
once a third source settles it.

### cyclingflash cannot fill the elevation gaps — checked 2026-09-11

Read through the Chrome extension (it serves the in-app browser a Cloudflare
interstitial). **Its elevation coverage starts in 2000.** Probed directly:
1937, 1954, 1962, 1980, 1990, 1992, 1995 and 1998 all return a distance and no
`Elevation gain`; 2000, 2001, 2002, 2004 and 2006 all return one. The 2006
stage-20 probe returns **1012 m**, matching what `patch_cyclingflash_elevation.py`
already stored, which is what confirms the extraction is right.

Every elevation gap in this database is pre-2000 — the pre-war Tour, the
1954-1962 block, Giro 1992-1999 — so **cyclingflash has nothing to offer them**
and nobody needs to relay figures by hand for those years. Its stage URLs are
`/race/tour-de-france-<year>/stages/stage-<n>`; the Giro's slug is
`giro-ditalia-<year>`, with no hyphen before "italia".

## Data Quality Notes

### KOM data by era

**Measured 2026-09-11, the first full-archive run** — possible only after
`validate_kom.py`'s data path was fixed the same day. **113 years: 39 ok,
18 mismatch, 56 no_reference.**

| decade | ok | median match |
|---|---|---|
| 1950s | 10/10 | **90%** |
| 1990s | 6/10 | 90% |
| 1980s | 5/10 | 80% |
| 2000s | 3/10 | 80% |
| 1960s-70s | 7/20 | **67%** |
| 2010s-20s | — | no reference at all |

**The "0% match" years below were partly an artefact and the list should not
be trusted as written.** The first run reported 48 mismatches; 30 of those were
years with NO external reference, scored as disagreeing with a source that said
nothing. bikeraceinfo and Wikipedia thin out after 2009, so every year from
2010 on was in that state. Real disagreements: 18.

What survives measurement: the **1960s-70s dip is real** (67% median), matching
the "PCS missing some climbs" note. The **1950s are the best decade in the
archive** at 10 of 10 and a 90% median, which nothing here previously claimed.

- **1933–1938**: Patched from Wikipedia top-10 via `patch_kom_wikipedia.py`
- **1960–1976**: Old PCS format. Totals run low vs Wikipedia — PCS missing some climbs
- **1977–1984, 1986–1987, 1990, 1998–1999**: Modern PCS format, mostly good
- **1985, 1988–1997, 2000, 2003–2004, 2010, 2015, 2018**: previously listed as
  "0% match, need alternative sources". Re-check each against the corrected
  run before acting: 2010, 2015 and 2018 have no reference at all, so their 0%
  was never evidence.

### Known DB quirks
- **1982 Stage 5** (Orchies→Fontaine-au-Pire, TTT): Cancelled due to farmer protest. Distance is null.
- **1987 Stage 25**: Had wrong `stage_date` (shared with stage 24). Fixed to 1987-07-27.
- **1904**: Post-DQ results patched manually — Garin et al. set to `gc_rank = NULL` at last stage, Cornet set to rank 1. Their Wikipedia times (all 15 finishers) are in `gc_all_times.json`.
- **1939**: A DNF rider (Jaminet, rank 64 mid-race) appears in the last stage with no gap; correctly excluded from "slowest finisher" calculation by `status = 'FINISHED'` filter.
- **1990 Stage 21** (Paris): Was stored as 45.5 km (duplicate of TT distance). Corrected to 182.5 km.
- **1905–1912 gc_gap_seconds**: All zeros at last stage for points-system years — PCS stored intra-stage gaps, not cumulative race time gaps. Not usable for time calculations.

### PCS strikes through a disqualified rank, and we threw the marker away (2026-09-11)

**This is the answer to the duplicated ranks, and it was visible on the page the
whole time.** PCS marks an annulled result by wrapping the rank in `<s>`,
keeping the number:

```html
<td><s>&nbsp;1&nbsp;</s></td><td></td><td></td>   Aucouturier — DISQUALIFIED
<td>1</td><td>1</td><td>+0:00</td>                Cornet — awarded the win
```

Every scraper here strips HTML tags, so both became a plain rank `1`. That is
where **39 stages with two rank-1 finishers** come from, and it is worse than a
cosmetic tie: `ingest_race` takes the first rank-1 row carrying an absolute time
as the stage winner, so on 1904 stage 3 every rider's finish time is computed
against the time of a man who was stripped of the result.

**Two PCS conventions, and we only handled one.** A literal `DSQ` in the rank
cell is already read as a status (344 rows). The struck-through numeric rank was
invisible.

**The empty GC cell is NOT the marker** — that was the tempting shortcut and it
is wrong. Fily Camille finished 6th on 1904 stage 3, is not struck, and has an
empty GC cell too. Only the `<s>` tag distinguishes them, and it does not
survive into the scrape files, so this cannot be repaired from what is on disk.

**`audit_disqualifications.py`** reads it from the live page by `source_slug`
and reports every struck rider we store as a finisher; `--apply` sets
`status='DSQ'` and `stage_rank=NULL` with provenance, and deliberately leaves
`finish_time_seconds` alone — the man rode and the clock ran; what was taken
away was the placing, not the afternoon.

**Measured 2026-09-11 across the 39 suspect stages: 85 disqualified riders
stored as finishers.** The years are the history — 1904, then 2006-2013:

| edition | struck riders stored as finishers |
|---|---|
| Tour 1904, all six stages | 29, being Maurice Garin, Lucien Pothier, César Garin, Hippolyte Aucouturier and Stéphane Chaput |
| Tour 2008 (st 4, 6, 9, 10, 20) | 25 |
| Tour 2007 (st 3, 7, 11, 13, 15, 18, 21) | 11 |
| Tour 2006 st17, 2009 st16, 2010 st15 | 11 |
| Giro 2013 st14, Tour 2011, 1968, 1977, 1987, 1992, San Sebastián 2009 | 9 |

The 1904 set matches the documented history exactly: the UVF heard testimony for
months and in December 1904 disqualified the first four finishers and every
stage winner — 29 riders punished, two for life — handing the race to 19-year-old
Henri Cornet four months after it ended.

**Built and applied 2026-09-11.** `stage_results.disqualified` records the
fact. The rank, the time and the row all stay — the ride happened, the placing
was taken away — and the frontend draws the rider struck through the way PCS
does, so he stays visible and the fact is visible with him. This is NOT
`status='DSQ'`, which means a rider thrown out on the day holding no rank at
all (344 rows, a different thing).

**Two shapes, and only one is findable from inside the database:**

- the rank is vacated and someone is **promoted** into it — 1904, Cornet given
  Aucouturier's win. Two riders end up with the same number, which is what
  `--duplicated-rank1` finds.
- the rank is vacated and **nobody moves up**. The 2005 Tour GC strikes
  Armstrong at 1, Ullrich at 3, Leipheimer at 6, Hincapie at 14, Boogerd at 24
  — and Basso stays 2, Mancebo 4, Vinokurov 5. **No duplicate rank exists, so
  nothing in our data hints at it.** Only the page shows it. These have to be
  asked for by year, which is why the seven Armstrong Tours were swept by name.

**374 results across 33 riders** are marked: Armstrong 147 (1999-2009),
Leipheimer 45, Hincapie 41, Boogerd 22, Ullrich 20, then a long tail down to
the 1904 six.

**A struck rider still anchors the stage's times, and that is deliberate.**
Refusing to let a disqualified man set the winning time sounds obviously right
and is wrong: his clock is the only absolute time on the page, and the rider
promoted into his place is shown TIED with him. Cornet's own time cell on 1904
stage 3 is PCS's ditto `0:00`, meaning "as above" — so blocking Aucouturier's
15:43:55 makes `winner_seconds` **zero** and times the whole stage from
nothing. I wrote that guard, and `TestDisqualifiedRanks` caught it.

**How it survives a rebuild.** A scrape file written before 2026-09-11 has 15
fields and no marker, and an absent marker means UNKNOWN, not "clean". The
usual patch-carry cannot help — it only rescues `PATCH_SOURCES`, and the honest
source for a struck rank is `pcs`, which ingest writes itself. So `ingest_race`
carries stored markers across explicitly and only a 16-field file is allowed to
change one. `STAGE_ROW_LEN` stays 15, `STAGE_ROW_LEN_V2` is 16, both accepted;
`EXTRACT_RESULTS` now reads `tds[0].querySelector('s')`. Re-scraping an edition
makes its marker self-describing and the ingest says which ones it had to
carry.

**Career pages carry it too (2026-09-11), and the shape is different on
purpose.** `riders_index.json` stores `dq` as a list of YEARS, not a boolean:
a disqualification belongs to a race, and the Riders page is a career
overview — a rider who lost one Tour did not lose the other nine. So:

- **By Stage sidebar** (one race, one year) — the rider's name and rank are
  drawn **struck through**, PCS's own convention. There the claim is true.
- **Riders grid** (a career) — a `⊘` marker BESIDE the name, never over it,
  with the years in its tooltip. Striking a career through would say the career
  was annulled.
- **Rider detail** — `⊘ result annulled: 1999, 2000, …`, unioned across every
  race the rider appears in, and deliberately SEPARATE from the curated
  `RIDERS_WITH_REVOKED_RESULTS` prose note: that list is an editorial decision
  about five riders, this is what the source marks. A rider in both gets both.
- **Filter** — a `⊘ Disqualified` toggle that ANDs with every other filter, so
  nationality "United States" plus that toggle answers "American riders who
  have been disqualified" in two clicks: 18,088 → 25 → 5 (Armstrong, Hincapie,
  Landis, Leipheimer, Zabriskie).

The payload baseline was re-cut in the same commit: `main.js` +1.2 KB and
`main.css` +0.1 KB gzipped, both under 2% in absolute terms but over the
relative gate. **The data files did not regress at all** — the `dq` arrays
exist on 33 riders of 19,002 and cost nothing measurable.

### Cross-checked against an independent list (2026-09-11)

`grandtourstatistics.nl/dsq.php` is a researcher's hand-built list of riders
disqualified by the jury in the Tour, Giro and Vuelta. It 403s a plain fetch;
it reads fine in a browser. Its inclusion rule is deliberately NARROWER than
PCS's: *"If his results were removed because of a doping test in a different
race, I don't count it"* — which excludes exactly the USADA-style annulments
(Leipheimer, Hincapie, Zabriskie) that PCS does strike.

Against the 28 race-years swept so far: **37 of its 45 entries are in this
database**, and the split says something useful about the two PCS conventions:

| convention | what it covers |
|---|---|
| struck rank (`disqualified=1`) | the overall annulments — Armstrong x8, Contador 2010, Landis 2006, Ullrich 2005, the 1904 top four |
| literal `DSQ` in the rank cell (`status='DSQ'`) | stage-level jury DQs — the ten further 1904 riders, Samyn and Stablinski 1968, the four Giro 2012 car-holders |

**The first comparison looked like 27 misses and was wrong**: it counted only
the new flag. Ten of the 1904 riders and every stage-level DQ were already
present as `status='DSQ'`. Any audit of this has to count both.

**The 8 genuine differences are PCS's, not ours** — each checked on the page
rather than assumed:

| rider | the list says | PCS shows |
|---|---|---|
| Froome, Giro 2010 st19 | DQ (held a police motorbike) | `DNF`, not struck |
| Durand, Tour 2002 st12 | DQ | **not on the page at all** |
| Fofonov, Tour 2008 | DQ afterwards (heptaminol) | rank 25, clean |
| Gölz / Pieters, Tour 1992 | DQ | `DNF`, not struck |

plus Nazon and Sweet (1999) and Blijlevens (2000) in the same shape. So the
database is faithful to PCS and PCS is incomplete against a dedicated
researcher. Filling these needs a second source per rider and a `manual`
provenance, not a re-scrape.

**Totals after the 2010-2012 sweep: 737 results, 40 riders** — Tour 594/29,
Vuelta 101/8, Giro 41/6, San Sebastián 1/1.

**Still open:** only 28 race-years have been swept. A vacated-rank
disqualification is invisible from inside our data, so every other edition
needs asking for by name.

[reference_grandtourstatistics]: https://www.grandtourstatistics.nl/dsq.php

### Times that no race produced (2026-09-11)

> **Resolved later the same day.** The subsections below were written while the
> 41 ITT stages still looked undecidable from inside this database. They are
> not: PCS distinguishes the two faults, and every one of the 41 is the same
> kind. What follows the rule is kept as the reasoning that got there.

#### The rule, and why "there is no rule" was wrong

A non-winner whose PCS `Time` cell matches `^[-+]?0:00$` **has no published
time**. That is the entire test, and it settles all 41 stages.

It holds regardless of rank, which is what made it hard to see. The filler
appears on two different kinds of row:

- **39 stages** — on rows PCS marks `DF` (no integer rank). Giro 1979 stage-3
  is the type case: 26 real times, then 91 `DF` rows at `-0:00`, which is
  exactly our 91 tied riders.
- **2 stages** — on rows carrying a **real integer rank**. Tour 1937
  stage-17b ranks 1-45 with only the winner timed; Vuelta 1995 prologue shows
  ranks 2-35 all at `0:00` over 7 km, which no prologue produces.

A genuine bunch finish never looks like this: riders who really share a time
share an actual duplicated value (`2:06`), not the filler. So the discriminator
the earlier note said did not exist is just this one regex, and **no stage in
this set is a mislabelled mass-start**.

#### Two traps, both hit while establishing that

- **`Timelag` is the GC gap, not the stage gap.** It is the obvious-looking
  column on a PCS results table and it is *non-monotonic with rank* (1979
  stage-3: rank 2 at `+0:30`, rank 3 at `+0:29`). The stage gap is in `Time`.
  Reading the wrong one gives wrong-but-plausible values — the same shape as
  parsing "Hardest stages" for vertical metres.
- **The filler has three spellings**: `0:00`, `+0:00` and `-0:00`. A filter
  catching only `0:00` reported **40 of 41 stages as recoverable by a
  re-scrape**. They are not — PCS has no more than we already store. The
  earlier note naming only `+0:00` is why this was worth re-checking.

Also worth recording: **speed is not a discriminator.** An m/km-style test on
winner speed flagged Giro 1979 stage-3 (31 km at 49.6 km/h) as too fast to be
an ITT. PCS's own page gives the same 49.556 km/h and a real gap column — it
was simply Moser. Worse, a baseline built from *all* ITT stages is contaminated
by these 41; it has to be built from stages with no mass tie.

#### What to do about it

`null_itt_filler_times.py` sets those 4,040 `finish_time_seconds` to NULL,
records `SOURCE_PCS` provenance on every row with the citing URL, and leaves
`stage_rank` and `status` alone — where PCS publishes an order without times
those riders did finish, and dropping the placing trades one defect for
another. It is idempotent and dry-run by default. **Not applied as of
2026-09-11.**

**Fixed at the source 2026-09-11 — a re-ingest no longer reintroduces them.**
`ingest_race.py` now refuses to credit an untimed ITT rider with the winner's
second: after a stage's rows are inserted, if `route_type == 'TT'` and more
than `ITT_TIE_LIMIT` (20) non-winners hold the winner's exact time, those
`finish_time_seconds` are NULLed and each gets `SOURCE_PCS` provenance. The
run reports what it refused. `null_itt_filler_times.py` is therefore a
one-time repair, not a recurring chore — it stays in the tree because the
values it wrote predate the guard.

**Why the rule is scoped to ITTs and not to the filler string.** On a
mass-start stage a zero gap is the ORDINARY case: Giro 1979 stage 5, "Sprint
of large group", has 115 riders legitimately on the winner's time. A rule
keyed on `+0:00` alone would erase every bunch finish in the database.
`route_type` at that point is already override-corrected, so Giro 1985
stage-8a — a circuit race PCS labels "Time trial" — is correctly not caught.
A TTT is excluded too, since a squad shares a time by design.

The threshold is the same 20 `validate_db` uses, from the same measured
distribution (genuine ties 1-20 a stage, the defect 21+, nothing between), so
ingest now stops producing exactly what the validator flags, and a real dead
heat still survives.

Proven end to end rather than by inspection: re-ingesting Giro 1979 against a
scratch copy of the DB left all four of its time trials at 10/24/26/24 timed
riders — identical to the patched state — while its non-TT stages stayed at
1,825 of 1,845, unchanged. `TestTimeTrialFillerGaps` covers it, and the two
assertions that matter were confirmed to FAIL with the guard disabled; the
other four assert the guard does NOT over-reach and pass either way.

Tour 1937 stage-17b also sits in the **99 zero-second finishers** set — its
winner time is 0 — so the two warnings overlap by exactly one stage.


Two `validate_db.py` warnings added on 2026-09-11 name 4,623 rows that are
still wrong. Both are absences that arrived wearing a time column's clothes,
which is the same defect the README opens with — and both were found by
asking the chart a physical question rather than by reading the data.

**42 stages typed as individual time trials have 4,211 riders on the winner's
exact time** — some fabricated, some correct under a wrong label; see the
correction below before acting on this.
An ITT is ridden alone against the clock; the field cannot share a time. Where
PCS has no per-rider times for an old ITT it publishes a filler gap of `+0:00`
against every rider, and ingest's `winner_seconds + gap_secs` reads that as a
real zero gap. The Giro's 1985 stage-8 45 km ITT has 172 riders on 53:52; the
2002 Vuelta opener 161 on 26:21.

The threshold is 20, and it comes from the distribution rather than taste.
Across 607 ITT stages the tie counts are bimodal — 497 with none, a tail of
1–20 that is genuine ties at second resolution (66 stages, 226 rows), then 44
stages with 21 or more, and nothing between 20 and 21.

**Corrected 2026-09-11, same day, by Eric.** The paragraph below originally
read this as proof the times were fabricated. It is not, and the reasoning had
a hole in it.

The tied rows are exactly the `+0:00` rows — that part is checked, not assumed.
On the Giro's 1957 stage 2: 97 rows in the scrape file, 49 carrying a real gap
and 48 carrying `+0:00`; the database ties 47 riders to the winner, a strict
subset of the 48 with zero overlap with the 49. But "half the field on the
winner's time, half with real gaps" is *also exactly what an ordinary road
stage looks like* — a bunch finish plus the riders who lost time. The pattern
does not distinguish a filler gap from a real one, and I used it as though it
did.

What forced the correction: **Giro 1985 stage 8a is not a time trial at all.**
PCS says `Won how: Time trial` and we derived `route_type='TT'` from it, but it
was a "Giri-sprint" — a 5 km circuit at Foggia ridden 9 times, with time
bonuses at the first and ninth crossings, one of five such stages in the 1980s
([1985 Giro, footnote 2](https://en.wikipedia.org/wiki/1985_Giro_d%27Italia)).
Wikipedia types it "Plain stage"; Allocchio won it from the bunch and our DB
has him correctly at rank 1 on 53:52, with the peloton on the same time. **The
171 shared times are correct data under a wrong label.** The tell was in our
own numbers: 45 km at 50.1 km/h, Foggia to Foggia, in 1985 — faster than
Moser's hour record, which no time trial of that length has ever been ridden at.

So this warning covers two populations that look identical in our data:

1. a genuine ITT where PCS's `+0:00` is filler — the derived times are wrong;
2. a mass-start stage PCS mislabelled in `won_how` — the times are right and
   `route_type` is wrong.

Across the flagged stages, the 30 km-and-longer ones average 45.6 km/h and
reach 56.2. No era rode an individual time trial at those speeds over that
distance, so population 2 is not a fringe case. **Check the stage against an
outside source before touching a value.** 1987's Giri-sprint (stage 20, ten
laps of 4 km at Como) is already typed as a road stage and is not affected.

**All five 1980s Giri-sprints, checked 2026-09-11 — only one needed fixing.**
Eric supplied the list; each was verified against our own data by its winner,
which is a strong check when the names are this obscure.

| stage | route | km | winner (ours) | route_type | action |
|---|---|---|---|---|---|
| 1985 st8a | Foggia → Foggia | 45.0 | Allocchio Stefano | was `TT` | **overridden to `F`** |
| 1986 st22 | Merano → Merano | 108.6 | Van Lancker Eric | `F` | already right |
| 1988 st21a | Jesolo → Vittorio Veneto | 73.0 | Freuler Urs | `F` | already right |
| 1989 st15b | Trento → Trento | 83.0 | Piasecki Lech | `F` | already right |
| 1987 st20 | Madesimo → Como | 156.0 | Rosola Paolo | `F` | already right |

Only 1985 was ever wrong, because it is the only one PCS labelled `Won how:
Time trial` — at 45 km it is short enough to read as one, while a 108 km or
156 km "time trial" never would. **The lesson is the length**: the format is
invisible to us on a long stage and indistinguishable from an ITT on a short
one.

The 1987 entry is the unsure one. A list circulated to Eric gave it as "stage
2a, San Remo, 16 km, won by Domenico Podenzana", and that fails three checks
here: 1987 has no `stage-2a` (the San Remo opening is prologue + `stage-1a`
31 km + `stage-1b` 8 km), no 16 km stage at all, and Podenzana — who did ride
that Giro and abandoned around stage 13 — placed no better than 5th in 1987,
taking his first Giro stage win in 1988. The
[1987 Giro article](https://en.wikipedia.org/wiki/1987_Giro_d%27Italia) names
stage 20 instead, "ten laps of 4 km around Como", which matches what we hold.
Either way the stage is already typed `F`, so nothing turns on it.

**And the 1987 Giro is not missing a stage — checked 2026-09-11, do not redo
this.** The obvious follow-up to "a 16 km San Remo stage we do not have" is
that we dropped one. We did not. Five independent checks agree:

- our slugs run unbroken (`prologue`, `1a`, `1b`, `2`–`22`), stage numbers 0-23
  are contiguous, and the dates run 21 May - 13 June with one rest day (31 May);
- Wikipedia's infobox says **"22 + Prologue, including one split stage"** — our
  24 files exactly, the split being stage 1;
- PCS's own route page lists the identical 24 slugs, with no `stage-2a`;
- 23 of 24 stage distances match Wikipedia to the kilometre;
- `export_race_summary.py`'s distance reconciliation reports nothing, and its
  own docstring names the signal — *"a large NEGATIVE gap is the missing-stages
  signature"*. Ours is -0.10%.

The whole 4 km gap (3,911 ours vs 3,915 published) is one stage: **21, Como →
Pila**, PCS 248 km against Wikipedia's 252. Left alone deliberately. PCS is the
primary source and provenance says so, the Giro's median PCS/Wikipedia
disagreement is 0.13%, and `export_race_summary.py` exports the DB sum rather
than Wikipedia's total on purpose — showing Wikipedia's figure would mask a
real missing-stage defect behind a correct-looking number.

**Fixing one, when you find one: `route_type_overrides.json`.** Not a DB
patch — `route_type` is not among the columns a re-ingest preserves, so a
direct UPDATE is reverted by the next rebuild with nothing to say it had gone.
The file is keyed by PCS `source_slug` (stable across the renumbering split
days cause), records the override's own source in `data_provenance` rather than
`pcs`, and carries `was` so that an entry whose reason has expired — PCS
starting to report the right type — is refused and reported rather than
silently applied. `won_how` is left as PCS wrote it; the classification is what
is being corrected, not the record of what the page said. 1985 stage-8a is the
seed entry and the worked example.

So **a re-ingest does not fix these**, and 21 of the 42 stages have scrape files
whose partial real gaps are already in the database. Only a re-scrape that
finds data PCS did not previously publish helps: the 2002 and 2003 Vuelta
openers gained full per-rider gaps that way on 2026-09-11. Where PCS still
shows filler, the honest value is NULL.

Nothing was written. Replacing 4,211 derived times with NULL is a decision
about what the site should show where the source is silent, not a cleanup, and
it belongs to Eric. The check exists so the number stays visible until then.

**99 finishers carry `finish_time_seconds = 0`**, across 11 stages. Zero is a
value, not an absence, and nobody finishes a bike race in no time. PCS gives
only the winner's time on these pages and leaves every other time cell blank;
an older ingest stored the blank as 0. Tour 1937's 37 km stage-25 ITT holds 45
of them, ranks 1–46 at zero beside a winner with a real 1:06:27.

Do not reach for a re-ingest here: today's code reads that same page's `+0:00`
filler and would credit all 46 with the winner's time, trading this defect for
the ITT tie above. NULL is right either way.

**9 team time trials hold 536 fewer riders than the stage after them.** Nobody
joins a race mid-way, so each of these is missing riders who were in the race.

The first guess was that PCS lists the riders dropped by their team outside the
per-team blocks and the parser reads only the blocks. **That is true for one
stage out of ten.** All ten were re-fetched by `source_slug` on 2026-09-11 and
both parses compared:

| stage | in DB | team blocks | results table | recoverable |
|---|---|---|---|---|
| Vuelta 2003 st1 | 168 | 168 | **197** | +29, done |
| Giro 1956 st2b | 69 | 69 | 1 | — |
| Giro 1988 st4b | 117 | 117 | 20 | — |
| Giro 1985 st2 | 135 | 135 | 10 | — |
| Giro 1989 st3 | 185 | 185 | 20 | — |
| Vuelta 1960 st1 | 30 | 30 | 1 | — |
| Vuelta 1961 st1a | 30 | 30 | 1 | — |
| Vuelta 1992 st2b | 108 | 108 | 20 | — |
| Tour 1954 st4a | 10 | 0 | 10 | — |
| Tour 1957 st3a | 15 | 0 | 15 | — |

Only the Vuelta 2003 opener publishes a full results table beside its team
blocks; `scrape_race.py` now parses both shapes and keeps whichever is fuller,
which recovers those 29. On the rest PCS has no more riders than we do — the
1954 and 1957 Tour stages really are 10 and 15 riders on the page. So this
warning is a coverage report, not a queue of parser bugs.

The same fix caught a worse case that this check could never have flagged,
because the damage was in the scrape file rather than the database. A 2026-09-11
re-scrape of the **2006 Vuelta** wrote a stage-1 file with **9 rows, starting at
rank 6** — `parse_ttt_rows` matching a fragment of that page — against 189 in
the DB. Ingesting it would have deleted 180 riders from a stage that has them.
The full results table on the same page has all 189 with real per-rider times,
which also clears the 153 riders that stage had sitting on the winner's time.

Two lessons, both already written down and both worth repeating here: run
`preview_reingest.py` before a re-ingest (that is what caught the 180), and a
row count that DROPS after a re-scrape is a question, never a result.

Fetch by `source_slug` when checking one. Six of the ten are split days whose
PCS slug is not `stage-<n>`: the 1992 Vuelta's DB stage 3 is `stage-2b`, and
fetching `stage-3` returns a 205 km road stage with 188 finishers, which looks
exactly like a fix and is a different race day.

Note the direction of the 2026-09-11 Vuelta re-ingest on this stage: it
*replaced* 197 rows carrying 151 fabricated ties with 168 rows carrying real
team times. Row count went down and correctness went up. That is why "rows
gone" is a question to ask rather than a verdict.

**"Dorsal 71" is not a parser bug.** 21 riders in the DB are named `Dorsal
<n>` — Catalan/Spanish for bib number — all from The Traka 360, and 9 of them
carry a DNS row. The raw timing feed really does publish `Nom: "DORSAL 71 "`:
the timing company recorded a bib and no name. Genuine upstream, already
checked; leave them alone.

### GC validation results
`validate_gc.py` against bikeraceinfo: 40/42 years pass at ≥70% GC leader match (1960–2005). The 2 failures (1979, 1998) are alignment issues around short TT stages, not real data errors.

---

## File Locations on Eric's Machine

- **Repo:** `~/Documents/GitHub/tdf-analytics/`
- **Database:** `~/Documents/GitHub/tdf-analytics/pipeline/cycling.db` (gitignored — back up with `pipeline/db_backup.py`)
- **Main site repo** (separate): hosts `www.ericshiflet.com`; TDF app lives at `/tdf-analytics/`
