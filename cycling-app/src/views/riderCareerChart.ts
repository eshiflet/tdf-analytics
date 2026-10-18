// The cross-race career chart on the rider detail page: one dot per season (or
// per constituent race, for the classics) on a shared year axis, by race and
// classification. Split out of riderDetail.ts, which keeps the data loading and
// the header/toggle chrome. This module draws; it never fetches, and navigation
// is handed back through `onNavigate`.
import type { RaceId } from "../raceRegistry";
import { RACES, RACE_SHORT_LABEL } from "../raceRegistry";
import { d3 } from "../d3";
import { fieldDefinitionLabel } from "../formatters";
import { positionTooltip, hideTooltip } from "../tooltip";
import { escapeHtml } from "../utils";
import type { RiderEntry } from "../riderIndexData";
import { fieldDefinitionByRace } from "../riderIndexData";
import { tooltipEl } from "../dom";

export type ClassifId = "gc" | "sprint" | "kom";

// Badge config per race (for toggle buttons and DNF dot outlines). The
// classics share one neutral gray across all 11 constituent races, and the
// off-road races one brown across their six — see the registry's `chart`
// comment for why neither set is coloured individually. "X" for gravel
// because G is already the Giro.
export const BADGE: Record<RaceId, { bg: string; text: string; label: string }> = {
  tour:     { bg: "#FFD400", text: "#111", label: "T" },
  giro:     { bg: "#E4007C", text: "#fff", label: "G" },
  vuelta:   { bg: "#E30613", text: "#fff", label: "V" },
  classics: { bg: "#9ca3af", text: "#111", label: "C" },
  gravel:   { bg: "#b4794a", text: "#fff", label: "X" },
};

export type CrossPt = {
  year: number; race: RaceId;
  finalRank: number; sprintRank: number; komRank: number; team: string | null;
  /** Constituent race name, for aggregate races (the classics). A Grand
   *  Tour point is fully identified by race+year and leaves this unset. */
  label?: string;
};

export interface CareerChartInput {
  /** Races to draw, already in RACE_IDS order. */
  races: RaceId[];
  byRace: Map<RaceId, RiderEntry>;
  classifs: Set<ClassifId>;
}

/** Creates a draw function bound to one container. Each call to it replaces
 *  the previous chart. */
export function createCareerChart(
  container: HTMLElement,
  onNavigate: (d: CrossPt, metric: "gc" | "points" | "kom") => void,
) {
  // The chart draw is deferred a tick so the flex container can lay out, and
  // that same timer is the coalescing point: when two indexes land close
  // together the second supersedes the first's pending draw instead of adding
  // to it. Without this a rider in five races paid five full chart renders.
  let pendingDraw: number | null = null;

  return function draw({ races, byRace, classifs }: CareerChartInput): void {
    container.innerHTML = "";
    if (pendingDraw !== null) { clearTimeout(pendingDraw); pendingDraw = null; }


    const allPoints: CrossPt[] = [];
    for (const race of races) {
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
    pendingDraw = setTimeout(() => {
      pendingDraw = null;
      const rect = container.getBoundingClientRect();
      const W = Math.max(rect.width || 800, 500);
      const H = Math.max(rect.height || 380, 280);
      const margin = { top: 50, right: 40, bottom: 44, left: 60 };
      const iW = W - margin.left - margin.right;
      const iH = H - margin.top - margin.bottom;

      // Max rank across all active classifications
      const rankValues: number[] = [];
      for (const p of allPoints) {
        if (classifs.has("gc")     && p.finalRank  < 9999) rankValues.push(p.finalRank);
        if (classifs.has("sprint") && p.sprintRank < 9999) rankValues.push(p.sprintRank);
        if (classifs.has("kom")    && p.komRank    < 9999) rankValues.push(p.komRank);
      }
      const maxRank = Math.max(d3.max(rankValues) ?? 10, 10);

      // GC DNF zone (only when GC is active)
      const gcDnfPts = classifs.has("gc")
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
        racesPerYear.set(year, races.filter((r) => allPoints.some((p) => p.race === r && p.year === year)));
      }
      const DOT_R = 5;
      function xPos(race: RaceId, year: number): number {
        const at = racesPerYear.get(year) ?? [];
        if (at.length <= 1) return xScale2(year);
        const idx = at.indexOf(race);
        return xScale2(year) + (idx - (at.length - 1) / 2) * (DOT_R * 2 + 1);
      }

      const svg = d3.select(container).append("svg")
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

      // X axis — tick only years present in active data.
      //
      // How many labels fit is a question about WIDTH, not about how many
      // years the rider raced. Labelling every year whenever there were 20 or
      // fewer was fine at the ~890px inner width of a desktop chart and
      // collided into an unreadable smear at 375px, where the SVG sits on its
      // 500px floor: "199219931994199519 96". Thin them to what actually fits
      // and keep the first and last, so the axis still says where the career
      // starts and ends.
      const YEAR_LABEL_PX = 34;   // a 4-digit year at 11px, plus breathing room
      const maxLabels = Math.max(2, Math.floor(iW / YEAR_LABEL_PX));
      const xAxis = d3.axisBottom(xScale2)
        .ticks(Math.min(uniqueYears.length, 12))
        .tickFormat((d) => String(d));
      if (uniqueYears.length <= 20) {
        if (uniqueYears.length <= maxLabels) {
          xAxis.tickValues(uniqueYears);
        } else {
          // Space by PIXEL POSITION, not by index. Taking every Nth year looks
          // right and is not: the years are unevenly spaced on the scale (a
          // rider misses seasons), so a fixed step still collides where they
          // bunch up. Keeping the last year on top of that made it worse —
          // 2009 and 2010 are adjacent and both got labelled.
          const kept: number[] = [];
          let lastX = -Infinity;
          for (const y of uniqueYears) {
            const x = xScale2(y);
            if (x - lastX >= YEAR_LABEL_PX) { kept.push(y); lastX = x; }
          }
          // The final year anchors the axis, so force it in — and drop what it
          // would sit on top of rather than letting the two collide.
          const last = uniqueYears[uniqueYears.length - 1];
          if (kept[kept.length - 1] !== last) {
            while (kept.length && xScale2(last) - xScale2(kept[kept.length - 1]) < YEAR_LABEL_PX) {
              kept.pop();
            }
            kept.push(last);
          }
          xAxis.tickValues(kept);
        }
      }
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
      const activeList = races;
      // The classics award neither jersey (registry: hasSprintKom) and no such
      // line is ever drawn for them, so they get no Sprint/KOM legend entry —
      // and their column isn't widened to fit labels that never appear.
      const contestsSprintKom = (r: RaceId) => RACES[r].hasSprintKom;
      const sprintKomRaces = activeList.filter(contestsSprintKom);
      const showSprintRow = classifs.has("sprint") && sprintKomRaces.length > 0;
      const showKomRow    = classifs.has("kom")    && sprintKomRaces.length > 0;
      const CHAR_W = 7, LINE_W = 12, LINE_GAP = 4, COL_GAP = 12;
      const raceLabel = (r: RaceId) => RACE_SHORT_LABEL[r];
      const colMaxW = (r: RaceId): number => {
        const labels = [raceLabel(r)];
        if (contestsSprintKom(r)) {
          if (showSprintRow) labels.push("Sprint");
          if (showKomRow)    labels.push("KOM");
        }
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
      const komY    = showKomRow    ? nextLegendY : null;
      if (komY    !== null) nextLegendY -= 13;
      const sprintY = showSprintRow ? nextLegendY : null;
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
        for (const race of sprintKomRaces) {
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
        for (const race of sprintKomRaces) {
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


      // Draw lines + dots per active race × classification
      for (const race of races) {
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
          // What that "Result #n" is a rank OVER. Only the off-road set carries
          // it, and only there can it differ from "place in the race that ran":
          // an elite_division edition ranks one category of a mass start, so
          // riders outside the category finished between these places. Without
          // it a career chart puts 2015's third-across-the-line and 2016's
          // third-pro on the same axis and says nothing.
          const fieldLabel = isAggregate
            ? fieldDefinitionLabel(
                fieldDefinitionByRace[d.race].get(`${d.label}|${d.year}`))
            : null;
          tooltipEl.innerHTML = `
            <div class="t-name">${d.year} ${escapeHtml(d.label ?? RACES[d.race].name)}</div>
            <div class="t-team">${escapeHtml(d.team ?? "—")}</div>
            ${gcPart}${sprintPart}${komPart}
            ${fieldLabel ? `<div class="t-team">${fieldLabel}</div>` : ""}
            <div style="color:var(--text-dim);font-size:11px">Click to view ${isAggregate ? "season" : "stage"} chart</div>
          `;
          positionTooltip(event);
        };

        if (classifs.has("gc")) {
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
            .on("click", (_e, d) => onNavigate(d, "gc"));

          const dnfRace = racePts.filter((p) => p.finalRank >= 9999);
          if (dnfRace.length > 0 && gcDnfPts.length > 0) {
            g.selectAll<SVGCircleElement, CrossPt>(`.career-dnf-${race}`)
              .data(dnfRace).join("circle")
              .attr("class", `career-dnf-${race}`)
              .attr("cx", xFn).attr("cy", mainH + DNF_H / 2 + 4)
              .attr("r", 6).attr("fill", "transparent").attr("stroke", BADGE[race].bg).attr("stroke-width", 1.5)
              .style("cursor", "pointer")
              .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
              .on("click", (_e, d) => onNavigate(d, "gc"));
          }
        }

        if (classifs.has("sprint")) {
          const sprintData = racePts.filter((p) => p.sprintRank < 9999);
          drawLine(sprintData, xFn, (d) => yScale2(d.sprintRank), sprintColor, "4,3");
          g.selectAll<SVGCircleElement, CrossPt>(`.career-sprint-${race}`)
            .data(sprintData).join("circle")
            .attr("class", `career-sprint-${race}`)
            .attr("cx", xFn).attr("cy", (d) => yScale2(d.sprintRank))
            .attr("r", 4).attr("fill", sprintColor).attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
            .style("cursor", "pointer")
            .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
            .on("click", (_e, d) => onNavigate(d, "points"));
        }

        if (classifs.has("kom")) {
          const komData = racePts.filter((p) => p.komRank < 9999);
          drawLine(komData, xFn, (d) => yScale2(d.komRank), komColor, "2,3");
          g.selectAll<SVGCircleElement, CrossPt>(`.career-kom-${race}`)
            .data(komData).join("circle")
            .attr("class", `career-kom-${race}`)
            .attr("cx", xFn).attr("cy", (d) => yScale2(d.komRank))
            .attr("r", 4).attr("fill", komColor).attr("stroke", "var(--bg)").attr("stroke-width", 1.5)
            .style("cursor", "pointer")
            .on("mousemove", showTip).on("mouseleave", () => hideTooltip())
            .on("click", (_e, d) => onNavigate(d, "kom"));
        }
      }
    }, 0) as unknown as number;
  };
}
