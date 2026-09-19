#!/usr/bin/env python3
"""
Read a stage's stored PCS general-classification page, and only if it is really
that stage's page.

WHY THIS IS A MODULE AND NOT THREE COPIES

Three callers need the same thing — audit_gc_ladders.py to explain a backwards
ladder, backfill_relegations.py to record the marker, ingest_race.py to keep
recording it — and the reading has two traps that each of them would otherwise
have to rediscover.

TRAP 1: OPEN BY source_slug, NEVER BY STAGE NUMBER. The 1978 Tour opens with a
prologue, so its stage 8 is PCS's `stage-7`. Reading `stage-8.json` puts a
different rider on every row, and the values then look wrong when they are
right.

TRAP 2: THE SLUG IS NOT ENOUGH EITHER. The 1992 Giro's twenty gc_pages files
are misnamed — each holds the NEXT stage's page. Comparing our stage N against
`gc_pages/stage-N` there produces a tidy 100% agreement with the WRONG stage,
which on 2026-09-19 was reported as "the 1992 Giro's GC is a stage stale" and
retracted within the hour. Nothing about the file says it is misnamed; the only
way to know is to check.

So every read is GATED on the page's own `result_rows` matching the
`stage_N.json` beside it: same winning rider, same number of finishers. A page
that cannot be matched is returned as None rather than used, because a page we
cannot place is worth less than no page at all.

The gate deliberately does NOT compare the date string. The same stage is dated
"18 July 1926" in one file and "1926-07-18" in the other, and gating on that
rejected a thousand good pages on the first attempt.

WHAT THE ASTERISK IS

PCS prints one on a rider whose PLACE the jury changed while his TIME stood —
"Tim Merlier relegated from 2nd to 89th" on Giro 2024 stage 11, whose page
carries a Penalties & Fines tab saying so. His stored time is then smaller than
that of the riders now ranked above him, so the classification appears to run
backwards. Across every stored GC page, 717 asterisked rows are out of order
and 227,820 unasterisked rows are not: 100% against 0.00%.

We store the rank and the time faithfully and drop the marker, which is what
makes the pair look self-contradictory downstream. This module is how the
marker gets back.
"""

import json
import os
import re

SCRAPE_DIR = {"Tour de France": "tour_scrapes", "Giro d'Italia": "giro_scrapes",
              "Vuelta a España": "vuelta_scrapes"}

HERE = os.path.dirname(os.path.abspath(__file__))

# The repeated unit must contain a colon. The scraper concatenates PCS's visible
# cell with its hidden sort span, so "*0:04" arrives as "*0:040:04" — but
# without the colon requirement a bare "11" reads as "1" doubled, and an
# eleven-second gap silently becomes a one-second one.
_DOUBLED = re.compile(r"\*?((?:\d+:)+\d{2})\1")
_CLOCK = re.compile(r"\d+(?::\d{2})*")


def parse_gap(cell):
    """(seconds, marked) for one PCS gap cell; seconds is None if unreadable.

    `marked` is reported even when the number cannot be read, because the marker
    is the half that explains the row.
    """
    cell = (cell or "").strip()
    marked = cell.startswith("*")
    doubled = _DOUBLED.fullmatch(cell)
    if doubled:
        cell = doubled.group(1)
    cell = cell.lstrip("*+")
    if not _CLOCK.fullmatch(cell):
        return None, marked
    total = 0
    for part in cell.split(":"):
        total = total * 60 + int(part)
    return total, marked


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def page_is_this_stage(page, stage_file):
    """Whether `page` really is the stage `stage_file` describes.

    Compares the two files' own result tables: same winning rider and same
    number of finishers. Both are read from the page rather than from its name,
    which is the whole point — the name is what goes wrong.
    """
    page_rows = (page or {}).get("result_rows") or []
    stage_rows = (stage_file or {}).get("rows") or []
    if not page_rows or not stage_rows:
        return False
    return page_rows[0][6] == stage_rows[0][6] and len(page_rows) == len(stage_rows)


def gc_page(race, year, stage_number, source_slug, root=None):
    """The verified GC page for one stage, or None.

    None covers every reason equally — no file, unreadable, or the page is some
    other stage's — because a caller must treat all three the same way.
    """
    directory = SCRAPE_DIR.get(race)
    if not directory or not source_slug:
        return None
    base = os.path.join(root or HERE, directory, str(year))
    page = _load(os.path.join(base, "gc_pages", f"{source_slug}.json"))
    stage_file = _load(os.path.join(base, f"stage_{stage_number}.json"))
    if page is None or stage_file is None:
        return None
    return page if page_is_this_stage(page, stage_file) else None


def marked_riders(page):
    """Rider ids PCS marks on this page's GC table.

    The leading row is the leader's absolute time, never a marked gap, so it is
    skipped rather than parsed.
    """
    rows = (page or {}).get("gc_rows") or []
    return {r[2] for r in rows[1:] if parse_gap(r[4])[1]}


def gc_ladder(page):
    """{rider_id: (rank, seconds, marked)} from a verified page."""
    rows = (page or {}).get("gc_rows") or []
    out = {}
    for i, r in enumerate(rows):
        seconds, marked = (0, False) if i == 0 else parse_gap(r[4])
        out[r[2]] = (int(r[0]), seconds, marked)
    return out
