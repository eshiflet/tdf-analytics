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

import os
import re
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
