#!/usr/bin/env python3
"""
Read a stage's stored PCS general-classification page, and only if it is really
that stage's page.

WHY THIS IS A MODULE AND NOT THREE COPIES

Three callers need the same thing — audit_gc_ladders.py to explain a backwards
ladder, backfill_time_adjusted.py to record the marker, ingest_race.py to keep
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

PCS prints one on a rider whose recorded time was AWARDED rather than raced. A
rider caught behind a crash inside the final kilometres is credited with his
group's time while keeping the place he actually finished in -- Primoz Roglic
is 34th on the road at Vuelta 2022 stage 16 with a gap of 0 -- so his time no
longer places him where he stands. Whole groups get it at once: 28 riders share
one stage time on Tour 1996 stage 7.

IT IS NOT A RELEGATION. That was the first reading, taken from a Penalties &
Fines tab on the same page, and it is wrong: on Giro 2024 stage 11 the rider
PCS itself names as relegated (Tim Merlier) carries NO marker, while four
sprinters around him do. PCS does not publish what each mark means, so nothing
here claims a reason -- only that the mark is present.

What the mark reliably identifies is the SHAPE, and in one direction only:
across every stored GC page, all 332 backwards steps sit on marked rows and
NONE of the 227,820 unmarked rows is out of order. The converse is false — 385
of the 717 marked rows are in order, because an awarded time need not land out
of sequence. So the mark is NECESSARY for a backwards step, not sufficient,
which is exactly what an exemption needs. (First measured as "100% against
0.00%" by carrying a running maximum down the ladder, which let one corrupt
cell — Tour 1996 st21 rank 43 reads "743:02:43" — condemn all 86 rows below
it. Compare each row with the one directly above it, never with a maximum.)
We store the rank and the time faithfully and drop the marker,
which is what makes the pair look self-contradictory downstream. This module is
how the marker gets back.
"""

import json
import os
import re

SCRAPE_DIR = {"Tour de France": "tour_scrapes", "Giro d'Italia": "giro_scrapes",
              "Vuelta a España": "vuelta_scrapes"}

# classification_scrapes stores one HTML page per stage, named for OUR stage
# number. Used only for the marker; nothing is parsed out of it for values.
PAGE_SLUG = {"Tour de France": "tour_de_france", "Giro d'Italia": "giro_d_italia",
             "Vuelta a España": "vuelta_a_espana"}

# The only tabs on such a page whose column is a TIME. Marks appear in STAGE
# (226), YOUTH (112), GC (84) and TEAMS (8) and NEVER in POINTS or KOM, whose
# columns are points — which is the clearest evidence available that the
# asterisk annotates a time. TEAMS is excluded because its time belongs to a
# team rather than a rider, and YOUTH because it is the same classification
# time as GC filtered to young riders, so a mark there is already in GC.
TIMED_TABS = ("STAGE", "GC")

HERE = os.path.dirname(os.path.abspath(__file__))

# The repeated unit must contain a colon. The scraper concatenates PCS's visible
# cell with its hidden sort span, so "*0:04" arrives as "*0:040:04" — but
# without the colon requirement a bare "11" reads as "1" doubled, and an
# eleven-second gap silently becomes a one-second one.
_DOUBLED = re.compile(r"\*?((?:\d+:)+\d{2})\1")
_CLOCK = re.compile(r"\d+(?::\d{2})*")
_ROW = re.compile(r"<tr\b.*?</tr>", re.S)
_RIDER = re.compile(r'href="(rider/[^"]+)"')


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


# The stage result table carries the same asterisk in its own gap cell, and it
# is the same fact about the same (stage, rider) row — the time was awarded
# rather than raced — so it sets the same flag rather than a second one. It is
# the cell that describes a rider credited with his group's time after a crash
# while keeping the place he finished in.
#
# The signal is strong but not the GC's clean sweep: 77 of 78 marked rows are
# out of order against 0.8% of unmarked ones. Measuring that needs PCS's
# "+0:00" filler excluded first — a non-winner whose cell reads +0:00 has no
# published time at all (see ai-context, "Times that no race produced"), and
# counting those as zero gaps invents 40,349 backwards steps out of nothing.
#
# COVERAGE IS A FLOOR, NOT A CEILING, and which scraper wrote a file decides
# it. Primoz Roglic at Vuelta 2022 stage 16 is the textbook case — 34th on the
# road with a gap of 0 — and he is NOT flagged, because that year has no
# gc_pages file and his row in stage_16.json carries a bare "+0:00". His mark
# survives only in classification_scrapes HTML, which holds 1,022 more marked
# rows we could claim. They are deliberately not read: a page there stacks the
# stage, GC, points, KOM and youth tables in `resTab` divs keyed by opaque
# numeric ids, and a mark in the points table says nothing about the GC time.
# Mis-scoping it would SUPPRESS real contradictions, which is the opposite of
# what this flag is for. Scope the tables first, or leave it.
STAGE_GAP_FIELD = 14


def marked_in_stage_rows(rows):
    """Rider ids the stage result table marks, from a stage file's own rows."""
    out = set()
    for r in rows or []:
        if len(r) > STAGE_GAP_FIELD and parse_gap(r[STAGE_GAP_FIELD])[1]:
            out.add(r[6])
    return out


def gc_gaps(page):
    """{rider_id: gap_seconds} from a verified page, or None if it lists TIMES.

    THE COLUMN IS NOT ALWAYS GAPS. Normally the leading row carries the
    leader's absolute time and every row below it a gap to him:

        ['36:35:42', '0:22', '0:41', ...]     Tour 1978, stage-7

    But where PCS has no time for the leader it prints its "-0:00" filler in
    his cell and ABSOLUTE times in everyone else's:

        ['-0:00', '49:18:15', '49:19:08', ...]  Tour 2006, stage-11

    Reading that as gaps offers 164 rows of ~49 HOURS to write into a gap
    column, and they look ordinary next to the genuine multi-hour gaps of the
    1910s. Two guards, because either alone lets it through: the leader's cell
    must be a real elapsed time rather than the filler, and no gap may reach
    it — a rider cannot be further behind the leader than the leader has been
    racing. A page that fails either is refused whole rather than filtered,
    since a column that is not what it claims cannot be trusted row by row.
    """
    return gc_gaps_with_reason(page)[0]


def gc_gaps_with_reason(page):
    """(gaps, reason) — reason names why, when gaps is None.

    The reasons are kept apart because they are not the same news. "too few
    rows" is an empty page and says nothing about the archive; "absolute times"
    is a page whose column means something other than it appears to, and a
    caller reporting both as one number would claim 1,355 pages were the
    dangerous kind when 54 are.
    """
    rows = (page or {}).get("gc_rows") or []
    if len(rows) < 2:
        return None, "too few rows"
    leader, _marked = parse_gap(rows[0][4])
    if not leader:
        # PCS's "-0:00" filler in the leader's cell: it has no time for him,
        # and prints absolute times below rather than gaps.
        return None, "absolute times"
    out = {rows[0][2]: 0}
    for r in rows[1:]:
        seconds, _m = parse_gap(r[4])
        if seconds is None:
            continue
        if seconds >= leader:
            return None, "absolute times"
        out[r[2]] = seconds
    return out, None


def marked_in_classification_html(race, year, stage_number, stage_rows, root=None):
    """Rider ids the stored HTML page marks, from its STAGE and GC tables.

    A THIRD artifact family, and it needs its own gate for the same reason the
    others do: 167 of the 1,023 files are NOT the stage their name claims —
    Giro 1935-1937 among them, where our numbering expands PCS's split days and
    theirs does not. The gate is the STAGE tab's own first rider and row count
    against `stage_rows`, which is the stage file the ingest already trusts.

    Scoped by TAB, never by position. scrape_classifications.tab_blocks() keys
    each table by the page's own nav, and without it a mark cannot be attributed
    to a table at all: this is the trap that produced a wrong bug report about
    Carretero, and a struck rank in the POINTS table says nothing about a time.
    """
    # No separate "did we get stage rows" test: an empty list cannot match the
    # page's row count, so the gate below already refuses it. Stating it twice
    # would be a condition no input can reach.
    slug = PAGE_SLUG.get(race)
    if not slug:
        return set()
    path = os.path.join(root or HERE, "classification_scrapes",
                        f"race_{slug}_{year}_stage_{stage_number}.html")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            html = f.read()
    except OSError:
        return set()
    from scrape_classifications import tab_blocks
    blocks = tab_blocks(html)
    rows = [r for r in _ROW.findall(blocks.get("STAGE", "")) if 'href="rider/' in r]
    if not rows or len(rows) != len(stage_rows):
        return set()
    winner = _RIDER.search(rows[0])
    if not winner or winner.group(1) != stage_rows[0][6]:
        return set()
    out = set()
    for tab in TIMED_TABS:
        for tr in _ROW.findall(blocks.get(tab, "")):
            if "<font>*" not in tr:
                continue
            rider = _RIDER.search(tr)
            if rider:
                out.add(rider.group(1))
    return out


def gc_ladder(page):
    """{rider_id: (rank, seconds, marked)} from a verified page.

    Used for the MARKER, which is readable whatever the time column means.
    Anything that needs the seconds as gaps must go through gc_gaps().
    """
    rows = (page or {}).get("gc_rows") or []
    out = {}
    for i, r in enumerate(rows):
        seconds, marked = (0, False) if i == 0 else parse_gap(r[4])
        out[r[2]] = (int(r[0]), seconds, marked)
    return out
