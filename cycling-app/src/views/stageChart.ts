// By Stage view: the main bump chart (rank-over-stages line chart). Ranking
// maths lives in stageRankings.ts, line/label restyling in stageHighlight.ts,
// the sidebar legend in stageLegend.ts and the Team/Nation filters in
// stageFilters.ts.
import type { NumberValue } from "../d3";
import { d3 } from "../d3";
import type { RiderSeries } from "../types";
import { state, raceConfig } from "../state";
import { chartEl, tooltipEl } from "../dom";
import { showStageTooltip, hideTooltip, positionTooltip } from "../tooltip";
import { displayName } from "../riderDisplay";
import { fmtTotalTime, fmtGap, fmtHms, stageLabel, stageTitle, stageAxisLabel } from "../formatters";
import { getDisplayPoints, buildGapBridges } from "./stageRankings";
import type { DisplayPoint } from "./stageRankings";
import { updateLineClasses, setHighlight } from "./stageHighlight";
import { refreshLegendState } from "./stageLegend";

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
  //
  // The right margin is what the END LABELS need, not a constant. It was 36,
  // which left them 30px after their 6px offset — while the widest surname in
  // the 2026 Tour renders at 70px and the median at 39px. Every label longer
  // than about five characters was being cut off by the SVG's edge, invisibly,
  // because until the de-collision pass they overlapped into a smear anyway.
  const margin = {
    top: 32, right: endLabelMargin(width), bottom: 36,
    left: state.currentMetric === "gc" ? 72 : 44,
  };
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

  // A screen reader announces an unlabelled <svg> as nothing at all, and this
  // one IS the page. role="img" plus a name at least says what is being shown
  // and for which race and year; the per-rider detail stays in the legend and
  // the Table sub-view, which are ordinary DOM.
  // Read currentMetric, NOT the isSprintPoints/isKomPoints flags above: those
  // mean "this metric AND its points display mode", so viewing the points
  // classification by RANK would have announced it as the general
  // classification. Caught by reading the label back on a /kom URL.
  const metricName =
    state.currentMetric === "points" ? `points classification by ${isSprintPoints ? "points" : "position"}`
    : state.currentMetric === "kom" ? `mountains classification by ${isKomPoints ? "points" : "position"}`
    : `general classification by ${isGcTime ? "time" : "position"}`;
  const svg = d3
    .select(chartEl)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("role", "img")
    .attr("aria-label",
      `${state.currentYear} ${raceConfig().name}: ${metricName}, stage by stage`)
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
    // The y a label WANTS, kept so layoutEndLabels() can re-spread from the
    // original positions every time instead of nudging already-nudged ones
    // further on each selection change.
    .attr("data-y0", (r) => {
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
        // A disqualification leaves TWO riders at rank 1 — PCS lists the
        // stripped rider and the promoted one — and find() took whichever came
        // first in the array. That is the stripped rider in both the cases
        // that reach this tooltip, and his total time is the one nobody
        // recomputed: the 1904 Tour showed Garin's, the 1948 Giro showed
        // Coppi's 4:51:45 for a 3,000 km race. Prefer the rank-1 rider who
        // actually carries a total; that is the rider whose time is the
        // official winning time.
        const gcWinner = state.dataset.riders.find((rd) => rd.finalRank === 1 && rd.totalTimeSeconds != null)
          ?? state.dataset.riders.find((rd) => rd.finalRank === 1);
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

/** How much room to leave at the right edge for the end labels.
 *
 *  Measures ONE string rather than all ~200: the longest label by character
 *  count is picked first with plain string work (no layout), and only that one
 *  is put through getComputedTextLength(). Character count is not a perfect
 *  proxy for pixel width — "WWW" is wider than "iii" — so the result carries a
 *  small pad, and the whole thing is clamped so that one freak name cannot eat
 *  the plot on a narrow window.
 *
 *  The floor is the old constant, so a chart with no labels at all is laid out
 *  exactly as it was. */
function endLabelMargin(width: number): number {
  const LABEL_OFFSET = 6;     // matches the label's x, above
  const MIN = 36;             // the previous fixed margin
  if (!state.dataset) return MIN;
  let longest = "";
  for (const r of state.dataset.riders) {
    const label = riderLabel(r);
    if (label.length > longest.length) longest = label;
  }
  if (!longest) return MIN;

  const probe = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  probe.setAttribute("width", "0");
  probe.setAttribute("height", "0");
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("class", "rider-end-label");
  text.style.fontSize = "10px";
  text.textContent = longest;
  probe.appendChild(text);
  document.body.appendChild(probe);
  // jsdom implements neither getComputedTextLength nor getBBox; fall back to a
  // width per character there so verify-views.mjs exercises the real path
  // rather than throwing.
  let measured = 0;
  try {
    measured = text.getComputedTextLength?.() || 0;
  } catch { measured = 0; }
  if (!measured) measured = longest.length * 5.6;
  probe.remove();

  const needed = LABEL_OFFSET + Math.ceil(measured) + 4;
  // Never more than a sixth of the chart: past that the names cost more plot
  // than they are worth, and the legend already carries every one of them.
  return Math.max(MIN, Math.min(needed, Math.floor(width / 6)));
}

/** Short label for chart lines: last name when available, else last word of full_name. */
function riderLabel(r: RiderSeries): string {
  if (r.lastName) return r.lastName;
  const parts = r.name.trim().split(" ");
  return parts[parts.length - 1];
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
      <div>Gap: ${fmtGap(point.gcGapSeconds, point.gcRank)}${
        rider.adj?.includes(point.stage) ? " *" : ""}</div>
      ${rider.adj?.includes(point.stage)
        ? `<div class="t-adj">* time awarded, not raced — credited with a group's `
          + `time while keeping the place he finished in</div>`
        : ""}
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
