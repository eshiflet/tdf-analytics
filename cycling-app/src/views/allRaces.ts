// All Races Overview view: four stacked line charts comparing every edition
// of the current race — distance, elevation, GC winner time, average speed.
import type { Selection } from "../d3";
import { d3 } from "../d3";
import { state, raceConfig } from "../state";
import type { RaceSummary } from "../raceRegistry";
import { ALL_RACES_BY_RACE } from "../raceRegistry";
import { allRacesChartEl, tooltipEl } from "../dom";
import { positionTooltip, hideTooltip } from "../tooltip";

export function drawAllRacesOverview() {
  allRacesChartEl.innerHTML = "";

  const ALL_RACES = ALL_RACES_BY_RACE[state.currentRace];
  const raceName = raceConfig().name;

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

  const imperial = state.allRacesUnit === "imperial";
  const KM_TO_MI = 0.621371;
  const M_TO_FT = 3.28084;

  const panels: PanelDef[] = [
    {
      yLabel: imperial ? "Distance (mi)" : "Distance (km)",
      series: [{
        label: "Total Distance",
        value: (r) => r.totalDistanceKm != null ? (imperial ? r.totalDistanceKm * KM_TO_MI : r.totalDistanceKm) : null,
        fmt: (v) => imperial ? `${Math.round(v).toLocaleString()} mi` : `${Math.round(v).toLocaleString()} km`,
        color: "var(--accent)",
      }],
    },
    {
      yLabel: imperial ? "Elevation (ft)" : "Elevation (m)",
      series: [{
        label: "Total Elevation",
        value: (r) => r.totalElevationM != null ? (imperial ? r.totalElevationM * M_TO_FT : r.totalElevationM) : null,
        fmt: (v) => imperial ? `${Math.round(v).toLocaleString()} ft` : `${Math.round(v).toLocaleString()} m`,
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
      yLabel: imperial ? "Avg Speed (mph)" : "Avg Speed (km/h)",
      series: [
        {
          label: "GC Winner",
          value: (r) => { const s = speed(r.totalDistanceKm, r.gcWinnerTimeSeconds); return s != null ? (imperial ? s * KM_TO_MI : s) : null; },
          fmt: (v) => imperial ? `${v.toFixed(1)} mph` : `${v.toFixed(1)} km/h`,
          color: "#22c55e",
        },
        {
          label: "Slowest Finisher",
          value: (r) => { const s = speed(r.totalDistanceKm, r.slowestFinisherTimeSeconds); return s != null ? (imperial ? s * KM_TO_MI : s) : null; },
          fmt: (v) => imperial ? `${v.toFixed(1)} mph` : `${v.toFixed(1)} km/h`,
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

  const firstTickDecade = Math.ceil(minYear / 10) * 10;
  const tickYears = d3.range(firstTickDecade, maxYear + 1, 10).filter((y) => y <= maxYear);

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
    raceConfig().warBands.forEach(({ start, end, label }) => {
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
            <div class="t-name">${r.year} ${raceName}</div>
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
