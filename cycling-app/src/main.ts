import * as d3 from "d3";
import type { GcDataset, RiderSeries, StageInfo } from "./types";

const PALETTE = [
  "#ffce00", "#ff6b6b", "#4dabf7", "#69db7c", "#da77f2",
  "#ff922b", "#22b8cf", "#f783ac", "#94d82d", "#9775fa",
  "#ffa94d", "#3bc9db", "#ff8787", "#63e6be", "#e599f7",
  "#74c0fc", "#ffd43b", "#b2f2bb", "#eebefa", "#a9e34b",
];

// Auto-discover every per-year dataset bundled under ./data — adding a new
// year is just a matter of dropping a new gc_by_stage_{year}.json file here,
// no code changes needed.
const yearModules = import.meta.glob<GcDataset>("./data/gc_by_stage_*.json", {
  eager: true,
  import: "default",
});
const DATASETS_BY_YEAR: Record<string, GcDataset> = {};
for (const [path, data] of Object.entries(yearModules)) {
  const match = path.match(/gc_by_stage_(\d+)\.json$/);
  if (match) DATASETS_BY_YEAR[match[1]] = data;
}
const YEARS = Object.keys(DATASETS_BY_YEAR).sort().reverse();
let currentYear = YEARS[0];
let currentMetric: "gc" | "points" = "gc";

let dataset: GcDataset;
let selected: Set<string> = new Set();
let highlighted: string | null = null;
let colorScale: d3.ScaleOrdinal<string, string>;

// Per-dataset points rankings, recomputed on year change.
// pointsRankAtStage: stageNumber → riderId → rank (1 = most points)
let pointsRankAtStage = new Map<number, Map<string, number>>();
// finalPointsRank: riderId → rank at last stage (used for "Top N" preset)
let finalPointsRank = new Map<string, number>();

const chartEl = document.getElementById("chart") as HTMLDivElement;
const legendEl = document.getElementById("legend") as HTMLDivElement;
const tooltipEl = document.getElementById("tooltip") as HTMLDivElement;
const chartAreaEl = tooltipEl.parentElement as HTMLDivElement;
const searchEl = document.getElementById("search") as HTMLInputElement;
const yearSelectEl = document.getElementById("year-select") as HTMLSelectElement;
const metricSelectEl = document.getElementById("metric-select") as HTMLSelectElement;

function fmtGap(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds === 0) return "leader";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const parts = h > 0 ? [h, m, s] : [m, s];
  return "+" + parts.map((p, i) => (i === 0 ? String(p) : String(p).padStart(2, "0"))).join(":");
}

function init() {
  try {
    buildYearSelect();
    buildMetricSelect();
    loadDataset(currentYear);
    wireControls();
  } catch (err) {
    chartEl.innerHTML = `<p style="color:#ff6b6b">Failed to load data: ${err}</p>`;
    console.error(err);
  }
}

function buildYearSelect() {
  yearSelectEl.innerHTML = "";
  for (const year of YEARS) {
    const opt = document.createElement("option");
    opt.value = year;
    opt.textContent = year;
    yearSelectEl.appendChild(opt);
  }
  yearSelectEl.value = currentYear;
  yearSelectEl.addEventListener("change", () => {
    currentYear = yearSelectEl.value;
    loadDataset(currentYear);
  });
}

function buildMetricSelect() {
  metricSelectEl.value = currentMetric;
  metricSelectEl.addEventListener("change", () => {
    currentMetric = metricSelectEl.value as "gc" | "points";
    // re-apply default selection for new metric
    applyDefaultSelection();
    buildLegend();
    drawChart();
  });
}

/** Recompute pointsRankAtStage and finalPointsRank for the current dataset. */
function computePointsRankings() {
  pointsRankAtStage = new Map();

  // Build a quick lookup: riderId → (stageNum → cumulativePoints)
  const cumPtsByRider = new Map<string, Map<number, number>>();
  for (const rider of dataset.riders) {
    const m = new Map<number, number>();
    for (const sp of rider.byStage) m.set(sp.stage, sp.cumulativePoints);
    cumPtsByRider.set(rider.id, m);
  }

  for (const stage of dataset.stages) {
    const n = stage.stage_number;
    // Only include riders who actually have a result at this stage
    const entries: Array<[string, number]> = [];
    for (const rider of dataset.riders) {
      const pts = cumPtsByRider.get(rider.id)?.get(n);
      if (pts !== undefined) entries.push([rider.id, pts]);
    }
    // Sort descending (most points first)
    entries.sort((a, b) => b[1] - a[1]);
    // Dense rank
    const rankMap = new Map<string, number>();
    let rank = 1;
    for (let i = 0; i < entries.length; i++) {
      if (i > 0 && entries[i][1] < entries[i - 1][1]) rank = i + 1;
      rankMap.set(entries[i][0], rank);
    }
    pointsRankAtStage.set(n, rankMap);
  }

  // Final points rank = rank at the last stage
  const lastStageNum = dataset.stages[dataset.stages.length - 1]?.stage_number;
  finalPointsRank = new Map(pointsRankAtStage.get(lastStageNum ?? -1) ?? []);
}

/** Return the "active" rank for a rider at a given stage under the current metric. */
function getActiveRank(riderId: string, stageNum: number): number | null {
  if (currentMetric === "gc") {
    const sp = dataset.riders.find((r) => r.id === riderId)?.byStage.find((p) => p.stage === stageNum);
    return sp?.gcRank ?? null;
  } else {
    // Only defined at stages where the rider has a byStage entry
    const rider = dataset.riders.find((r) => r.id === riderId);
    if (!rider?.byStage.some((p) => p.stage === stageNum)) return null;
    return pointsRankAtStage.get(stageNum)?.get(riderId) ?? null;
  }
}

/** Build the rank series for a rider to feed into d3 line/dot/label rendering. */
function getDisplayPoints(rider: RiderSeries): Array<{ stage: number; rank: number | null }> {
  if (currentMetric === "gc") {
    return rider.byStage.map((p) => ({ stage: p.stage, rank: p.gcRank }));
  } else {
    return rider.byStage.map((p) => ({
      stage: p.stage,
      rank: pointsRankAtStage.get(p.stage)?.get(rider.id) ?? null,
    }));
  }
}

/** Returns the "effective final rank" for a rider under the current metric. */
function effectiveFinalRank(rider: RiderSeries): number {
  if (currentMetric === "gc") return rider.finalRank;
  return finalPointsRank.get(rider.id) ?? 9999;
}

function applyDefaultSelection(preset = 20) {
  selected = new Set(dataset.riders.filter((r) => effectiveFinalRank(r) <= preset).map((r) => r.id));
}

function loadDataset(year: string) {
  dataset = DATASETS_BY_YEAR[year];
  colorScale = d3
    .scaleOrdinal<string, string>()
    .domain(dataset.riders.map((r) => r.id))
    .range(PALETTE);

  computePointsRankings();
  applyDefaultSelection(20);

  highlighted = null;
  searchEl.value = "";
  document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
    b.classList.remove("active"),
  );
  document.querySelector<HTMLButtonElement>('.button-row button[data-preset="20"]')?.classList.add(
    "active",
  );

  buildLegend();
  drawChart();
}

function wireControls() {
  document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
        b.classList.remove("active"),
      );
      btn.classList.add("active");
      const preset = btn.dataset.preset;
      if (preset === "all") {
        selected = new Set(dataset.riders.map((r) => r.id));
      } else if (preset === "none") {
        selected = new Set();
      } else {
        const n = parseInt(preset ?? "20", 10);
        applyDefaultSelection(n);
      }
      refreshLegendState();
      updateLineClasses();
    });
  });

  searchEl.addEventListener("input", () => {
    const q = searchEl.value.trim().toLowerCase();
    if (!q) {
      highlighted = null;
      updateLineClasses();
      refreshLegendState();
      return;
    }
    const match = dataset.riders.find((r) => r.name.toLowerCase().includes(q));
    if (match) {
      selected.add(match.id);
      highlighted = match.id;
      const legendRow = legendEl.querySelector<HTMLDivElement>(`[data-id="${cssEscape(match.id)}"]`);
      legendRow?.scrollIntoView({ block: "nearest" });
    }
    refreshLegendState();
    updateLineClasses();
  });
}

function cssEscape(s: string): string {
  return s.replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
}

function buildLegend() {
  legendEl.innerHTML = "";
  // Sort legend by effective final rank for the current metric
  const sorted = [...dataset.riders].sort((a, b) => effectiveFinalRank(a) - effectiveFinalRank(b));
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
    name.textContent = rider.name;
    name.title = `${rider.name} — ${rider.team ?? ""}`;

    row.appendChild(rank);
    row.appendChild(swatch);
    row.appendChild(name);

    row.addEventListener("click", () => {
      if (selected.has(rider.id)) {
        selected.delete(rider.id);
      } else {
        selected.add(rider.id);
      }
      refreshLegendState();
      updateLineClasses();
    });

    row.addEventListener("mouseenter", () => {
      highlighted = rider.id;
      updateLineClasses();
    });
    row.addEventListener("mouseleave", () => {
      highlighted = null;
      updateLineClasses();
    });

    legendEl.appendChild(row);
  }
  refreshLegendState();
}

function refreshLegendState() {
  legendEl.querySelectorAll<HTMLDivElement>(".legend-item").forEach((row) => {
    const id = row.dataset.id!;
    const isSelected = selected.has(id);
    row.classList.toggle("active", isSelected);
    const swatch = row.querySelector<HTMLSpanElement>(".legend-swatch")!;
    swatch.style.background = isSelected ? colorScale(id) : "var(--line-dim)";
  });
}

let xScale: d3.ScaleLinear<number, number>;
let yScale: d3.ScaleLinear<number, number>;

function drawChart() {
  chartEl.innerHTML = "";
  const containerRect = chartEl.getBoundingClientRect();
  const width = Math.max(containerRect.width, 600);
  const height = Math.max(containerRect.height, 480);
  const margin = { top: 32, right: 36, bottom: 36, left: 44 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const stages = dataset.stages;
  const maxStage = d3.max(stages, (s) => s.stage_number) ?? 21;

  // Determine y-axis domain from the display points of all riders
  let maxRank = 1;
  for (const r of dataset.riders) {
    for (const dp of getDisplayPoints(r)) {
      if (dp.rank !== null) maxRank = Math.max(maxRank, dp.rank);
    }
  }

  xScale = d3.scaleLinear().domain([1, maxStage]).range([0, innerWidth]);
  yScale = d3.scaleLinear().domain([1, maxRank]).range([0, innerHeight]);

  const svg = d3
    .select(chartEl)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`);

  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

  // gridlines (horizontal, every 10 ranks)
  const yTickValues = d3.range(10, maxRank + 1, 10);
  g.append("g")
    .attr("class", "grid grid-y")
    .call(
      d3
        .axisLeft(yScale)
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
        .axisBottom(xScale)
        .tickValues(d3.range(1, maxStage + 1))
        .tickSize(-innerHeight)
        .tickFormat(() => ""),
    );

  // x axis — bottom
  g.append("g")
    .attr("class", "axis x-axis")
    .attr("transform", `translate(0,${innerHeight})`)
    .call(
      d3
        .axisBottom(xScale)
        .ticks(maxStage)
        .tickFormat((d) => String(d)),
    );

  // x axis — top (with stage-info hover)
  const xAxisTop = g
    .append("g")
    .attr("class", "axis x-axis x-axis-top")
    .call(
      d3
        .axisTop(xScale)
        .ticks(maxStage)
        .tickFormat((d) => String(d)),
    );

  const stagesByNumber = new Map(stages.map((s) => [s.stage_number, s]));
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
    .text("Stage");

  // y axis
  g.append("g")
    .attr("class", "axis y-axis")
    .call(
      d3
        .axisLeft(yScale)
        .tickValues([1, ...yTickValues])
        .tickFormat((d) => `#${d}`),
    );

  const yLabel = currentMetric === "gc" ? "GC position" : "Points rank";
  g.append("text")
    .attr("class", "axis-label")
    .attr("transform", `translate(${-margin.left + 14},${innerHeight / 2}) rotate(-90)`)
    .attr("text-anchor", "middle")
    .text(yLabel);

  const lineGen = d3
    .line<{ stage: number; rank: number | null }>()
    .defined((d) => d.rank !== null)
    .x((d) => xScale(d.stage))
    .y((d) => yScale(d.rank as number))
    .curve(d3.curveMonotoneX);

  const lineLayer = g.append("g").attr("class", "lines");
  const dotLayer = g.append("g").attr("class", "dots");
  const hitLayer = g.append("g").attr("class", "hit-areas");

  lineLayer
    .selectAll<SVGPathElement, RiderSeries>("path")
    .data(dataset.riders, (r) => r.id)
    .join("path")
    .attr("class", "rider-line")
    .attr("data-id", (r) => r.id)
    .attr("d", (r) => lineGen(getDisplayPoints(r)))
    .attr("stroke", "var(--line-dim)");

  // invisible wide hit-path per rider, for easier hover targeting
  hitLayer
    .selectAll<SVGPathElement, RiderSeries>("path")
    .data(dataset.riders, (r) => r.id)
    .join("path")
    .attr("fill", "none")
    .attr("stroke", "transparent")
    .attr("stroke-width", 10)
    .attr("d", (r) => lineGen(getDisplayPoints(r)))
    .style("cursor", "pointer")
    .on("mouseenter", (_event, r) => {
      highlighted = r.id;
      updateLineClasses();
    })
    .on("mousemove", (event, r) => showTooltip(event, r))
    .on("mouseleave", () => {
      highlighted = null;
      updateLineClasses();
      hideTooltip();
    })
    .on("click", (_event, r) => {
      if (selected.has(r.id)) selected.delete(r.id);
      else selected.add(r.id);
      refreshLegendState();
      updateLineClasses();
    });

  // end-of-line dots + labels for selected riders
  dotLayer
    .selectAll<SVGCircleElement, RiderSeries>("circle")
    .data(dataset.riders, (r) => r.id)
    .join("circle")
    .attr("class", "rider-dot")
    .attr("data-id", (r) => r.id)
    .attr("r", 3)
    .attr("cx", (r) => {
      const last = lastDefinedDisplay(r);
      return last ? xScale(last.stage) : -100;
    })
    .attr("cy", (r) => {
      const last = lastDefinedDisplay(r);
      return last ? yScale(last.rank as number) : -100;
    });

  const labelLayer = g.append("g").attr("class", "labels");
  labelLayer
    .selectAll<SVGTextElement, RiderSeries>("text")
    .data(dataset.riders, (r) => r.id)
    .join("text")
    .attr("class", "rider-end-label")
    .attr("data-id", (r) => r.id)
    .attr("x", (r) => {
      const last = lastDefinedDisplay(r);
      return last ? xScale(last.stage) + 6 : -100;
    })
    .attr("y", (r) => {
      const last = lastDefinedDisplay(r);
      return last ? yScale(last.rank as number) + 3 : -100;
    })
    .style("font-size", "10px")
    .text((r) => lastName(r.name));

  updateLineClasses();

  window.addEventListener("resize", debounce(() => drawChart(), 200));
}

function lastDefinedDisplay(r: RiderSeries): { stage: number; rank: number | null } | null {
  const dp = getDisplayPoints(r);
  for (let i = dp.length - 1; i >= 0; i--) {
    if (dp[i].rank !== null) return dp[i];
  }
  return null;
}

function lastName(full: string): string {
  const parts = full.trim().split(" ");
  return parts[parts.length - 1];
}

function updateLineClasses() {
  d3.selectAll<SVGPathElement, unknown>(".lines .rider-line").each(function () {
    const el = d3.select(this as SVGPathElement);
    const id = (this as SVGPathElement).getAttribute("data-id")!;
    const isSelected = selected.has(id);
    const isHighlighted = highlighted === id;
    el.classed("hidden-line", false);
    el.classed("dimmed", !isSelected && !isHighlighted);
    el.classed("highlighted", isHighlighted);
    el.attr("stroke", isSelected || isHighlighted ? colorScale(id) : "var(--line-dim)");
    el.style("stroke-opacity", isHighlighted ? 1 : isSelected ? 0.95 : 0.12);
  });

  d3.selectAll<SVGCircleElement, unknown>(".dots .rider-dot").each(function () {
    const id = (this as SVGCircleElement).getAttribute("data-id")!;
    const isSelected = selected.has(id);
    const isHighlighted = highlighted === id;
    d3.select(this as SVGCircleElement)
      .style("opacity", isSelected || isHighlighted ? 1 : 0)
      .attr("fill", isSelected || isHighlighted ? colorScale(id) : "var(--line-dim)");
  });

  d3.selectAll<SVGTextElement, unknown>(".labels .rider-end-label").each(function () {
    const id = (this as SVGTextElement).getAttribute("data-id")!;
    const isSelected = selected.has(id);
    const isHighlighted = highlighted === id;
    d3.select(this as SVGTextElement)
      .style("opacity", isSelected || isHighlighted ? 1 : 0)
      .attr("fill", isSelected || isHighlighted ? colorScale(id) : "var(--line-dim)");
  });
}

function showTooltip(event: MouseEvent, rider: RiderSeries) {
  const containerRect = chartEl.getBoundingClientRect();
  const margin = { left: 44, top: 16 };
  const mouseX = event.clientX - containerRect.left - margin.left;
  const stageGuess = Math.round(xScale.invert(mouseX));

  if (currentMetric === "gc") {
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
      <div class="t-name">${rider.name}</div>
      <div class="t-team">${rider.team ?? ""}</div>
      <div>Stage ${point.stage} &middot; GC #${point.gcRank ?? "—"}</div>
      <div>Gap: ${fmtGap(point.gcGapSeconds)}</div>
      ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
    `;
  } else {
    // Points mode
    const point =
      rider.byStage.find((p) => p.stage === stageGuess) ??
      rider.byStage[rider.byStage.length - 1];
    if (!point) return;
    const ptsRank = pointsRankAtStage.get(point.stage)?.get(rider.id) ?? null;
    tooltipEl.innerHTML = `
      <div class="t-name">${rider.name}</div>
      <div class="t-team">${rider.team ?? ""}</div>
      <div>Stage ${point.stage} &middot; Points rank #${ptsRank ?? "—"}</div>
      <div>Cumulative pts: ${point.cumulativePoints}</div>
      ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
    `;
  }

  tooltipEl.hidden = false;
  const areaRect = chartAreaEl.getBoundingClientRect();
  tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
  const tooltipWidth = tooltipEl.offsetWidth;
  const spaceOnRight = window.innerWidth - event.clientX;
  if (spaceOnRight < tooltipWidth + 24) {
    tooltipEl.style.left = `${event.clientX - areaRect.left - tooltipWidth - 10}px`;
  } else {
    tooltipEl.style.left = `${event.clientX - areaRect.left + 24}px`;
  }
}

function showStageTooltip(event: MouseEvent, stage: StageInfo) {
  const containerRect = chartEl.getBoundingClientRect();
  const distance = stage.distance_km != null ? `${Math.round(stage.distance_km)} km` : "—";
  const vertical = stage.vertical_meters != null ? `${stage.vertical_meters} m` : "—";
  const type = stage.route_type ?? "—";

  tooltipEl.innerHTML = `
    <div>${stage.start_location ?? "—"}</div>
    <div>${stage.finish_location ?? "—"}</div>
    <div>${distance}, ${vertical}, ${type}</div>
  `;
  tooltipEl.hidden = false;
  const areaRect2 = chartAreaEl.getBoundingClientRect();
  tooltipEl.style.top = `${event.clientY - areaRect2.top - 10}px`;
  const tooltipWidth2 = tooltipEl.offsetWidth;
  const spaceOnRight2 = window.innerWidth - event.clientX;
  if (spaceOnRight2 < tooltipWidth2 + 24) {
    tooltipEl.style.left = `${event.clientX - areaRect2.left - tooltipWidth2 - 10}px`;
  } else {
    tooltipEl.style.left = `${event.clientX - areaRect2.left + 24}px`;
  }
}

function hideTooltip() {
  tooltipEl.hidden = true;
}

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}

// Unused but kept for type-checking completeness
void getActiveRank;

init();
