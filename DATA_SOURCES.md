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

| source | rows | reach it with | good for |
|---|---|---|---|
| [`pcs`](#pcs--procyclingstatscom) | 112,138 | plain HTTP | everything, for every race |
| [`athlinks`](#athlinks) | 17,365 | public JSON API | Life Time gravel/MTB results |
| [`derived`](#derived) | 6,686 | — computed here | never fetched; always second-best |
| [`sportmaniacs`](#sportmaniacs) | 4,695 | JSON API | The Traka 2023-2026 |
| [`bikeraceinfo`](#bikeraceinfo) | 2,046 | plain HTTP | Tour cross-checking, KOM, distances |
| [`tretzesports`](#tretzesports) | 1,147 | JSON API | The Traka 2021-2022 |
| [`manual`](#manual) | 13 | — | hand-entered, with a reason |
| [`wikipedia`](#wikipedia) | 12 | plain HTTP | a specific corrected value |
| [`cyclingflash`](#cyclingflash) | 2 | **Chrome extension only** | elevation, **2000 onward** |
| [`unknown`](#unknown) | 3,480 | — | predates provenance; origin unproven |

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

## athlinks

`https://api.athlinks.com/` — public JSON. The timer for the Life Time gravel
and MTB races. Raw responses are cached under `gravel_scrapes/_raw/`.

**It has a malformed location shape**: the country code lands in `region` and
junk in `country`, always with `region: "US "`. Guarded in
`scrape_athlinks.to_row` by testing `region`, never the country value — `SV` is
a real code for El Salvador and Athlinks also uses it correctly.

## sportmaniacs

`https://sportmaniacs.com/` JSON API. The Traka 2023-2026. Publishes a real
per-edition club, which is captured in the scrape files but deliberately not
ingested.

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

Predates provenance tracking; origin unproven. Not a source, a debt.
`audit_elevation.py` upgrades `unknown` to `pcs` where it can verify the stored
value against the page, which is how this number goes down.

---

## Adding a source

1. A constant in `race_common.py` and an entry in `VALID_SOURCES`.
2. Every writer calls `record_provenance()` for **every column it writes**.
3. If a patch script writes it, add the name to `PATCH_SOURCES` in
   `race_set_ingest.py` — otherwise the next re-ingest silently reverts it.
4. A row here.
