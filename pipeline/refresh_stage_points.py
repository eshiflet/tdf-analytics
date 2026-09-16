#!/usr/bin/env python3
"""
Re-read per-stage sprint/KOM points from PCS into existing scrape files.

WHY THIS EXISTS, and why it is not `scrape_race.py --all`. Two defects fixed on
2026-09-14 both live in how points were READ, not in how stage rows were read:

  1. PCS 500s `<slug>-points` and `<slug>-kom` for the FINAL stage of every
     Grand Tour, and a missing page was treated as "no points awarded". Every
     finale scraped this way carries zero sprint and zero KOM points.
  2. `parse_points_page` took the last numeric cell in the row, which on a
     modern PCS table is `delta_pnt` ("Today"), not `pnt`. Where the trailing
     cell was blank it fell back onto `pnt` and was right, so the totals came
     out low and plausible rather than obviously broken.

Per-stage points live INSIDE each scrape file, written at scrape time, so only
re-reading the pages moves them. A full re-scrape would do that — and would
also rewrite every result row, which is a far larger surface than the defect:
it reverts name-swap repairs (replayed, but still), and re-runs row parsing
over 3,810 files to fix two dictionary keys. This rewrites ONLY
`sprint_points` and `kom_points`, and asserts every other key is untouched
before saving.

The Tour is deliberately not covered: its points come from
scrape_sprint_per_stage.py and scrape_kom_points.py, which already select their
column by `data-code` and never had either defect.

Usage:
  python3 refresh_stage_points.py --race vuelta --probe          # what has points at all
  python3 refresh_stage_points.py --race giro 1990-1999 --dry-run
  python3 refresh_stage_points.py --race giro --apply
  python3 refresh_stage_points.py --race vuelta --apply --resume  # skip finished years
"""

import argparse
import json
import os
import sys
import time

from race_common import RACES, exit_on_help, parse_year_args
import scrape_race as SR

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".refresh_stage_points_done.json")
LOCK = os.path.join(HERE, ".refresh_stage_points.lock")


class _Lock:
    """Refuse to run twice at once.

    Two copies of this ran concurrently on 2026-09-15 — same race, same years.
    Nothing corrupted a scrape file (each write is one atomic os.replace of a
    value both processes computed identically), but they doubled the request
    rate on a small site, and they interleaved writes to the resume file, whose
    last writer wins: three finished years came back unmarked and looked
    unfinished. A run that cannot say what it has done is worse than a slow one.
    """

    def __enter__(self):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                with open(LOCK) as f:
                    who = f.read().strip()
            except OSError:
                who = "unknown"
            pid = who.split()[0] if who else ""
            if pid.isdigit():
                try:
                    os.kill(int(pid), 0)          # signal 0: liveness only
                except OSError:
                    print(f"removing stale lock from dead pid {pid}")
                    os.unlink(LOCK)
                    return self.__enter__()
            raise SystemExit(
                f"another refresh is already running ({who}).\n"
                f"Wait for it, or if you are sure it is dead: rm {LOCK}")
        os.write(fd, f"{os.getpid()} {' '.join(sys.argv[1:])}".encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        try:
            os.unlink(LOCK)
        except OSError:
            pass


def stage_files(race, year):
    d = os.path.join(HERE, f"{race}_scrapes", str(year))
    if not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        if f.startswith("stage_") and f.endswith(".json"):
            out.append((int(f[len("stage_"):-len(".json")]), os.path.join(d, f)))
    return sorted(out)


def years_on_disk(race):
    d = os.path.join(HERE, f"{race}_scrapes")
    return sorted(int(x) for x in os.listdir(d)
                  if x.isdigit() and os.path.isdir(os.path.join(d, x)))


def fetch_points(race_info, year, slug, need_stage_page):
    """(sprint, kom, pages_fetched, saw) for one stage, mirroring scrape_stage.

    The stage's own result page is fetched only as a FALLBACK, because it is
    the expensive one and is needed exactly where PCS 500s the dedicated pages.
    """
    base = f"{SR.BASE}/race/{race_info.pcs_slug}/{year}"
    n = 0
    # NOT soft_fail_429. A soft fail returns None, which is indistinguishable
    # here from "PCS has no such page" — and this tool writes what it parses,
    # so a rate-limit would be recorded as "no points awarded" and delete real
    # data. Let fetch back off and retry instead.
    pts_html = SR.fetch(f"{base}/{slug}-points"); n += 1
    time.sleep(SR.DELAY * 0.5)
    kom_html = SR.fetch(f"{base}/{slug}-kom"); n += 1
    page = None
    if (not pts_html or not kom_html) and need_stage_page:
        time.sleep(SR.DELAY * 0.5)
        page = SR.fetch(f"{base}/{slug}/result/result"); n += 1
    sprint = SR.parse_points_page(pts_html or page, "sprint")
    kom = SR.parse_points_page(kom_html or page, "kom")
    # Did we actually SEE a page for each? An empty parse means two completely
    # different things depending on this, and the guard below turns on it.
    saw = {"sprint": bool(pts_html or page), "kom": bool(kom_html or page)}
    return sprint, kom, n, saw


# Keys this tool is allowed to change. Everything else in the file must come
# back byte-identical, which is the whole reason for not re-scraping.
MUTABLE = {"sprint_points", "kom_points"}

DERIVED_RECORD = os.path.join(HERE, "derived_final_stage_points.json")


def derived_finales():
    """{(race, year, stage)} filled by derive_final_stage_points.py.

    Those finales hold points taken from PCS's cumulative classifications
    because the stage page publishes none. To this tool that page looks exactly
    like "no points awarded", so without this set a refresh would purge them —
    the same shape as a re-scrape undoing a name-swap repair.
    """
    if not os.path.exists(DERIVED_RECORD):
        return set()
    with open(DERIVED_RECORD, encoding="utf-8") as f:
        rec = json.load(f)
    return {(race, int(y), e["stage"]) for race, years in rec.items()
            for y, e in years.items()}


DERIVED = derived_finales()


def refresh_year(race, race_info, year, apply_changes, probe_only):
    files = stage_files(race, year)
    if not files:
        return None
    last = max(n for n, _ in files)
    changed, lost, purged, fetched = [], [], [], 0

    for n, path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # The PCS slug, never a URL rebuilt from the stage number: the two
        # diverge on any split day.
        slug = data.get("slug") or f"stage-{n}"
        before = (data.get("sprint_points") or {}, data.get("kom_points") or {})

        # A probe run asks two questions per year and no more: does the finale
        # have points PCS never served us (defect 1), and does an ordinary
        # mid-race stage have any at all (which tells us whether the era
        # publishes them, without fetching twenty stages to find out)?
        if probe_only and n not in (last, files[len(files) // 2][0]):
            continue

        sprint, kom, got, saw = fetch_points(race_info, year, slug,
                                             need_stage_page=(n == last))
        fetched += got

        # A stage may only lose points if we SAW the page say so. An empty
        # parse has two opposite meanings and nothing in the value itself
        # separates them: it is either PCS genuinely publishing no points, or
        # our request failing (a 429 outlasting its retries, a Cloudflare
        # challenge). Writing the second as if it were the first would delete
        # real data silently. So a drop is allowed when the page came back and
        # simply has no points column, and refused when it did not come back.
        #
        # This matters because many of the drops here are CORRECT and wanted:
        # on pre-1990 KOM pages PCS lists who crossed each climb with no `pnt`
        # column at all, and the old "last numeric cell" parser fell through to
        # the Age column — Giro 1961 stage 15 stored Bahamontes 32 and Taccone
        # 21, which are their ages, not points.
        drop_sprint = bool(before[0]) and not sprint
        drop_kom = bool(before[1]) and not kom
        if (drop_sprint or drop_kom) and (race, year, n) in DERIVED:
            # Derived from the classifications, not from this page. The page
            # having nothing is exactly why they were derived.
            time.sleep(SR.DELAY * 0.5)
            continue
        if (drop_sprint and not saw["sprint"]) or (drop_kom and not saw["kom"]):
            lost.append((n, slug, before, (sprint, kom)))
            time.sleep(SR.DELAY * 0.5)
            continue
        if drop_sprint or drop_kom:
            purged.append((n, slug, before, (sprint, kom)))

        if (sprint, kom) != before:
            changed.append((n, slug, before, (sprint, kom)))
            if apply_changes:
                data["sprint_points"], data["kom_points"] = sprint, kom
                with open(path, encoding="utf-8") as f:
                    on_disk = json.load(f)
                for k in on_disk:
                    if k not in MUTABLE and on_disk[k] != data[k]:
                        raise SystemExit(
                            f"REFUSING to write {path}: key {k!r} would change, "
                            "and this tool may only touch sprint_points/kom_points")
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, path)
        time.sleep(SR.DELAY * 0.5)

    return {"year": year, "stages": len(files), "fetched": fetched,
            "changed": changed, "lost": lost, "purged": purged}


def main(argv=None):
    exit_on_help(__doc__)
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", choices=("giro", "vuelta"), required=True)
    ap.add_argument("years", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="one mid stage + the finale per year; says where points exist at all")
    ap.add_argument("--resume", action="store_true", help="skip years already completed")
    args = ap.parse_args(argv)
    if not args.apply:
        args.dry_run = True

    race = args.race
    race_info = RACES[race]
    lock = _Lock().__enter__() if args.apply else None
    wanted = parse_year_args(args.years) if args.years else None
    years = [y for y in years_on_disk(race) if not wanted or y in wanted]

    done = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            done = json.load(f)
    key = lambda y: f"{race}:{y}"
    if args.resume:
        years = [y for y in years if key(y) not in done]

    print(f"{race}: {len(years)} year(s), delay {SR.DELAY}s"
          f"{' [PROBE]' if args.probe else ''}{'' if args.apply else ' [DRY RUN]'}")
    total_changed = total_fetched = total_lost = total_purged = 0
    for y in years:
        r = refresh_year(race, race_info, y, args.apply and not args.probe, args.probe)
        if not r:
            continue
        total_fetched += r["fetched"]
        total_changed += len(r["changed"])
        total_lost += len(r["lost"])
        total_purged += len(r["purged"])
        for n, slug, b, a in r["lost"]:
            print(f"  !! {race} {y} st{n} ({slug}): REFUSED — would have dropped "
                  f"sprint {sum(b[0].values())}->{sum(a[0].values())}, "
                  f"kom {sum(b[1].values())}->{sum(a[1].values())}. Re-run this year.")
        if r["changed"]:
            print(f"  {race} {y}: {len(r['changed'])}/{r['stages']} stage(s) change")
            for n, slug, b, a in r["changed"][:4]:
                print(f"      st{n:>2} ({slug}): sprint {sum(b[0].values()):>4} -> {sum(a[0].values()):>4}"
                      f"   kom {sum(b[1].values()):>4} -> {sum(a[1].values()):>4}")
            if len(r["changed"]) > 4:
                print(f"      ... and {len(r['changed'])-4} more")
        else:
            print(f"  {race} {y}: no change ({r['stages']} stages)")
        sys.stdout.flush()
        if args.apply and not args.probe and not r["lost"]:
            done[key(y)] = True
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump(done, f)

    print(f"\n{race}: {total_changed} stage(s) changed, {total_fetched} page(s) fetched"
          f"{'' if args.apply else '  [DRY RUN - nothing written]'}")
    if total_purged:
        print(f"{race}: {total_purged} stage(s) had points REMOVED — the page has no "
              f"points column, so the old values were read off a neighbouring "
              f"column (usually Age). Spot-check a few against PCS.")
    if lock:
        lock.__exit__()
    if total_lost:
        print(f"{race}: {total_lost} stage(s) REFUSED to avoid dropping existing "
              f"points — re-run those years before trusting this pass complete.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
