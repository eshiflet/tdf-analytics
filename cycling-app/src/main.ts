// Modular d3 imports — pulls only the submodules we use instead of the full
// d3 meta-package (which bundles geo, force, hierarchy, zoom, etc. unused here).
import { select, selectAll, type Selection } from "d3-selection";
import { scaleLinear, scaleBand, scaleOrdinal, type ScaleLinear, type ScaleOrdinal } from "d3-scale";
import { axisLeft, axisBottom, axisTop } from "d3-axis";
import { line, curveMonotoneX } from "d3-shape";
import { max, min, range } from "d3-array";
import type { NumberValue } from "d3-scale";

// Thin shim so existing `d3.*` call sites keep working without churn.
const d3 = {
  select, selectAll,
  scaleLinear, scaleBand, scaleOrdinal,
  axisLeft, axisBottom, axisTop,
  line, curveMonotoneX,
  max, min, range,
};

import type { GcDataset, RiderSeries, RiderStagePoint, StageInfo } from "./types";

const PALETTE = [
  "#ffce00", "#ff6b6b", "#4dabf7", "#69db7c", "#da77f2",
  "#ff922b", "#22b8cf", "#f783ac", "#94d82d", "#9775fa",
  "#ffa94d", "#3bc9db", "#ff8787", "#63e6be", "#e599f7",
  "#74c0fc", "#ffd43b", "#b2f2bb", "#eebefa", "#a9e34b",
];

// Auto-discover every per-year dataset under ./data, but only take each
// file's URL (eager ?url glob = a list of tiny strings in the main bundle).
// The data itself is fetched + JSON.parsed on demand, NOT imported as a JS
// module: dynamic import() would pin every visited year in the browser's
// module registry forever, which made LRU eviction below purely cosmetic.
// fetch() keeps the data out of the module graph so evicted years can
// actually be garbage-collected, and JSON.parse is faster than parsing the
// same content as a JS object literal.
// Adding a new year is still just dropping in a gc_by_stage_{year}.json file.
const yearUrls = import.meta.glob<string>("./data/gc_by_stage_*.json", {
  query: "?url",
  import: "default",
  eager: true,
});
const URLS_BY_YEAR: Record<string, string> = {};
for (const [path, url] of Object.entries(yearUrls)) {
  const match = path.match(/gc_by_stage_(\d+)\.json/);
  if (match) URLS_BY_YEAR[match[1]] = url;
}
const YEARS = Object.keys(URLS_BY_YEAR).sort().reverse();

// Bounded LRU of parsed per-year datasets, so a long session that hops between
// many years never grows memory without limit. Re-visiting an evicted year
// re-fetches from the browser's HTTP cache (no network), only re-parsing.
const DATASET_CACHE = new Map<string, GcDataset>();
const DATASET_CACHE_MAX = 6;

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

async function getDataset(year: string): Promise<GcDataset> {
  const cached = DATASET_CACHE.get(year);
  if (cached) {
    // refresh recency
    DATASET_CACHE.delete(year);
    DATASET_CACHE.set(year, cached);
    return cached;
  }
  const ds = await fetchJson<GcDataset>(URLS_BY_YEAR[year]);
  DATASET_CACHE.set(year, ds);
  if (DATASET_CACHE.size > DATASET_CACHE_MAX) {
    const oldest = DATASET_CACHE.keys().next().value;
    if (oldest !== undefined) DATASET_CACHE.delete(oldest);
  }
  return ds;
}
let currentYear = YEARS[0];
let currentMetric: "gc" | "points" | "kom" = "gc";

let dataset: GcDataset;
let selected: Set<string> = new Set();
let highlighted: string | null = null;
// Rider whose career chart is open on the Riders view (null = grid). Only
// consulted for hash routing while currentView === "riders".
let currentRiderId: string | null = null;
let colorScale: ScaleOrdinal<string, string>;

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
const viewRidersBtn = document.getElementById("view-riders") as HTMLButtonElement;
const ridersChartEl = document.getElementById("riders-chart") as HTMLDivElement;
const overviewSummaryEl = document.getElementById("overview-summary") as HTMLElement;
const subtitleStage = document.getElementById("subtitle-stage") as HTMLElement | null;
const subtitleOverview = document.getElementById("subtitle-overview") as HTMLElement;

import allRacesSummaryRaw from "./data/all_races_summary.json";
interface RaceSummary { year: number; totalDistanceKm: number | null; totalElevationM: number | null; gcWinnerTimeSeconds: number | null; slowestFinisherTimeSeconds: number | null; }
const ALL_RACES: RaceSummary[] = allRacesSummaryRaw as RaceSummary[];

let currentView: "stage" | "overview" | "allraces" | "riders" = "stage";

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
  if (!dataset) return; // initial fetch in flight; loadDataset() redraws
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
        positionTooltip(event);
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
    wireControls();
    // Single resize handler for the lifetime of the page — redraws whichever
    // view is active. (Previously re-registered on every drawChart() call,
    // leaking a listener per year/metric switch.)
    window.addEventListener("resize", debounce(() => {
      if (currentView === "stage") drawChart();
      else if (currentView === "overview") drawOverview();
      else if (currentView === "allraces") drawAllRacesOverview();
    }, 200));
    window.addEventListener("hashchange", () => {
      applyHash().catch(showLoadError);
    });
    applyHash()
      .then((handled) => {
        if (!handled) {
          // No (or unrecognized) hash: seed the URL without adding a history
          // entry, then fall through to the default load below.
          window.history.replaceState(null, "", computeHash());
        }
        // Load whenever no dataset is in memory yet. This covers three cases:
        // empty/unrecognized hash, deep links landing on riders/allraces (which
        // need a dataset for later stage/overview navigation), and deep links
        // that exactly match the default state — applyHash() treats those as
        // "already in sync" and returns without loading anything.
        if (!dataset) return loadDataset(currentYear);
      })
      .catch(showLoadError);
  } catch (err) {
    showLoadError(err);
  }
}

function showLoadError(err: unknown) {
  chartEl.innerHTML = `<p style="color:#ff6b6b">Failed to load data: ${err}</p>`;
  console.error(err);
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
    updateHash();
    loadDataset(currentYear).catch(showLoadError);
  });
}

function buildMetricSelect() {
  metricSelectEl.value = currentMetric;
  metricSelectEl.addEventListener("change", () => {
    currentMetric = metricSelectEl.value as "gc" | "points" | "kom";
    updateHash();
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
  // One pass over each rider's byStage array instead of a per-stage
  // rider.byStage.find() scan (which was O(stages × riders × stages)).
  const rankAtStage = new Map<number, Map<string, number>>();
  for (const stage of dataset.stages) rankAtStage.set(stage.stage_number, new Map());
  for (const rider of dataset.riders) {
    for (const sp of rider.byStage) {
      const rank = getRank(sp);
      if (rank != null) rankAtStage.get(sp.stage)?.set(rider.id, rank);
    }
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
  if (!dataset) return; // initial fetch in flight; loadDataset() reapplies
  selected = new Set(dataset.riders.filter((r) => effectiveFinalRank(r) <= preset).map((r) => r.id));
}

async function loadDataset(year: string) {
  dataset = await getDataset(year);
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
  else if (currentView === "overview") drawOverview();
}

function switchView(view: "stage" | "overview" | "allraces" | "riders") {
  currentView = view;
  viewStageBtn.classList.toggle("active", view === "stage");
  viewOverviewBtn.classList.toggle("active", view === "overview");
  viewAllRacesBtn.classList.toggle("active", view === "allraces");
  viewRidersBtn.classList.toggle("active", view === "riders");
  if (subtitleStage) subtitleStage.hidden = view !== "stage";
  subtitleOverview.hidden = view !== "overview";
  chartEl.classList.toggle("hidden", view !== "stage");
  sidebarEl.classList.toggle("hidden", view !== "stage");
  overviewChartEl.classList.toggle("visible", view === "overview");
  overviewSummaryEl.hidden = view !== "overview";
  allRacesChartEl.classList.toggle("visible", view === "allraces");
  ridersChartEl.classList.toggle("visible", view === "riders");
  if (view === "stage") drawChart();
  else if (view === "overview") drawOverview();
  else if (view === "allraces") drawAllRacesOverview();
  else drawRidersPage().catch(showLoadError);
  updateHash();
}

// ─── Hash routing ────────────────────────────────────────────────────────────
// Formats: #<year>/stage/<metric> · #<year>/overview · #allraces
//          #riders · #riders/<rider-slug>
// State changes push a hash entry (so back/forward walk through app states);
// hashchange applies the hash back onto app state. The compare-with-
// computeHash() guard on both sides breaks the write→event→write loop.

function computeHash(): string {
  if (currentView === "riders") {
    return currentRiderId
      ? `#riders/${currentRiderId.replace(/^rider\//, "")}`
      : "#riders";
  }
  if (currentView === "allraces") return "#allraces";
  if (currentView === "overview") return `#${currentYear}/overview`;
  return `#${currentYear}/stage/${currentMetric}`;
}

// Suppresses hash writes while a hash is being applied, so the intermediate
// draw calls inside applyHash() don't push partial states onto the history.
let applyingHash = false;

function updateHash() {
  if (applyingHash) return;
  const h = computeHash();
  if (window.location.hash !== h) window.location.hash = h;
}

/** Applies the current location.hash to app state. Returns false if the hash
 *  was empty/unrecognized and the caller should fall back to defaults. */
async function applyHash(): Promise<boolean> {
  const hash = window.location.hash;
  if (!hash || hash === "#") return false;
  if (hash === computeHash()) return true; // already in sync (our own write)
  const parts = hash.slice(1).split("/");
  applyingHash = true;
  try {
    if (parts[0] === "allraces") {
      switchView("allraces");
      return true;
    }

    if (parts[0] === "riders") {
      if (parts[1]) {
        await ensureRiderIndex();
        const id = `rider/${parts[1]}`;
        if (riderIndex.has(id)) {
          switchView("riders"); // renders grid synchronously (index is built)
          drawRiderDetail(id);
          return true;
        }
      }
      switchView("riders");
      return true;
    }

    const [year, view, metric] = parts;
    if (!URLS_BY_YEAR[year]) return false;
    currentYear = year;
    yearSelectEl.value = year;
    if (view !== "overview") {
      currentMetric = metric === "points" || metric === "kom" ? metric : "gc";
      metricSelectEl.value = currentMetric;
    }
    await loadDataset(year);
    switchView(view === "overview" ? "overview" : "stage");
    return true;
  } finally {
    applyingHash = false;
  }
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

  // One crosshair line per panel — populated during the forEach below.
  // Event handlers close over this array by reference, so by the time a
  // user can hover, all entries are present.
  const crosshairLines: Selection<SVGLineElement, unknown, null, undefined>[] = [];

  const showCrosshair = (year: number) => {
    const cx = xScale(year);
    crosshairLines.forEach((line) =>
      line.attr("x1", cx).attr("x2", cx).attr("visibility", "visible")
    );
  };
  const hideCrosshair = () =>
    crosshairLines.forEach((line) => line.attr("visibility", "hidden"));

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
          positionTooltip(event);
          showCrosshair(r.year);
        })
        .on("mouseleave", () => { hideTooltip(); hideCrosshair(); });
    });

    // Crosshair line for this panel (appended after series so it sits on top;
    // pointer-events:none so dots underneath remain hoverable)
    crosshairLines.push(
      g.append("line")
        .attr("class", "all-races-crosshair")
        .attr("y1", 0).attr("y2", panelHeight)
        .attr("stroke", "rgba(255,255,255,0.5)")
        .attr("stroke-width", 1)
        .attr("stroke-dasharray", "3,3")
        .attr("pointer-events", "none")
        .attr("visibility", "hidden")
    );

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
      if (!dataset) return; // initial fetch in flight; selection state comes with it
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
    if (!dataset) return; // initial fetch in flight; nothing to search yet
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
  viewRidersBtn.addEventListener("click", () => switchView("riders"));
}

function cssEscape(s: string): string {
  return s.replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
}

// "Soviet Union" and "Yugoslavia" are genuine historical entities with no
// current ISO 3166-1 code / flag emoji, so they get hand-built inline SVGs
// (official Wikimedia Commons artwork) instead of an emoji lookup — see
// HISTORICAL_FLAG_SVG below. The star/hammer/sickle on the Soviet flag are
// enlarged (1.6x, per request) relative to the official proportions so the
// emblem stays legible at the small size these render at in the app.
const HISTORICAL_FLAG_SVG: Record<string, string> = {
  "Soviet Union": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1.3em" height="0.65em"><path fill="#bc0000" fill-opacity="1" d="M0 0h1200v600H0z" style="fill:#cc0000;fill-opacity:1" /><g transform="translate(209.5,90) scale(1.6) translate(-209.5,-90)"><path d="m 200.0005,37.5 -8.41933,25.911886 H 164.336 L 186.37777,79.426122 177.95844,105.338 200.0005,89.323465 222.04257,105.338 213.62324,79.426122 235.665,63.411886 h -27.24516 z m 0,13.499987 5.38828,16.583473 h 17.43718 l -14.107,10.249496 5.38827,16.583472 L 200.0005,84.167224 185.89378,94.416428 191.28205,77.832956 177.17504,67.58346 h 17.43718 z" style="fill:#ffd700;fill-opacity:1;stroke:none;stroke-width:0.14999977px;stroke-linecap:butt;stroke-linejoin:miter;stroke-opacity:1" /><g style="fill:#ffd700;fill-opacity:1" transform="matrix(0.98931879,0,0,0.98673811,3.8297658,3.7659398)"><path d="m 137.43744,171.69421 18.86296,18.9937 17.78834,-17.66589 c 27.05847,29.021 55.43807,56.99501 82.28704,86.12782 4.03444,4.06233 10.59815,4.085 14.66056,0.0506 4.06232,-4.03445 4.08499,-10.59815 0.0506,-14.66056 -28.81871,-27.1901 -57.72545,-54.60143 -86.55328,-81.89095 l 23.96499,-23.80003 -33.34026,-4.61605 z" style="fill:#ffd700;fill-opacity:1;stroke:none;stroke-width:0.48919073;stroke-miterlimit:4;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:1" /><path d="m 198.2887,110.1955 c 15.51743,8.7394 27.29872,21.28122 34.2484,34.3924 7.04394,13.28902 10.13959,27.16218 10.20325,38.25433 0.13054,22.74374 -18.43771,41.18184 -41.18183,41.18184 -12.13597,0 -23.04607,-5.24868 -30.58302,-13.60085 l -4.16863,3.51033 c -0.70999,-0.27231 -1.46387,-0.41221 -2.22429,-0.41276 -1.82948,1.9e-4 -3.56621,0.80531 -4.74859,2.20136 -2.97368,0.38896 -5.46251,2.44529 -6.40534,5.29224 -3.13486,6.28843 -8.63524,11.21997 -15.29104,13.4776 -0.0637,0.0216 -0.11992,0.05 -0.1758,0.0783 -3.07749,1.12758 -6.16259,3.1643 -8.78919,5.80245 -5.19155,5.23656 -7.72858,11.93658 -6.30024,16.63822 -0.14098,0.40857 -0.21361,0.83759 -0.21498,1.26979 1.5e-4,2.17082 1.75991,3.93058 3.93073,3.93073 0.54341,-0.002 1.08053,-0.11639 1.57745,-0.33632 4.69369,1.05881 11.06885,-1.54582 16.05444,-6.55917 2.82624,-2.85072 4.94356,-6.22349 5.98303,-9.53062 2.31696,-6.62278 7.29699,-12.01856 13.62281,-15.05312 0.15105,-0.0725 0.27303,-0.14714 0.38218,-0.22358 2.12082,-1.01408 3.67251,-2.92895 4.225,-5.2139 9.70222,11.44481 24.25255,18.75299 40.51876,19.13577 29.83352,0.70205 52.13299,-21.25802 53.16414,-52.83642 0.51894,-15.89259 -5.62993,-36.3847 -19.6412,-53.19089 -10.70835,-12.84441 -26.40987,-23.50795 -44.18699,-28.20777 z" style="fill:#ffd700;fill-opacity:1;stroke:none;stroke-width:0.50003481;stroke-miterlimit:4;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:1" /></g></g></svg>',
  Yugoslavia: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 500" width="1.3em" height="0.65em"><path fill="#003893" d="M0 0h1000v500H0z"/><path fill="#fff" d="M0 166.667h1000V500H0z"/><g fill="#de0000"><path d="M0 333.333h1000V500H0z"/><path fill-rule="evenodd" stroke="#fcd115" stroke-width="8.89" d="m500 97.716 34.193 105.222 110.638.005-89.506 65.035 34.185 105.225-89.51-65.03-89.511 65.029 34.185-105.225-89.506-65.035 110.638-.005z"/></g></svg>',
};

// Every current-country nationality string that appears in the exported
// data (checked against all 112 years).
const NATIONALITY_TO_ISO: Record<string, string> = {
  Algeria: "DZ", Argentina: "AR", Australia: "AU", Austria: "AT", Belarus: "BY",
  Belgium: "BE", Brazil: "BR", Canada: "CA", China: "CN", Colombia: "CO",
  "Costa Rica": "CR", Croatia: "HR", "Czech Republic": "CZ", Denmark: "DK",
  Ecuador: "EC", Eritrea: "ER", Estonia: "EE", Ethiopia: "ET", Finland: "FI",
  France: "FR", Germany: "DE", "Great Britain": "GB", Hungary: "HU",
  Ireland: "IE", Israel: "IL", Italy: "IT", Japan: "JP", Kazakhstan: "KZ",
  Latvia: "LV", Liechtenstein: "LI", Lithuania: "LT", Luxembourg: "LU",
  Mexico: "MX", Moldova: "MD", Monaco: "MC", Morocco: "MA", Netherlands: "NL",
  "New Zealand": "NZ", Norway: "NO", Poland: "PL", Portugal: "PT",
  Romania: "RO", Russia: "RU", Slovakia: "SK", Slovenia: "SI",
  "South Africa": "ZA", Spain: "ES", Sweden: "SE", Switzerland: "CH",
  Tunisia: "TN", Ukraine: "UA", "United States": "US", Uzbekistan: "UZ",
  Venezuela: "VE",
};

// Regional Indicator Symbols: each ISO 3166-1 alpha-2 letter maps to a
// Unicode codepoint offset by 127397, so "FR" renders as the French flag
// emoji. No image assets or network requests needed.
function isoToFlagEmoji(iso2: string): string {
  return [...iso2.toUpperCase()].map((c) => String.fromCodePoint(127397 + c.charCodeAt(0))).join("");
}

/** Small flag <span> for a nationality, or null if unrecognized/absent. */
function nationalityFlagEl(nationality: string | null | undefined): HTMLSpanElement | null {
  if (!nationality) return null;
  const flag = document.createElement("span");
  flag.className = "nationality-flag";
  flag.title = nationality;
  const historicalSvg = HISTORICAL_FLAG_SVG[nationality];
  if (historicalSvg) {
    flag.innerHTML = historicalSvg;
    return flag;
  }
  const iso2 = NATIONALITY_TO_ISO[nationality];
  if (!iso2) return null;
  flag.textContent = isoToFlagEmoji(iso2);
  return flag;
}

// ─── Jersey Icons (Riders page only) ────────────────────────────────────────
// One icon per classification a rider has ever won at least once (GC winners
// across multiple years — e.g. Greg LeMond's 3 yellow jerseys — still get a
// single icon, since riderJerseysWon() only checks "won at least once").
// Hand-drawn generic jersey silhouette (not official ASO artwork) reused for
// all four, colored/patterned per classification.
const JERSEY_PATH = "M9,2 L4,2 L1,6 L5,9 L5,22 L19,22 L19,9 L23,6 L20,2 L15,2 Q12,5 9,2 Z";

function jerseySvg(fill: string, stroke = "#00000055"): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="1.3em" height="1.3em"><path d="${JERSEY_PATH}" fill="${fill}" stroke="${stroke}" stroke-width="1" stroke-linejoin="round"/></svg>`;
}

let komJerseyClipCounter = 0;
/** White jersey + red polka dots, clipped to the jersey silhouette. Each call
 *  gets a unique clipPath id — reusing one id would make every KOM icon on
 *  the page reference whichever <clipPath> happened to render first. */
function komJerseySvg(): string {
  const clipId = `komclip${komJerseyClipCounter++}`;
  const dots = [6, 10, 14, 18]
    .flatMap((y, row) => {
      const offset = row % 2 ? 2 : 0;
      return [5 + offset, 10 + offset, 15 + offset, 20 + offset].map(
        (x) => `<circle cx="${x}" cy="${y}" r="1.3" fill="#E4002B"/>`,
      );
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="1.3em" height="1.3em"><defs><clipPath id="${clipId}"><path d="${JERSEY_PATH}"/></clipPath></defs><path d="${JERSEY_PATH}" fill="#FFFFFF" stroke="#888888" stroke-width="1" stroke-linejoin="round"/><g clip-path="url(#${clipId})">${dots}</g></svg>`;
}

const JERSEY_LABELS = { gc: "GC winner", sprint: "Sprint (points) winner", kom: "KOM winner", youth: "Young rider winner" } as const;
type JerseyCategory = keyof typeof JERSEY_LABELS;

/** Every year this rider won each classification (GC/sprint/KOM derived from
 *  per-year rank data; youth from the pipeline's classification_standings
 *  lookup, since that classification isn't in the per-year JSON at all). */
function jerseyYearsWon(entry: RiderEntry): Record<JerseyCategory, number[]> {
  const gc: number[] = [], sprint: number[] = [], kom: number[] = [];
  for (const [year, y] of entry.years) {
    if (y.finalRank === 1) gc.push(year);
    if (y.sprintRank === 1) sprint.push(year);
    if (y.komRank === 1) kom.push(year);
  }
  const sortAsc = (a: number, b: number) => a - b;
  return {
    gc: gc.sort(sortAsc),
    sprint: sprint.sort(sortAsc),
    kom: kom.sort(sortAsc),
    youth: [...entry.youthWinYears].sort(sortAsc),
  };
}

function jerseyIconSvg(category: JerseyCategory): string {
  return category === "gc" ? jerseySvg("#FFD400")
    : category === "sprint" ? jerseySvg("#3FA535")
    : category === "kom" ? komJerseySvg()
    : jerseySvg("#FFFFFF", "#888888");
}

/** Small jersey <span> icons for every classification a rider has won. */
function jerseyIconsEl(entry: RiderEntry): HTMLSpanElement[] {
  const years = jerseyYearsWon(entry);
  return (Object.keys(JERSEY_LABELS) as JerseyCategory[])
    .filter((category) => years[category].length > 0)
    .map((category) => {
      const el = document.createElement("span");
      el.className = "jersey-icon";
      el.title = JERSEY_LABELS[category];
      el.innerHTML = jerseyIconSvg(category);
      return el;
    });
}

/** Jersey icons + a "(year, year, ...)" label after each — rider detail page
 *  only; the Riders grid uses the plain icons from jerseyIconsEl(). */
function jerseyIconsWithYearsEl(entry: RiderEntry): HTMLSpanElement[] {
  const years = jerseyYearsWon(entry);
  const out: HTMLSpanElement[] = [];
  for (const category of Object.keys(JERSEY_LABELS) as JerseyCategory[]) {
    if (years[category].length === 0) continue;
    const icon = document.createElement("span");
    icon.className = "jersey-icon";
    icon.title = JERSEY_LABELS[category];
    icon.innerHTML = jerseyIconSvg(category);
    out.push(icon);
    const yearsEl = document.createElement("span");
    yearsEl.className = "jersey-years";
    yearsEl.textContent = `(${years[category].join(", ")})`;
    out.push(yearsEl);
  }
  return out;
}

function buildLegend() {
  if (!dataset) return; // initial fetch in flight; loadDataset() rebuilds
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
    const flag = nationalityFlagEl(rider.nationality);
    if (flag) row.appendChild(flag);

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

let xScale: ScaleLinear<number, number>;
let yScale: ScaleLinear<number, number>;

function drawChart() {
  // The initial dataset fetch may still be in flight (clicking a view button
  // or resizing during load lands here). loadDataset() redraws the current
  // view when it resolves, so bailing out is safe.
  if (!dataset) return;
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

  // Compute each rider's display series once per draw; the line generator,
  // hit paths, end dots, and end labels all read from these maps.
  const displayPointsById = new Map<string, Array<{ stage: number; rank: number | null }>>();
  const lastDefinedById = new Map<string, { stage: number; rank: number | null } | null>();
  let maxRank = 1;
  for (const r of dataset.riders) {
    const dp = getDisplayPoints(r);
    displayPointsById.set(r.id, dp);
    let last: { stage: number; rank: number | null } | null = null;
    for (let i = dp.length - 1; i >= 0; i--) {
      if (dp[i].rank !== null) { last = dp[i]; break; }
    }
    lastDefinedById.set(r.id, last);
    for (const p of dp) {
      if (p.rank !== null && p.rank > maxRank) maxRank = p.rank;
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
  const stageLabelFmt = (d: NumberValue) => stagesByNumber.get(+d)?.stage_label ?? String(d);

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
    .attr("d", (r) => lineGen(displayPointsById.get(r.id)!))
    .attr("stroke", "var(--line-dim)");

  // invisible wide hit-path per rider, for easier hover targeting
  hitLayer
    .selectAll<SVGPathElement, RiderSeries>("path")
    .data(dataset.riders, (r) => r.id)
    .join("path")
    .attr("fill", "none")
    .attr("stroke", "transparent")
    .attr("stroke-width", 10)
    .attr("d", (r) => lineGen(displayPointsById.get(r.id)!))
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
      const last = lastDefinedById.get(r.id);
      return last ? xScale(last.stage) : -100;
    })
    .attr("cy", (r) => {
      const last = lastDefinedById.get(r.id);
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
      const last = lastDefinedById.get(r.id);
      return last ? xScale(last.stage) + 6 : -100;
    })
    .attr("y", (r) => {
      const last = lastDefinedById.get(r.id);
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
        positionTooltip(event);
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
      positionTooltip(event);
    })
    .on("mouseout", () => { tooltipEl.hidden = true; });

  updateLineClasses();
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

  positionTooltip(event);
}

function showStageTooltip(event: MouseEvent, stage: StageInfo) {
  const distance = stage.distance_km != null ? `${Math.round(stage.distance_km)} km` : "—";
  const vertical = stage.vertical_meters != null ? `${stage.vertical_meters} m` : "—";
  const type = stage.route_type ?? "—";

  tooltipEl.innerHTML = `
    <div>${stage.start_location ?? "—"}</div>
    <div>${stage.finish_location ?? "—"}</div>
    <div>${distance}, ${vertical}, ${type}</div>
  `;
  positionTooltip(event);
}

function hideTooltip() {
  tooltipEl.hidden = true;
}

// Shows the tooltip at the pointer, flipping to the left of the cursor when
// it would overflow the right edge of the window. Offsets are computed from
// chartAreaEl because that's the tooltip's positioning parent (.chart-area is
// position:relative) — measuring any other container skews the placement by
// that container's padding offset.
function positionTooltip(event: MouseEvent) {
  tooltipEl.hidden = false;
  const areaRect = chartAreaEl.getBoundingClientRect();
  tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
  const tw = tooltipEl.offsetWidth;
  tooltipEl.style.left = window.innerWidth - event.clientX < tw + 24
    ? `${event.clientX - areaRect.left - tw - 10}px`
    : `${event.clientX - areaRect.left + 24}px`;
}

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}

// ─── Rider Index ─────────────────────────────────────────────────────────────

interface RiderEntry {
  id: string;
  name: string;
  nationality: string | null;
  youthWinYears: number[];
  years: Map<number, { finalRank: number; sprintRank: number; komRank: number; team: string | null }>;
  teams: Set<string>;
}

const riderIndex = new Map<string, RiderEntry>();
let allTeamsSorted: string[] = [];
let allNationalitiesSorted: string[] = [];

// URL-only import (see the year-data comment up top for why we fetch instead
// of importing the JSON as a module).
import ridersIndexUrl from "./data/riders_index.json?url";

// Compact prebuilt index (pipeline/export_riders_index.py): one small file
// instead of reading all 113 per-year datasets just to populate the Riders
// page. Lazy-loaded as its own chunk the first time the Riders view opens, so
// it never weighs down first paint (the default view is the stage chart).
// Shape: { teams: [names], riders: { slug: { n, c, y: { year: tuple } } } }
// Rider keys are slugs (id minus the "rider/" prefix, re-added on load) and
// teams are integer indexes into the shared string table (-1 = no team) —
// both cut the payload versus repeating the strings inline.
// Year tuple: [gcRank, teamIdx] when the rider had no sprint/KOM ranking that
// year (the common case), or [gcRank, teamIdx, sprintRank, komRank] with 0
// standing in for an absent rank. Normalized to 9999 sentinels on load.
type RawYearTuple =
  | [number, number]
  | [number, number, number, number];
type RawRiderIndex = {
  teams: string[];
  riders: Record<string, { n: string; c: string | null; yw?: number[]; y: Record<string, RawYearTuple> }>;
};

let riderIndexBuilt = false;

async function ensureRiderIndex(): Promise<void> {
  if (riderIndexBuilt) return;
  const raw = await fetchJson<RawRiderIndex>(ridersIndexUrl);
  const teamTable = raw.teams;
  for (const [slug, rec] of Object.entries(raw.riders)) {
    const id = `rider/${slug}`;
    const years = new Map<number, { finalRank: number; sprintRank: number; komRank: number; team: string | null }>();
    const teams = new Set<string>();
    for (const [yearStr, [finalRank, teamIdx, sprintRank, komRank]] of Object.entries(rec.y)) {
      const team = teamIdx >= 0 ? teamTable[teamIdx] : null;
      years.set(parseInt(yearStr), {
        finalRank,
        sprintRank: sprintRank || 9999,
        komRank: komRank || 9999,
        team,
      });
      if (team) teams.add(team);
    }
    riderIndex.set(id, { id, name: rec.n, nationality: rec.c ?? null, youthWinYears: rec.yw ?? [], years, teams });
  }
  allTeamsSorted = [...teamTable].sort();
  allNationalitiesSorted = [...new Set(
    [...riderIndex.values()].map((r) => r.nationality).filter((n): n is string => !!n),
  )].sort();
  riderIndexBuilt = true;
}

// ─── Riders Page ─────────────────────────────────────────────────────────────

let ridersSearchQuery = "";
let ridersFilterYear = "";
let ridersFilterTeam = "";
let ridersFilterNationality = "";

function filteredRiders(): RiderEntry[] {
  const q = ridersSearchQuery.toLowerCase();
  const yr = ridersFilterYear ? parseInt(ridersFilterYear) : null;
  return [...riderIndex.values()]
    .filter((e) => {
      if (q && !e.name.toLowerCase().includes(q)) return false;
      if (yr !== null && !e.years.has(yr)) return false;
      if (ridersFilterTeam && !e.teams.has(ridersFilterTeam)) return false;
      if (ridersFilterNationality && e.nationality !== ridersFilterNationality) return false;
      return true;
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

async function drawRidersPage() {
  currentRiderId = null;
  updateHash();
  ridersChartEl.innerHTML = "";
  if (!riderIndexBuilt) {
    const loading = document.createElement("div");
    loading.className = "riders-count-label";
    loading.textContent = "Loading riders…";
    ridersChartEl.appendChild(loading);
    await ensureRiderIndex();
    // Bail out if the user navigated away while the index was loading.
    if (currentView !== "riders") return;
    ridersChartEl.innerHTML = "";
  }

  const controls = document.createElement("div");
  controls.className = "riders-controls";

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.placeholder = "Search rider name…";
  searchInput.className = "riders-search-input";
  searchInput.value = ridersSearchQuery;

  const yearSel = document.createElement("select");
  yearSel.className = "riders-filter-select";
  [["", "All years"], ...YEARS.map((y) => [y, y])].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    yearSel.appendChild(opt);
  });
  yearSel.value = ridersFilterYear;

  const teamSel = document.createElement("select");
  teamSel.className = "riders-filter-select";
  [["", "All teams"], ...allTeamsSorted.map((t) => [t, t])].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    teamSel.appendChild(opt);
  });
  teamSel.value = ridersFilterTeam;

  const nationalitySel = document.createElement("select");
  nationalitySel.className = "riders-filter-select";
  [["", "All nationalities"], ...allNationalitiesSorted.map((n) => [n, n])].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    nationalitySel.appendChild(opt);
  });
  nationalitySel.value = ridersFilterNationality;

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "riders-clear-btn";
  clearBtn.textContent = "Clear All";

  const countLabel = document.createElement("span");
  countLabel.className = "riders-count-label";

  controls.append(searchInput, yearSel, teamSel, nationalitySel, clearBtn, countLabel);
  ridersChartEl.appendChild(controls);

  const grid = document.createElement("div");
  grid.className = "riders-grid";
  ridersChartEl.appendChild(grid);

  function refreshGrid() {
    const results = filteredRiders();
    countLabel.textContent = `${results.length.toLocaleString()} rider${results.length !== 1 ? "s" : ""}`;
    grid.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const entry of results) {
      const btn = document.createElement("button");
      btn.className = "rider-name-btn";
      btn.appendChild(document.createTextNode(entry.name));
      const flag = nationalityFlagEl(entry.nationality);
      if (flag) btn.appendChild(flag);
      for (const jersey of jerseyIconsEl(entry)) btn.appendChild(jersey);
      btn.title = entry.name;
      btn.dataset.id = entry.id;
      frag.appendChild(btn);
    }
    grid.appendChild(frag);
  }

  // One delegated listener instead of one closure per button (~5,400 of them).
  grid.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>(".rider-name-btn");
    if (btn?.dataset.id) drawRiderDetail(btn.dataset.id);
  });

  // Debounced: refreshGrid rebuilds the whole grid, so don't do it per keystroke.
  const debouncedSearch = debounce(() => { ridersSearchQuery = searchInput.value; refreshGrid(); }, 150);
  searchInput.addEventListener("input", debouncedSearch);
  yearSel.addEventListener("change", () => { ridersFilterYear = yearSel.value; refreshGrid(); });
  teamSel.addEventListener("change", () => { ridersFilterTeam = teamSel.value; refreshGrid(); });
  nationalitySel.addEventListener("change", () => { ridersFilterNationality = nationalitySel.value; refreshGrid(); });
  clearBtn.addEventListener("click", () => {
    ridersSearchQuery = "";
    ridersFilterYear = "";
    ridersFilterTeam = "";
    ridersFilterNationality = "";
    searchInput.value = "";
    yearSel.value = "";
    teamSel.value = "";
    nationalitySel.value = "";
    refreshGrid();
  });
  refreshGrid();
}

function drawRiderDetail(riderId: string) {
  ridersChartEl.innerHTML = "";
  const entry = riderIndex.get(riderId);
  if (!entry) return;
  currentRiderId = riderId;
  updateHash();

  // Header
  const header = document.createElement("div");
  header.className = "rider-detail-header";

  const backBtn = document.createElement("button");
  backBtn.className = "rider-back-btn";
  backBtn.textContent = "← All Riders";
  backBtn.addEventListener("click", () => drawRidersPage());

  const nameEl = document.createElement("h2");
  nameEl.className = "rider-detail-name";
  nameEl.appendChild(document.createTextNode(entry.name));
  const detailFlag = nationalityFlagEl(entry.nationality);
  if (detailFlag) nameEl.appendChild(detailFlag);
  for (const el of jerseyIconsWithYearsEl(entry)) nameEl.appendChild(el);

  const metaEl = document.createElement("div");
  metaEl.className = "rider-detail-meta";

  const years = [...entry.years.keys()].sort((a, b) => a - b);
  const finishYears = years.filter((yr) => entry.years.get(yr)!.finalRank < 9999);
  const bestRank = finishYears.length > 0
    ? Math.min(...finishYears.map((yr) => entry.years.get(yr)!.finalRank))
    : null;

  const metaParts: string[] = [];
  if (entry.nationality) metaParts.push(entry.nationality);
  metaParts.push(`${years.length} Tour${years.length !== 1 ? "s" : ""} (${years[0]}–${years[years.length - 1]})`);
  if (bestRank !== null) metaParts.push(`Best: GC #${bestRank}`);

  metaEl.textContent = metaParts.join("  ·  ");
  header.append(backBtn, nameEl, metaEl);
  ridersChartEl.appendChild(header);

  const chartContainer = document.createElement("div");
  chartContainer.className = "rider-career-chart";
  ridersChartEl.appendChild(chartContainer);

  // Defer one tick so the flex container has a chance to lay out
  setTimeout(() => {
    const rect = chartContainer.getBoundingClientRect();
    const W = Math.max(rect.width || 800, 500);
    const H = Math.max(rect.height || 380, 280);
    const margin = { top: 30, right: 40, bottom: 44, left: 60 };
    const iW = W - margin.left - margin.right;
    const iH = H - margin.top - margin.bottom;

    type YrResult = { year: number; finalRank: number; sprintRank: number; komRank: number; team: string | null };
    const allData: YrResult[] = years.map((yr) => ({
      year: yr,
      finalRank: entry.years.get(yr)!.finalRank,
      sprintRank: entry.years.get(yr)!.sprintRank,
      komRank: entry.years.get(yr)!.komRank,
      team: entry.years.get(yr)!.team,
    }));
    const finishData = allData.filter((d) => d.finalRank < 9999);
    const dnfData = allData.filter((d) => d.finalRank >= 9999);
    const sprintData = allData.filter((d) => d.sprintRank < 9999);
    const komData = allData.filter((d) => d.komRank < 9999);

    const allRankedRanks = [
      ...finishData.map((d) => d.finalRank),
      ...sprintData.map((d) => d.sprintRank),
      ...komData.map((d) => d.komRank),
    ];
    const maxRank = Math.max(d3.max(allRankedRanks, (d) => d) ?? 10, 10);
    const DNF_H = dnfData.length > 0 ? 36 : 0;
    const mainH = iH - DNF_H - (DNF_H > 0 ? 8 : 0);

    const xPad = Math.max((years[years.length - 1] - years[0]) * 0.06, 1.5);
    const xScale2 = d3.scaleLinear()
      .domain([years[0] - xPad, years[years.length - 1] + xPad])
      .range([0, iW]);

    const yScale2 = d3.scaleLinear()
      .domain([1, maxRank])
      .range([0, mainH]);

    const svg = d3.select(chartContainer).append("svg")
      .attr("width", W).attr("height", H)
      .attr("viewBox", `0 0 ${W} ${H}`);

    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    // Y gridlines + axis
    const yTickVals = maxRank <= 10
      ? d3.range(1, maxRank + 1)
      : d3.range(0, maxRank + 1, maxRank > 50 ? 20 : 10).filter((v) => v > 0);

    g.append("g").attr("class", "grid grid-y")
      .call(d3.axisLeft(yScale2).tickValues(yTickVals).tickSize(-iW).tickFormat(() => ""));

    g.append("g").attr("class", "axis y-axis")
      .call(d3.axisLeft(yScale2).tickValues(yTickVals).tickFormat((d) => `#${d}`));

    // X axis
    g.append("g").attr("class", "axis x-axis")
      .attr("transform", `translate(0,${iH - 4})`)
      .call(
        d3.axisBottom(xScale2)
          .ticks(Math.min(years.length, 12))
          .tickFormat((d) => String(d))
      )
      .call((ax) => ax.select(".domain").remove())
      .call((ax) => ax.selectAll(".tick line").remove());

    // Axis labels
    g.append("text").attr("class", "axis-label")
      .attr("transform", `translate(${-margin.left + 14},${mainH / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .text("Rank");

    g.append("text").attr("class", "axis-label")
      .attr("x", iW / 2).attr("y", iH + margin.bottom - 8)
      .attr("text-anchor", "middle")
      .text("Year");

    // Legend (top-right): GC / Sprint / KOM
    const legendItems = [
      { label: "GC", color: "var(--accent)" },
      { label: "Sprint", color: "#22c55e" },
      { label: "KOM", color: "#ef4444" },
    ];
    let legendX = iW;
    for (let i = legendItems.length - 1; i >= 0; i--) {
      const item = legendItems[i];
      g.append("text")
        .attr("x", legendX).attr("y", -14)
        .attr("text-anchor", "end")
        .attr("dominant-baseline", "middle")
        .attr("font-size", "11px").attr("fill", item.color)
        .text(item.label);
      const textW = item.label.length * 7;
      g.append("line")
        .attr("x1", legendX - textW - 16).attr("x2", legendX - textW - 4)
        .attr("y1", -14).attr("y2", -14)
        .attr("stroke", item.color).attr("stroke-width", 2);
      legendX = legendX - textW - 22;
    }

    // DNF zone divider
    if (dnfData.length > 0) {
      g.append("line")
        .attr("x1", 0).attr("x2", iW)
        .attr("y1", mainH + 4).attr("y2", mainH + 4)
        .attr("stroke", "#4a5160").attr("stroke-dasharray", "3,3").attr("stroke-opacity", 0.6);
      g.append("text")
        .attr("x", -6).attr("y", mainH + DNF_H / 2 + 4)
        .attr("text-anchor", "end").attr("dominant-baseline", "middle")
        .attr("font-size", "10px").attr("fill", "#ef4444").attr("fill-opacity", 0.7)
        .text("DNF/DNS");
    }

    // Helper: draw a line series split on gaps > 5 years
    function drawLine(data: YrResult[], yFn: (d: YrResult) => number, color: string) {
      if (data.length < 2) return;
      const lineGen = d3.line<YrResult>()
        .x((d) => xScale2(d.year))
        .y((d) => yFn(d))
        .curve(d3.curveMonotoneX);
      const segs: YrResult[][] = [];
      let seg: YrResult[] = [data[0]];
      for (let i = 1; i < data.length; i++) {
        if (data[i].year - data[i - 1].year <= 5) seg.push(data[i]);
        else { segs.push(seg); seg = [data[i]]; }
      }
      segs.push(seg);
      for (const s of segs) {
        if (s.length > 1) {
          g.append("path").datum(s)
            .attr("fill", "none").attr("stroke", color)
            .attr("stroke-width", 1.5).attr("stroke-opacity", 0.5)
            .attr("d", lineGen);
        }
      }
    }

    drawLine(finishData, (d) => yScale2(d.finalRank), "var(--accent)");
    drawLine(sprintData, (d) => yScale2(d.sprintRank), "#22c55e");
    drawLine(komData, (d) => yScale2(d.komRank), "#ef4444");

    // Tooltip helper
    function showDotTooltip(event: MouseEvent, d: YrResult) {
      const gcPart = d.finalRank < 9999 ? `<div>GC #${d.finalRank}</div>` : "<div>GC DNF/DNS</div>";
      const sprintPart = d.sprintRank < 9999 ? `<div style="color:#22c55e">Sprint #${d.sprintRank}</div>` : "";
      const komPart = d.komRank < 9999 ? `<div style="color:#ef4444">KOM #${d.komRank}</div>` : "";
      tooltipEl.innerHTML = `
        <div class="t-name">${d.year} Tour de France</div>
        <div class="t-team">${d.team ?? "—"}</div>
        ${gcPart}${sprintPart}${komPart}
        <div style="color:var(--text-dim);font-size:11px">Click to view stage chart</div>
      `;
      positionTooltip(event);
    }

    function handleDotClick(metric: "gc" | "points" | "kom") {
      return (_e: MouseEvent, d: YrResult) => {
        currentYear = String(d.year);
        yearSelectEl.value = currentYear;
        currentMetric = metric;
        metricSelectEl.value = metric;
        loadDataset(currentYear).then(() => {
          selected = new Set([riderId]);
          buildLegend();
          switchView("stage");
        }).catch(showLoadError);
      };
    }

    // GC finish dots
    g.selectAll<SVGCircleElement, YrResult>(".career-dot")
      .data(finishData).join("circle")
      .attr("class", "career-dot")
      .attr("cx", (d) => xScale2(d.year))
      .attr("cy", (d) => yScale2(d.finalRank))
      .attr("r", 5)
      .attr("fill", "var(--accent)").attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .on("mousemove", showDotTooltip)
      .on("mouseleave", () => hideTooltip())
      .on("click", handleDotClick("gc"));

    // Sprint dots
    g.selectAll<SVGCircleElement, YrResult>(".career-dot-sprint")
      .data(sprintData).join("circle")
      .attr("class", "career-dot-sprint")
      .attr("cx", (d) => xScale2(d.year))
      .attr("cy", (d) => yScale2(d.sprintRank))
      .attr("r", 4)
      .attr("fill", "#22c55e").attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .on("mousemove", showDotTooltip)
      .on("mouseleave", () => hideTooltip())
      .on("click", handleDotClick("points"));

    // KOM dots
    g.selectAll<SVGCircleElement, YrResult>(".career-dot-kom")
      .data(komData).join("circle")
      .attr("class", "career-dot-kom")
      .attr("cx", (d) => xScale2(d.year))
      .attr("cy", (d) => yScale2(d.komRank))
      .attr("r", 4)
      .attr("fill", "#ef4444").attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .on("mousemove", showDotTooltip)
      .on("mouseleave", () => hideTooltip())
      .on("click", handleDotClick("kom"));

    // DNF dots (hollow, in DNF zone)
    if (dnfData.length > 0) {
      g.selectAll<SVGCircleElement, YrResult>(".career-dot-dnf")
        .data(dnfData).join("circle")
        .attr("class", "career-dot-dnf")
        .attr("cx", (d) => xScale2(d.year))
        .attr("cy", mainH + DNF_H / 2 + 4)
        .attr("r", 4)
        .attr("fill", "none").attr("stroke", "#ef4444").attr("stroke-width", 1.5)
        .on("mousemove", showDotTooltip)
        .on("mouseleave", () => hideTooltip())
        .on("click", handleDotClick("gc"));
    }
  });
}

init();
