// Rider detail view: cross-race career chart for one rider, with toggles to
// show/hide each race and each classification (GC/Sprint/KOM) independently.
// Not filtered to the current race — shows every race the rider has results
// in. See riders.ts's header comment for the circular-import note (this file
// and riders.ts call each other for grid↔detail navigation).
import type { RaceId } from "../raceRegistry";
import { RACE_IDS, RACES, RACE_SHORT_LABEL } from "../raceRegistry";
import { d3 } from "../d3";
import { state } from "../state";
import { ridersChartEl, yearSelectEl, metricSelectEl, tooltipEl } from "../dom";
import { updateHash } from "../hashRouting";
import { positionTooltip, hideTooltip } from "../tooltip";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import type { RiderEntry } from "../riderIndexData";
import { riderIndexByRace, ensureRiderIndexFor } from "../riderIndexData";
import { buildLegend } from "./stageChart";
import { setRace, loadDataset, switchView, showLoadError } from "../main";
import { drawRidersPage } from "./riders";

export async function drawRiderDetail(riderId: string): Promise<void> {
  // Claim the slot before the first await so drawRidersPage can bail if it
  // resumes from its own await and sees a detail is now in flight.
  state.currentRiderId = riderId;
  ridersChartEl.innerHTML = "";

  // Load all race indexes in parallel, then find rider in each
  await Promise.all(RACE_IDS.map((r) => ensureRiderIndexFor(r)));
  const byRace = new Map<RaceId, RiderEntry>();
  for (const race of RACE_IDS) {
    const e = riderIndexByRace[race].get(riderId);
    if (e) byRace.set(race, e);
  }
  if (byRace.size === 0) return;

  updateHash();

  // Prefer entry from currentRace for name/nationality; fall back to first found
  const primaryEntry = byRace.get(state.currentRace) ?? [...byRace.values()][0];

  // Badge config per race (for toggle buttons and DNF dot outlines). The
  // classics share one neutral gray across all 11 constituent races — see the
  // registry's `chart` comment for why they aren't coloured individually.
  const BADGE: Record<RaceId, { bg: string; text: string; label: string }> = {
    tour:     { bg: "#FFD400", text: "#111", label: "T" },
    giro:     { bg: "#E4007C", text: "#fff", label: "G" },
    vuelta:   { bg: "#E30613", text: "#fff", label: "V" },
    classics: { bg: "#9ca3af", text: "#111", label: "C" },
  };

  // ── Header ──────────────────────────────────────────────────────────────────
  const header = document.createElement("div");
  header.className = "rider-detail-header";

  const backBtn = document.createElement("button");
  backBtn.className = "rider-back-btn";
  backBtn.textContent = "← All Riders";
  backBtn.addEventListener("click", () => drawRidersPage());

  const nameEl = document.createElement("h2");
  nameEl.className = "rider-detail-name";
  nameEl.appendChild(document.createTextNode(displayName(primaryEntry)));
  const detailFlag = nationalityFlagEl(primaryEntry.nationality);
  if (detailFlag) nameEl.appendChild(detailFlag);

  const metaEl = document.createElement("div");
  metaEl.className = "rider-detail-meta";
  const metaParts: string[] = [];
  for (const [race, entry] of byRace) {
    const yrs = [...entry.years.keys()].sort((a, b) => a - b);
    const finished = yrs.filter((yr) => entry.years.get(yr)!.finalRank < 9999);
    const best = finished.length > 0
      ? Math.min(...finished.map((yr) => entry.years.get(yr)!.finalRank))
      : null;
    // "TDF" is kept for the Tour rather than the registry's "Tour" so this
    // summary line reads exactly as it always has.
    const raceName = race === "tour" ? "TDF" : RACE_SHORT_LABEL[race];
    let part = `${yrs.length} ${raceName}`;
    if (best !== null) part += ` · Best #${best}`;
    metaParts.push(part);
  }
  metaEl.textContent = metaParts.join(", ");
  header.append(backBtn, nameEl, metaEl);
  ridersChartEl.appendChild(header);

  // ── Toggle bar: race buttons (T/G/V) + divider + classification buttons ───────
  type ClassifId = "gc" | "sprint" | "kom";
  const activeRaces   = new Set<RaceId>(byRace.keys());
  // Sprint/KOM only exist if at least one race this rider has data in
  // contests them — a classics-only rider gets neither the toggles nor the
  // legend rows, rather than two controls that can never show anything.
  const hasSprintKom = [...byRace.keys()].some((r) => RACES[r].hasSprintKom);
  const classifIds: ClassifId[] = hasSprintKom ? ["gc", "sprint", "kom"] : ["gc"];
  const activeClassifs = new Set<ClassifId>(classifIds);

  const toggleGroup = document.createElement("div");
  toggleGroup.className = "race-toggle-group";

  // Race toggles
  for (const race of RACE_IDS) {
    const btn = document.createElement("button");
    btn.className = "race-toggle-btn";
    const hasData = byRace.has(race);
    const badge = BADGE[race];
    btn.textContent = badge.label;
    btn.title = RACES[race].name;
    btn.style.setProperty("--race-color", badge.bg);
    btn.style.setProperty("--race-text", badge.text);
    if (!hasData) {
      btn.classList.add("no-data");
    } else {
      btn.classList.add("active");
      btn.addEventListener("click", () => {
        if (activeRaces.has(race)) {
          if (activeRaces.size === 1) return;
          activeRaces.delete(race);
          btn.classList.replace("active", "inactive");
        } else {
          activeRaces.add(race);
          btn.classList.replace("inactive", "active");
        }
        redrawChart();
      });
    }
    toggleGroup.appendChild(btn);
  }

  // Divider — only meaningful when there are classification toggles to
  // separate the race toggles from.
  if (classifIds.length > 1) {
    const divider = document.createElement("span");
    divider.className = "toggle-divider";
    divider.textContent = "|";
    toggleGroup.appendChild(divider);
  }

  // Classification toggles
  for (const classif of (classifIds.length > 1 ? classifIds : [])) {
    const label = classif === "gc" ? "GC" : classif === "sprint" ? "Sprint" : "KOM";
    const btn = document.createElement("button");
    btn.className = "classif-toggle-btn active";
    btn.textContent = label;
    btn.addEventListener("click", () => {
      if (activeClassifs.has(classif)) {
        if (activeClassifs.size === 1) return;
        activeClassifs.delete(classif);
        btn.classList.replace("active", "inactive");
      } else {
        activeClassifs.add(classif);
        btn.classList.replace("inactive", "active");
      }
      redrawChart();
    });
    toggleGroup.appendChild(btn);
  }
  ridersChartEl.appendChild(toggleGroup);

  // ── Chart container ──────────────────────────────────────────────────────────
  const chartContainer = document.createElement("div");
  chartContainer.className = "rider-career-chart";
  ridersChartEl.appendChild(chartContainer);

  function redrawChart() {
    chartContainer.innerHTML = "";

    type CrossPt = {
      year: number; race: RaceId;
      finalRank: number; sprintRank: number; komRank: number; team: string | null;
      /** Constituent race name, for aggregate races (the classics). A Grand
       *  Tour point is fully identified by race+year and leaves this unset. */
      label?: string;
    };

    const allPoints: CrossPt[] = [];
    for (const race of activeRaces) {
      const entry = byRace.get(race)!;
      if (entry.constituents) {
        // Aggregate race: one point per constituent race contested, so a
        // single season contributes up to 11 dots. They share an x position
        // and separate vertically by finishing rank.
        for (const [yr, results] of entry.constituents) {
          for (const r of results) {
            allPoints.push({
              year: yr, race, finalRank: r.rank,
              sprintRank: 9999, komRank: 9999, team: r.team, label: r.race,
            });
          }
        }
      } else {
        for (const [yr, data] of entry.years) {
          allPoints.push({ year: yr, race, ...data });
        }
      }
    }
    if (allPoints.length === 0) return;

    const allYears = allPoints.map((p) => p.year);
    const minYear = Math.min(...allYears);
    const maxYear = Math.max(...allYears);

    // Defer one tick so the flex container has a chance to lay out
    setTimeout(() => {
      const rect = chartContainer.getBoundingClientRect();
      const W = Math.max(rect.width || 800, 500);
      const H = Math.max(rect.height || 380, 280);
      const margin = { top: 50, right: 40, bottom: 44, left: 60 };
      const iW = W - margin.left - margin.right;
      const iH = H - margin.top - margin.bottom;

      // Max rank across all active classifications
      const rankValues: number[] = [];
      for (const p of allPoints) {
        if (activeClassifs.has("gc")     && p.finalRank  < 9999) rankValues.push(p.finalRank);
        if (activeClassifs.has("sprint") && p.sprintRank < 9999) rankValues.push(p.sprintRank);
        if (activeClassifs.has("kom")    && p.komRank    < 9999) rankValues.push(p.komRank);
      }
      const maxRank = Math.max(d3.max(rankValues) ?? 10, 10);

      // GC DNF zone (only when GC is active)
      const gcDnfPts = activeClassifs.has("gc")
        ? allPoints.filter((p) => p.finalRank >= 9999)
        : [];
      const DNF_H = gcDnfPts.length > 0 ? 36 : 0;
      const mainH = iH - DNF_H - (DNF_H > 0 ? 8 : 0);

      const xPad = Math.max((maxYear - minYear) * 0.06, 1.5);
      const xScale2 = d3.scaleLinear()
        .domain([minYear - xPad, maxYear + xPad])
        .range([0, iW]);
      const yScale2 = d3.scaleLinear()
        .domain([1, maxRank])
        .range([0, mainH]);

      // Per-year x offset so dots from different races sharing a year sit
      // side-by-side (touching) rather than on top of each other.
      const uniqueYears = [...new Set(allPoints.map((p) => p.year))].sort((a, b) => a - b);
      const racesPerYear = new Map<number, RaceId[]>();
      for (const year of uniqueYears) {
        racesPerYear.set(year, [...activeRaces].filter((r) => allPoints.some((p) => p.race === r && p.year === year)));
      }
      const DOT_R = 5;
      function xPos(race: RaceId, year: number): number {
        const at = racesPerYear.get(year) ?? [];
        if (at.length <= 1) return xScale2(year);
        const idx = at.indexOf(race);
        return xScale2(year) + (idx - (at.length - 1) / 2) * (DOT_R * 2 + 1);
      }

      const svg = d3.select(chartContainer).append("svg")
        .attr("width", W).attr("height", H)
        .attr("viewBox", `0 0 ${W} ${H}`);
      const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

      // Y grid + axis
      const yTickVals = maxRank <= 10
        ? d3.range(1, maxRank + 1)
        : d3.range(0, maxRank + 1, maxRank > 50 ? 20 : 10).filter((v) => v > 0);
      g.append("g").attr("class", "grid grid-y")
        .call(d3.axisLeft(yScale2).tickValues(yTickVals).tickSize(-iW).tickFormat(() => ""));
      g.append("g").attr("class", "axis y-axis")
        .call(d3.axisLeft(yScale2).tickValues(yTickVals).tickFormat((d) => `#${d}`));

      // X axis — tick only years present in active data
      const xAxis = d3.axisBottom(xScale2)
        .ticks(Math.min(uniqueYears.length, 12))
        .tickFormat((d) => String(d));
      if (uniqueYears.length <= 20) xAxis.tickValues(uniqueYears);
      g.append("g").attr("class", "axis x-axis")
        .attr("transform", `translate(0,${iH - 4})`)
        .call(xAxis)
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

      // Legend: 1–3 rows depending on active classifications.
      // Legend: columns per active race, rows per active classification.
      // Text is left-aligned so "T/S/K" first letters line up vertically.
      // Layout: [line 12px] [gap 4px] [text left-aligned] — per column.
      // Columns are right-to-left with a 12px gap between them.
      const activeList = [...activeRaces];
      const CHAR_W = 7, LINE_W = 12, LINE_GAP = 4, COL_GAP = 12;
      const raceLabel = (r: RaceId) => RACE_SHORT_LABEL[r];
      const colMaxW = (r: RaceId): number => {
        const labels = [raceLabel(r)];
        if (activeClassifs.has("sprint")) labels.push("Sprint");
        if (activeClassifs.has("kom"))    labels.push("KOM");
        return Math.max(...labels.map(l => l.length * CHAR_W));
      };

      // Line-start x per race, computed right-to-left
      const lineX = new Map<RaceId, number>();
      let rx = iW;
      for (let i = activeList.length - 1; i >= 0; i--) {
        const race = activeList[i];
        const colW = LINE_W + LINE_GAP + colMaxW(race);
        rx -= colW;
        lineX.set(race, rx);
        if (i > 0) rx -= COL_GAP;
      }
      const textX = (r: RaceId) => lineX.get(r)! + LINE_W + LINE_GAP;

      // Y positions, bottom-up
      let nextLegendY = -9;
      const komY    = activeClassifs.has("kom")    ? nextLegendY : null;
      if (komY    !== null) nextLegendY -= 13;
      const sprintY = activeClassifs.has("sprint") ? nextLegendY : null;
      if (sprintY !== null) nextLegendY -= 13;
      const raceY   = nextLegendY;

      // Row 1: race name. Solid line for the Grand Tours, a dot for aggregate
      // races — matching what actually gets drawn for each (no trend line).
      for (const race of activeList) {
        const lx = lineX.get(race)!;
        if (RACES[race].stagesAreRaces) {
          g.append("circle")
            .attr("cx", lx + LINE_W / 2).attr("cy", raceY)
            .attr("r", 3.5).attr("fill", RACES[race].chart.gc);
        } else {
          g.append("line")
            .attr("x1", lx).attr("x2", lx + LINE_W)
            .attr("y1", raceY).attr("y2", raceY)
            .attr("stroke", RACES[race].chart.gc).attr("stroke-width", 2);
        }
        g.append("text")
          .attr("x", textX(race)).attr("y", raceY)
          .attr("text-anchor", "start").attr("dominant-baseline", "middle")
          .attr("font-size", "11px").attr("fill", RACES[race].chart.gc)
          .text(raceLabel(race));
      }

      // Row 2: Sprint, dashed
      if (sprintY !== null) {
        for (const race of activeList) {
          const lx = lineX.get(race)!;
          g.append("line")
            .attr("x1", lx).attr("x2", lx + LINE_W)
            .attr("y1", sprintY).attr("y2", sprintY)
            .attr("stroke", RACES[race].chart.sprint).attr("stroke-width", 1.5)
            .attr("stroke-dasharray", "4,3");
          g.append("text")
            .attr("x", textX(race)).attr("y", sprintY)
            .attr("text-anchor", "start").attr("dominant-baseline", "middle")
            .attr("font-size", "10px").attr("fill", RACES[race].chart.sprint)
            .text("Sprint");
        }
      }

      // Row 3: KOM, dotted
      if (komY !== null) {
        for (const race of activeList) {
          const lx = lineX.get(race)!;
          g.append("line")
            .attr("x1", lx).attr("x2", lx + LINE_W)
            .attr("y1", komY).attr("y2", komY)
            .attr("stroke", RACES[race].chart.kom).attr("stroke-width", 1.5)
            .attr("stroke-dasharray", "2,3");
          g.append("text")
            .attr("x", textX(race)).attr("y", komY)
            .attr("text-anchor", "start").attr("dominant-baseline", "middle")
            .attr("font-size", "10px").attr("fill", RACES[race].chart.kom)
            .text("KOM");
        }
      }

      // DNF zone divider
      if (gcDnfPts.length > 0) {
        g.append("line")
          .attr("x1", 0).attr("x2", iW)
          .attr("y1", mainH + 4).attr("y2", mainH + 4)
          .attr("stroke", "#4a5160").attr("stroke-dasharray", "3,3").attr("stroke-opacity", 0.6);
        g.append("text")
          .attr("x", -6).attr("y", mainH + DNF_H / 2 + 4)
          .attr("text-anchor", "end").attr("dominant-baseline", "middle")
          .attr("font-size", "10px").attr("fill", "#aaa").attr("fill-opacity", 0.7)
          .text("DNF/DNS");
      }

      // Helper: draw a classification line split on >5yr gaps, with optional dash
      function drawLine(
        data: CrossPt[],
        xFn: (d: CrossPt) => number,
        yFn: (d: CrossPt) => number,
        color: string,
        dashArray = "",
      ) {
        if (data.length < 2) return;
        const lineGen = d3.line<CrossPt>().x(xFn).y(yFn).curve(d3.curveMonotoneX);
        const segs: CrossPt[][] = [];
        let seg: CrossPt[] = [data[0]];
        for (let i = 1; i < data.length; i++) {
          if (data[i].year - data[i - 1].year <= 5) seg.push(data[i]);
          else { segs.push(seg); seg = [data[i]]; }
        }
        segs.push(seg);
        for (const s of segs) {
          if (s.length > 1) {
            const p = g.append("path").datum(s)
              .attr("fill", "none").attr("stroke", color)
              .attr("stroke-width", 1.5).attr("stroke-opacity", 0.5)
              .attr("d", lineGen);
            if (dashArray) p.attr("stroke-dasharray", dashArray);
          }
        }
      }

      // Shared dot-click handler: switch race + year + metric then load stage chart
      function doNavigate(d: CrossPt, metric: "gc" | "points" | "kom") {
        setRace(d.race);
        state.currentYear = String(d.year);
        yearSelectEl.value = state.currentYear;
        state.currentMetric = metric;
        metricSelectEl.value = metric;
        loadDataset(state.currentYear).then(() => {
          state.selected = new Set([riderId]);
          buildLegend();
          switchView("stage");
        }).catch(showLoadError);
      }

      // Draw lines + dots per active race × classification
      for (const race of activeRaces) {
        const racePts = allPoints.filter((p) => p.race === race).sort((a, b) => a.year - b.year);
        const { gc: gcColor, sprint: sprintColor, kom: komColor } = RACES[race].chart;
        const xFn = (d: CrossPt) => xPos(d.race, d.year);

        // A classics point names the individual race it came from and reads
        // "Result #n" — it's a placing on the day, not a GC standing.
        const isAggregate = RACES[race].stagesAreRaces;
        const showTip = (event: MouseEvent, d: CrossPt) => {
          const rankWord   = isAggregate ? "Result" : "GC";
          const gcPart     = d.finalRank  < 9999 ? `<div>${rankWord} #${d.finalRank}</div>` : `<div>${rankWord} DNF/DNS</div>`;
          const sprintPart = d.sprintRank < 9999 ? `<div style="color:${sprintColor}">Sprint #${d.sprintRank}</div>` : "";
          const komPart    = d.komRank    < 9999 ? `<div style="color:${komColor}">KOM #${d.komRank}</div>` : "";
          tooltipEl.innerHTML = `
            <div class="t-name">${d.year} ${d.label ?? RACES[d.race].name}</div>
            <div class="t-team">${d.team ?? "—"}</div>
            ${gcPart}${sprintPart}${komPart}
            <div style="color:var(--text-dim);font-size:11px">Click to view ${isAggregate ? "season" : "stage"} chart</div>
          `;
          positionTooltip(event);
        };

        if (activeClassifs.has("gc")) {
          const gcFinish = racePts.filter((p) => p.finalRank < 9999);
          // No trend line for an aggregate race: consecutive points are
          // different races (often several within one season), so joining
          // them would draw a progression that doesn't exist.
          if (!isAggregate) drawLine(gcFinish, xFn, (d) => yScale2(d.finalRank), gcColor);
          g.selectAll<SVGCircleElement, CrossPt>(`.career-gc-${race}`)
            .data(gcFinish).join("circle")
            .attr("class", `career-gc-${race}`)
            .attr("cx", xFn).attr("cy", (d) => yScale2(d.finalRank))
            .attr("r", DOT_R).attr("fill", gcColor).attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
            .style("cursor", "pointer")
            .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
            .on("click", (_e, d) => doNavigate(d, "gc"));

          const dnfRace = racePts.filter((p) => p.finalRank >= 9999);
          if (dnfRace.length > 0 && gcDnfPts.length > 0) {
            g.selectAll<SVGCircleElement, CrossPt>(`.career-dnf-${race}`)
              .data(dnfRace).join("circle")
              .attr("class", `career-dnf-${race}`)
              .attr("cx", xFn).attr("cy", mainH + DNF_H / 2 + 4)
              .attr("r", 6).attr("fill", "transparent").attr("stroke", BADGE[race].bg).attr("stroke-width", 1.5)
              .style("cursor", "pointer")
              .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
              .on("click", (_e, d) => doNavigate(d, "gc"));
          }
        }

        if (activeClassifs.has("sprint")) {
          const sprintData = racePts.filter((p) => p.sprintRank < 9999);
          drawLine(sprintData, xFn, (d) => yScale2(d.sprintRank), sprintColor, "4,3");
          g.selectAll<SVGCircleElement, CrossPt>(`.career-sprint-${race}`)
            .data(sprintData).join("circle")
            .attr("class", `career-sprint-${race}`)
            .attr("cx", xFn).attr("cy", (d) => yScale2(d.sprintRank))
            .attr("r", 4).attr("fill", sprintColor).attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
            .style("cursor", "pointer")
            .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
            .on("click", (_e, d) => doNavigate(d, "points"));
        }

        if (activeClassifs.has("kom")) {
          const komData = racePts.filter((p) => p.komRank < 9999);
          drawLine(komData, xFn, (d) => yScale2(d.komRank), komColor, "2,3");
          g.selectAll<SVGCircleElement, CrossPt>(`.career-kom-${race}`)
            .data(komData).join("circle")
            .attr("class", `career-kom-${race}`)
            .attr("cx", xFn).attr("cy", (d) => yScale2(d.komRank))
            .attr("r", 4).attr("fill", komColor).attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
            .style("cursor", "pointer")
            .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
            .on("click", (_e, d) => doNavigate(d, "kom"));
        }
      }
    }, 0);
  }

  redrawChart();
}
