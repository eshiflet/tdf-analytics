# Optimization pass — findings and two proposals
**2026-08-21.** Written while you were out. Everything in "Landed" is done,
verified and committed; everything in "Proposals" is untouched code awaiting
your call.

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

**B2 — Re-apply automatically (~half a day).** A `reapply_patches.py` that runs
every guarded patch script in order, invoked at the end of any full ingest. The
patches are already idempotent and guarded. Turns a remembered step into an
enforced one.

**B3 — Patches write to the scrape files (~2 days).** The real fix: a patch
edits the scrape JSON and records provenance there, so ingest reproduces it and
the DB becomes a pure function of the files. This is already how the gravel set
works — every correction it makes lives in the scrape files or
`_course_map.json`, which is why a rebuild reproduces them exactly. Biggest
change, and it makes the scrape files no longer a faithful record of what the
source said, so it needs a `source`/`corrected` split inside each file.

**Recommendation: B1 now, B2 soon, B3 only if a third race set appears.** B1
alone would have caught what I did, in seconds, automatically.

---

## Not proposing

- **Bundle size.** `main.js` is 224 KB / 59 KB gzipped. Fine.
- **Per-year data files.** Biggest classics year is 42 KB gzipped, fetched one
  at a time. Fine.
- **Merging the ingest scripts further.** The remaining 42% overlap is the
  rider-identity model, which genuinely differs between the two sets.
