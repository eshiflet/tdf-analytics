#!/usr/bin/env python3
"""
Fill vertical_meters for Tour de France Paris finales that PCS leaves blank.

PCS genuinely has no elevation for these stages — the stage page shows an empty
"Vertical meters:" field (and empty Parcours type / ProfileScore, distance 0 km),
so there is nothing to scrape and the NULL in the DB is faithful. The values
here are RECONSTRUCTED, and are recorded as SOURCE_DERIVED rather than
SOURCE_PCS so a future bulk re-scrape can tell them apart from scraped data.

Method (see docstring of each entry for the per-stage numbers):

  1. Trace the route from the official ASO road-book map onto OSM roads with
     BRouter, using the towns and spot altitudes printed on the ASO profile as
     control points. Keep the waypoint count low — too many waypoints make
     BRouter zigzag and inflate distance by 15-20%.
  2. Sample EU-DEM 25 m every 50 m along the routed line (opentopodata).
  3. Sum positive deltas after a 250 m moving average. That filter was
     calibrated against 2010 stage 19 (Bordeaux-Pauillac ITT, 52.0 km), the
     only nearby stage with a PCS elevation and an unambiguous route: it
     reproduces PCS's 167 m as 173 m (ratio 1.04). Raw unfiltered sums
     overshoot by ~70%.
  4. Add the Champs-Elysees circuit separately. It cannot be measured from the
     DEM because central Paris is a surface model — buildings put Etoile at
     66-74 m against a true ~62 m. Instead it is ANCHORED on 2011 stage 21
     (Creteil-Paris, 95.0 km), whose 436 m PCS total is known: running steps
     1-3 on the 2011 run-in gives 266 m, leaving 170 m for its eight laps,
     i.e. ~21 m per lap.

Do NOT try to digitise the ASO profile artwork. Its printed labels (km marks
and spot altitudes) are reliable and are used above, but the drawn silhouette
is decorative, not metric: 2011's terrain occupies nine vertical pixels for a
stage with 436 m of real climbing, and integrating it yields anywhere between
177 m and 499 m depending only on the smoothing window.

Accuracy: expressing each stage as 436 m + (its run-in - 2011's run-in) makes
most of the method's systematic bias cancel, since the laps are common to every
stage here. Residual uncertainty is roughly +/- 5% where the profile gives good
anchors, and worse where it does not.

ERR LOW. Where a stage is uncertain, the stored value is the low end of the
plausible range, not the midpoint. An under-stated elevation is a mild
understatement of a stage's difficulty; an over-stated one invents climbing that
was never ridden, and would show up as a bogus outlier in the Race Overview
charts. Two consequences in practice:

  - When the reconstructed route falls short of the ASO distance and the missing
    kilometres are FLAT (typically the run into Paris along the Seine), add them
    at a flat rate of ~3 m/km rather than scaling the whole route up. Uniform
    scaling multiplies the hilly sections too and over-counts.
  - Where a specific doubt has a known size (an unverifiable valley start, say),
    subtract it rather than splitting the difference.

Usage:  python3 patch_paris_finale_elevation.py [--dry-run]
"""

import argparse
import os
import sqlite3
import sys

from race_common import DB_PATH, SOURCE_DERIVED, record_provenance

# NOTE ON THE LAPS. The number and length of the Champs-Elysees laps is NOT
# constant across these years — read it off each profile's passage marks rather
# than assuming eight. At ~22 m of climbing per lap: 2002 ran TEN laps (first
# "Haut des Champs" at km 81 of 144), 2003 ran NINE plus a one-off 29 km
# centenary loop out to the Hotel de Ville and Place de la Nation, and 2004 and
# 2011 ran eight shorter 6.125 km laps rather than the usual 6.5 km.
#
# year -> (stage_number, vertical_meters, note)
STAGES = {
    2001: (
        20,
        980,
        # Corbeil-Essonnes -> Paris, 160.5 km. WEAKEST of the whole set: the
        # profile names only three places in 108 km of run-in (Breux-Jouy 28.5,
        # cote de Gif-sur-Yvette 60, Chatenay-Malabry 78), leaving a 30 km
        # unanchored approach into Paris. Reconstruction came out 13% short, so
        # 16 km was added at the flat 3 m/km rate rather than scaled up.
        # ASO prints no start altitude; 2005 starts in the same town and prints
        # 70 m, so the same valley-exit clip was applied (clip lands at 71 m).
        "run-in 835 m (clipped, flat shortfall added) + 8-lap circuit 176 m",
    ),
    2002: (
        20,
        585,
        # Melun -> Paris, 144.0 km. Flat Brie and Marne country — run-in ascent
        # only 376 m over 79 km (4.7 m/km). Route fit is the best of this
        # group (+0.6%). TEN laps, not eight: the first "Haut des Champs" is at
        # km 81, giving 64.4 km of circuit at 6.5 km a lap, worth ~220 m.
        # Melun's start reads 55 m against ASO's 72 m, but the profile does not
        # show a valley exit, so nothing was clipped.
        "run-in 376 m (DEM) + 10-lap circuit 220 m",
    ),
    2003: (
        20,
        730,
        # Ville-d'Avray -> Paris, 152.0 km. The centenary Tour, and the only
        # non-standard circuit here: 1st passage at km 64.5, then a 29 km loop
        # through central Paris (Hotel de Ville 82.5, Place de la Nation 86.5)
        # to the 2nd passage at 93.5, then NINE 6.5 km laps to the finish.
        # Circuit term = 10 Champs climbs (~220 m) + 22.5 km of extra flat
        # central-Paris riding at ~3 m/km (~68 m) = ~290 m.
        # Run-in 64 km over Le Mont Valerien (cat 4); start 127 m vs ASO 140,
        # Le Chesnay 135 vs ASO 138 — both good.
        "run-in 453 m (DEM) + 9 laps and the centenary Paris loop, ~290 m",
    ),
    2004: (
        20,
        725,
        # Montereau -> Paris, 163.0 km. BEST fit of this group: route within
        # 1.2%, and the same Montereau valley-start trap as 2009 (ASO 120 m,
        # town 53 m) — clipping to put Echouboulains at ASO's 8.0 km lands at
        # 119 m against the printed 120 m, and Echouboulains itself reads 120 m
        # against 118. Flat Brie throughout, run-in 576 m over 113.5 km.
        # Eight SHORTER laps (6.125 km, passages 6.0-6.5 km apart) = 170 m,
        # the same circuit 2011 rode.
        "run-in 576 m (DEM, valley exit clipped) + 8-lap circuit 170 m",
    ),
    2005: (
        21,
        855,
        # Corbeil-Essonnes -> Paris, 144.5 km. Hurepoix hills: cote de
        # Gif-sur-Yvette (cat 4, 153 m) and Chatenay-Malabry 155 m. Route +3.0%.
        # Valley start again (ASO 70 m, Corbeil 42 m) — clipped, though the clip
        # lands at 84 m rather than 70, and Saint-Vrain comes out 5 km late and
        # 26 m high, so the opening is the weak part of this one.
        #
        # NB the Paris finale is stage 21 this year, not stage 20 — 2005 s20 is
        # a different stage and already carries a real PCS 806 m.
        "run-in 702 m (DEM, valley exit clipped) + 8-lap circuit 176 m",
    ),
    2006: (
        20,
        1090,
        # Sceaux-Antony -> Paris, 154.5 km. The hilliest of these finales: two
        # cat-4 climbs (Gif-sur-Yvette, Mont-Valerien) and a profile that
        # oscillates between 45 m and 195 m the whole way — Chatenay 177,
        # Orsay 164, Gif 176, Velizy 195. Run-in 100 km reconstructed as
        # 90.7 km (-9%), ascent 912 m -> 1005 m normalised. Circuit 176 m.
        #
        # LOWEST CONFIDENCE of the set (+/- ~10%). The -9% shortfall is split
        # between hilly terrain (Orsay/Gif, -6.4 km) and the flat Seine
        # corridor (Courbevoie/Neuilly, -4.5 km). Per the ERR LOW rule the
        # stored value scales only the hilly part (1090) rather than the whole
        # route uniformly, which would have given 1150. Waypoints at Orsay and Gif had to be moved off
        # the valley town centres onto the plateau to match ASO's printed
        # altitudes (the town centres sit ~100 m lower).
        #
        # NB this stage previously held vertical_meters = 0 / profile_score = 0
        # with 'unknown' provenance — the only TDF stage with a zero, a blank
        # PCS field parsed as 0. Both are replaced here (profile_score -> NULL).
        "run-in 914 m (DEM, flat shortfall added at 3 m/km) + 8-lap circuit 176 m",
    ),
    2007: (
        20,
        885,
        # Marcoussis -> Paris, 146.0 km. Run-in 93 km reconstructed as 91.6 km
        # (-1.6%) — the best distance fit of the three — ascent 788 m ->
        # 801 m normalised. Circuit 176 m.
        #
        # CAVEAT: no ASO profile exists for this stage, only the road-book map,
        # so there are no km marks or spot altitudes to validate against and
        # no way to check the start altitude for the valley-exit trap that
        # caught 2009 and 2008. The route (Marcoussis, Briis-sous-Forges, the
        # D131/D27 loop, Rochefort, Bullion, Cernay, Chevreuse, then the same
        # Saclay/Verrieres/Chatenay/Meudon approach as 2008 and 2010) is taken
        # from the map alone. DEM shows the first 4 km climbing 88 -> 168 m
        # out of Marcoussis; that is consistent with the map's N446/D35 exit
        # onto the Hurepoix plateau. Per the ERR LOW rule the stored value
        # assumes the departure reelle was already on the plateau and drops
        # that 70 m; if the riders really did climb out of Marcoussis the true
        # figure is ~955 m.
        "run-in 801 m less a 70 m unverifiable start climb + 8-lap circuit 176 m",
    ),
    2008: (
        21,
        900,
        # Étampes -> Paris, 143.0 km. Two cat-4 climbs (Saint-Rémy-lès-
        # Chevreuse 182 m, Châteaufort 186 m). Run-in 90 km reconstructed as
        # 92.1 km after clipping (+2%), ascent 744 m normalised. Circuit 176 m.
        #
        # Same start trap as 2009: ASO prints 133 m for Étampes but the town
        # sits at ~80 m in the Juine valley, and the profile is level from km 0
        # to La Forêt-le-Roi (145 m at 7.5 km), so km 0 is already on the
        # plateau. Clipping removed a spurious 73 m valley exit.
        #
        # ASO's altitudes for the Chevreuse climbs run ~20-35 m above any
        # ground within 2 km (Châteaufort 186 vs a local max of 167, Christ de
        # Saclay 187 vs 162), so those anchors were not force-matched. The
        # anchors that do agree: La Forêt-le-Roi +5, Verrieres +4, Chatenay
        # +16, Meudon +1, Paris -4.
        "run-in 744 m (DEM, valley exit clipped) + 8-lap circuit 176 m",
    ),
    2009: (
        21,
        650,
        # Montereau-Fault-Yonne -> Paris, 164.0 km. Run-in 111.5 km
        # reconstructed as 101.4 km (-9%) across the Brie plateau; DEM matched
        # ASO's spot altitudes at Echouboulains (+4 m), Les Ecrennes (-4 m),
        # Mormant (-2 m), Marles (+4 m) and Joinville (+2 m). Run-in ascent
        # 484 m, very evenly spread (2.7-6.0 m/km) — the plateau varies by only
        # 16 m over its first 74 km.
        #
        # NOTE the start: ASO prints 118 m for Montereau, but the town sits at
        # ~53 m at the Seine/Yonne confluence. The profile's silhouette is level
        # from km 0 through Echouboulains, so ASO's km 0 (the departure reelle)
        # is already up on the plateau — routing from the town centre adds a
        # spurious 77 m valley exit. Clipping the route so the remaining
        # distance to Echouboulains is ASO's 7.5 km lands at 118.9 m, matching
        # the printed 118 m and confirming the clip.
        #
        # Circuit 8 x 6.5 km laps (first passage at km 112) = 176 m, same as
        # 2010. 484 + 176 = 660 m; with the ITT calibration factor, 650 m.
        "run-in 484 m (DEM, valley exit clipped) + 8-lap circuit 176 m",
    ),
    2010: (
        20,
        660,
        # Longjumeau -> Paris, 102.5 km. Run-in 49.5 km reconstructed as
        # 50.38 km (+1.7%); DEM matched ASO's spot altitudes at Orsay (-2 m),
        # Meudon (-1 m) and Verrieres (+4 m). Run-in ascent 493 m — unusually
        # hilly for a Paris finale, climbing to ~160 m three times (Villejust
        # and Saclay plateaus, then 55 m -> 170 m up to Chatenay-Malabry in
        # 5 km). Circuit 8 x 6.5 km laps = 176 m. 493 + 176 = 669 m; applying
        # the ITT calibration factor (1.04) gives 660 m.
        "run-in 493 m (DEM) + 8-lap circuit 176 m, anchored on 2011 = 436 m",
    ),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    updated = 0
    for year, (stage_number, vert, note) in sorted(STAGES.items()):
        row = cur.execute(
            """SELECT s.stage_id, s.vertical_meters, s.profile_score, s.distance_km,
                      s.start_location, s.finish_location, p.source AS prov_source,
                      p.script AS prov_script
                 FROM stages s
                 JOIN race_editions e ON e.edition_id = s.edition_id
                 JOIN races r ON r.race_id = e.race_id
                 LEFT JOIN data_provenance p
                        ON p.entity = 'stages' AND p.entity_id = s.stage_id
                       AND p.field = 'vertical_meters'
                WHERE r.name = 'Tour de France'
                  AND e.year = ? AND s.stage_number = ?""",
            (year, stage_number),
        ).fetchone()

        if row is None:
            print(f"ERROR: {year} stage {stage_number} not found", file=sys.stderr)
            conn.close()
            return 1

        # A stored 0 is not a real measurement — no Paris finale is flat to the
        # metre. 2006 stage 20 is the only TDF stage carrying one, a blank PCS
        # field parsed as 0, and it is treated as missing here. Any other
        # non-null value is left alone: it may be a real PCS number that
        # appeared since this script was written.
        # A value this script derived earlier may be revised (estimates get
        # refined as more years are reconstructed and the method tightens).
        # Anything else that is already populated is left strictly alone.
        ours = (row["prov_source"] == SOURCE_DERIVED
                and row["prov_script"] == os.path.basename(__file__))
        if row["vertical_meters"] and not ours:
            print(f"SKIP  {year} stage {stage_number}: already has "
                  f"vertical_meters={row['vertical_meters']}"
                  f" (source={row['prov_source'] or 'none'})")
            continue
        if row["vertical_meters"] == vert:
            print(f"OK    {year} stage {stage_number}: unchanged at {vert}")
            continue
        if row["vertical_meters"]:
            print(f"REVISE {year} stage {stage_number}: "
                  f"{row['vertical_meters']} -> {vert}")

        print(f"SET   {year} stage {stage_number} "
              f"{row['start_location']} -> {row['finish_location']} "
              f"({row['distance_km']} km): vertical_meters = {vert}")
        print(f"        {note}")

        if not args.dry_run:
            cur.execute("UPDATE stages SET vertical_meters = ? WHERE stage_id = ?",
                        (vert, row["stage_id"]))
            record_provenance(cur, "stages", row["stage_id"], "vertical_meters",
                              SOURCE_DERIVED,
                              source_ref="BRouter/OSM route + EU-DEM 25 m, "
                                         "circuit anchored on 2011 s21 = 436 m")
            # A profile_score of 0 came from the same blank PCS field. It is a
            # PCS-specific metric that cannot be reconstructed, so record the
            # honest gap rather than leaving a fabricated zero in place.
            if row["profile_score"] == 0:
                cur.execute("UPDATE stages SET profile_score = NULL "
                            "WHERE stage_id = ?", (row["stage_id"],))
                cur.execute("DELETE FROM data_provenance WHERE entity='stages' "
                            "AND entity_id=? AND field='profile_score'",
                            (row["stage_id"],))
                print("        cleared a bogus profile_score = 0 -> NULL")
            updated += 1

    if args.dry_run:
        print("\n(dry run — nothing written)")
        conn.rollback()
    else:
        conn.commit()
        print(f"\nUpdated {updated} stage(s).")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
