// By Stage view: the main bump chart (rank-over-stages line chart) plus its
// sidebar legend and Team/Nation filter dropdowns. This is the app's biggest,
// most state-touching view — ranking computation, chart rendering, legend,
// and filters all live here together since they're genuinely one cohesive
// unit (all only make sense in the context of this one view).
import type { NumberValue } from "../d3";
import { d3 } from "../d3";
import type { RiderSeries, RiderStagePoint } from "../types";
import { state, raceConfig } from "../state";
import {
  chartEl, legendEl, tooltipEl,
  teamFilterBtn, teamFilterPanel, nationFilterBtn, nationFilterPanel,
} from "../dom";
import { showStageTooltip, hideTooltip, positionTooltip } from "../tooltip";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import { fmtTotalTime, fmtGap, fmtHms, stageLabel, stageTitle, stageAxisLabel } from "../formatters";

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
  for (const stage of state.dataset.stages) rankAtStage.set(stage.stage_number, new Map());
  for (const rider of state.dataset.riders) {
    for (const sp of rider.byStage) {
      const rank = getRank(sp);
      if (rank != null) rankAtStage.get(sp.stage)?.set(rider.id, rank);
    }
  }
  // Build finalRank only for riders who reached the final stage; DNF riders
  // keep their mid-race rank in rankAtStage but are excluded from finalRank
  // so they don't pollute "Top N" selection or the legend ordering.
  const finalStageNum = Math.max(...state.dataset.stages.map((s) => s.stage_number));
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
    for (const rider of state.dataset.riders) {
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
    for (const rider of state.dataset.riders) {
      if (rider.byStage.length === 0) continue;
      const lastSp = rider.byStage[rider.byStage.length - 1];
      if (lastSp.stage !== finalStageNum) continue;
      const rank = getRank(lastSp);
      if (rank != null) finalRank.set(rider.id, rank);
    }
  }
  const ridersAtFinal = new Map<number, { riders: RiderSeries[]; points: number }>();
  for (const rider of state.dataset.riders) {
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

type DisplayPoint = { stage: number; rank: number | null; status: string };

/** Build the display-value series for a rider to feed into d3 line/dot/label
 *  rendering. The "rank" field doubles as the plotted y-value: it's an actual
 *  rank in every mode except GC Time, where it holds gcGapSeconds instead —
 *  0 for the stage leader, increasing for riders further behind. `status` is
 *  carried along so drawChart() can tell "still racing, no time recorded"
 *  (status FINISHED, rank null) apart from a real exit (DNF/DNS/etc). */
function getDisplayPoints(rider: RiderSeries): DisplayPoint[] {
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
function buildGapBridges(points: DisplayPoint[]): Array<[DisplayPoint, DisplayPoint]> {
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
  state.selected = new Set(state.dataset.riders.filter((r) => effectiveFinalRank(r) <= preset).map((r) => r.id));
}

export function drawChart() {
  // The initial dataset fetch may still be in flight (clicking a view button
  // or resizing during load lands here). loadDataset() redraws the current
  // view when it resolves, so bailing out is safe.
  if (!state.dataset) return;
  chartEl.innerHTML = "";
  const containerRect = chartEl.getBoundingClientRect();
  const width = Math.max(containerRect.width, 600);
  const height = Math.max(containerRect.height, 480);
  // Ticks use each race's abbreviation ("LBL"), which fits horizontally at
  // 11-across — so the classics need no extra margin over a Grand Tour. The
  // full name is still one hover away on the top axis.
  const margin = { top: 32, right: 36, bottom: 36, left: state.currentMetric === "gc" ? 72 : 44 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const stages = state.dataset.stages;
  const minStage = d3.min(stages, (s) => s.stage_number) ?? 0;
  const maxStage = d3.max(stages, (s) => s.stage_number) ?? 21;
  const isGcTime = state.currentMetric === "gc" && state.gcDisplayMode === "time";
  const isSprintPoints = state.currentMetric === "points" && state.sprintDisplayMode === "points";
  const isKomPoints = state.currentMetric === "kom" && state.komDisplayMode === "points";

  // Compute each rider's display series once per draw; the line generator,
  // hit paths, end dots, and end labels all read from these maps.
  const displayPointsById = new Map<string, DisplayPoint[]>();
  const lastDefinedById = new Map<string, DisplayPoint | null>();
  // "Still racing, no time recorded" connectors — GC-only, see buildGapBridges.
  const bridgesById = new Map<string, Array<[DisplayPoint, DisplayPoint]>>();
  let maxRank = 1;
  for (const r of state.dataset.riders) {
    const dp = getDisplayPoints(r);
    displayPointsById.set(r.id, dp);
    let last: DisplayPoint | null = null;
    for (let i = dp.length - 1; i >= 0; i--) {
      if (dp[i].rank !== null) { last = dp[i]; break; }
    }
    lastDefinedById.set(r.id, last);
    if (state.currentMetric === "gc") bridgesById.set(r.id, buildGapBridges(dp));
    for (const p of dp) {
      if (p.rank !== null && p.rank > maxRank) maxRank = p.rank;
    }
  }

  state.xScale = d3.scaleLinear().domain([minStage, maxStage]).range([0, innerWidth]);
  state.yScale = d3.scaleLinear()
    .domain(isGcTime ? [0, maxRank] : (isSprintPoints || isKomPoints) ? [maxRank, 0] : [1, maxRank])
    .range([0, innerHeight]);

  const svg = d3
    .select(chartEl)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`);

  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

  // No-data overlays for classifications that didn't exist yet
  // These era cutoffs are about the Tour's own jersey competitions, so they
  // must not fire for a race that reuses the points metric for something else
  // — the classics' season standings run back to the 1890s.
  const jerseyEras = raceConfig().hasSprintKom;
  const noDataMessage =
    jerseyEras && state.currentMetric === "points" && parseInt(state.currentYear) < 1953
      ? "No data because the green jersey sprint points competition started in 1953"
      : jerseyEras && state.currentMetric === "kom" && parseInt(state.currentYear) < 1933
      ? "No data because the KOM points competition started in 1933, though the polka dot jersey wasn't used until 1975"
      : null;

  if (noDataMessage) {
    g.append("text")
      .attr("x", innerWidth / 2)
      .attr("y", 60)
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("fill", "var(--text-muted, #888)")
      .attr("font-size", "22px")
      .text(noDataMessage);
    return;
  }

  // gridlines (horizontal) — "nice" ticks in GC Time / Sprint Points mode, every 10 ranks otherwise
  const yTickValues = isGcTime || isSprintPoints || isKomPoints
    ? d3.scaleLinear().domain([0, maxRank]).nice().ticks(6).filter((v) => v > 0)
    : d3.range(10, maxRank + 1, 10);
  g.append("g")
    .attr("class", "grid grid-y")
    .call(
      d3
        .axisLeft(state.yScale)
        .tickValues(yTickValues)
        .tickSize(-innerWidth)
        .tickFormat(() => ""),
    );

  // gridlines (vertical, one per stage)
  g.append("g")
    .attr("class", "grid grid-x")
    .attr("transform", `translate(0,${innerHeight})`)
    .call(
      d3
        .axisBottom(state.xScale)
        .tickValues(d3.range(minStage, maxStage + 1))
        .tickSize(-innerHeight)
        .tickFormat(() => ""),
    );

  const stagesByNumber = new Map(stages.map((s) => [s.stage_number, s]));
  const stageLabelFmt = (d: NumberValue) => {
    const s = stagesByNumber.get(+d);
    return s?.stage_short_label ?? s?.stage_label ?? String(d);
  };

  // x axis — bottom
  const xAxisBottom = g
    .append("g")
    .attr("class", "axis x-axis")
    .attr("transform", `translate(0,${innerHeight})`)
    .call(
      d3
        .axisBottom(state.xScale)
        .ticks(maxStage)
        .tickFormat(stageLabelFmt),
    );

  // x axis — top (with stage-info hover)
  const xAxisTop = g
    .append("g")
    .attr("class", "axis x-axis x-axis-top")
    .call(
      d3
        .axisTop(state.xScale)
        .ticks(maxStage)
        .tickFormat(stageLabelFmt),
    );
  xAxisTop
    .selectAll<SVGGElement, number>(".tick")
    .style("cursor", (d) => (stagesByNumber.has(d) ? "help" : null))
    .on("mousemove", (event, d) => {
      const stage = stagesByNumber.get(d);
      if (stage) showStageTooltip(event, stage);
    })
    .on("mouseleave", () => hideTooltip());

  g.append("text")
    .attr("class", "axis-label")
    .attr("x", innerWidth / 2)
    .attr("y", innerHeight + margin.bottom - 4)
    .attr("text-anchor", "middle")
    .text(stageAxisLabel());

  // y axis
  g.append("g")
    .attr("class", "axis y-axis")
    .call(
      d3
        .axisLeft(state.yScale)
        .tickValues(isGcTime || isSprintPoints || isKomPoints ? [0, ...yTickValues] : [1, ...yTickValues])
        .tickFormat((d) => isGcTime ? fmtHms(d as number) : (isSprintPoints || isKomPoints) ? String(d) : `#${d}`),
    );


  const lineGen = d3
    .line<DisplayPoint>()
    .defined((d) => d.rank !== null)
    .x((d) => state.xScale(d.stage))
    .y((d) => state.yScale(d.rank as number))
    .curve(d3.curveMonotoneX);

  const lineLayer = g.append("g").attr("class", "lines");
  const dotLayer = g.append("g").attr("class", "dots");
  const hitLayer = g.append("g").attr("class", "hit-areas");

  lineLayer
    .selectAll<SVGPathElement, RiderSeries>("path")
    .data(state.dataset.riders, (r) => r.id)
    .join("path")
    .attr("class", "rider-line")
    .attr("data-id", (r) => r.id)
    .attr("d", (r) => lineGen(displayPointsById.get(r.id)!))
    .attr("stroke", "var(--line-dim)");

  // "Still racing, no time recorded" dashed connectors (GC only). Flatten
  // riderId -> bridges into one row per segment for the d3 join; shares the
  // rider-line class so updateLineClasses()'s sweep already restyles these
  // for free on selection/highlight changes, just dashed via CSS.
  type BridgeRow = { riderId: string; from: DisplayPoint; to: DisplayPoint };
  const bridgeRows: BridgeRow[] = [];
  for (const [riderId, bridges] of bridgesById) {
    for (const [from, to] of bridges) bridgeRows.push({ riderId, from, to });
  }

  lineLayer
    .selectAll<SVGPathElement, BridgeRow>("path.rider-line-bridge")
    .data(bridgeRows, (b) => `${b.riderId}:${b.from.stage}`)
    .join("path")
    .attr("class", "rider-line rider-line-bridge")
    .attr("data-id", (b) => b.riderId)
    .attr("d", (b) => lineGen([b.from, b.to]))
    .attr("stroke", "var(--line-dim)");

  // invisible wide hit-path per rider, for easier hover targeting
  hitLayer
    .selectAll<SVGPathElement, RiderSeries>("path")
    .data(state.dataset.riders, (r) => r.id)
    .join("path")
    .attr("fill", "none")
    .attr("stroke", "transparent")
    .attr("stroke-width", 10)
    .attr("d", (r) => lineGen(displayPointsById.get(r.id)!))
    .style("cursor", "pointer")
    .on("mouseenter", (_event, r) => {
      setHighlight(r.id);
    })
    .on("mousemove", (event, r) => showTooltip(event, r))
    .on("mouseleave", () => {
      setHighlight(null);
      hideTooltip();
    })
    .on("click", (_event, r) => {
      if (state.selected.has(r.id)) state.selected.delete(r.id);
      else state.selected.add(r.id);
      refreshLegendState();
      updateLineClasses();
    });

  // Matching invisible hit-paths for the dashed bridge segments, so they're
  // hoverable/clickable too — but with a tooltip explaining the gap instead
  // of showTooltip()'s (misleading, here) rank lookup.
  hitLayer
    .selectAll<SVGPathElement, BridgeRow>("path.bridge-hit")
    .data(bridgeRows, (b) => `${b.riderId}:${b.from.stage}`)
    .join("path")
    .attr("class", "bridge-hit")
    .attr("fill", "none")
    .attr("stroke", "transparent")
    .attr("stroke-width", 10)
    .attr("d", (b) => lineGen([b.from, b.to]))
    .style("cursor", "pointer")
    .on("mouseenter", (_event, b) => setHighlight(b.riderId))
    .on("mousemove", (event, b) => {
      const rider = state.dataset.riders.find((r) => r.id === b.riderId);
      if (!rider) return;
      const gapStages = [];
      for (let s = b.from.stage + 1; s < b.to.stage; s++) gapStages.push(stageLabel(s));
      // The same visual gap means different things: mid-stage-race it's a day
      // with no recorded time for a rider still in the race; across a classics
      // season it's simply a race the rider didn't enter.
      const gapNote = raceConfig().stagesAreRaces
        ? `${gapStages.join(", ")}: did not ride`
        : `Stage${gapStages.length > 1 ? "s" : ""} ${gapStages.join(", ")}: no time recorded — still in the race`;
      tooltipEl.innerHTML = `
        <div class="t-name">${displayName(rider)}</div>
        <div class="t-team">${rider.team ?? ""}</div>
        <div>${gapNote}</div>
      `;
      positionTooltip(event);
    })
    .on("mouseleave", () => {
      setHighlight(null);
      hideTooltip();
    })
    .on("click", (_event, b) => {
      if (state.selected.has(b.riderId)) state.selected.delete(b.riderId);
      else state.selected.add(b.riderId);
      refreshLegendState();
      updateLineClasses();
    });

  // end-of-line dots + labels for selected riders
  dotLayer
    .selectAll<SVGCircleElement, RiderSeries>("circle")
    .data(state.dataset.riders, (r) => r.id)
    .join("circle")
    .attr("class", "rider-dot")
    .attr("data-id", (r) => r.id)
    .attr("r", 3)
    .attr("cx", (r) => {
      const last = lastDefinedById.get(r.id);
      return last ? state.xScale(last.stage) : -100;
    })
    .attr("cy", (r) => {
      const last = lastDefinedById.get(r.id);
      return last ? state.yScale(last.rank as number) : -100;
    });

  const labelLayer = g.append("g").attr("class", "labels");
  labelLayer
    .selectAll<SVGTextElement, RiderSeries>("text")
    .data(state.dataset.riders, (r) => r.id)
    .join("text")
    .attr("class", "rider-end-label")
    .attr("data-id", (r) => r.id)
    .attr("x", (r) => {
      const last = lastDefinedById.get(r.id);
      return last ? state.xScale(last.stage) + 6 : -100;
    })
    .attr("y", (r) => {
      const last = lastDefinedById.get(r.id);
      return last ? state.yScale(last.rank as number) + 3 : -100;
    })
    .style("font-size", "10px")
    .text((r) => {
      if (state.currentMetric !== "gc") {
        const isKom = state.currentMetric === "kom";
        const finalRank = isKom ? state.finalKomRank : state.finalPointsRank;
        const ridersAtFinal = isKom ? state.ridersAtFinalKomRank : state.ridersAtFinalPointsRank;
        const group = ridersAtFinal.get(finalRank.get(r.id)!);
        if (group && group.riders.length > 1) return `(${group.riders.length}) ${riderLabel(r)}`;
      }
      return riderLabel(r);
    })
    .style("cursor", (r) => state.currentMetric === "gc" ? "default" : "pointer")
    .on("mouseover", (event: MouseEvent, r: RiderSeries) => {
      if (state.currentMetric === "gc") {
        const lastStage = r.byStage[r.byStage.length - 1];
        const gcRank = lastStage?.gcRank ?? r.finalRank;
        const gap = lastStage?.gcGapSeconds ?? null;
        const gcWinner = state.dataset.riders.find((rd) => rd.finalRank === 1);
        const winnerTime = fmtTotalTime(gcWinner?.totalTimeSeconds ?? null);
        const timeStr = gap === 0 || gcRank === 1
          ? winnerTime
          : fmtGap(gap, gcRank);
        tooltipEl.innerHTML = `
          <div class="t-name">${displayName(r)}</div>
          <div class="t-team">${r.team ?? ""}</div>
          <div>GC #${gcRank ?? "—"} &middot; ${timeStr}</div>
        `;
        positionTooltip(event);
        return;
      }
      const isKom = state.currentMetric === "kom";
      const finalRank = isKom ? state.finalKomRank : state.finalPointsRank;
      const ridersAtFinal = isKom ? state.ridersAtFinalKomRank : state.ridersAtFinalPointsRank;
      const rank = finalRank.get(r.id);
      if (rank === undefined) return;
      const group = ridersAtFinal.get(rank);
      if (!group) return;
      const label = isKom ? "KOM" : "Points";
      const names = group.riders.map((rd) => displayName(rd)).join("<br>");
      tooltipEl.innerHTML = `
        <div class="t-name">Final ${label} Rank #${rank}</div>
        <div class="t-team">${group.points} pts</div>
        <div>${names}</div>
      `;
      positionTooltip(event);
    })
    .on("mouseout", () => { tooltipEl.hidden = true; });

  updateLineClasses();
}

/** Short label for chart lines: last name when available, else last word of full_name. */
function riderLabel(r: RiderSeries): string {
  if (r.lastName) return r.lastName;
  const parts = r.name.trim().split(" ");
  return parts[parts.length - 1];
}

export function cssEscape(s: string): string {
  return s.replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
}

// Restyle one rider's line based on current selected/highlighted state.
function styleRiderLine(pathEl: SVGPathElement) {
  const el = d3.select(pathEl);
  const id = pathEl.getAttribute("data-id")!;
  const isSelected = state.selected.has(id);
  const isHighlighted = state.highlighted === id;
  el.classed("hidden-line", false);
  el.classed("dimmed", !isSelected && !isHighlighted);
  el.classed("highlighted", isHighlighted);
  el.attr("stroke", isSelected || isHighlighted ? state.colorScale(id) : "var(--line-dim)");
  el.style("stroke-opacity", isHighlighted ? 1 : isSelected ? 0.95 : 0.12);
}

// Restyle one rider's end dot or end label (same visibility rules for both).
function styleRiderMarker(el: SVGCircleElement | SVGTextElement) {
  const id = el.getAttribute("data-id")!;
  const isSelected = state.selected.has(id);
  const isHighlighted = state.highlighted === id;
  d3.select(el)
    .style("opacity", isSelected || isHighlighted ? 1 : 0)
    .attr("fill", isSelected || isHighlighted ? state.colorScale(id) : "var(--line-dim)");
}

// Full sweep across every rider — needed when the selection set changes
// (legend clicks, presets, filters) or after a redraw.
export function updateLineClasses() {
  d3.selectAll<SVGPathElement, unknown>(".lines .rider-line").each(function () {
    styleRiderLine(this as SVGPathElement);
  });
  d3.selectAll<SVGCircleElement, unknown>(".dots .rider-dot").each(function () {
    styleRiderMarker(this as SVGCircleElement);
  });
  d3.selectAll<SVGTextElement, unknown>(".labels .rider-end-label").each(function () {
    styleRiderMarker(this as SVGTextElement);
  });
}

// Restyle just one rider's three chart elements (line, end dot, end label).
function restyleRider(id: string) {
  const esc = cssEscape(id);
  // A rider can have multiple line segments now (the solid line plus zero or
  // more dashed "no time recorded" bridges) — restyle all of them, not just
  // the first match.
  chartEl.querySelectorAll<SVGPathElement>(`.lines .rider-line[data-id="${esc}"]`).forEach(styleRiderLine);
  const dot = chartEl.querySelector<SVGCircleElement>(`.dots .rider-dot[data-id="${esc}"]`);
  if (dot) styleRiderMarker(dot);
  const label = chartEl.querySelector<SVGTextElement>(`.labels .rider-end-label[data-id="${esc}"]`);
  if (label) styleRiderMarker(label);
}

// O(1) hover path: only the previously-highlighted rider and the new one
// change appearance, so restyle exactly those two instead of sweeping all
// ~200 lines + dots + labels on every mouseenter/mouseleave.
export function setHighlight(id: string | null) {
  if (state.highlighted === id) return;
  const prev = state.highlighted;
  state.highlighted = id;
  if (prev) restyleRider(prev);
  if (id) restyleRider(id);
}

// Rider-hover tooltip content for the stage chart — kept here rather than in
// tooltip.ts because it's tightly coupled to this view's rank maps and scales.
function showTooltip(event: MouseEvent, rider: RiderSeries) {
  const containerRect = chartEl.getBoundingClientRect();
  const margin = { left: state.currentMetric === "gc" ? 72 : 44, top: 16 };
  const mouseX = event.clientX - containerRect.left - margin.left;
  const stageGuess = Math.round(state.xScale.invert(mouseX));

  if (state.currentMetric === "gc") {
    const point =
      rider.byStage.find((p) => p.stage === stageGuess && p.gcRank !== null) ??
      ((): typeof rider.byStage[0] | null => {
        for (let i = rider.byStage.length - 1; i >= 0; i--) {
          if (rider.byStage[i].gcRank !== null) return rider.byStage[i];
        }
        return null;
      })();
    if (!point) return;
    tooltipEl.innerHTML = `
      <div class="t-name">${displayName(rider)}</div>
      <div class="t-team">${rider.team ?? ""}</div>
      <div>${stageTitle(point.stage)} &middot; ${raceConfig().hasCumulativeGc ? "GC" : "Result"} #${point.gcRank ?? "—"}</div>
      <div>Gap: ${fmtGap(point.gcGapSeconds, point.gcRank)}</div>
      ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
    `;
  } else {
    const point =
      rider.byStage.find((p) => p.stage === stageGuess) ??
      rider.byStage[rider.byStage.length - 1];
    if (!point) return;
    if (state.currentMetric === "kom") {
      const komRank = state.komRankAtStage.get(point.stage)?.get(rider.id) ?? null;
      tooltipEl.innerHTML = `
        <div class="t-name">${displayName(rider)}</div>
        <div class="t-team">${rider.team ?? ""}</div>
        <div>${stageTitle(point.stage)} &middot; KOM rank #${komRank ?? "—"}</div>
        <div>Cumulative KOM pts: ${point.cumulativeKomPoints}</div>
        ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
      `;
    } else {
      const ptsRank = state.pointsRankAtStage.get(point.stage)?.get(rider.id) ?? null;
      tooltipEl.innerHTML = `
        <div class="t-name">${displayName(rider)}</div>
        <div class="t-team">${rider.team ?? ""}</div>
        <div>${stageTitle(point.stage)} &middot; Points rank #${ptsRank ?? "—"}</div>
        <div>Cumulative pts: ${point.cumulativePoints}</div>
        ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
      `;
    }
  }

  positionTooltip(event);
}

export function buildLegend() {
  if (!state.dataset) return; // initial fetch in flight; loadDataset() rebuilds
  legendEl.innerHTML = "";
  // Sort legend by effective final rank for the current metric
  const sorted = [...state.dataset.riders].sort((a, b) => effectiveFinalRank(a) - effectiveFinalRank(b));
  for (const rider of sorted) {
    const row = document.createElement("div");
    row.className = "legend-item";
    row.dataset.id = rider.id;

    const rank = document.createElement("span");
    rank.className = "legend-rank";
    const r = effectiveFinalRank(rider);
    rank.textContent = r < 9999 ? String(r) : "–";

    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";

    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = displayName(rider);
    name.title = `${displayName(rider)} — ${rider.team ?? ""}`;

    row.appendChild(rank);
    row.appendChild(swatch);
    row.appendChild(name);
    const flag = nationalityFlagEl(rider.nationality);
    if (flag) row.appendChild(flag);

    swatch.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.selected.has(rider.id)) {
        state.selected.delete(rider.id);
      } else {
        state.selected.add(rider.id);
      }
      refreshLegendState();
      updateLineClasses();
    });

    name.addEventListener("click", (e) => {
      e.stopPropagation();
      const slug = rider.id.replace(/^rider\//, "");
      window.location.hash = `#riders/${slug}`;
    });

    row.addEventListener("mouseenter", () => {
      setHighlight(rider.id);
    });
    row.addEventListener("mouseleave", () => {
      setHighlight(null);
    });

    legendEl.appendChild(row);
  }
  refreshLegendState();
}

export function refreshLegendState() {
  legendEl.querySelectorAll<HTMLDivElement>(".legend-item").forEach((row) => {
    const id = row.dataset.id!;
    const isSelected = state.selected.has(id);
    row.classList.toggle("active", isSelected);
    const swatch = row.querySelector<HTMLSpanElement>(".legend-swatch")!;
    swatch.style.background = isSelected ? state.colorScale(id) : "var(--line-dim)";
  });
}

/** Recomputes `selected` from the active team/nation filters (OR within a
 *  facet, AND across facets). No-op if neither filter has a selection, so it
 *  never fights with the Top 10/20/All quick-select buttons when unused. */
export function applyStageTeamNationFilter() {
  if (!state.dataset) return;
  if (state.stageFilterTeams.size === 0 && state.stageFilterNations.size === 0) return;
  state.selected = new Set(
    state.dataset.riders
      .filter(
        (r) =>
          (state.stageFilterTeams.size === 0 || (r.team && state.stageFilterTeams.has(r.team))) &&
          (state.stageFilterNations.size === 0 || (r.nationality && state.stageFilterNations.has(r.nationality))),
      )
      .map((r) => r.id),
  );
  document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
    b.classList.remove("active"),
  );
}

export function updateFilterButtonLabel(btn: HTMLButtonElement, base: string, count: number) {
  btn.textContent = count > 0 ? `${base} (${count})` : base;
  btn.classList.toggle("active", count > 0);
}

export function closeFilterPanels() {
  teamFilterPanel.hidden = true;
  nationFilterPanel.hidden = true;
}

export function clearStageTeamNationFilters() {
  state.stageFilterTeams.clear();
  state.stageFilterNations.clear();
  updateFilterButtonLabel(teamFilterBtn, "Team", 0);
  updateFilterButtonLabel(nationFilterBtn, "Nation", 0);
  teamFilterPanel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(
    (cb) => (cb.checked = false),
  );
  nationFilterPanel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(
    (cb) => (cb.checked = false),
  );
  closeFilterPanels();
}

function buildFilterPanel(
  panel: HTMLDivElement,
  options: string[],
  activeSet: Set<string>,
  btn: HTMLButtonElement,
  baseLabel: string,
  showFlags = false,
) {
  panel.innerHTML = "";

  const actions = document.createElement("div");
  actions.className = "filter-panel-actions";
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "filter-panel-clear";
  clear.textContent = "Clear";
  clear.addEventListener("click", () => {
    activeSet.clear();
    panel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach((cb) => (cb.checked = false));
    updateFilterButtonLabel(btn, baseLabel, activeSet.size);
    applyStageTeamNationFilter();
    refreshLegendState();
    updateLineClasses();
  });
  actions.appendChild(clear);
  panel.appendChild(actions);

  for (const option of options) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = option;
    cb.checked = activeSet.has(option);
    cb.addEventListener("change", () => {
      if (cb.checked) activeSet.add(option);
      else activeSet.delete(option);
      updateFilterButtonLabel(btn, baseLabel, activeSet.size);
      applyStageTeamNationFilter();
      refreshLegendState();
      updateLineClasses();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(option));
    if (showFlags) {
      const flag = nationalityFlagEl(option);
      if (flag) label.appendChild(flag);
    }
    panel.appendChild(label);
  }
}

/** Rebuilds the Team/Nation dropdown contents for the current dataset and
 *  resets both filters (team/nation membership is specific to each year). */
export function buildStageFilters() {
  if (!state.dataset) return;
  const hadActiveFilter = state.stageFilterTeams.size > 0 || state.stageFilterNations.size > 0;

  const teams = [...new Set(state.dataset.riders.map((r) => r.team).filter((t): t is string => !!t))].sort();
  const nations = [...new Set(state.dataset.riders.map((r) => r.nationality).filter((n): n is string => !!n))].sort();

  // Carry the filter *values* over across a year change, dropping only the
  // ones that don't exist in the new year's teams/nations (e.g. a team name
  // from 2024 that didn't race in 2022).
  state.stageFilterTeams = new Set([...state.stageFilterTeams].filter((t) => teams.includes(t)));
  state.stageFilterNations = new Set([...state.stageFilterNations].filter((n) => nations.includes(n)));

  updateFilterButtonLabel(teamFilterBtn, "Team", state.stageFilterTeams.size);
  updateFilterButtonLabel(nationFilterBtn, "Nation", state.stageFilterNations.size);

  buildFilterPanel(teamFilterPanel, teams, state.stageFilterTeams, teamFilterBtn, "Team");
  buildFilterPanel(nationFilterPanel, nations, state.stageFilterNations, nationFilterBtn, "Nation", true);

  if (state.stageFilterTeams.size > 0 || state.stageFilterNations.size > 0) {
    applyStageTeamNationFilter();
  } else if (hadActiveFilter) {
    // Every previously-selected team/nation was absent from this year —
    // nothing carries over, so behave like the "None" button was pressed.
    state.selected = new Set();
    document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
      b.classList.remove("active"),
    );
  }
}
