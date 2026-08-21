// Race History view: how each one-day classic changed across its own lifetime.
//
// The Grand Tours' All Years Summary totals one race's stages per year. That is
// meaningless for the classics — a season is eleven unrelated races, so its
// "total distance" is an arbitrary sum. This is the opposite pivot: one panel
// per RACE, tracked across its whole history (Paris-Roubaix 1896-2026).
//
// SMALL MULTIPLES, not eleven overlaid lines. Categorical color tops out at
// eight hues before adjacent series stop being reliably distinguishable, and a
// 9th series must fold into small multiples rather than invent a hue. Faceting
// also removes the need for a categorical palette at all: each panel holds a
// single series, so one validated accent carries every panel and the panel
// title supplies identity instead of a legend.
import { d3 } from "../d3";
import { allRacesChartEl, tooltipEl } from "../dom";
import { positionTooltip, hideTooltip } from "../tooltip";
import { fetchJson } from "../dataLoading";
import { state } from "../state";
// main.ts imports this module, so this is a cycle — safe for the same reason
// riders.ts's is (see its header comment): updateUnitToggle is only ever called
// from inside an event handler, never while the module is being evaluated.
import { updateUnitToggle } from "../main";

type YearPoint = { y: number; km?: number; kmh?: number; n?: number };
type RaceSeries = { name: string; short: string; first: number; last: number; years: YearPoint[] };

// A `?url` glob, matching how every other data file in the app is discovered.
// `new URL(..., import.meta.url)` also builds, but emits an absolute URL that
// resolves against a file:// base outside a browser — which silently broke the
// jsdom smoke tests. The glob yields a plain path string instead.
// One glob per race SET, keyed by the data directory, so a second aggregate
// race (the off-road set) is picked up without touching this view again.
const historyUrlModules = import.meta.glob<string>("../data/*/race_history.json", {
  query: "?url",
  import: "default",
  eager: true,
});
const HISTORY_URL_BY_RACE: Record<string, string> = {};
for (const [path, url] of Object.entries(historyUrlModules)) {
  const match = path.match(/\.\.\/data\/([^/]+)\/race_history\.json$/);
  if (match) HISTORY_URL_BY_RACE[match[1]] = url;
}

// Slot-1 blue at its dark-surface step. Validated against this app's #0f1115
// surface: inside the L 0.48-0.67 band, chroma floor, and >= 3:1 contrast.
const LINE = "#3987e5";

type MetricId = "kmh" | "km" | "n";
const METRICS: { id: MetricId; label: string }[] = [
  { id: "kmh", label: "Winning speed" },
  { id: "km", label: "Distance" },
  { id: "n", label: "Finishers" },
];

const KM_TO_MI = 0.621371;

/** Axis label, tooltip format and value conversion for the metric on screen,
 *  in the unit the km/mi toggle currently selects. Speed converts too — mph is
 *  the imperial reading of km/h — while finishers is a plain count and is the
 *  same number either way. */
function unitSpec(metricId: MetricId, imperial: boolean) {
  if (metricId === "kmh") {
    return imperial
      ? { axis: "mph", fmt: (v: number) => `${v.toFixed(1)} mph`, convert: (v: number) => v * KM_TO_MI }
      : { axis: "km/h", fmt: (v: number) => `${v.toFixed(1)} km/h`, convert: (v: number) => v };
  }
  if (metricId === "km") {
    return imperial
      ? { axis: "mi", fmt: (v: number) => `${Math.round(v)} mi`, convert: (v: number) => v * KM_TO_MI }
      : { axis: "km", fmt: (v: number) => `${Math.round(v)} km`, convert: (v: number) => v };
  }
  return { axis: "riders", fmt: (v: number) => `${Math.round(v)} finishers`, convert: (v: number) => v };
}

// Keyed by race, not a single slot: two aggregate races now have a history
// file, and a shared cache would show the classics' panels under Gravel after
// a visit to either.
const cache: Record<string, RaceSeries[]> = {};
let metric: MetricId = "kmh";

/** Whether the km/mi toggle means anything for the metric on screen — main.ts
 *  hides the button for Finishers, which is a count with no unit. */
export function raceHistoryUsesDistanceUnits(): boolean {
  return metric !== "n";
}

export async function drawClassicsHistory(): Promise<void> {
  allRacesChartEl.innerHTML = "";
  const raceKey = state.currentRace;
  if (!cache[raceKey]) {
    const url = HISTORY_URL_BY_RACE[raceKey];
    if (!url) {
      allRacesChartEl.textContent = "No race history for this race.";
      return;
    }
    allRacesChartEl.textContent = "Loading race history…";
    cache[raceKey] = (await fetchJson<{ races: RaceSeries[] }>(url)).races;
    allRacesChartEl.innerHTML = "";
  }
  const races = cache[raceKey];

  const spec = unitSpec(metric, state.allRacesUnit === "imperial");
  // Every read of a data point goes through this, so the axis, the lines and
  // the tooltip can't disagree about which unit they're in.
  const valueAt = (p: YearPoint): number | null => {
    const raw = p[metric];
    return raw == null ? null : spec.convert(raw);
  };

  // Metric switch, one row above the charts.
  const bar = document.createElement("div");
  bar.className = "race-toggle-group";
  for (const m of METRICS) {
    const b = document.createElement("button");
    b.className = m.id === metric ? "classif-toggle-btn active" : "classif-toggle-btn inactive";
    b.textContent = m.label;
    b.addEventListener("click", () => {
      metric = m.id;
      // Finishers has no unit, so the km/mi button has to appear or disappear
      // with the metric, not just on entering the view.
      updateUnitToggle();
      drawClassicsHistory();
    });
    bar.appendChild(b);
  }
  allRacesChartEl.appendChild(bar);

  // Shared scales across every panel — the whole point is comparing races to
  // each other, which a per-panel axis would quietly prevent.
  const allPts = races.flatMap((r) => r.years.map(valueAt).filter((v): v is number => v != null));
  if (allPts.length === 0) return;
  const yMin = Math.min(...allPts), yMax = Math.max(...allPts);
  const xMin = Math.min(...races.map((r) => r.first));
  const xMax = Math.max(...races.map((r) => r.last));

  const grid = document.createElement("div");
  grid.className = "history-grid";
  allRacesChartEl.appendChild(grid);

  for (const race of races) {
    const cell = document.createElement("div");
    cell.className = "history-cell";
    const title = document.createElement("div");
    title.className = "history-title";
    // Single series per panel: the title IS the identity, so no legend.
    title.textContent = `${race.name}  ${race.first}–${race.last}`;
    cell.appendChild(title);
    grid.appendChild(cell);

    const W = 300, H = 130;
    const margin = { top: 8, right: 8, bottom: 18, left: 34 };
    const iW = W - margin.left - margin.right;
    const iH = H - margin.top - margin.bottom;

    const svg = d3.select(cell).append("svg")
      .attr("viewBox", `0 0 ${W} ${H}`)
      .attr("preserveAspectRatio", "none")
      .attr("class", "history-svg");
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const x = d3.scaleLinear().domain([xMin, xMax]).range([0, iW]);
    const y = d3.scaleLinear().domain([yMin, yMax]).nice().range([iH, 0]);

    g.append("g").attr("class", "grid grid-y")
      .call(d3.axisLeft(y).ticks(3).tickSize(-iW).tickFormat(() => ""));
    g.append("g").attr("class", "axis y-axis")
      .call(d3.axisLeft(y).ticks(3));
    g.append("g").attr("class", "axis x-axis")
      .attr("transform", `translate(0,${iH})`)
      .call(d3.axisBottom(x).ticks(4).tickFormat((d) => String(d)));

    const pts = race.years.filter((p) => p[metric] != null);
    // Break the line across gaps of more than 3 years so the war years read as
    // the holes they are instead of a straight line implying racing continued.
    const segs: YearPoint[][] = [];
    let seg: YearPoint[] = [];
    for (const p of pts) {
      if (seg.length && p.y - seg[seg.length - 1].y > 3) { segs.push(seg); seg = []; }
      seg.push(p);
    }
    if (seg.length) segs.push(seg);

    const line = d3.line<YearPoint>().x((p) => x(p.y)).y((p) => y(valueAt(p)!));
    for (const s of segs) {
      if (s.length === 1) {
        g.append("circle").attr("cx", x(s[0].y)).attr("cy", y(valueAt(s[0])!))
          .attr("r", 1.6).attr("fill", LINE);
      } else {
        g.append("path").datum(s).attr("fill", "none")
          .attr("stroke", LINE).attr("stroke-width", 2).attr("d", line);
      }
    }

    // Hover: nearest year under the pointer, per the interaction default.
    const hover = g.append("line").attr("class", "crosshair")
      .attr("y1", 0).attr("y2", iH).attr("stroke", "var(--line-dim)").attr("opacity", 0);
    svg.append("rect")
      .attr("x", margin.left).attr("y", margin.top).attr("width", iW).attr("height", iH)
      .attr("fill", "transparent")
      .on("mousemove", (event: MouseEvent) => {
        // The SVG scales to its container via viewBox, so client pixels are not
        // user units — convert through the element's own width rather than
        // reading offsetX, which would be wrong by the scale factor.
        const svgEl = (event.currentTarget as SVGRectElement).ownerSVGElement!;
        const r = svgEl.getBoundingClientRect();
        const mx = ((event.clientX - r.left) / r.width) * W;
        const year = x.invert(mx - margin.left);
        let best: YearPoint | null = null;
        for (const p of pts) if (!best || Math.abs(p.y - year) < Math.abs(best.y - year)) best = p;
        if (!best) return;
        hover.attr("x1", x(best.y)).attr("x2", x(best.y)).attr("opacity", 1);
        tooltipEl.innerHTML =
          `<div class="t-name">${race.name}</div>` +
          `<div class="t-team">${best.y}</div>` +
          `<div>${spec.fmt(valueAt(best)!)}</div>`;
        positionTooltip(event);
      })
      .on("mouseleave", () => { hover.attr("opacity", 0); hideTooltip(); });

    const axis = document.createElement("div");
    axis.className = "history-axis-label";
    axis.textContent = spec.axis;
    cell.appendChild(axis);
  }
}
