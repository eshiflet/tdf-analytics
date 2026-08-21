#!/usr/bin/env python3
"""
Shared constants and helpers for the multi-race pipeline.

Three independent groups live here:

  - StageRow, the canonical schema for a single rider's row from a scraped
    stage-results table. All three races' ingest paths (add_pre1960.py for
    TDF, ingest_race.py for Giro/Vuelta) and the swap-detection/fix tools
    (detect_name_swaps.py, fix_2026_name_swaps.py) parse rows through this
    one type instead of indexing raw lists by position — see its docstring.

  - PCS stage-result parsing helpers + the ingest-only RACES registry
    (Giro/Vuelta only — TDF's ingest mechanism, add_pre1960.py/add_stages.py,
    predates this and has its own file discovery/DB logic). Used by
    ingest_race.py.

  - resolve_race_arg(), for the export scripts that cover all three races
    (export_riders_index.py, export_race_summary.py). TDF/Giro/Vuelta share
    an export format but TDF's scrape/ingest pipeline predates and differs
    from the other two, so it has no entry in the ingest-only RACES below.
"""

import json
import os
import re
import sys
from dataclasses import dataclass


STAGE_ROW_LEN = 15


@dataclass
class StageRow:
    """
    One rider's row from a scraped stage-results table, in the canonical
    field order produced by EXTRACT_RESULTS in scrape_stage_template.js:

      [rnk, gc_pos, gc_lag, bib, age, name, slug, nat, team, team_slug,
       uci_pts, pcs_pts, bonus, abs_time, gap]

    All fields are raw strings exactly as scraped (a row may represent a
    non-finisher, e.g. rnk="DNF"); use parse_int/parse_time_to_seconds/
    parse_bonus_seconds below to convert. Keep this field order in sync with
    the JS template if the extraction format ever changes — both sides
    reference each other in their docstrings so a mismatch is easy to spot.
    """
    rnk: str
    gc_pos: str
    gc_lag: str
    bib: str
    age: str
    name: str
    slug: str
    nat: str
    team: str
    team_slug: str
    uci_pts: str
    pcs_pts: str
    bonus: str
    abs_time: str
    gap: str

    @classmethod
    def from_list(cls, row: list) -> "StageRow":
        if len(row) != STAGE_ROW_LEN:
            raise ValueError(
                f"stage row must have exactly {STAGE_ROW_LEN} fields, got {len(row)}: {row!r}"
            )
        return cls(*row)

    def to_list(self) -> list:
        return [self.rnk, self.gc_pos, self.gc_lag, self.bib, self.age, self.name,
                self.slug, self.nat, self.team, self.team_slug, self.uci_pts,
                self.pcs_pts, self.bonus, self.abs_time, self.gap]


def swap_identity(row_a: list, row_b: list) -> None:
    """
    Swap name/slug/nat — the three fields a PCS table-extraction artifact
    commonly transposes between two adjacent rows — between row_a and row_b
    in place. bib/age/team/gc/time fields are left untouched, since those
    have consistently stayed correctly tied to the row in every swap found
    so far (see detect_name_swaps.py).
    """
    sr_a, sr_b = StageRow.from_list(row_a), StageRow.from_list(row_b)
    row_a[5], row_b[5] = sr_b.name, sr_a.name
    row_a[6], row_b[6] = sr_b.slug, sr_a.slug
    row_a[7], row_b[7] = sr_b.nat, sr_a.nat


HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")

STAGE_NOTES_PATH = os.path.join(HERE, "stage_notes.json")


def load_stage_notes(path=STAGE_NOTES_PATH):
    """
    stage_notes.json as {(race_name, year, stage_number): entry}.

    Records why a stage has no results in the cases where that absence is
    permanent and correct. A cancelled stage with zero results is byte-for-byte
    indistinguishable from a stage nobody has scraped yet, so without this the
    same handful get re-investigated every time someone audits the DB — Giro
    2011's stage 4, ridden as a processional tribute to Wouter Weylandt with no
    classification taken, has no result to find and never will.

    Lives outside the DB on purpose: ingest_race.py deletes and re-inserts a
    whole edition, and only a fixed tuple of columns survives that. A note in a
    stages column would be wiped by the next re-ingest with nothing to warn
    that it had gone.

    Keys use the DB's contiguous stage_number, NOT the PCS slug — the two
    diverge after any split day. The slug is carried in the entry for
    cross-checking, never for rebuilding a URL.
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {
        (race, int(year), int(stage)): entry
        for race, years in raw.items() if not race.startswith("_")
        for year, stages in years.items()
        for stage, entry in stages.items()
    }


ICON_TO_ROUTE = {"p1": "F", "p2": "H", "p3": "H", "p4": "M", "p5": "M"}

COUNTRY_NAMES = {
    "fr": "France", "nl": "Netherlands", "be": "Belgium", "si": "Slovenia",
    "es": "Spain", "dk": "Denmark", "it": "Italy", "gb": "Great Britain",
    "co": "Colombia", "au": "Australia", "ca": "Canada", "us": "United States",
    "no": "Norway", "za": "South Africa", "pt": "Portugal", "lv": "Latvia",
    "ru": "Russia", "pl": "Poland", "ec": "Ecuador", "de": "Germany",
    "lu": "Luxembourg", "ch": "Switzerland", "kz": "Kazakhstan", "ie": "Ireland",
    "at": "Austria", "cz": "Czech Republic", "er": "Eritrea", "mc": "Monaco",
    "ar": "Argentina", "br": "Brazil", "by": "Belarus", "cn": "China",
    "cr": "Costa Rica", "dz": "Algeria", "ee": "Estonia", "et": "Ethiopia",
    "fi": "Finland", "hr": "Croatia", "hu": "Hungary", "il": "Israel",
    "jp": "Japan", "li": "Liechtenstein", "lt": "Lithuania", "ma": "Morocco",
    "md": "Moldova", "mx": "Mexico", "nz": "New Zealand", "ro": "Romania",
    "se": "Sweden", "sk": "Slovakia", "tn": "Tunisia", "ua": "Ukraine",
    "uz": "Uzbekistan", "ve": "Venezuela", "cl": "Chile", "uy": "Uruguay",
    "bg": "Bulgaria", "mt": "Malta",
}

# Stage-file layout predates the per-year-subdir convention for this one
# year; only Giro's 2026 scrape used the old flat pipeline/giro_scrapes/
# layout instead of pipeline/giro_scrapes/2026/.
FLAT_FALLBACK_YEAR = 2026


@dataclass(frozen=True)
class RaceInfo:
    name: str               # DB races.name / edition_name, e.g. "Giro d'Italia"
    country: str
    scrapes_dirname: str    # pipeline/<scrapes_dirname>/YEAR/stage_N.json
    flat_2026_fallback: bool  # legacy flat-layout fallback for FLAT_FALLBACK_YEAR


RACES: dict[str, RaceInfo] = {
    "giro": RaceInfo(
        name="Giro d'Italia", country="Italy",
        scrapes_dirname="giro_scrapes", flat_2026_fallback=True,
    ),
    "vuelta": RaceInfo(
        name="Vuelta a España", country="Spain",
        scrapes_dirname="vuelta_scrapes", flat_2026_fallback=False,
    ),
}


@dataclass(frozen=True)
class ClassicInfo:
    name: str        # DB races.name / frontend stage_label, e.g. "Paris-Roubaix"
    short: str       # x-axis tick label, e.g. "PR"
    country: str


# The one-day classics, keyed by their PCS URL slug. These are 11 INDEPENDENT
# races in the DB (races.race_type = 'one_day', one stage per edition); the
# frontend's single "One-day Classics" race is an aggregation built at export
# time by export_classics.py, ordered by each race's actual date so a
# reshuffled season (2020: Lombardia in August) comes out right.
#
# Slugs are PCS's, not guessable: San Sebastian is `san-sebastian`, NOT
# `clasica-san-sebastian` — the latter 500s, and a 500 page looks exactly like
# a cancelled race to a parser, which silently invented six cancellations
# before this was caught. Verify a slug against a real URL before adding one.
CLASSICS: dict[str, ClassicInfo] = {
    "omloop-het-nieuwsblad": ClassicInfo("Omloop Het Nieuwsblad", "OHN", "Belgium"),
    "strade-bianche":        ClassicInfo("Strade Bianche", "SB", "Italy"),
    "milano-sanremo":        ClassicInfo("Milan-San Remo", "MSR", "Italy"),
    "gent-wevelgem":         ClassicInfo("Gent-Wevelgem", "GW", "Belgium"),
    "ronde-van-vlaanderen":  ClassicInfo("Tour of Flanders", "RVV", "Belgium"),
    "paris-roubaix":         ClassicInfo("Paris-Roubaix", "PR", "France"),
    "amstel-gold-race":      ClassicInfo("Amstel Gold Race", "AGR", "Netherlands"),
    "la-fleche-wallonne":    ClassicInfo("La Fleche Wallonne", "FW", "Belgium"),
    "liege-bastogne-liege":  ClassicInfo("Liege-Bastogne-Liege", "LBL", "Belgium"),
    "san-sebastian":         ClassicInfo("Clasica de San Sebastian", "CSS", "Spain"),
    "il-lombardia":          ClassicInfo("Il Lombardia", "IL", "Italy"),
}


@dataclass(frozen=True)
class GravelInfo:
    name: str          # DB races.name / frontend stage_label, e.g. "Unbound Gravel"
    short: str         # x-axis tick label, e.g. "UB"
    country: str
    master_id: int     # Athlinks masterEventId — the race's whole edition list
    discipline: str    # 'gravel' | 'mtb'; drives route_type, see gravel_route_type


# The six Life Time off-road races, keyed by a slug of our own (Athlinks has no
# stable text slug — it addresses everything by numeric id). These are six
# INDEPENDENT races in the DB (races.race_type = 'gravel', one stage per
# edition); the frontend's single "Gravel & MTB" race is an aggregation built
# at export time by export_gravel.py, ordered by each race's actual date. Same
# shape as the one-day classics, for the same reason.
#
# The six are today's Life Time Grand Prix line-up, but the archive here is
# deliberately WIDER than that series: Leadville has run since 1994 and
# Chequamegon since 1983, and those editions are the point. A season before
# 2021 therefore holds fewer than six races, exactly as a classics season
# before 1907 holds fewer than eleven.
GRAVEL: dict[str, GravelInfo] = {
    "sea-otter":    GravelInfo("Sea Otter Classic", "SO", "United States", 36141, "mtb"),
    "unbound":      GravelInfo("Unbound Gravel", "UB", "United States", 174195, "gravel"),
    "leadville":    GravelInfo("Leadville Trail 100 MTB", "LV", "United States", 219291, "mtb"),
    "chequamegon":  GravelInfo("Chequamegon MTB Festival", "CQ", "United States", 32709, "mtb"),
    "little-sugar": GravelInfo("Little Sugar MTB", "LS", "United States", 381583, "mtb"),
    "big-sugar":    GravelInfo("Big Sugar Gravel", "BS", "United States", 359937, "gravel"),
}


def gravel_route_type(discipline):
    """'G' (gravel) or 'X' (mountain bike) for an off-road race.

    The Grand Tours and classics carry F/H/M here — a climbing grade derived
    from PCS's ProfileScore. Athlinks publishes no elevation at all and PCS
    does not cover these races (verified: searching PCS for "unbound" returns
    nothing while "gravel" returns plenty), so there is no honest way to grade
    them by climbing. Surface is the property that actually distinguishes
    these races from everything else in the app, and the Race Overview colours
    its bars off this field — leaving it NULL would paint Unbound flat green,
    which is a claim, not a gap. Two new codes, no pretend gradient.
    """
    return {"gravel": "G", "mtb": "X"}.get(discipline)


def classic_route_type(profile_score):
    """F/H/M for a one-day race, from PCS's own ProfileScore.

    The Race Overview colours its bars by route_type, and a NULL falls back to
    Flat green — which would paint Liege-Bastogne-Liege the same as Roubaix.
    ProfileScore is PCS's grade-aware climbing metric, so it separates these
    honestly (Roubaix 15, Gent-Wevelgem 33, Flanders 93, Liege 182,
    Lombardia 260) where raw m/km does not. Derived, not scraped — record it
    as SOURCE_DERIVED.
    """
    if profile_score is None:
        return None
    if profile_score < 60:
        return "F"
    if profile_score <= 150:
        return "H"
    return "M"


def parse_time_to_seconds(text):
    if not text:
        return None
    t = text.strip().lstrip("+").lstrip("*")
    if t in ("", ",,", ",", "-"):
        return None
    if not re.match(r"^\d+:\d{2}(:\d{2})?$", t):
        return None
    parts = [int(p) for p in t.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_bonus_seconds(text):
    if not text:
        return 0
    m = re.match(r"^(-?\d+)", str(text).strip().replace("″", "").replace("″", ""))
    return int(m.group(1)) if m else 0


def parse_int(text):
    if text is None:
        return None
    t = str(text).strip()
    return int(t) if re.match(r"^-?\d+$", t) else None


def detect_route_type(icon: str, won_how: str) -> str:
    wh = (won_how or "").lower()
    if "team time trial" in wh or "ttt" in wh:
        return "TTT"
    if "time trial" in wh:
        return "TT"
    return ICON_TO_ROUTE.get(icon or "p1", "F")


_TITLE_LINE_RE = re.compile(r'title-line2[^>]*>(.*?)</div>', re.S)
_TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.S)
_TITLE_KM_RE = re.compile(r"\(([\d.,]+)\s*km\)")
_TITLE_TT_RE = re.compile(r"\((ITT|TTT)\)")


def parse_stage_title(html: str) -> dict:
    """Read PCS's stage headline, which carries facts the info panel omits.

        <div class="title-line2 ...">
          <font class="blue">Stage 23 (ITT) (Final)</font> » <font class="red">Versailles › Paris</font>
          <font class="red">(54km)</font>
        </div>

    Two things live here and nowhere else on the page:

    * The DISTANCE, even when the info panel prints "Distance: 0 km". PCS does
      that for a long tail of older stages — the 1969 and 1970 Tour finales
      both read 0 km in the panel while the headline says 37km and 54km.
    * An explicit **(ITT)** or **(TTT)** marker. "Won how" is empty on old
      stages, so detect_route_type falls back to flat and decisive time trials
      end up stored as road stages.

    Returns {'label', 'distance_km', 'tt_kind'}; any key may be None. The
    marker also appears in <title> ("Tour de France 1970 Stage 23 (ITT)
    results"), so both are checked.

    The distance is NOT infallible — PCS's 1986 Tour stage-23 headline repeats
    stage 16's 246.5 km instead of the finale's 255 km. Treat it as a source to
    reconcile, not a value to trust blindly; see backfill_stage_titles.py for
    the duplicate guard.
    """
    m = _TITLE_LINE_RE.search(html or "")
    line = ""
    if m:
        line = " ".join(re.sub(r"<[^>]+>", " ", m.group(1))
                        .replace("&nbsp;", " ").split())
    tag = _TITLE_TAG_RE.search(html or "")
    km = _TITLE_KM_RE.search(line)
    tt = _TITLE_TT_RE.search(f"{tag.group(1) if tag else ''} {line}")
    distance = None
    if km:
        try:
            distance = float(km.group(1).replace(",", ""))
        except ValueError:
            distance = None
    return {
        "label": line.split("&raquo;")[0].split("»")[0].strip() or None,
        "distance_km": distance if distance else None,
        "tt_kind": tt.group(1) if tt else None,
    }


def gap_violations(pairs) -> int:
    """How many finishers sit at zero gap BEHIND a rider who lost time.

    `pairs` is an iterable of (rank, gap_seconds); rank may be a string or int,
    gap may be None. Only numeric ranks count — a DNF has no place in the
    finishing order.

    A finishing order's gaps never decrease: once a rider is 1:02 down, nobody
    behind him is level with the winner. A gap that drops back to zero is PCS's
    ditto mark — it prints ",," for "same as the rider above" — read as no gap
    at all. 1,500 stages carry that damage, on some of them 189 riders of 198.

    Rank 1 is skipped on purpose. PCS renders the winner's time and gap in a
    single cell, so his gap field repeats his own finishing time; counting it
    would make `peak` enormous and every later zero look like a violation. That
    mistake inflated a first count of this from 97 stages to 1,055.
    """
    peak = 0
    bad = 0
    for rank, gap in pairs:
        r = str(rank).strip()
        if not r.isdigit() or r == "1" or gap is None:
            continue
        if gap > peak:
            peak = gap
        elif peak > 0 and gap == 0:
            bad += 1
    return bad


def row_gap_violations(rows) -> int:
    """gap_violations for scrape rows in StageRow order."""
    return gap_violations(
        (r[0], parse_time_to_seconds(r[14]))
        for r in rows if len(r) == STAGE_ROW_LEN)


def apply_stage_title(info: dict, html: str) -> dict:
    """Fill an info dict's gaps from the stage headline. Mutates and returns it.

    Only fills what the info panel failed to give: a distance it reported as
    0 km or omitted, and a TT marker when "Won how" is empty. A real scraped
    value always wins — the headline is the fallback, not the override.
    """
    title = parse_stage_title(html)
    have_km = 0.0
    m = re.match(r"([\d.]+)", str(info.get("Distance") or ""))
    if m:
        have_km = float(m.group(1))
    if title["distance_km"] and not have_km:
        info["Distance"] = f"{title['distance_km']} km"
        info["DistanceSource"] = "pcs-title"
    if title["tt_kind"] and not (info.get("Won how") or "").strip(" -"):
        info["TitleTT"] = title["tt_kind"]
    return info


def parse_year_args(args: list[str]) -> list[int]:
    years = []
    for a in args:
        if a.startswith("-"):
            continue
        if "-" in a and not a.startswith("-"):
            parts = a.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                years.extend(range(int(parts[0]), int(parts[1]) + 1))
                continue
        if a.isdigit():
            years.append(int(a))
    return sorted(set(years))


# ── Export-script race resolution (TDF + Giro + Vuelta) ─────────────────────
# Matches export_gc.py's own inline convention: --race {tdf,giro,vuelta},
# defaulting to tdf. race_subdir is both the src/data/<slug> directory name
# and the frontend's RaceId; race_arg "tdf" is historical (predates the
# tour/giro/vuelta slug scheme) and maps to subdir "tour".
EXPORT_RACE_INFO = {
    "tdf": ("Tour de France", "tour"),
    "giro": ("Giro d'Italia", "giro"),
    "vuelta": ("Vuelta a España", "vuelta"),
}


def resolve_race_arg(argv: list[str]) -> tuple[str, str]:
    """Reads --race from argv (default 'tdf'). Returns (db_name, data_subdir)."""
    race_arg = "tdf"
    if "--race" in argv:
        race_arg = argv[argv.index("--race") + 1]
    if race_arg not in EXPORT_RACE_INFO:
        raise SystemExit(f"error: unknown race '{race_arg}' (use 'tdf', 'giro', or 'vuelta')")
    return EXPORT_RACE_INFO[race_arg]


# ── PCS slug ↔ DB stage-number mapping ──────────────────────────────────────
# PCS identifies a stage by a URL slug ("stage-3", or "stage-3a"/"stage-3b"
# for a split day where two stages were raced on the same date). The DB needs
# a single contiguous INTEGER stage_number (UNIQUE per edition), so a split
# day consumes two numbers: stage-3a -> 3, stage-3b -> 4, stage-4 -> 5.
#
# Deriving the DB number from the slug's digits alone is WRONG for any edition
# with a split (both halves parse to the same number and collide — the second
# silently overwrote the first for 68 Vuelta and 111 TDF split-days). Deriving
# it from list position alone is also wrong: discover_stages() drops any stage
# whose probe fails, and positional numbering would then shift every later
# stage down one, silently mislabeling them.
#
# assign_stage_numbers() does both safely: it numbers by position (so splits
# work) but first verifies the slug sequence is complete and well-ordered, so
# a dropped stage is a loud abort instead of a silent shift.

_SLUG_RE = re.compile(r"^stage-(\d+)([a-d]?)$")


def assign_stage_numbers(slugs: list[str]) -> tuple[list[tuple[int, str]], str | None]:
    """Map an ordered list of PCS slugs to sequential DB stage numbers.

    Returns (pairs, error). On success pairs is [(db_stage_number, slug), ...]
    and error is None. On any gap/ordering problem pairs is [] and error is a
    human-readable reason — callers must abort rather than write partial data,
    since every downstream join keys off stage_number.
    """
    parsed = []
    has_prologue = False
    for i, slug in enumerate(slugs):
        # A prologue is slugged 'prologue' (not 'stage-0') and must come first.
        # It takes DB stage_number 0 without consuming a numbered slot.
        if slug == "prologue":
            if i != 0:
                return [], "'prologue' appears after another stage"
            has_prologue = True
            continue
        m = _SLUG_RE.match(slug)
        if not m:
            return [], f"unparseable stage slug {slug!r}"
        parsed.append((int(m.group(1)), m.group(2), slug))

    expected = 1          # next whole PCS stage number we require
    prev_letter = ""
    prev_num = None
    for num, letter, slug in parsed:
        if letter in ("", "a"):
            if num != expected:
                return [], (
                    f"stage sequence gap: expected stage-{expected}, found {slug!r}. "
                    "A stage is missing from discovery — re-run rather than "
                    "renumbering, or every later stage will be mislabeled."
                )
            expected = num + 1
        else:
            # 'b'/'c'/'d' must continue the sub-stage sequence of the same number
            if prev_num != num or prev_letter not in ("a", "b", "c"):
                return [], f"orphaned sub-stage {slug!r} (no preceding stage-{num}a)"
            if ord(letter) != ord(prev_letter) + 1:
                return [], f"sub-stage out of order: {slug!r} follows stage-{num}{prev_letter}"
        prev_num, prev_letter = num, letter

    numbered = [(i + 1, slug) for i, (_, _, slug) in enumerate(parsed)]
    if has_prologue:
        numbered.insert(0, (0, "prologue"))
    return numbered, None


# ── Data provenance ─────────────────────────────────────────────────────────
# Every write of a stored value should say where the value came from. See the
# data_provenance table in schema.sql for the granularity rule (per-field on
# stages; one 'results' row per stage covering all its stage_results).
#
# Why this exists: several corruption bugs were slow to diagnose because the DB
# could not say where a number originated — Vuelta 1990's vertical_meters was
# correct while its profile_score was shifted by one, and TDF split years have
# PCS elevation partly overwritten by later Wikipedia backfills, which is why
# those still can't be safely bulk re-scraped.
#
# Honesty rule: never guess a source. If it isn't known, record SOURCE_UNKNOWN
# (or leave no row) rather than assuming — a confidently wrong provenance is
# worse than an admitted gap, because it invites exactly the bulk re-scrape
# that would destroy good patched values.

SOURCE_PCS = "pcs"              # scraped from procyclingstats.com
SOURCE_WIKIPEDIA = "wikipedia"  # from a Wikipedia route/results table
SOURCE_BIKERACEINFO = "bikeraceinfo"  # from bikeraceinfo.com (patch_bri_distances.py)
SOURCE_CYCLINGFLASH = "cyclingflash"  # from cyclingflash.com; relayed by the repo
                                # owner, since Cloudflare blocks automated fetches
SOURCE_ATHLINKS = "athlinks"    # from the public Athlinks results API; Life Time
                                # owns Athlinks, so for its own off-road races
                                # this is the timer's own data, not an aggregator
SOURCE_MANUAL = "manual"        # hand-entered or hand-corrected
SOURCE_DERIVED = "derived"      # computed from other DB values, not fetched
SOURCE_UNKNOWN = "unknown"      # predates provenance tracking; origin unproven

VALID_SOURCES = frozenset({
    SOURCE_PCS, SOURCE_WIKIPEDIA, SOURCE_BIKERACEINFO, SOURCE_CYCLINGFLASH,
    SOURCE_ATHLINKS, SOURCE_MANUAL, SOURCE_DERIVED, SOURCE_UNKNOWN,
})


def record_provenance(cur, entity, entity_id, field, source,
                      source_ref=None, script=None):
    """Record where one stored value came from. Upserts; last writer wins.

    `cur` is a live sqlite3 cursor — provenance is written in the same
    transaction as the value it describes, so the two can't drift apart.
    """
    if source not in VALID_SOURCES:
        raise ValueError(
            f"unknown provenance source {source!r}; expected one of "
            f"{sorted(VALID_SOURCES)}"
        )
    from datetime import datetime, timezone
    if script is None:
        script = os.path.basename(sys.argv[0]) or None
    cur.execute(
        """INSERT INTO data_provenance
             (entity, entity_id, field, source, source_ref, script, recorded_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(entity, entity_id, field) DO UPDATE SET
             source=excluded.source, source_ref=excluded.source_ref,
             script=excluded.script, recorded_at=excluded.recorded_at""",
        (entity, entity_id, field, source, source_ref, script,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )


def record_provenance_bulk(cur, entity, entity_id, fields, source,
                           source_ref=None, script=None):
    """record_provenance() for several fields of one row sharing a source."""
    for field in fields:
        record_provenance(cur, entity, entity_id, field, source,
                          source_ref=source_ref, script=script)


# ── Team time trial results ─────────────────────────────────────────────────
# Lives here rather than in one scraper because all three races run TTTs and
# all three scrapers were missing it. See parse_ttt_rows.

_TTT_LIST_RE = re.compile(r'<ul class="list ttt-results">(.*?)</ul>', re.S)
_TTT_TEAM_RE = re.compile(r'href="(team/[^"]+)"[^>]*>(.*?)</a>', re.S)
_TTT_RANK_RE = re.compile(r'<div class="w10 fs14">\s*(\d+)\s*</div>')
_TTT_TIME_RE = re.compile(r'<div[^>]*\btime\b[^>]*>\s*([\d:]+)\s*</div>')
_TTT_GAP_RE = re.compile(r'</div>\s*<div class="w25 fs14">\s*([+\d:]+)\s*</div>')
_TTT_RIDER_RE = re.compile(
    r'<span class="flag (\w+)"></span>\s*<a[^>]*href="(rider/[^"]+)"[^>]*>(.*?)</a>', re.S)


def _strip_tags(html: str) -> str:
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&amp;", "&").replace("&#160;", " ").replace("&nbsp;", " ")
    return " ".join(t.split())


def parse_ttt_rows(html: str) -> list[list]:
    """Rows for a TEAM time trial, whose results are grouped by team.

    A TTT page is shaped completely differently from an ordinary stage. Instead
    of one <tr> per rider, PCS emits

        <ul class="list ttt-results">
          <li> <div>rank</div> <a href="team/...">Team</a>
               <div class="time">42:49</div> <div>+0:00</div>
               <table> <tr><a href="rider/...">Name</a></tr> ... </table>
          </li>

    with the per-rider time cells EMPTY: every rider takes the team's time and
    the team's placing, which is how a TTT works.

    The ordinary find_results_table/parse_rows pair finds essentially nothing
    here — and, worse, returns ONE stray row rather than none, so the stage
    lands in the DB looking populated. 47 stages across all three races held a
    handful of results instead of a full field that way (~3,568 results),
    including Vuelta 2015's opening TTT, which stored 1 result for a 175-rider
    field, and Vuelta 1989 stage 3a.

    Returns rows in the canonical StageRow order so nothing downstream needs a
    special case. bib/age/GC are blank — the TTT view does not carry them.
    """
    m = _TTT_LIST_RE.search(html)
    if not m:
        return []

    rows = []
    for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.S):
        team_m = _TTT_TEAM_RE.search(li)
        if not team_m:
            continue                      # the header <li> carries no team link
        team_slug, team_name = team_m.group(1), _strip_tags(team_m.group(2))

        rank_m, time_m, gap_m = (_TTT_RANK_RE.search(li), _TTT_TIME_RE.search(li),
                                 _TTT_GAP_RE.search(li))
        rank = rank_m.group(1) if rank_m else ""
        team_time = time_m.group(1) if time_m else ""
        team_gap = gap_m.group(1) if gap_m else ""

        for nat, slug, name_html in _TTT_RIDER_RE.findall(li):
            rows.append([
                rank, "", "", "", "",
                _strip_tags(name_html), slug, nat,
                team_name, team_slug,
                "", "", "", team_time, team_gap,
            ])
    return rows
