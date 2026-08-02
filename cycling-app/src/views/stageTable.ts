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

/** Finds a rider's byStage entry for a given stage number, or undefined if
 *  the rider has no data there (race not run yet, or they'd already exited
 *  the race by an earlier stage). */
function pointAt(rider: RiderSeries, stageNumber: number): RiderStagePoint | undefined {
  return rider.byStage.find((p) => p.stage === stageNumber);
}

function cellFor(rider: RiderSeries, stageNumber: number): Cell {
  const sp = pointAt(rider, stageNumber);
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

/** Light background tint for a cell: red (worst in this stage column) through
 *  green (best), based on where its "goodness" value falls among every
 *  colorable cell in the same column — a percentile rank rather than a raw
 *  linear scale, so one outlier (e.g. a broom-wagon gap) doesn't wash out the
 *  rest of the gradient. */
function colorScaleForColumn(cells: Cell[]): (goodness: number) => string {
  const sorted = [...new Set(cells.filter((c) => c.colorable && c.goodness != null).map((c) => c.goodness as number))]
    .sort((a, b) => a - b);
  const n = sorted.length;
  return (goodness: number) => {
    if (n <= 1) return "hsl(70, 45%, 24%)";
    const idx = sorted.indexOf(goodness);
    const t = idx / (n - 1);
    const hue = 120 * t; // 0 = red, 120 = green
    return `hsl(${hue}, 55%, 24%)`;
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
  const riders = [...state.dataset.riders].sort((a, b) => {
    const ka = riderSortKey(a);
    const kb = riderSortKey(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    if (ka[1] !== kb[1]) return ka[1] - kb[1];
    return ka[2].localeCompare(kb[2]);
  });

  // Precompute every cell up front so we can build per-column color scales
  // before rendering rows.
  const cellsByStage = new Map<number, Cell[]>();
  const cellByRiderStage = new Map<string, Cell>();
  for (const stage of stages) {
    const cells: Cell[] = [];
    for (const rider of riders) {
      const cell = cellFor(rider, stage.stage_number);
      cells.push(cell);
      cellByRiderStage.set(`${rider.id}:${stage.stage_number}`, cell);
    }
    cellsByStage.set(stage.stage_number, cells);
  }
  const colorScaleByStage = new Map<number, (goodness: number) => string>();
  for (const stage of stages) {
    colorScaleByStage.set(stage.stage_number, colorScaleForColumn(cellsByStage.get(stage.stage_number)!));
  }

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
  for (const rider of riders) {
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

    for (const stage of stages) {
      const td = document.createElement("td");
      const cell = cellByRiderStage.get(`${rider.id}:${stage.stage_number}`)!;
      td.textContent = cell.text;
      if (cell.colorable && cell.goodness != null) {
        td.style.background = colorScaleByStage.get(stage.stage_number)!(cell.goodness);
      } else if (cell.text && cell.text !== "—") {
        td.classList.add("stage-table-status");
      }
      row.appendChild(td);
    }

    tbody.appendChild(row);
  }
  table.appendChild(tbody);

  wrap.appendChild(table);
  stageTableEl.appendChild(wrap);
}
