// Rank maps and display series for the By Stage view: per-stage sprint/KOM
// rankings, the value each metric plots, gap bridges, and final-rank lookups.
// Split out of stageChart.ts; depends on state only.
import type { RiderSeries, RiderStagePoint } from "../types";
import { state, raceConfig, dataset } from "../state";

function buildRankMapsFromField(
  getRank: (sp: RiderStagePoint) => number | null | undefined,
  getCumPts: (sp: RiderStagePoint) => number,
): {
  rankAtStage: Map<number, Map<string, number>>;
  finalRank: Map<string, number>;
  ridersAtFinal: Map<number, { riders: RiderSeries[]; points: number }>;
} {
  // One pass over each rider's byStage array instead of a per-stage
  // rider.byStage.find() scan (which was O(stages × riders × stages)).
  const rankAtStage = new Map<number, Map<string, number>>();
  for (const stage of dataset().stages) rankAtStage.set(stage.stage_number, new Map());
  for (const rider of dataset().riders) {
    for (const sp of rider.byStage) {
      const rank = getRank(sp);
      if (rank != null) rankAtStage.get(sp.stage)?.set(rider.id, rank);
    }
  }
  // Build finalRank only for riders who reached the final stage; DNF riders
  // keep their mid-race rank in rankAtStage but are excluded from finalRank
  // so they don't pollute "Top N" selection or the legend ordering.
  const finalStageNum = Math.max(...dataset().stages.map((s) => s.stage_number));
  // Requiring presence at the final stage is right for a stage race — a rider
  // who abandoned has no final GC. It is wrong for a SEASON: skipping the last
  // classic does not remove you from the standings. Mathieu van der Poel
  // finished 2nd on 2024 points without riding Il Lombardia, and was being
  // dropped from the legend and every Top-N preset entirely.
  const seasonStanding = raceConfig().stagesAreRaces;
  const finalRank = new Map<string, number>();
  if (seasonStanding) {
    // Rank on the season TOTAL, not on the rank held at each rider's own last
    // race — otherwise everyone who ever led shows as #1 (2024 listed both
    // Pogacar and van der Poel there, since each led when they stopped).
    const totals: Array<[string, number]> = [];
    for (const rider of dataset().riders) {
      if (rider.byStage.length === 0) continue;
      const pts = getCumPts(rider.byStage[rider.byStage.length - 1]);
      if (pts > 0) totals.push([rider.id, pts]);
    }
    totals.sort((a, b) => b[1] - a[1]);
    let prevPts: number | null = null, prevRank = 0;
    totals.forEach(([id, pts], i) => {
      const rank = pts === prevPts ? prevRank : i + 1;
      finalRank.set(id, rank);
      prevRank = rank;
      prevPts = pts;
    });
  } else {
    for (const rider of dataset().riders) {
      if (rider.byStage.length === 0) continue;
      const lastSp = rider.byStage[rider.byStage.length - 1];
      if (lastSp.stage !== finalStageNum) continue;
      const rank = getRank(lastSp);
      if (rank != null) finalRank.set(rider.id, rank);
    }
  }
  const ridersAtFinal = new Map<number, { riders: RiderSeries[]; points: number }>();
  for (const rider of dataset().riders) {
    const rank = finalRank.get(rider.id);
    if (rank === undefined) continue;
    const lastSp = rider.byStage.length > 0 ? rider.byStage[rider.byStage.length - 1] : undefined;
    const ptsVal = lastSp ? getCumPts(lastSp) : 0;
    if (!ridersAtFinal.has(rank)) ridersAtFinal.set(rank, { riders: [], points: ptsVal });
    ridersAtFinal.get(rank)!.riders.push(rider);
  }
  return { rankAtStage, finalRank, ridersAtFinal };
}

export function computePointsRankings() {
  ({ rankAtStage: state.pointsRankAtStage, finalRank: state.finalPointsRank, ridersAtFinal: state.ridersAtFinalPointsRank } =
    buildRankMapsFromField((sp) => sp.sprintRank, (sp) => sp.cumulativePoints));
  ({ rankAtStage: state.komRankAtStage, finalRank: state.finalKomRank, ridersAtFinal: state.ridersAtFinalKomRank } =
    buildRankMapsFromField((sp) => sp.komRank, (sp) => sp.cumulativeKomPoints));
}

function activeRankMap(stageNum: number): Map<string, number> | undefined {
  if (state.currentMetric === "kom") return state.komRankAtStage.get(stageNum);
  return state.pointsRankAtStage.get(stageNum);
}

export type DisplayPoint = { stage: number; rank: number | null; status: string };

/** Build the display-value series for a rider to feed into d3 line/dot/label
 *  rendering. The "rank" field doubles as the plotted y-value: it's an actual
 *  rank in every mode except GC Time, where it holds gcGapSeconds instead —
 *  0 for the stage leader, increasing for riders further behind. `status` is
 *  carried along so drawChart() can tell "still racing, no time recorded"
 *  (status FINISHED, rank null) apart from a real exit (DNF/DNS/etc). */
export function getDisplayPoints(rider: RiderSeries): DisplayPoint[] {
  if (state.currentMetric === "gc") {
    if (state.gcDisplayMode === "time") {
      return rider.byStage.map((p) => ({ stage: p.stage, rank: p.gcGapSeconds, status: p.status }));
    }
    return rider.byStage.map((p) => ({ stage: p.stage, rank: p.gcRank, status: p.status }));
  }
  if (state.currentMetric === "points" && state.sprintDisplayMode === "points") {
    return rider.byStage.map((p) => ({ stage: p.stage, rank: p.cumulativePoints, status: p.status }));
  }
  if (state.currentMetric === "kom" && state.komDisplayMode === "points") {
    return rider.byStage.map((p) => ({ stage: p.stage, rank: p.cumulativeKomPoints, status: p.status }));
  }
  return rider.byStage.map((p) => ({
    stage: p.stage,
    rank: activeRankMap(p.stage)?.get(rider.id) ?? null,
    status: p.status,
  }));
}

// Only bridge short gaps (this many stages of missing data or fewer). A
// single "DF" day is exactly what this is for — connecting the rider across
// a real, multi-week data hole (some pre-1990s Giro/Vuelta years have GC for
// only a handful of stages, e.g. stage 7 and the final stage, and nothing
// between) is worse than a break: a long straight dashed line fabricates the
// impression of a known, gradual trend instead of "we have no idea what
// happened here." Past this threshold, leave the line broken like before.
const MAX_BRIDGE_GAP_STAGES = 2;

/** Finds runs of "still racing, no time recorded" stages (status FINISHED,
 *  rank null) bounded on both sides by a known rank, and returns one
 *  [from, to] pair per short run to draw as a dashed connector — visual
 *  continuity instead of a silent break in the line. A run adjoining a real
 *  exit (DNF/DNS/DSQ/OTL/...) is never bridged; neither is a null run open at
 *  either end of the data, nor one longer than MAX_BRIDGE_GAP_STAGES (see
 *  above — a long gap should stay a visible break, not a fabricated line). */
export function buildGapBridges(points: DisplayPoint[]): Array<[DisplayPoint, DisplayPoint]> {
  const bridges: Array<[DisplayPoint, DisplayPoint]> = [];
  let i = 0;
  while (i < points.length) {
    if (points[i].rank !== null) { i++; continue; }
    const from = points[i - 1];
    let j = i;
    let allFinished = true;
    while (j < points.length && points[j].rank === null) {
      if (points[j].status !== "FINISHED") allFinished = false;
      j++;
    }
    const to = points[j];
    if (
      from && from.rank !== null && to && to.rank !== null && allFinished &&
      to.stage - from.stage <= MAX_BRIDGE_GAP_STAGES + 1
    ) {
      bridges.push([from, to]);
    }
    i = j;
  }
  return bridges;
}

/** Returns the "effective final rank" for a rider under the current metric. */
export function effectiveFinalRank(rider: RiderSeries): number {
  if (state.currentMetric === "gc") return rider.finalRank;
  if (state.currentMetric === "kom") return state.finalKomRank.get(rider.id) ?? 9999;
  return state.finalPointsRank.get(rider.id) ?? 9999;
}

export function applyDefaultSelection(preset = 20) {
  if (!state.dataset) return; // initial fetch in flight; loadDataset() reapplies
  state.selected = new Set(dataset().riders.filter((r) => effectiveFinalRank(r) <= preset).map((r) => r.id));
}
