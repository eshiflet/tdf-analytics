// Race Overview view: per-stage bar charts of distance, elevation gain, and
// difficulty score for the selected year, colored by route type.
import type { StageInfo } from "../types";
import { d3 } from "../d3";
import { state, raceConfig } from "../state";
import { overviewChartEl, overviewSummaryEl, tooltipEl } from "../dom";
import { positionTooltip, hideTooltip } from "../tooltip";
import { ROUTE_COLOR, ROUTE_LABEL, difficultyScore, stageTitle } from "../formatters";

const KM_TO_MI = 0.621371;
const M_TO_FT = 3.28084;

/** Below this share of ridden stages carrying a figure, a sum is not a total.
 *
 *  Mirrors export_race_summary.ELEVATION_MIN_COVERAGE, which suppresses the
 *  same number for the same reason in the all-races table. Two places showing
 *  a season's elevation under two different rules would be worse than either. */
const ELEVATION_MIN_COVERAGE = 0.5;

export function drawOverview() {
  if (!state.dataset) return; // initial fetch in flight; loadDataset() redraws
  overviewChartEl.innerHTML = "";
  const stages = state.dataset.stages;
  if (!stages.length) return;

  const imperial = state.overviewUnit === "imperial";
  // Totals summary in the topbar. Cancelled stages/races are excluded: PCS
  // still publishes the planned distance for a day that was never raced (the
  // 2020 Paris-Roubaix's 259 km, Giro 2011 st4), and counting it overstates
  // what was actually ridden. They stay in the chart below, drawn muted, so
  // the gap in the season is still visible.
  const ridden = stages.filter((st) => !st.cancelled);
  const totalDistKm = ridden.reduce((s, st) => s + (st.distance_km ?? 0), 0);
  const totalElevM = ridden.reduce((s, st) => s + (st.vertical_meters ?? 0), 0);
  const distDisplay = imperial
    ? `${Math.round(totalDistKm * KM_TO_MI).toLocaleString()} mi`
    : `${Math.round(totalDistKm).toLocaleString()} km`;
  // A PARTIAL sum is not a total, and printing one is worse than printing
  // nothing: the classics in 1950 know the elevation of one race in eight, and
  // showing that figure labelled "Total Elevation" understates the season by a
  // factor of eight while looking authoritative. 74 race-seasons did exactly
  // that, including gravel 2026 — where The Traka's 4,198 m stood for a season
  // that also ran Leadville, Unbound and Sea Otter.
  //
  // The threshold is the pipeline's own: export_race_summary.ELEVATION_MIN_COVERAGE
  // suppresses the same sum for the same reason in the all-races table, and the
  // two disagreeing about what a total is would be worse than either rule.
  //
  // The old guard was "does ANY stage have elevation", written when the
  // off-road set had none at all. PCS gravel elevation arrived on 2026-09-09
  // and turned that assumption into this bug.
  const withElev = ridden.filter((st) => (st.vertical_meters ?? 0) > 0).length;
  const elevCoverage = ridden.length ? withElev / ridden.length : 0;
  const elevDisplay = elevCoverage < ELEVATION_MIN_COVERAGE
    ? "—"
    : imperial
      ? `${Math.round(totalElevM * M_TO_FT).toLocaleString()} ft`
      : `${totalElevM.toLocaleString()} m`;
  // A bare dash says "unknown" where the truth is "known for some of them". The
  // count goes in the title so a reader who wonders can find out without it
  // competing with the number beside it.
  const elevTitle = elevCoverage < ELEVATION_MIN_COVERAGE && withElev > 0
    ? ` title="Elevation is known for ${withElev} of ${ridden.length} — too few to total"`
    : "";
  overviewSummaryEl.innerHTML = `
    <span class="overview-summary-item"><span class="overview-summary-label">Total Distance</span> <span class="overview-summary-value">${distDisplay}</span></span>
    <span class="overview-summary-sep">·</span>
    <span class="overview-summary-item"><span class="overview-summary-label">Total Elevation</span> <span class="overview-summary-value"${elevTitle}>${elevDisplay}</span></span>
  `;

  const containerRect = overviewChartEl.getBoundingClientRect();
  const totalWidth = Math.max(containerRect.width || 800, 600);
  const totalHeight = Math.max(containerRect.height || 500, 400);

  const margin = { top: 12, right: 24, bottom: 32, left: 80 };
  const innerWidth = totalWidth - margin.left - margin.right;

  const usesGradeAwareScore = stages.some((s) => s.profile_score != null);
  const difficultyLabel = `Difficulty Score (${usesGradeAwareScore ? "grade aware" : "simple ascent"})`;

  const hasElevationData = stages.some((s) => (s.vertical_meters ?? 0) > 0);

  const panels = [
    { key: "distance",   label: imperial ? "Distance (mi)" : "Distance (km)",           value: (s: StageInfo) => (s.distance_km ?? 0) * (imperial ? KM_TO_MI : 1),     noData: false },
    { key: "elevation",  label: imperial ? "Elevation Gain (ft)" : "Elevation Gain (m)", value: (s: StageInfo) => (s.vertical_meters ?? 0) * (imperial ? M_TO_FT : 1),   noData: !hasElevationData },
    { key: "difficulty", label: difficultyLabel,                                          value: difficultyScore,                                                           noData: !hasElevationData },
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

    // Panel label (rotated vertical)
    g.append("text")
      .attr("class", "overview-panel-label")
      .attr("transform", `translate(${-margin.left + 12},${panelHeight / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .text(panel.label);

    if (panel.noData) {
      // Draw a subtle empty panel background
      g.append("rect")
        .attr("x", 0)
        .attr("y", 0)
        .attr("width", innerWidth)
        .attr("height", panelHeight)
        .attr("fill", "currentColor")
        .attr("opacity", 0.04)
        .attr("rx", 4);

      g.append("text")
        .attr("x", innerWidth / 2)
        .attr("y", panelHeight / 2)
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "middle")
        .attr("class", "overview-no-data-label")
        .text("No data available");
    } else {
      const maxVal = d3.max(stages, panel.value) ?? 1;
      const yScale = d3.scaleLinear().domain([0, maxVal * 1.08]).range([panelHeight, 0]);

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
        // A cancelled race is drawn muted so a planned-but-unridden bar can't
        // be mistaken for a real result.
        .attr("fill", (s) => (s.cancelled ? "#3a3f4b" : ROUTE_COLOR[s.route_type ?? "F"] ?? ROUTE_COLOR.F))
        .on("mousemove", (event: MouseEvent, s: StageInfo) => {
          const diff = difficultyScore(s);
          const distStr = s.distance_km != null
            ? imperial
              ? `${(s.distance_km * KM_TO_MI).toFixed(1)} mi`
              : `${Math.round(s.distance_km)} km`
            : "—";
          const elevStr = s.vertical_meters != null
            ? imperial
              ? `${Math.round(s.vertical_meters * M_TO_FT).toLocaleString()} ft`
              : `${s.vertical_meters.toLocaleString()} m`
            : "—";
          tooltipEl.innerHTML = `
            <div class="t-name">${stageTitle(s.stage_number)}${s.cancelled ? " — cancelled" : ""}</div>
            <div class="t-team">${s.start_location ?? "—"} → ${s.finish_location ?? "—"}</div>
            <div>${ROUTE_LABEL[s.route_type ?? "F"] ?? s.route_type}</div>
            <div>Distance: ${distStr}</div>
            <div>Elevation: ${elevStr}</div>
            <div>Difficulty: ${diff.toFixed(1)}</div>
          `;
          positionTooltip(event);
        })
        .on("mouseleave", () => hideTooltip());
    }

    // X-axis on last panel only
    if (pi === panels.length - 1) {
      g.append("g")
        .attr("class", "axis x-axis")
        .attr("transform", `translate(0,${panelHeight})`)
        .call(
          d3.axisBottom(xScale)
            .tickFormat((d) => {
              const s = stages.find((st) => String(st.stage_number) === d);
              return s?.stage_short_label ?? s?.stage_label ?? d;
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
