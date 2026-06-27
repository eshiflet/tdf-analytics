import * as d3 from "d3";
import type { GcDataset, RiderSeries, RiderStagePoint, StageInfo } from "./types";

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
let currentMetric: "gc" | "points" | "kom" = "gc";

let dataset: GcDataset;
let selected: Set<string> = new Set();
let highlighted: string | null = null;
let colorScale: d3.ScaleOrdinal<string, string>;

// Per-dataset points/KOM rankings, recomputed on year change.
let pointsRankAtStage = new Map<number, Map<string, number>>();
let finalPointsRank = new Map<string, number>();
let ridersAtFinalPointsRank = new Map<number, { riders: RiderSeries[]; points: number }>();

let komRankAtStage = new Map<number, Map<string, number>>();
let finalKomRank = new Map<string, number>();
let ridersAtFinalKomRank = new Map<number, { riders: RiderSeries[]; points: number }>();

const chartEl = document.getElementById("chart") as HTMLDivElement;
const overviewChartEl = document.getElementById("overview-chart") as HTMLDivElement;
const legendEl = document.getElementById("legend") as HTMLDivElement;
const sidebarEl = document.getElementById("sidebar") as HTMLElement;
const tooltipEl = document.getElementById("tooltip") as HTMLDivElement;
const chartAreaEl = tooltipEl.parentElement as HTMLDivElement;
const searchEl = document.getElementById("search") as HTMLInputElement;
const yearSelectEl = document.getElementById("year-select") as HTMLSelectElement;
const metricSelectEl = document.getElementById("metric-select") as HTMLSelectElement;
const viewStageBtn = document.getElementById("view-stage") as HTMLButtonElement;
const viewOverviewBtn = document.getElementById("view-overview") as HTMLButtonElement;
const viewAllRacesBtn = document.getElementById("view-all-races") as HTMLButtonElement;
const allRacesChartEl = document.getElementById("all-races-chart") as HTMLDivElement;
const overviewSummaryEl = document.getElementById("overview-summary") as HTMLElement;
const subtitleStage = document.getElementById("subtitle-stage") as HTMLElement | null;
const subtitleOverview = document.getElementById("subtitle-overview") as HTMLElement;

import allRacesSummaryRaw from "./data/all_races_summary.json";
interface RaceSummary { year: number; totalDistanceKm: number | null; totalElevationM: number | null; gcWinnerTimeSeconds: number | null; slowestFinisherTimeSeconds: number | null; }
const ALL_RACES: RaceSummary[] = allRacesSummaryRaw as RaceSummary[];

let currentView: "stage" | "overview" | "allraces" = "stage";

function fmtTotalTime(seconds: number | null): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function stageLabel(stageNum: number): string {
  return dataset?.stages.find((s) => s.stage_number === stageNum)?.stage_label ?? String(stageNum);
}

function fmtGap(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds === 0) return "leader";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const parts = h > 0 ? [h, m, s] : [m, s];
  return "+" + parts.map((p, i) => (i === 0 ? String(p) : String(p).padStart(2, "0"))).join(":");
}

// ─── Route type colors & difficulty ──────────────────────────────────────────

const ROUTE_COLOR: Record<string, string> = {
  P:   "#9b59b6",  // prologue — purple
  TT:  "#7f8c8d",  // time trial — gray
  TTT: "#95a5a6",  // team TT — light gray
  F:   "#27ae60",  // flat — green
  H:   "#e67e22",  // hilly — orange
  M:   "#e74c3c",  // mountain — red
};

const ROUTE_LABEL: Record<string, string> = {
  P: "Prologue", TT: "Time Trial", TTT: "Team TT",
  F: "Flat", H: "Hilly", M: "Mountain",
};

const ROUTE_MULTIPLIER: Record<string, number> = {
  P: 0.3, TT: 0.5, TTT: 0.6, F: 1.0, H: 1.3, M: 1.8,
};

function difficultyScore(stage: StageInfo): number {
  const vm = stage.vertical_meters ?? 0;
  const dk = stage.distance_km ?? 0;
  if (dk === 0) return 0;
  const mult = ROUTE_MULTIPLIER[stage.route_type ?? "F"] ?? 1.0;
  return (vm * vm) / (dk * 1000) * mult;
}

function drawOverview() {
  overviewChartEl.innerHTML = "";
  const stages = dataset.stages;
  if (!stages.length) return;

  // Totals summary in the topbar
  const totalDist = stages.reduce((s, st) => s + (st.distance_km ?? 0), 0);
  const totalElev = stages.reduce((s, st) => s + (st.vertical_meters ?? 0), 0);
  overviewSummaryEl.innerHTML = `
    <span class="overview-summary-item"><span class="overview-summary-label">Total Distance</span> <span class="overview-summary-value">${Math.round(totalDist).toLocaleString()} km</span></span>
    <span class="overview-summary-sep">·</span>
    <span class="overview-summary-item"><span class="overview-summary-label">Total Elevation</span> <span class="overview-summary-value">${totalElev.toLocaleString()} m</span></span>
  `;

  const containerRect = overviewChartEl.getBoundingClientRect();
  const totalWidth = Math.max(containerRect.width || 800, 600);
  const totalHeight = Math.max(containerRect.height || 500, 400);

  const margin = { top: 12, right: 24, bottom: 32, left: 80 };
  const innerWidth = totalWidth - margin.left - margin.right;

  const panels = [
    { key: "distance",   label: "Distance (km)",      value: (s: StageInfo) => s.distance_km ?? 0 },
    { key: "elevation",  label: "Elevation Gain (m)",  value: (s: StageInfo) => s.vertical_meters ?? 0 },
    { key: "difficulty", label: "Difficulty Score",    value: difficultyScore },
  ];

  const panelHeight = Math.floor((totalHeight - margin.top - margin.bottom - (panels.length - 1) * 12) / panels.length);

  const svg = d3.select(overviewChartEl)
    .append("svg")
    .attr("width", totalWidth)
    .attr("height", totalHeight);

  const stageNums = stages.map((s) => s.stage_number);
  const xScale = d3.scaleBand()
    .domain(stageNums.map(String))
    .range([0, innerWidth])
    .padding(0.15);

  panels.forEach((panel, pi) => {
    const yTop = margin.top + pi * (panelHeight + 12);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${yTop})`);

    const maxVal = d3.max(stages, panel.value) ?? 1;
    const yScale = d3.scaleLinear().domain([0, maxVal * 1.08]).range([panelHeight, 0]);

    // Panel label (rotated vertical)
    g.append("text")
      .attr("class", "overview-panel-label")
      .attr("transform", `translate(${-margin.left + 12},${panelHeight / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .text(panel.label);

    // Y-axis (3 ticks)
    const yAxis = d3.axisLeft(yScale).ticks(3).tickSize(-innerWidth);
    g.append("g")
      .attr("class", "axis y-axis overview-y-axis")
      .call(yAxis)
      .call((ax) => ax.select(".domain").remove())
      .call((ax) => ax.selectAll(".tick line").attr("stroke", "#4a5160").attr("stroke-opacity", 0.4))
      .call((ax) => ax.selectAll(".tick text").attr("x", -6).attr("text-anchor", "end"));

    // Bars
    g.selectAll<SVGRectElement, StageInfo>(".overview-bar")
      .data(stages)
      .join("rect")
      .attr("class", "overview-bar")
      .attr("x", (s) => xScale(String(s.stage_number)) ?? 0)
      .attr("y", (s) => yScale(panel.value(s)))
      .attr("width", xScale.bandwidth())
      .attr("height", (s) => panelHeight - yScale(panel.value(s)))
      .attr("rx", 2)
      .attr("fill", (s) => ROUTE_COLOR[s.route_type ?? "F"] ?? ROUTE_COLOR.F)
      .on("mousemove", (event: MouseEvent, s: StageInfo) => {
        const diff = difficultyScore(s);
        tooltipEl.innerHTML = `
          <div class="t-name">Stage ${s.stage_label}</div>
          <div class="t-team">${s.start_location ?? "—"} → ${s.finish_location ?? "—"}</div>
          <div>${ROUTE_LABEL[s.route_type ?? "F"] ?? s.route_type}</div>
          <div>Distance: ${s.distance_km != null ? Math.round(s.distance_km) + " km" : "—"}</div>
          <div>Elevation: ${s.vertical_meters != null ? s.vertical_meters.toLocaleString() + " m" : "—"}</div>
          <div>Difficulty: ${diff.toFixed(1)}</div>
        `;
        tooltipEl.hidden = false;
        const areaRect = chartAreaEl.getBoundingClientRect();
        tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
        const tw = tooltipEl.offsetWidth;
        tooltipEl.style.left = window.innerWidth - event.clientX < tw + 24
          ? `${event.clientX - areaRect.left - tw - 10}px`
          : `${event.clientX - areaRect.left + 24}px`;
      })
      .on("mouseleave", () => hideTooltip());

    // X-axis on last panel only
    if (pi === panels.length - 1) {
      g.append("g")
        .attr("class", "axis x-axis")
        .attr("transform", `translate(0,${panelHeight})`)
        .call(
          d3.axisBottom(xScale)
            .tickFormat((d) => {
              const s = stages.find((st) => String(st.stage_number) === d);
              return s?.stage_label ?? d;
            })
        )
        .call((ax) => ax.select(".domain").remove())
        .call((ax) => ax.selectAll(".tick line").remove());
    }
  });

  // Route type legend below the chart
  const legendData = [...new Set(stages.map((s) => s.route_type ?? "F"))].sort();
  const legendDiv = document.createElement("div");
  legendDiv.className = "route-legend";
  legendDiv.style.paddingLeft = `${margin.left}px`;
  for (const rt of legendData) {
    const item = document.createElement("div");
    item.className = "route-legend-item";
    const swatch = document.createElement("div");
    swatch.className = "route-legend-swatch";
    swatch.style.background = ROUTE_COLOR[rt] ?? "#888";
    const label = document.createElement("span");
    label.textContent = ROUTE_LABEL[rt] ?? rt;
    item.appendChild(swatch);
    item.appendChild(label);
    legendDiv.appendChild(item);
  }
  overviewChartEl.appendChild(legendDiv);
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
    currentMetric = metricSelectEl.value as "gc" | "points" | "kom";
    applyDefaultSelection(20);
    document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
      b.classList.remove("active"),
    );
    document.querySelector<HTMLButtonElement>('.button-row button[data-preset="20"]')?.classList.add("active");
    buildLegend();
    drawChart();
  });
}

function buildRankMapsFromField(
  getRank: (sp: RiderStagePoint) => number | null | undefined,
  getCumPts: (sp: RiderStagePoint) => number,
): {
  rankAtStage: Map<number, Map<string, number>>;
  finalRank: Map<string, number>;
  ridersAtFinal: Map<number, { riders: RiderSeries[]; points: number }>;
} {
  const rankAtStage = new Map<number, Map<string, number>>();
  for (const stage of dataset.stages) {
    const n = stage.stage_number;
    const rankMap = new Map<string, number>();
    for (const rider of dataset.riders) {
      const sp = rider.byStage.find((p) => p.stage === n);
      if (sp) {
        const rank = getRank(sp);
        if (rank != null) rankMap.set(rider.id, rank);
      }
    }
    rankAtStage.set(n, rankMap);
  }
  // Build finalRank from each rider's last byStage entry so that DNF'd riders
  // (who have no byStage entry for the actual last stage) are still ranked
  // correctly when their rank was back-filled by the export pipeline.
  const finalRank = new Map<string, number>();
  for (const rider of dataset.riders) {
    if (rider.byStage.length === 0) continue;
    const lastSp = rider.byStage[rider.byStage.length - 1];
    const rank = getRank(lastSp);
    if (rank != null) finalRank.set(rider.id, rank);
  }
  const ridersAtFinal = new Map<number, { riders: RiderSeries[]; points: number }>();
  for (const rider of dataset.riders) {
    const rank = finalRank.get(rider.id);
    if (rank === undefined) continue;
    const lastSp = rider.byStage.length > 0 ? rider.byStage[rider.byStage.length - 1] : undefined;
    const ptsVal = lastSp ? getCumPts(lastSp) : 0;
    if (!ridersAtFinal.has(rank)) ridersAtFinal.set(rank, { riders: [], points: ptsVal });
    ridersAtFinal.get(rank)!.riders.push(rider);
  }
  return { rankAtStage, finalRank, ridersAtFinal };
}

function computePointsRankings() {
  ({ rankAtStage: pointsRankAtStage, finalRank: finalPointsRank, ridersAtFinal: ridersAtFinalPointsRank } =
    buildRankMapsFromField((sp) => sp.sprintRank, (sp) => sp.cumulativePoints));
  ({ rankAtStage: komRankAtStage, finalRank: finalKomRank, ridersAtFinal: ridersAtFinalKomRank } =
    buildRankMapsFromField((sp) => sp.komRank, (sp) => sp.cumulativeKomPoints));
}

function activeRankMap(stageNum: number): Map<string, number> | undefined {
  if (currentMetric === "kom") return komRankAtStage.get(stageNum);
  return pointsRankAtStage.get(stageNum);
}

/** Return the "active" rank for a rider at a given stage under the current metric. */
function getActiveRank(riderId: string, stageNum: number): number | null {
  if (currentMetric === "gc") {
    const sp = dataset.riders.find((r) => r.id === riderId)?.byStage.find((p) => p.stage === stageNum);
    return sp?.gcRank ?? null;
  }
  const rider = dataset.riders.find((r) => r.id === riderId);
  if (!rider?.byStage.some((p) => p.stage === stageNum)) return null;
  return activeRankMap(stageNum)?.get(riderId) ?? null;
}

/** Build the rank series for a rider to feed into d3 line/dot/label rendering. */
function getDisplayPoints(rider: RiderSeries): Array<{ stage: number; rank: number | null }> {
  if (currentMetric === "gc") {
    return rider.byStage.map((p) => ({ stage: p.stage, rank: p.gcRank }));
  }
  return rider.byStage.map((p) => ({
    stage: p.stage,
    rank: activeRankMap(p.stage)?.get(rider.id) ?? null,
  }));
}

/** Returns the "effective final rank" for a rider under the current metric. */
function effectiveFinalRank(rider: RiderSeries): number {
  if (currentMetric === "gc") return rider.finalRank;
  if (currentMetric === "kom") return finalKomRank.get(rider.id) ?? 9999;
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

  viewOverviewBtn.textContent = `${currentYear} Race Overview`;

  buildLegend();
  if (currentView === "stage") drawChart();
  else drawOverview();
}

function switchView(view: "stage" | "overview" | "allraces") {
  currentView = view;
  viewStageBtn.classList.toggle("active", view === "stage");
  viewOverviewBtn.classList.toggle("active", view === "overview");
  viewAllRacesBtn.classList.toggle("active", view === "allraces");
  if (subtitleStage) subtitleStage.hidden = view !== "stage";
  subtitleOverview.hidden = view !== "overview";
  chartEl.classList.toggle("hidden", view !== "stage");
  sidebarEl.classList.toggle("hidden", view !== "stage");
  overviewChartEl.classList.toggle("visible", view === "overview");
  overviewSummaryEl.hidden = view !== "overview";
  allRacesChartEl.classList.toggle("visible", view === "allraces");
  if (view === "stage") drawChart();
  else if (view === "overview") drawOverview();
  else drawAllRacesOverview();
}

function drawAllRacesOverview() {
  allRacesChartEl.innerHTML = "";

  const containerRect = allRacesChartEl.getBoundingClientRect();
  const totalWidth = Math.max(containerRect.width || 800, 600);
  const totalHeight = Math.max(containerRect.height || 500, 400);
  const margin = { top: 20, right: 36, bottom: 40, left: 80 };
  const innerWidth = totalWidth - margin.left - margin.right;

  type SeriesDef = {
    value: (r: RaceSummary) => number | null;
    fmt: (v: number) => string;
    label: string;     // legend / tooltip label
    color: string;
  };
  type PanelDef = { yLabel: string; series: SeriesDef[] };

  const speed = (distKm: number | null, timeSec: number | null) =>
    distKm && timeSec ? distKm / (timeSec / 3600) : null;

  const panels: PanelDef[] = [
    {
      yLabel: "Distance (km)",
      series: [{
        label: "Total Distance",
        value: (r) => r.totalDistanceKm,
        fmt: (v) => `${Math.round(v).toLocaleString()} km`,
        color: "var(--accent)",
      }],
    },
    {
      yLabel: "Elevation (m)",
      series: [{
        label: "Total Elevation",
        value: (r) => r.totalElevationM,
        fmt: (v) => `${Math.round(v).toLocaleString()} m`,
        color: "var(--accent)",
      }],
    },
    {
      yLabel: "Winner Time (h)",
      series: [{
        label: "GC Winner Time",
        value: (r) => r.gcWinnerTimeSeconds != null ? r.gcWinnerTimeSeconds / 3600 : null,
        fmt: (v) => `${v.toFixed(1)} h`,
        color: "var(--accent)",
      }],
    },
    {
      yLabel: "Avg Speed (km/h)",
      series: [
        {
          label: "GC Winner",
          value: (r) => speed(r.totalDistanceKm, r.gcWinnerTimeSeconds),
          fmt: (v) => `${v.toFixed(1)} km/h`,
          color: "#22c55e",
        },
        {
          label: "Slowest Finisher",
          value: (r) => speed(r.totalDistanceKm, r.slowestFinisherTimeSeconds),
          fmt: (v) => `${v.toFixed(1)} km/h`,
          color: "#ef4444",
        },
      ],
    },
  ];

  const panelHeight = Math.floor(
    (totalHeight - margin.top - margin.bottom - (panels.length - 1) * 16) / panels.length
  );

  const svg = d3.select(allRacesChartEl)
    .append("svg")
    .attr("width", totalWidth)
    .attr("height", totalHeight)
    .attr("viewBox", `0 0 ${totalWidth} ${totalHeight}`);

  const minYear = ALL_RACES[0].year;
  const maxYear = ALL_RACES[ALL_RACES.length - 1].year;
  const xScale = d3.scaleLinear()
    .domain([minYear, maxYear])
    .range([0, innerWidth]);

  const tickYears = d3.range(1910, maxYear + 1, 10).filter((y) => y <= maxYear);

  panels.forEach((panel, pi) => {
    const yTop = margin.top + pi * (panelHeight + 16);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${yTop})`);

    // y domain spans all series in this panel
    const allVals = panel.series.flatMap((s) =>
      ALL_RACES.map((r) => s.value(r)).filter((v): v is number => v != null)
    );
    const maxVal = d3.max(allVals) ?? 1;
    const minVal = panel.series.length > 1 ? (d3.min(allVals) ?? 0) * 0.97 : 0;
    const yScale = d3.scaleLinear().domain([minVal, maxVal * 1.03]).range([panelHeight, 0]);

    // Panel y-label
    g.append("text")
      .attr("class", "overview-panel-label")
      .attr("transform", `translate(${-margin.left + 12},${panelHeight / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .text(panel.yLabel);

    // War-year shaded bands (draw before data lines so they sit behind)
    [{ start: 1914.5, end: 1918.5, label: "WWI" },
     { start: 1939.5, end: 1946.5, label: "WWII" }].forEach(({ start, end, label }) => {
      const bx = xScale(start);
      const bw = xScale(end) - bx;
      g.append("rect")
        .attr("x", bx).attr("y", 0)
        .attr("width", bw).attr("height", panelHeight)
        .attr("fill", "rgba(239,68,68,0.14)")
        .attr("pointer-events", "none");
      // Label on top panel only to avoid repetition
      if (pi === 0) {
        g.append("text")
          .attr("x", bx + bw / 2).attr("y", panelHeight / 2)
          .attr("text-anchor", "middle").attr("dominant-baseline", "middle")
          .attr("font-size", "11px").attr("fill", "rgba(239,68,68,0.45)")
          .attr("pointer-events", "none")
          .text(label);
      }
    });

    // Y gridlines — y=0 tick gets a brighter stroke
    g.append("g")
      .attr("class", "axis y-axis overview-y-axis")
      .call(d3.axisLeft(yScale).ticks(4).tickSize(-innerWidth))
      .call((ax) => ax.select(".domain").remove())
      .call((ax) => ax.selectAll(".tick line").attr("stroke", "#4a5160").attr("stroke-opacity", 0.4))
      .call((ax) => ax.selectAll<SVGGElement, number>(".tick").filter((d) => d === 0)
        .select("line").attr("stroke", "#8a9ab0").attr("stroke-opacity", 0.85))
      .call((ax) => ax.selectAll(".tick text").attr("x", -6).attr("text-anchor", "end"));

    // Draw each series
    panel.series.forEach((s, si) => {
      const defined = (r: RaceSummary) => s.value(r) != null;
      const lineGen = d3.line<RaceSummary>()
        .defined(defined)
        .x((r) => xScale(r.year))
        .y((r) => yScale(s.value(r) as number))
        .curve(d3.curveMonotoneX);

      g.append("path")
        .datum(ALL_RACES)
        .attr("fill", "none")
        .attr("stroke", s.color)
        .attr("stroke-width", 1.5)
        .attr("d", lineGen);

      g.selectAll<SVGCircleElement, RaceSummary>(`.all-races-dot-s${si}`)
        .data(ALL_RACES.filter(defined))
        .join("circle")
        .attr("class", `all-races-dot all-races-dot-s${si}`)
        .attr("cx", (r) => xScale(r.year))
        .attr("cy", (r) => yScale(s.value(r) as number))
        .attr("r", 3)
        .attr("fill", s.color)
        .on("mousemove", (event: MouseEvent, r: RaceSummary) => {
          const val = s.value(r)!;
          tooltipEl.innerHTML = `
            <div class="t-name">${r.year} Tour de France</div>
            <div>${s.label}: ${s.fmt(val)}</div>
          `;
          tooltipEl.hidden = false;
          const areaRect = allRacesChartEl.getBoundingClientRect();
          tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
          const tw = tooltipEl.offsetWidth;
          tooltipEl.style.left = window.innerWidth - event.clientX < tw + 24
            ? `${event.clientX - areaRect.left - tw - 10}px`
            : `${event.clientX - areaRect.left + 24}px`;
        })
        .on("mouseleave", () => hideTooltip());
    });

    // Legend for multi-series panels
    if (panel.series.length > 1) {
      panel.series.forEach((s, si) => {
        const lx = innerWidth - 160 + si * 100;
        g.append("line")
          .attr("x1", lx).attr("x2", lx + 18)
          .attr("y1", 8).attr("y2", 8)
          .attr("stroke", s.color).attr("stroke-width", 2);
        g.append("text")
          .attr("x", lx + 22).attr("y", 8)
          .attr("dominant-baseline", "middle")
          .attr("font-size", "11px")
          .attr("fill", "var(--text-muted, #888)")
          .text(s.label);
      });
    }

    // Vertical gridlines
    g.append("g")
      .attr("class", "axis x-axis all-races-x-grid")
      .attr("transform", `translate(0,${panelHeight})`)
      .call(
        d3.axisBottom(xScale)
          .tickValues(tickYears)
          .tickSize(-panelHeight)
          .tickFormat(() => "")
      )
      .call((ax) => ax.select(".domain").remove())
      .call((ax) => ax.selectAll(".tick line")
        .attr("stroke", "#4a5160")
        .attr("stroke-opacity", 0.4));

    // Decade tick marks on every panel's bottom edge
    g.append("g")
      .attr("class", "axis x-axis all-races-x-ticks")
      .attr("transform", `translate(0,${panelHeight})`)
      .call(
        d3.axisBottom(xScale)
          .tickValues(tickYears)
          .tickSize(4)
          .tickFormat(() => "")
      )
      .call((ax) => ax.select(".domain").remove())
      .call((ax) => ax.selectAll(".tick line")
        .attr("stroke", "#8a9ab0")
        .attr("stroke-opacity", 0.7));

    // X-axis labels on last panel only
    if (pi === panels.length - 1) {
      g.append("g")
        .attr("class", "axis x-axis")
        .attr("transform", `translate(0,${panelHeight})`)
        .call(
          d3.axisBottom(xScale)
            .tickValues(tickYears)
            .tickFormat((y) => String(y))
        )
        .call((ax) => ax.select(".domain").remove())
        .call((ax) => ax.selectAll(".tick line").remove());
    }
  });
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

  viewStageBtn.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).tagName === "SELECT") return; // let metric-select handle its own clicks
    switchView("stage");
  });
  viewOverviewBtn.addEventListener("click", () => switchView("overview"));
  viewAllRacesBtn.addEventListener("click", () => switchView("allraces"));
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
  const minStage = d3.min(stages, (s) => s.stage_number) ?? 0;
  const maxStage = d3.max(stages, (s) => s.stage_number) ?? 21;

  // Determine y-axis domain from the display points of all riders
  let maxRank = 1;
  for (const r of dataset.riders) {
    for (const dp of getDisplayPoints(r)) {
      if (dp.rank !== null) maxRank = Math.max(maxRank, dp.rank);
    }
  }

  xScale = d3.scaleLinear().domain([minStage, maxStage]).range([0, innerWidth]);
  yScale = d3.scaleLinear().domain([1, maxRank]).range([0, innerHeight]);

  const svg = d3
    .select(chartEl)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`);

  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

  // No-data overlays for classifications that didn't exist yet
  const noDataMessage =
    currentMetric === "points" && parseInt(currentYear) < 1953
      ? "No data because the green jersey sprint points competition started in 1953"
      : currentMetric === "kom" && parseInt(currentYear) < 1933
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
        .tickValues(d3.range(minStage, maxStage + 1))
        .tickSize(-innerHeight)
        .tickFormat(() => ""),
    );

  const stagesByNumber = new Map(stages.map((s) => [s.stage_number, s]));
  const stageLabelFmt = (d: d3.NumberValue) => stagesByNumber.get(+d)?.stage_label ?? String(d);

  // x axis — bottom
  g.append("g")
    .attr("class", "axis x-axis")
    .attr("transform", `translate(0,${innerHeight})`)
    .call(
      d3
        .axisBottom(xScale)
        .ticks(maxStage)
        .tickFormat(stageLabelFmt),
    );

  // x axis — top (with stage-info hover)
  const xAxisTop = g
    .append("g")
    .attr("class", "axis x-axis x-axis-top")
    .call(
      d3
        .axisTop(xScale)
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

  const yLabel = currentMetric === "gc" ? "GC position" : currentMetric === "kom" ? "KOM rank" : "Points rank";
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
    .text((r) => {
      if (currentMetric !== "gc") {
        const isKom = currentMetric === "kom";
        const finalRank = isKom ? finalKomRank : finalPointsRank;
        const ridersAtFinal = isKom ? ridersAtFinalKomRank : ridersAtFinalPointsRank;
        const group = ridersAtFinal.get(finalRank.get(r.id)!);
        if (group && group.riders.length > 1) return `(${group.riders.length}) ${lastName(r.name)}`;
      }
      return lastName(r.name);
    })
    .style("cursor", (r) => currentMetric === "gc" ? "default" : "pointer")
    .on("mouseover", (event: MouseEvent, r: RiderSeries) => {
      if (currentMetric === "gc") {
        const lastStage = r.byStage[r.byStage.length - 1];
        const gcRank = lastStage?.gcRank ?? r.finalRank;
        const gap = lastStage?.gcGapSeconds ?? null;
        const gcWinner = dataset.riders.find((rd) => rd.finalRank === 1);
        const winnerTime = fmtTotalTime(gcWinner?.totalTimeSeconds ?? null);
        const timeStr = gap === 0 || gcRank === 1
          ? winnerTime
          : fmtGap(gap);
        tooltipEl.innerHTML = `
          <div class="t-name">${r.name}</div>
          <div class="t-team">${r.team ?? ""}</div>
          <div>GC #${gcRank ?? "—"} &middot; ${timeStr}</div>
        `;
        tooltipEl.hidden = false;
        const areaRect = chartAreaEl.getBoundingClientRect();
        tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
        const tw = tooltipEl.offsetWidth;
        tooltipEl.style.left = window.innerWidth - event.clientX < tw + 24
          ? `${event.clientX - areaRect.left - tw - 10}px`
          : `${event.clientX - areaRect.left + 24}px`;
        return;
      }
      const isKom = currentMetric === "kom";
      const finalRank = isKom ? finalKomRank : finalPointsRank;
      const ridersAtFinal = isKom ? ridersAtFinalKomRank : ridersAtFinalPointsRank;
      const rank = finalRank.get(r.id);
      if (rank === undefined) return;
      const group = ridersAtFinal.get(rank);
      if (!group) return;
      const label = isKom ? "KOM" : "Points";
      const names = group.riders.map((rd) => rd.name).join("<br>");
      tooltipEl.innerHTML = `
        <div class="t-name">Final ${label} Rank #${rank}</div>
        <div class="t-team">${group.points} pts</div>
        <div>${names}</div>
      `;
      tooltipEl.hidden = false;
      const areaRect = chartAreaEl.getBoundingClientRect();
      tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
      const tw = tooltipEl.offsetWidth;
      tooltipEl.style.left = window.innerWidth - event.clientX < tw + 24
        ? `${event.clientX - areaRect.left - tw - 10}px`
        : `${event.clientX - areaRect.left + 24}px`;
    })
    .on("mouseout", () => { tooltipEl.hidden = true; });

  updateLineClasses();

  window.addEventListener("resize", debounce(() => {
    if (currentView === "stage") drawChart(); else drawOverview();
  }, 200));
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
      <div>Stage ${stageLabel(point.stage)} &middot; GC #${point.gcRank ?? "—"}</div>
      <div>Gap: ${fmtGap(point.gcGapSeconds)}</div>
      ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
    `;
  } else {
    const point =
      rider.byStage.find((p) => p.stage === stageGuess) ??
      rider.byStage[rider.byStage.length - 1];
    if (!point) return;
    if (currentMetric === "kom") {
      const komRank = komRankAtStage.get(point.stage)?.get(rider.id) ?? null;
      tooltipEl.innerHTML = `
        <div class="t-name">${rider.name}</div>
        <div class="t-team">${rider.team ?? ""}</div>
        <div>Stage ${stageLabel(point.stage)} &middot; KOM rank #${komRank ?? "—"}</div>
        <div>Cumulative KOM pts: ${point.cumulativeKomPoints}</div>
        ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
      `;
    } else {
      const ptsRank = pointsRankAtStage.get(point.stage)?.get(rider.id) ?? null;
      tooltipEl.innerHTML = `
        <div class="t-name">${rider.name}</div>
        <div class="t-team">${rider.team ?? ""}</div>
        <div>Stage ${stageLabel(point.stage)} &middot; Points rank #${ptsRank ?? "—"}</div>
        <div>Cumulative pts: ${point.cumulativePoints}</div>
        ${point.status !== "FINISHED" ? `<div style="color:#ff6b6b">${point.status}</div>` : ""}
      `;
    }
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
