# Data sources

Every value in `cycling.db` came from somewhere, and `data_provenance` records
which source for each one. This file is the index: what each source is, where
it lives, how to reach it, what it is good for, and where it stops being good.

The source names below are the exact strings in `data_provenance.source`, and
the constants in `pipeline/race_common.py` (`SOURCE_PCS`, `SOURCE_CYCLINGFLASH`,
…). `VALID_SOURCES` rejects anything else, so adding a source means adding it
there first.

**The rule that governs all of this: never guess.** A NULL is a gap; a value is
a claim. If no source has it, it stays NULL and `coverage.py` counts it.

---

## At a glance

Row counts are `data_provenance` rows, measured **2026-09-19** (143,332 total).
They move with every ingest — re-measure rather than trusting them:

```sql
SELECT source, COUNT(*) FROM data_provenance GROUP BY 1 ORDER BY 2 DESC;
```

| source | rows | reach it with | good for |
|---|---|---|---|
| [`pcs`](#pcs--procyclingstatscom) | 112,189 | plain HTTP | everything, for every race |
| [`athlinks`](#athlinks) | 16,294 | public JSON API | Life Time gravel/MTB results |
| [`derived`](#derived) | 6,840 | — computed here | never fetched; always second-best |
| [`unknown`](#unknown) | 4,236 | — | origin unproven. **Read its section — this number going UP can mean things got better** |
| [`bikeraceinfo`](#bikeraceinfo) | 2,046 | plain HTTP | Tour cross-checking, KOM, distances |
| [`sportmaniacs`](#sportmaniacs) | 911 | JSON API | The Traka 2023-2026 |
| [`tretzesports`](#tretzesports) | 726 | JSON API | The Traka 2021-2022 |
| [`manual`](#manual) | 53 | — | hand-entered, with a reason |
| [`wikipedia`](#wikipedia) | 35 | plain HTTP | a specific corrected value |
| [letour.fr](#letourfr--the-races-own-site) | 1, as `manual` | plain HTTP (year archive needs a browser) | the Tour's own record, for gaps PCS has |
| [`cyclingflash`](#cyclingflash) | 2 | **Chrome extension only** | elevation, **2000 onward** |

---

## pcs — procyclingstats.com

The primary source for all seven race sets. Everything else here exists to
cross-check it or to fill something it lacks.

- **Stage result**: `/race/<race>/<year>/<source_slug>/result/result`
- **Race route** (elevation PCS omits from stage pages):
  `/race/<race>/<year>/route/stages`
- **Slugs**: `tour-de-france`, `giro-d-italia`, `vuelta-a-espana`, and the
  one-day races by their own name. Gravel lives under `national-race/`, which
  **PCS's own search does not index** — see "PCS's gravel coverage" in
  ai-context.md.

**Address a stage by `source_slug`, never by `stage_number`.** The two diverge
after every split day: the DB's stage 3 of the 1992 Vuelta is the page
`stage-2b`. This is the single most expensive mistake available here.

Plain `urllib` with a browser User-Agent works. It rate-limits, so
`SCRAPE_DELAY` (default 2.5s) applies to every networked script, and **two
scrapers must never run at once** — concurrent runs return wrong data, not
errors. Bulk work uses the DevTools snippet in `scrape_stage_template.js`.

**Known PCS errors — where it is not silent but WRONG.** Each was checked
against other sources, not assumed:

| what | PCS says | reality |
|---|---|---|
| `rider/mathieu-belanger-barette` | "Mathieu Belanger Barette" | **Bélanger-Barrette**, double R, per the [UCI](https://www.uci.org/rider-details/86038), Precision Hydration, Cycling Weekly, Velo, Reserve Wheels and FirstCycling. PCS has one page and `...barrette` is a 404. Its birth date (3 Aug 1989) matches the press profile, so the *rider* is right and only the *name* is wrong. Our canonical id deliberately does NOT follow PCS here — see `rider_aliases.json`. |
| Giro 1985 stage-8a | `Won how: Time trial` | a 9x5 km mass-start circuit race, won from the bunch. Corrected via `route_type_overrides.json` |
| Giro 1946 winner time | a figure implying 46.5 km/h over 3,050 km | unusable; stored as NULL |
| jury expulsions | `DNF`/`DNS`, or the rider vanishes | the nine Festina riders of 1998 were expelled, and PCS strikes none of them |
| split-day time trials | the GC TOTAL in the stage Time column | the 1962 Tour's 23 km stage-2b reads 10:45:17, refused by `implausible_speed` |

**PCS is the PRIMARY source — a statement about volume, not correctness.** It
is authoritative for exactly one thing: the `rider_id` string, because our ids
are its slugs by convention. That is a naming convention, not a truth claim,
and the Bélanger-Barrette row above is the case where the two come apart.

**PCS publishes elevation on TWO surfaces, and they are not independent**
(established 2026-09-19 by fetching 81 editions):
- The **stage page** carries `Vertical meters` in its info block. That is where
  2,879 of the archive's values came from, matched exactly out of the stored
  scrape files.
- The **route page** carries the same table for the whole edition, and is the
  only surface for stages whose stage page PCS serves empty — **76 of the 77
  such stages are the edition's FINAL one**, the Paris/Madrid finale. 78 values
  were proven from it.
- Where both exist **they agree**. So the two are one source checked twice, not
  two sources — which is exactly what makes the seven stages that match
  NEITHER (Tour 2005 st14, six 2006 stages, Tour 2016 st13) a real anomaly
  rather than a choice between two publishers. Use
  `scrape_route_overview_elevation.py --verify-unknown` to re-establish this;
  it records provenance and never writes a value.

**Known silences, all verified rather than assumed:**
- No elevation before ~1963 on the route page, and none at all for the 1954-62
  Tour block or Giro 1992-99.
- No per-rider times on 41 old time trials — filler (`0:00`, `+0:00`, `-0:00`)
  where a time should be. See "Times that no race produced".
- Jury expulsions are `DNF`/`DNS` or absent, not struck through. The nine
  Festina riders of 1998 are `DNS`. See "PCS strikes through a disqualified
  rank".

## bikeraceinfo

`https://bikeraceinfo.com/` — a researcher's Tour archive. Plain HTTP, no
challenge.

- **KOM by year**: `/tdf/tdf<year>.html`, fetched live by `validate_kom.py`.
- **Per-stage GC**: `pipeline/bri_stages.json`, in the repo, covering 1960-2025.
  Used by `validate_gc.py`.
- **Distances**: `patch_bri_distances.py` (2,046 rows, the bulk of this source).

**Align to our stages by DATE.** Its stage numbering is not ours and the counts
disagree — BRI lists 20 stages for 1998 against our 22. `build_date_map()` does
this; the older positional matcher survives only as a fallback. Its `date`
field is not one shape: `"Sunday, July 12"` in 1998, `"Saturday, July 2: 19 km"`
plus a paragraph of preview in 2005.

## cyclingflash

`https://cyclingflash.com/` — good, independent, and the second source that
settled two PCS elevation outliers (2001 and 2006 Paris finales).

**Reaching it: use the Claude in Chrome extension.** It serves a Cloudflare
bot-verification interstitial to plain `urllib` and to the in-app browser, but
loads normally in a signed-in Chrome profile. Install the extension, open the
side panel, sign in, and drive it with the `claude-in-chrome` tools. Do not try
to script around the interstitial.

- **Stage page**: `/race/tour-de-france-<year>/stages/stage-<n>`
- **Giro slug is `giro-ditalia-<year>`** — no hyphen before "italia".
- Fields: `Distance`, and `Elevation gain` where it has it.

**Its elevation coverage starts in 2000.** Probed 2026-09-11: 1937, 1954, 1962,
1980, 1990, 1992, 1995 and 1998 return a distance and no elevation; 2000, 2001,
2002, 2004 and 2006 return one. **Every elevation gap in this database is
pre-2000**, so cyclingflash cannot fill any of them — worth knowing before
anyone spends an afternoon on it. It is still the right second opinion for
2000-onward figures that look wrong.

## wikipedia

Used for specific corrected values with a cited article, not bulk import —
`patch_msr_2013_distance.py` (Milan-San Remo 2013, 246 km),
`fix_paris_finale_distances.py`, and the 1933-38 KOM patch.

## letour.fr — the race's own site

`https://www.letour.fr/` — the organiser's site, and therefore the most
authoritative record that exists for the Tour. Already used once, and worth
reaching for whenever PCS has a gap or looks wrong about a Tour result.

**Currently recorded as `manual`, not as its own source**, and the reason is
worth keeping: the history archive at `/en/history` is a JavaScript year
selector, and **the URL does not change when you pick a year**. There is no
per-year page to cite, so `patch_1905_unranked_finishers.py` records what it
found there as `manual` with a prose `source_ref` rather than a link. That
patch is the one row: the 1905 stage-1 finishers PCS holds at rank 999 with no
time, which letour.fr lists as 29 riders sharing 16th at +5h20'00".

**Two ways in:**

- **The year archive** — `/en/history`, driven through the Claude in Chrome
  extension (the selector needs JavaScript; plain `urllib` gets the shell).
  Filters by year, and by data type: rankings, starters, stages, jersey
  wearers, stage winners.
- **The ASO *guide historique*, which IS citable** —
  `https://storage-aso.lequipe.fr/ASO/cycling_tdf/tdf2025-guide-historique.pdf`,
  an 8 MB official PDF, HTTP 200 over plain `curl`. **The URL pattern is not
  general**: the 2024 and 2023 equivalents 404, so find the current link from
  the history page rather than constructing one. This is the better citation
  when a value needs a stable reference.

If letour.fr ever supplies more than a handful of values it should get its own
`SOURCE_LETOUR` constant instead of riding under `manual` — that would make its
rows separable from genuinely hand-entered ones, which is the point of
provenance. Not done, because one row does not justify the migration.

## athlinks

`https://api.athlinks.com/` — public JSON. The timer for the Life Time gravel
and MTB races. Raw responses are cached under `gravel_scrapes/_raw/`.

**It has a malformed location shape**: the country code lands in `region` and
junk in `country`, always with `region: "US "`. Guarded in
`scrape_athlinks.to_row` by testing `region`, never the country value — `SV` is
a real code for El Salvador and Athlinks also uses it correctly.

**What it publishes that is worth reading** (all of it reaches the scrape files;
see ai-context.md's "What the Athlinks data will and will not tell you"):

- `locality` — the rider's home town, and the strongest identity signal in the
  file. It settled Jeff Bradley (Davenport, Iowa on his 7-Eleven road career and
  on all three Chequamegon rides) and Alfred Thresher (Las Vegas on all three
  Leadvilles). Decisive PAIRWISE, on a candidate something else proposed; useless
  in bulk, because riders move house.
- `region` — often the RACE's state rather than the rider's, whenever the
  locality string already carries one. Also spelt both ways, `CO` and `COLORADO`,
  for one rider in different years.
- `bib` — at Leadville a returning rider is seeded with LAST year's finishing
  position as this year's number. Holds for 75% of returning top-100 finishers
  and 8% of those outside 300th, so it is seeding rather than coincidence, and it
  chains a career together across editions.
- `rankings.overall` — stored as `rank_overall`, and different from `stage_rank`,
  which is the men's/division rank. The bib chain needs the overall number.
- `age` — **unreliable at plus or minus 3 to 5 years.** Lachlan Morton's Dirty
  Kanza 2019 row says 19 when he was 27. Athlinks also writes `0` for "not
  recorded" in the older editions. A four-year disagreement between two ids is
  not evidence they are different people; a self-contradiction beyond about six
  years is evidence one id is two people.
- **Series flags glued to the name.** Leadville appends its Leadman marker —
  `(l)` on 40 riders in 2011, `LM` on 71 in 2013, no other year. Stripped by
  `race_common.strip_series_flag()` before the identity key is taken.
- **Tandem entries** — two people on one bib, name fields concatenated, sitting
  in a contiguous bib block. Listed in `tandem_entries.json` and dropped.

## sportmaniacs

`https://sportmaniacs.com/` JSON API. The Traka 2023-2026. Publishes a real
per-edition club, which is captured in the scrape files but deliberately not
ingested.

**No location field of any kind** — nationality and club only. Everything the
athlinks entry above says about home towns applies to the five Life Time races
and not to The Traka.

**It is not automatically beaten by PCS.** For an open mass-start gravel race
PCS lists only the riders it holds road pages for — 21 of The Traka 2023's 291
classified men. `resolve_traka_events.py` now compares what each source would
actually contribute under its own field rule and prefers PCS only on a tie. See
ai-context.md's "The Traka: PCS does not automatically win".

## tretzesports

`https://tretzesports.com/curses3/backend/code/api/` — Klassmark's own timing
for The Traka 2021-2022.

**It writes placeholders into the name field**: `{"Nom": "DORSAL 71 ", "Temps":
"DNS"}`. *Dorsal* is Spanish for bib number. Filtered at ingest by
`ingest_gravel.is_placeholder_name()`, which drops one only when the row also
carries no result.

## derived

Computed here, never fetched — `route_type` from a profile icon, `gap_seconds`
from a winner's time, the cross-race membership bitmask. **Always second-best
to a scrape**, and `scrape_route_overview_elevation.py --replace-derived`
exists to overwrite it when a real figure turns up. The ten reconstructed
2001-2010 Paris finales ran from 48% under to 2.9x over PCS's own numbers,
which is the standing argument against deriving anything.

## manual

Hand-entered, each with a `source_ref` saying why. Thirteen rows. Reserve it
for a value a human established and no fetch can reproduce.

## unknown

Origin unproven. Not a source, a debt — and a deliberately recorded one.

**The count going UP can mean things got better.** It rose from 3,480 to 4,236
on 2026-09-19 in the same pass that PROVED 2,957 elevation values, because
`backfill_provenance.py` also wrote an honest `unknown` for 2,751
`profile_score` values that had had **no row at all**. A field with no
provenance row is invisible; a field with an `unknown` row is on a list. Count
"values with no row" separately from "values recorded as unknown" — the first
is the failure.

**How an `unknown` becomes proven.** Only by matching an artifact, never by
assumption — a wrong `pcs` invites the bulk re-scrape that destroys good
patched values, whereas `unknown` is just a to-do list.

- `backfill_provenance.py` reads the value out of the stage scrape file and
  claims `pcs` only when it MATCHES and the file is gated to that stage by its
  own Distance or Date. `stage_<n>.json` is not a stable key across a split day,
  so the filename is never enough. This proved **2,879** elevation values and
  127 profile scores.
- `scrape_route_overview_elevation.py --verify-unknown` does the same against
  PCS's ROUTE page, for the stages whose stage page carries no figure — mostly
  the Paris/Madrid finales, where PCS serves an empty stage page. **78 more.**
  It records provenance and never writes a stage value.
- `audit_elevation.py` verifies a stored value against the page directly.
- `--upgrade-unknown` (on `backfill_provenance.py`) replaces an `unknown`
  placeholder with a proven source and nothing else. Verified across all
  143,332 rows on 2026-09-19: the only transitions were 231 `unknown -> pcs`
  and 92 `unknown -> derived`, **0 away from a real source**.

**Elevation is now 99.59% proven** — 3,421 `pcs`, 8 `unknown`, 0 with no row,
against 2,964 unproven that morning. The 8 that remain are listed under "Open
items" in `ai-context.md`; seven of them hold a figure that matches **neither**
PCS surface, and the eighth is a cancelled stage.

---

## Adding a source

1. A constant in `race_common.py` and an entry in `VALID_SOURCES`.
2. Every writer calls `record_provenance()` for **every column it writes**.
3. If a patch script writes it, add the name to `PATCH_SOURCES` in
   `race_set_ingest.py` — otherwise the next re-ingest silently reverts it.
4. A row here.
