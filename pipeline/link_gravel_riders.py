#!/usr/bin/env python3
"""Decide, once, which rider_id every name in the gravel scrapes belongs to.

The point of the exercise: Peter Stetina rode seven Tours de France and then
went gravel, and Alexey Vermeulen, Lachlan Morton, Petr Vakoc, Simon Pellaud,
Tsgabu Grmay and Chad Haga all cross the same line. Their road results are
already in this DB under a PCS slug (`rider/peter-stetina`). If the gravel
ingest mints a second identity for them, the Riders detail page shows two
half-careers and the crossover — the reason for having both datasets in one
app — is invisible.

PCS does not cover these races (verified: its search returns nothing for
"unbound" while "gravel" returns plenty), so there is no id to join on. Names
are all there is, and a name match is a claim about a person. This script
makes that claim explicitly, records its evidence, and writes the answer to
gravel_scrapes/_rider_ids.json for review — rather than deciding silently
inside an ingest loop where a wrong merge would be invisible.

A wrong merge is the expensive error here: it fuses two people's careers and
nothing downstream can tell. So the rule is deliberately strict, and the
fallback (a fresh gravel-only identity) is cheap and reversible.

  MATCH requires all of:
    * exactly one existing rider whose folded name tokens are the same SET
      (order-independent: the DB stores PCS's "Vermeulen Alexey", Athlinks
      ships "Alexey Vermeulen")
    * at least two name tokens — single-token names are not evidence
    * career plausibility: the existing rider's road results must fall within
      CAREER_SPAN years of the gravel result. This is what stops a 2014
      Leadville amateur from being merged into a 1930s Tour rider who happens
      to share a name, and it does most of the work.
    * birth years within BIRTH_TOLERANCE, when both sides know one.

  Everything else mints `rider/<slug>` (or `<slug>-gvl` if that slug is taken
  by someone we just rejected) and says why in the report.

Usage:
  python3 link_gravel_riders.py              # resolve + write report
  python3 link_gravel_riders.py --show-matches
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

from race_common import GRAVEL

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "cycling.db")
SCRAPES = os.path.join(HERE, "gravel_scrapes")
OUT_PATH = os.path.join(SCRAPES, "_rider_ids.json")

# A rider whose road career ended more than this many years before a gravel
# ride is not the same person. Generous on purpose — Stetina's last Tour was
# 2019 and he is still racing gravel; Ned Overend would stretch it further.
CAREER_SPAN = 30
BIRTH_TOLERANCE = 2

# A country disagreement is NOT evidence on its own: these sources record where
# an athlete registered from, not their passport, and the archive is full of
# honest conflicts — Mohorič rides for Slovenia and enters from Monaco, Woods
# for Canada from Andorra, Voigt as a German from the US. Every one of those is
# a rider whose road career overlaps or nearly touches the gravel result.
#
# Combined with a long silence it is different. Nobody stops racing for two
# decades and comes back under a different flag; that pattern is a namesake.
# The two it rejects are Sean Yates (road to 1996, a Spanish-registered rider
# in the 2024 Traka) and Dag Selander (one Norwegian road result in 1981, US
# off-road results in 1999 and 2006) — and it leaves every long-gap match whose
# country AGREES, which is what Carmichael, Bradley and Friel are.
STALE_SPAN = 15

UNDECOMPOSED = {"ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th",
                "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i"}


def fold(text):
    """Accent-stripped, punctuation-free, lowercase. Mirrors the frontend's
    foldForSearch so a name matches here iff a user could find it there."""
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(UNDECOMPOSED.get(c, c) for c in t)
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def tokens(name):
    return frozenset(t for t in fold(name).split() if t)


def slugify(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", fold(name))).strip("-")


def load_existing(cur):
    """Riders known from races OTHER than these six, by folded token set.

    Also carries each rider's result-year span, which is the strongest
    disqualifier available: names repeat across 130 years, careers do not.

    The `race_type != 'gravel'` filter is what makes this script idempotent.
    Run once, its gravel-only riders are minted into `riders`; run again
    without the filter and every one of them matches ITSELF, so the report
    claims 3,591 riders crossed over from the road when the true number is 93.
    The ids come out the same either way, but a linker that cannot tell its own
    output from evidence is one bad merge away from doing real damage — and the
    number it prints is the only thing a human reviews.
    """
    cur.execute("""
        SELECT ri.rider_id, ri.full_name, ri.first_name, ri.last_name,
               ri.nationality_code, ri.birth_year_approx,
               MIN(e.year) AS first_year, MAX(e.year) AS last_year
        FROM riders ri
        JOIN stage_results sr ON sr.rider_id = ri.rider_id
        JOIN stages s ON s.stage_id = sr.stage_id
        JOIN race_editions e ON e.edition_id = s.edition_id
        JOIN races ra ON ra.race_id = e.race_id
        WHERE ra.race_type != 'gravel'
        GROUP BY ri.rider_id""")
    by_tokens = defaultdict(list)
    all_ids = set()
    for row in cur.fetchall():
        rec = dict(row)
        all_ids.add(rec["rider_id"])
        keys = {tokens(rec["full_name"])}
        if rec["first_name"] and rec["last_name"]:
            keys.add(tokens(f"{rec['first_name']} {rec['last_name']}"))
        for k in keys:
            if k:
                by_tokens[k].append(rec)
    return by_tokens, all_ids


def gravel_people():
    """Every distinct name in the scrapes, with the evidence about it.

    Identity inside the gravel corpus is by name, the same basis PCS itself
    uses. Where one name carries inconsistent ages or countries across
    editions, that is flagged as a possible homonym rather than silently split
    — splitting on age would fracture the many riders whose age Athlinks never
    recorded.
    """
    people = {}
    # Restricted to the six race directories, not every subdirectory: the
    # sibling _raw/ fetch cache is also *.json and has no "info" block.
    paths = [p for p in sorted(glob.glob(os.path.join(SCRAPES, "*", "*.json")))
             if os.path.basename(os.path.dirname(p)) in GRAVEL]
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        year = data["info"]["year"]
        for r in data["rows"]:
            key = fold(r["name"]).strip()
            if not key:
                continue
            p = people.setdefault(key, {
                "name": r["name"], "first_name": r["first_name"],
                "last_name": r["last_name"], "years": set(), "countries": set(),
                "births": set(), "results": 0, "pcs_slugs": set(),
            })
            p["years"].add(year)
            p["results"] += 1
            if r.get("country"):
                p["countries"].add(r["country"])
            if r.get("age"):
                p["births"].add(year - int(r["age"]))
            # A PCS-sourced row carries the rider's real id. That ends the
            # guessing for this person: everything below is machinery for
            # deciding identity from a NAME, which is only necessary because
            # Athlinks has no id to offer. Only `rider/` counts —
            # `national-rider/` is a different namespace that does not exist
            # in `riders`.
            if r.get("pcs_is_pro") and r.get("pcs_slug"):
                p["pcs_slugs"].add(r["pcs_slug"])
    return people


def decide(person, by_tokens):
    """(rider_id or None, decision, evidence) for one gravel name."""
    # PCS publishes the id, so there is nothing to decide. This is strictly
    # better evidence than any name rule below and is checked first.
    slugs = person.get("pcs_slugs") or set()
    if len(slugs) == 1:
        slug = next(iter(slugs))
        return slug, "pcs_slug", f"PCS publishes this rider as {slug}"
    if len(slugs) > 1:
        # One folded name, two PCS ids: two different people who happen to
        # share a name. Guessing between them is exactly the wrong merge this
        # script exists to avoid.
        return (None, "new_ambiguous_pcs",
                f"PCS has {len(slugs)} different riders under this name: "
                + ", ".join(sorted(slugs)))
    toks = tokens(person["name"])
    if len(toks) < 2:
        return None, "new_single_token", "fewer than two name tokens"

    cands = by_tokens.get(toks, [])
    if not cands:
        return None, "new_no_candidate", "no existing rider with this name"
    if len(cands) > 1:
        names = ", ".join(c["rider_id"] for c in cands[:4])
        return None, "new_ambiguous", f"{len(cands)} existing riders share this name: {names}"

    c = cands[0]
    gy_min, gy_max = min(person["years"]), max(person["years"])
    if c["last_year"] is None:
        return None, "new_no_results", f"{c['rider_id']} has no results to date-check against"
    # Careers, not names, are what make two people the same person.
    if gy_min - c["last_year"] > CAREER_SPAN or c["first_year"] - gy_max > CAREER_SPAN:
        return (None, "new_era_mismatch",
                f"{c['rider_id']} raced {c['first_year']}-{c['last_year']}, "
                f"gravel {gy_min}-{gy_max}")
    # No birth year is published by either Traka source, so for those riders the
    # check below cannot fire at all and this is the only disqualifier left.
    gravel_countries = set(person.get("countries") or ())
    if (c["nationality_code"] and gravel_countries
            and c["nationality_code"] not in gravel_countries
            and gy_min - c["last_year"] > STALE_SPAN):
        return (None, "new_country_and_era_mismatch",
                f"{c['rider_id']} is {c['nationality_code']} and last raced "
                f"{c['last_year']}; this rider entered from "
                f"{'/'.join(sorted(gravel_countries))} in {gy_min}")
    if person["births"] and c["birth_year_approx"]:
        near = min(abs(b - c["birth_year_approx"]) for b in person["births"])
        if near > BIRTH_TOLERANCE:
            return (None, "new_birth_mismatch",
                    f"{c['rider_id']} born ~{c['birth_year_approx']}, "
                    f"gravel age implies ~{sorted(person['births'])}")
    return (c["rider_id"], "matched",
            f"{c['full_name']} ({c['nationality_code'] or '??'}), "
            f"road {c['first_year']}-{c['last_year']}, gravel {gy_min}-{gy_max}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-matches", action="store_true")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # `taken` holds only NON-gravel ids for the same reason: a slug this script
    # minted on a previous run belongs to the same person, so reusing it is
    # correct — suffixing it would split them in two.
    by_tokens, taken = load_existing(cur)
    conn.close()

    people = gravel_people()
    if not people:
        print("no gravel scrapes found — run scrape_athlinks.py first")
        return 1

    out, counts, matches, homonyms = {}, defaultdict(int), [], []
    minted = set()
    for key in sorted(people):
        p = people[key]
        rider_id, decision, why = decide(p, by_tokens)
        if rider_id is None:
            slug = f"rider/{slugify(p['name'])}"
            # Never reuse a slug we just declined to match into — that would
            # re-create by the back door exactly the merge the rule refused.
            if slug in taken or slug in minted:
                slug = f"{slug}-gvl"
            rider_id = slug
            minted.add(slug)
        else:
            matches.append((p["name"], rider_id, why, p["results"]))
        counts[decision] += 1
        # Two people can share a name inside the gravel corpus as easily as
        # across it, and Athlinks gives nothing to tell them apart: racerId is
        # null on most rows. An age spread wider than a rounding error is the
        # only signal, and it is NOT conclusive — Lachlan Morton's Dirty Kanza
        # 2019 row records his age as 19 when he was 27, so the spread there is
        # one upstream typo, not two riders. Ryan Sellner's (1967 and 2003, same
        # Minnesota town) really does look like a father and a son.
        #
        # So this flags rather than splits. Splitting automatically would
        # fracture the real crossover riders this whole script exists to keep
        # whole, to fix a handful of amateur collisions.
        suspect = len(p["births"]) > 1 and max(p["births"]) - min(p["births"]) > 3
        if suspect:
            homonyms.append((p["name"], sorted(p["births"]), sorted(p["countries"]),
                             sorted(p["years"])))
        out[key] = {
            "pcs_slug": sorted(p.get("pcs_slugs") or ())[:1] or None,
            "rider_id": rider_id, "name": p["name"],
            "first_name": p["first_name"], "last_name": p["last_name"],
            "decision": decision, "evidence": why,
            "country": sorted(p["countries"])[0] if p["countries"] else None,
            "countries": sorted(p["countries"]),
            # MEDIAN, not mean: one mistyped age should not drag a rider's
            # birth year by four years, which is what averaging Morton's ten
            # 1992s against one 2000 did.
            "birth_year_approx": (sorted(p["births"])[len(p["births"]) // 2]
                                  if p["births"] else None),
            "homonym_suspect": suspect,
            "results": p["results"], "years": sorted(p["years"]),
        }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"{len(people):,} distinct names in the gravel scrapes")
    for k in sorted(counts):
        print(f"  {k:<20} {counts[k]:>6}")
    print(f"\n{len(matches)} linked to an existing (road) rider:")
    for name, rid, why, n in sorted(matches, key=lambda m: -m[3])[:60 if args.show_matches else 25]:
        print(f"  {name:<28} -> {rid:<34} {n:>3} results   {why}")
    if len(matches) > 25 and not args.show_matches:
        print(f"  ... {len(matches)-25} more (--show-matches)")
    if homonyms:
        print(f"\n{len(homonyms)} names with an inconsistent birth year "
              f"(possible homonyms sharing one identity — review):")
        for name, births, countries, years in homonyms[:20]:
            print(f"  {name:<28} births {births}  {countries}  years {years}")
    print(f"\nwrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
