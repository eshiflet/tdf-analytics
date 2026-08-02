// By Stage Table view: a spreadsheet-style grid of every rider (rows,
// ordered by bib number) x every stage (columns), showing whichever GC /
// Sprint / KOM value is currently selected via the same toggle buttons the
// graph view uses (state.gcDisplayMode / sprintDisplayMode / komDisplayMode).
import type { RiderSeries, RiderStagePoint } from "../types";
import { state } from "../state";
import { stageTableEl } from "../dom";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import { fmtGap } from "../formatters";

type Cell = {
  text: string;
  // Sort key used only to rank cells within a stage column for coloring —
  // "goodness" is oriented so larger is always better (green), regardless of
  // whether the underlying stat is itself lower-is-better (time, rank) or
  // higher-is-better (points).
  goodness: number | null;
  colorable: boolean;
};

/** Builds one cell from a rider's entry for a stage. `sp` is undefined when
 *  the rider has no data there (race not run yet, or they'd already exited
 *  the race by an earlier stage). */
function cellFor(sp: RiderStagePoint | undefined): Cell {
  if (!sp) return { text: "", goodness: null, colorable: false };
  if (sp.status !== "FINISHED") return { text: sp.status, goodness: null, colorable: false };

  if (state.currentMetric === "gc") {
    if (state.gcDisplayMode === "time") {
      const v = sp.gcGapSeconds;
      return { text: fmtGap(v), goodness: v == null ? null : -v, colorable: v != null };
    }
    const v = sp.gcRank;
    return { text: v == null ? "—" : String(v), goodness: v == null ? null : -v, colorable: v != null };
  }

  if (state.currentMetric === "points") {
    if (state.sprintDisplayMode === "points") {
      const v = sp.cumulativePoints;
      return { text: String(v), goodness: v > 0 ? v : null, colorable: v > 0 };
    }
    const v = sp.sprintRank;
    return { text: v == null ? "—" : String(v), goodness: v == null ? null : -v, colorable: v != null };
  }

  // kom
  if (state.komDisplayMode === "points") {
    const v = sp.cumulativeKomPoints;
    return { text: String(v), goodness: v > 0 ? v : null, colorable: v > 0 };
  }
  const v = sp.komRank;
  return { text: v == null ? "—" : String(v), goodness: v == null ? null : -v, colorable: v != null };
}

// Gradient stops as [hue, saturation%, lightness%], worst to best. Spelled
// out as stops rather than a plain 0→120 hue sweep so the ramp reads as four
// distinct bands — red, orange, yellow, green — and so the green end can sit
// brighter and more saturated than the red end, which is what makes the
// leaders pop out of a field of ~180 riders.
const GRADIENT_STOPS: Array<[number, number, number]> = [
  [0, 62, 20],   // red — worst
  [22, 60, 24],  // orange
  [48, 55, 26],  // yellow
  [88, 50, 26],  // yellow-green
  [132, 55, 30], // green — best
];

// A raw percentile spreads evenly across the field, which on a 180-rider
// column leaves everyone from 1st to ~30th in near-identical green. Raising
// it to this power stretches the best end across far more of the ramp (top
// ~10 green, ~20th yellow-green, ~40-50th yellow, midfield orange). The cost
// is resolution at the bottom, where the difference between 120th and 140th
// isn't worth distinguishing anyway.
const TOP_EMPHASIS = 2;

/** Maps a 0..1 percentile (1 = best) onto GRADIENT_STOPS, after the
 *  TOP_EMPHASIS curve. */
function rampColor(t: number): string {
  const scaled = Math.pow(t, TOP_EMPHASIS) * (GRADIENT_STOPS.length - 1);
  const i = Math.min(Math.floor(scaled), GRADIENT_STOPS.length - 2);
  const f = scaled - i;
  const [h0, s0, l0] = GRADIENT_STOPS[i];
  const [h1, s1, l1] = GRADIENT_STOPS[i + 1];
  const lerp = (a: number, b: number) => Math.round((a + (b - a) * f) * 10) / 10;
  return `hsl(${lerp(h0, h1)}, ${lerp(s0, s1)}%, ${lerp(l0, l1)}%)`;
}

/** Light background tint for a cell: red (worst in this stage column) through
 *  green (best), based on where its "goodness" value falls among every
 *  colorable cell in the same column — a percentile rank rather than a raw
 *  linear scale, so one outlier (e.g. a broom-wagon gap) doesn't wash out the
 *  rest of the gradient. */
function colorScaleForColumn(cells: Cell[]): (goodness: number) => string {
  const sorted = [...new Set(cells.filter((c) => c.colorable && c.goodness != null).map((c) => c.goodness as number))]
    .sort((a, b) => a - b);
  const rankOf = new Map(sorted.map((g, i) => [g, i]));
  const n = sorted.length;
  return (goodness: number) => {
    if (n <= 1) return rampColor(1);
    return rampColor((rankOf.get(goodness) ?? 0) / (n - 1));
  };
}

function riderSortKey(rider: RiderSeries): [number, number, string] {
  // Bib-ordered first (1 at top); riders with no known bib sort after every
  // bibbed rider, alphabetically among themselves.
  if (rider.bibNumber != null) return [0, rider.bibNumber, ""];
  return [1, 0, displayName(rider)];
}

export function drawStageTable() {
  if (!state.dataset) return;
  stageTableEl.innerHTML = "";

  const stages = state.dataset.stages;
  // Sort keys computed once per rider rather than rebuilt twice on every
  // comparison.
  const sortKeys = new Map(state.dataset.riders.map((r) => [r.id, riderSortKey(r)] as const));
  const riders = [...state.dataset.riders].sort((a, b) => {
    const ka = sortKeys.get(a.id)!;
    const kb = sortKeys.get(b.id)!;
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    if (ka[1] !== kb[1]) return ka[1] - kb[1];
    return ka[2].localeCompare(kb[2]);
  });

  // Every cell, indexed [riderIndex][stageIndex], precomputed so the
  // per-column color scales can be built before any row is rendered. Each
  // rider's byStage array is walked once into a stage-number lookup, rather
  // than a .find() scan per (rider, stage) pair — the same O(riders x
  // stages^2) trap the bump chart's rank maps already avoid.
  const grid: Cell[][] = riders.map((rider) => {
    const byStage = new Map<number, RiderStagePoint>();
    for (const sp of rider.byStage) byStage.set(sp.stage, sp);
    return stages.map((s) => cellFor(byStage.get(s.stage_number)));
  });
  const colorScales = stages.map((_, si) => colorScaleForColumn(grid.map((row) => row[si])));

  const wrap = document.createElement("div");
  wrap.className = "stage-table-wrap";

  const table = document.createElement("table");
  table.className = "stage-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const bibTh = document.createElement("th");
  bibTh.className = "col-bib";
  bibTh.textContent = "Bib";
  const riderTh = document.createElement("th");
  riderTh.className = "col-rider";
  riderTh.textContent = "Rider";
  headRow.appendChild(bibTh);
  headRow.appendChild(riderTh);
  for (const stage of stages) {
    const th = document.createElement("th");
    th.textContent = stage.stage_label;
    if (stage.start_location || stage.finish_location) {
      th.title = `${stage.start_location ?? "?"} → ${stage.finish_location ?? "?"}`;
    }
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  riders.forEach((rider, ri) => {
    const row = document.createElement("tr");

    const bibTd = document.createElement("td");
    bibTd.className = "col-bib";
    bibTd.textContent = rider.bibNumber != null ? String(rider.bibNumber) : "—";
    row.appendChild(bibTd);

    const riderTd = document.createElement("td");
    riderTd.className = "col-rider";
    const nameSpan = document.createElement("span");
    nameSpan.className = "stage-table-name";
    nameSpan.textContent = displayName(rider);
    nameSpan.title = rider.team ?? "";
    nameSpan.addEventListener("click", () => {
      const slug = rider.id.replace(/^rider\//, "");
      window.location.hash = `#riders/${slug}`;
    });
    riderTd.appendChild(nameSpan);
    const flag = nationalityFlagEl(rider.nationality);
    if (flag) riderTd.appendChild(flag);
    row.appendChild(riderTd);

    grid[ri].forEach((cell, si) => {
      const td = document.createElement("td");
      td.textContent = cell.text;
      if (cell.colorable && cell.goodness != null) {
        td.style.background = colorScales[si](cell.goodness);
      } else if (cell.text && cell.text !== "—") {
        td.classList.add("stage-table-status");
      }
      row.appendChild(td);
    });

    tbody.appendChild(row);
  });
  table.appendChild(tbody);

  wrap.appendChild(table);
  stageTableEl.appendChild(wrap);
}
