# Optimization pass — findings and two proposals
**2026-08-21.** Written while you were out. Everything in "Landed" is done,
verified and committed; everything in "Proposals" is untouched code awaiting
your call.

> ## CLOSED 2026-08-22 — every item resolved
>
> | item | outcome |
> |---|---|
> | Exporter + ingest dedup | merged (PR #7, #8) |
> | B1 — detect patch reverts | merged (PR #8) |
> | B2 — prevent patch reverts | merged (PR #8) |
> | B3 — patches write to scrape files | **declined**, agreed unnecessary once B2 landed |
> | Proposal A — riders_index re-encode | PR #10 |
> | giro/vuelta script dedup | PR #9 |
> | `race_set_export.py` direct tests | PR #10 |
> | Unused frontend exports | PR #11 |
>
> Kept as written rather than rewritten, so the reasoning that led to each
> decision stays legible. Outcomes are recorded inline below.

---

## The headline finding is a bug I caused, then fixed

**Re-running `ingest_classics.py` silently reverts every correction that lives
only in the database.**

I hit this by re-ingesting to verify a refactor. Afterwards:

- Milan–San Remo 2013 was back to PCS's wrong **121.0 km / `pcs`**, discarding
  the 246 km Wikipedia correction from `cf3fa9b`
- **1,884 team attributions** from bikeraceinfo were gone (84,800 → 82,916)

Nothing failed. Result counts were identical either way (102,261), every
validator stayed green, and the loss was invisible except by looking at one
specific value. I caught it only because I checksummed the results table before
and after and went looking when the checksums moved.

Restored from the pre-session backup and rebuilt gravel from its scrapes;
current state verified back to 246 km / `wikipedia` and 84,800 teams. Now
documented at the top of `ai-context.md` under **"DANGER: re-running
ingest_classics.py reverts every DB-only patch"**.

The underlying architecture issue: **the scrape files are not the source of
truth, but the ingest treats them as if they are.** Corrections live in a
second, invisible layer (the `patch_*.py` scripts) that only a human remembers
to re-apply. See Proposal B.

---

## Landed

### 1. Aggregate exporters merged — 495 lines to 371

`export_gravel.py` was a copy of `export_classics.py`, measured **71% identical
line-for-line**. I wrote that duplication during the gravel build and flagged
it at the time.

The remaining 29% turned out not to be logic. Everything set-specific falls out
of the data:

- the season-standings pass is a **no-op** for a set that awards no points —
  every off-road result has `pcs_points` NULL, so totals stay 0 and
  `sprintRank` stays None, which is exactly what that set ships. No flag.
- `tidx(None)` is already −1, so a set with no teams emits an empty `teams`
  table without being told it has none
- `start_location`, `finish_location`, `profile_score` are NULL for off-road,
  so selecting them unconditionally yields the same null-filled output

Now `race_set_export.py` (294 lines) plus two ~38-line entry points that keep
their own docstrings, since the *why* differs even though the *how* doesn't.

**Verified byte-identical output for both sets.**

### 2. Shared ingest helpers

`upsert_country`, `upsert_race` and the atomic `replace_edition` block were
duplicated across the two ingests. `replace_edition` is the one that clears a
re-ingested edition's provenance rows — and `validate_db.py` has a dedicated
error for what happens when that is missed. Two copies of that block is exactly
how that error comes back.

Now in `race_set_ingest.py`. Rider upserts deliberately stay separate: the
classics identify by PCS slug, the off-road set by resolved name, and merging
them would need a flag choosing the identity model.

### 3. Two riders gained a nationality

The clean rebuild fixed `rider/dexter-pham` and `rider/elliot-bach`, whose
nationality was a stale NULL from an early gravel ingest (`upsert_rider` never
overwrites, so the first insert's gap persisted). Both now match
`_rider_ids.json`. Nothing lost.

### Measured and rejected

Reporting these so they don't get re-proposed:

| idea | measured effect |
|---|---|
| Nationality as a table index in `riders_index.json` | **−1.0%** gzipped. gzip already handles the repetition |
| Drop always-constant `byStage` fields from per-year files | **−3 to −4%** gzipped. Not worth frontend churn |

---

## Proposal A — re-encode `riders_index.json` (−22% gzipped)

> **DONE 2026-08-22 (PR #10), and the measurement contradicted the prediction.**
> Measured in the browser on the real 11,934-rider file, median of 7, forcing
> layout each iteration: **703 KB → 547 KB gzipped (−22%)** and parse+build
> **250.1 ms → 189.9 ms (−24%)**. Both axes improve.
>
> The worry below — that deriving `finalRank` would reinstate the ~380 ms
> `defineLazyConstituents()` avoids — did not materialise. That cost was
> materialising 11,934 objects, not iterating numbers: a `min()` over a flat
> numeric array costs ~1.5 ms, while parsing 156 KB less JSON saves far more.
> The getter stays lazy and now reads the same `ym` array.
>
> Nationality-as-index was measured at −1.0% and **dropped** as not worth the
> churn, as anticipated below.

**Worth doing. Needs a browser measurement first, which is why I didn't.**

`classics/riders_index.json` is 688 KB gzipped, the single largest thing the app
downloads, fetched whenever the Riders page opens. Of it, `m` is 42% and `y`
27%. Those two carry redundancy:

1. every year key is stored **twice**, once in `y` and once in `m`
2. `y[year][0]` is `finalRank`, which is `min()` of the ranks in `m[year]` —
   **fully derivable**

Measured alternatives, gzipped:

| encoding | size | change |
|---|---|---|
| current | 688 KB | — |
| merge `y`+`m`, derive finalRank | 553 KB | −19.5% |
| …and flatten the inner pairs | **534 KB** | **−22.3%** |
| plus nationality indexing | 529 KB | −23.1% (the last 0.8% is not worth it) |

Proposed shape: `y: { "1892": [teamIdx, raceIdx, rank, raceIdx, rank, …] }`,
replacing both maps.

**The risk, and why it's your call.** Deriving `finalRank` means touching
`m`-shaped data at load time — which is precisely what
`defineLazyConstituents()` exists to avoid. Your note in `ai-context.md` says
that lazy non-enumerable getter is load-bearing and cost ~380 ms when eager.

My read is that it's still safe: the 380 ms was **materialising 11,934
`ConstituentResult` objects**, not iterating numbers. A `min()` over a flat
numeric array is a tight loop that should be single-digit milliseconds. But
"should be" is not a measurement, and your own note says measure before claiming
a perf win — including forcing layout in the A/B.

**Cost:** ~1 hour. Touches `race_set_export.py` `build_index()`,
`riderIndexData.ts`, and the Grand Tour indexes need to keep working (they have
no `m`, so the loader must handle both shapes or all four get re-encoded).

**Recommendation:** do it, with a before/after measurement of Riders-page open
time on the classics index as the gate.

---

## Proposal B — make the scrape files the whole truth

**This is the architectural one, and it's what the MSR incident is really about.**

Today a value can come from two places: the scrape file (via ingest) or a
`patch_*.py` script (straight into the DB). Ingest overwrites; patches restore.
Which wins depends on **run order**, and nothing enforces it.

That's fine while you remember. It is not fine as the number of races grows —
the Grand Tours have a dozen patch scripts behind them, and a full
`ingest_race.py` run would silently revert all of them the same way.

Three options, cheapest first:

**B1 — Guard rail only (~1 hour).** Add `validate_db.py` checks that assert the
known-patched values are still in place: MSR 2013 at 246 km with `wikipedia`
provenance, bikeraceinfo team count above a floor, etc. Driven off
`data_provenance`, so it generalises: *"any field whose provenance is not `pcs`
should still not be `pcs` after a re-ingest."* Doesn't fix the architecture,
but converts a silent revert into a loud failure.

**B2 — Re-apply automatically. DONE 2026-08-21, and better than proposed.**

The proposal was a `reapply_patches.py` running every patch script in order.
Built instead as a carry-over inside the ingest, which is strictly better: no
registry to maintain, no ordering to get right, no subprocesses, and it covers
any patch that recorded provenance rather than only the registered ones.

`capture_patches()` reads the patched values out of `data_provenance` before the
edition is deleted; `restore_patches()` hands them back after the rebuild, keyed
on stage_number and rider_id because stage_id and result_id are both re-issued.
Wired into all three ingests.

Result: **a full classics re-ingest is now lossless** — 841 values carried, zero
export diffs, MSR 2013 still 246 km / `wikipedia`. Verified on the Grand Tour
path too (Giro 1919: stage 9 restored 277.0 -> 248.0, stage 10 reported as a
patch the source has caught up with).

Two real defects surfaced while building it:

- skipping `record_provenance()` for a *redundant* patch left Giro 1919 stage 10
  with no attribution at all — value unchanged, provenance gone
- `patch_classics_times.py` wrote two columns but recorded one, so the carry-over
  restored the finish time and not the gap, nulling `gcGapSeconds` for 79
  Gent-Wevelgem 2005 riders. Fixed, 81 provenance rows backfilled

Both are covered by `test_patch_carry.py` (8 tests).

**The rule B2 depends on:** a patch must call `record_provenance()` for every
column it writes. That was already the repo's stated convention; it is now
load-bearing.

**B3 — Patches write to the scrape files (~2 days).** *(Declined 2026-08-22:
B2 achieves the same guarantee without making the scrape files stop being a
faithful record of what the source said.)* The real fix: a patch
edits the scrape JSON and records provenance there, so ingest reproduces it and
the DB becomes a pure function of the files. This is already how the gravel set
works — every correction it makes lives in the scrape files or
`_course_map.json`, which is why a rebuild reproduces them exactly. Biggest
change, and it makes the scrape files no longer a faithful record of what the
source said, so it needs a `source`/`corrected` split inside each file.

**Recommendation: B1 now, B2 soon, B3 only if a third race set appears.** B1
alone would have caught what I did, in seconds, automatically.

### B1 — DONE, 2026-08-21

Built and proved against the damaged database. Replaying that DB through the
new checks produces:

```
ERROR VALUES LOST: one_day.team_id fell from 84,800 to 82,916 (1,884 gone)
ERROR VALUES LOST: one_day.finish_time_seconds fell from 72,911 to 72,831 (80 gone)
ERROR PATCH LOST: Milan-San Remo 2013 stage 1 distance_km was 'wikipedia', now 'pcs'
```

and 0 errors against the healthy one. Note the second line: **80 lost finishing
times I never noticed** — the check found more than the incident that prompted
it.

Three layers, because the failure has three shapes:

1. **`patched_values.json`** — 25 stage-field patches keyed on race/year/stage/
   field/source, never on stage_id. A re-ingest deletes the provenance along
   with the patch, so absence cannot be detected from the DB alone.
2. **Value-count invariants** — `stage_results` with a non-NULL `team_id` /
   `finish_time_seconds`, per race_type. These patches keep provenance keyed to
   a stage_id the re-ingest replaces, so after a revert the provenance is merely
   stale rather than contradicted, and only the COUNT moves.
3. **Contradiction** — live provenance claiming a value that is now NULL. No
   baseline needed.

Also fixed two things found on the way: `replace_edition()` was clearing only
`entity='stages'` provenance, so every re-ingest-then-re-patch cycle left the
previous cycle's `entity='stage_results'` rows behind — 4,450 had accumulated,
now purged via `--purge-stale-provenance` and prevented from recurring.

---

## Not proposing

- **Bundle size.** `main.js` is 224 KB / 59 KB gzipped. Fine.
- **Per-year data files.** Biggest classics year is 42 KB gzipped, fetched one
  at a time. Fine.
- **Merging the ingest scripts further.** The remaining 42% overlap is the
  rider-identity model, which genuinely differs between the two sets.

## Found after this was written

Two things this pass did not anticipate, both now handled:

- **The giro/vuelta script pairs** — three pairs at 85–95% identical, 2,006
  lines down to 1,259 (PR #9). The win was coverage rather than line count: the
  fixture tests imported `scrape_vuelta`, so the Giro's identical 584 lines were
  untested.
- **`giro_gc_winner_times.json` had no writer.** Traced through git: it was never
  a script's output, but three separate PCS-sourced operations. Now documented in
  a `_README` block, and the reason `check_giro_gc_times.py` must NOT pass
  `--write-winner-times` is recorded — a sweep would reintroduce Giro 1946's
  impossible 46.5 km/h value, which was deliberately omitted.
