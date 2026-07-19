#!/usr/bin/env python3
"""
Shared constants and PCS stage-result parsing helpers for the Giro/Vuelta
ingest pipeline.

Both races' scrape files come from the same PCS result-table structure, so
the parsing logic here is identical across races — only race identity (DB
name/country, scrape directory, legacy layout quirks) differs. That
per-race identity lives in RACES below; ingest_race.py is the only script
that should need to branch on race name.
"""

import os
import re
from dataclasses import dataclass

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
