// By Stage Table view: a spreadsheet-style grid of every rider (rows,
// ordered by bib number) x every stage (columns), showing whichever GC /
// Sprint / KOM value is currently selected via the same toggle buttons the
// graph view uses (state.gcDisplayMode / sprintDisplayMode / komDisplayMode).
import type { RiderSeries, RiderStagePoint } from "../types";
import { state, raceConfig } from "../state";
import { stageTableEl, chartAreaEl, gcTimeToggleBtn, sprintModeToggleBtn, komModeToggleBtn } from "../dom";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import { fmtGapHM } from "../formatters";
import { showStageTooltip, hideTooltip } from "../tooltip";

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
      return { text: fmtGapHM(v, sp.gcRank), goodness: v == null ? null : -v, colorable: v != null };
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

/** Rank teams like a medal table: most wins first, ties broken by most 2nd
 *  places, then 3rd, and so on.
 *
 *  Only meaningful for an aggregate race, where a season's "stages" are
 *  separate races and a bib is not a stable identity (numbers are reassigned
 *  every race, and two teams can share a range — see ai-context.md). Returns
 *  team name -> display order; a team absent from the map (rider with no
 *  team) sorts last.
 *
 *  Comparing full count vectors is O(maxRank) per comparison, so the ordering
 *  is resolved ONCE here and each rider then carries a plain integer key —
 *  rather than re-deriving it inside the rider comparator.
 */
function buildTeamOrder(riders: RiderSeries[]): Map<string, number> {
  const counts = new Map<string, number[]>();
  let maxRank = 0;
  for (const rider of riders) {
    if (!rider.team) continue;
    let vec = counts.get(rider.team);
    if (!vec) counts.set(rider.team, (vec = []));
    for (const sp of rider.byStage) {
      const rank = sp.gcRank;
      // DNF/DNS carry no rank and contribute nothing — a team is ordered on
      // what it achieved, not on how many riders it entered.
      if (rank == null) continue;
      vec[rank] = (vec[rank] ?? 0) + 1;
      if (rank > maxRank) maxRank = rank;
    }
  }

  const ordered = [...counts.keys()].sort((a, b) => {
    const va = counts.get(a)!;
    const vb = counts.get(b)!;
    for (let rank = 1; rank <= maxRank; rank++) {
      const diff = (vb[rank] ?? 0) - (va[rank] ?? 0);
      if (diff !== 0) return diff;
    }
    // Identical record (commonly: no finishers at all) — keep it stable and
    // predictable rather than leaving it to sort implementation order.
    return a.localeCompare(b);
  });

  return new Map(ordered.map((team, i) => [team, i]));
}

/** Which rows get the alternating team wash: flips at every team boundary in
 *  the sorted list, so each contiguous block alternates with its neighbours.
 *
 *  Keyed on the BOUNDARY rather than on team identity, which means a trailing
 *  run of riders with no team reads as one block instead of banding on and off
 *  once per rider — and a team that somehow appears twice still delineates
 *  correctly against whatever sits next to it. */
function buildTeamBands(riders: RiderSeries[]): boolean[] {
  const bands = new Array<boolean>(riders.length).fill(false);
  let band = false;
  for (let i = 0; i < riders.length; i++) {
    if (i > 0 && riders[i].team !== riders[i - 1].team) band = !band;
    bands[i] = band;
  }
  return bands;
}

/** Compute team groupings from the sorted rider list.
 *  Returns an array parallel to `riders` where each entry is:
 *  - rowspan > 0: emit a team cell spanning this many rows
 *  - rowspan === 0: skip (the cell above already spans this row)
 *  Only consecutive runs of the same non-null team are merged. */
function buildTeamRowspans(riders: RiderSeries[]): number[] {
  const rowspans = new Array<number>(riders.length).fill(1);
  let i = 0;
  while (i < riders.length) {
    const team = riders[i].team;
    if (team === null) { i++; continue; }
    let j = i + 1;
    while (j < riders.length && riders[j].team === team) j++;
    const span = j - i;
    rowspans[i] = span;
    for (let k = i + 1; k < j; k++) rowspans[k] = 0;
    i = j;
  }
  return rowspans;
}

export function drawStageTable() {
  if (!state.dataset) return;
  // Rescue toggle buttons from the previous wrap (if they were moved there)
  // before innerHTML = "" would destroy them.
  for (const btn of [gcTimeToggleBtn, sprintModeToggleBtn, komModeToggleBtn]) {
    chartAreaEl.appendChild(btn);
  }
  stageTableEl.innerHTML = "";

  const stages = state.dataset.stages;
  // An aggregate race groups by team and hides the bib column: bib numbers are
  // reassigned per race and two teams can legitimately share a range, so they
  // are neither a stable identity nor a useful ordering here.
  const groupByTeam = raceConfig().stagesAreRaces;

  // Sort keys computed once per rider rather than rebuilt twice on every
  // comparison.
  const teamOrder = groupByTeam ? buildTeamOrder(state.dataset.riders) : null;
  const sortKeys = new Map(state.dataset.riders.map((r) => {
    if (!teamOrder) return [r.id, riderSortKey(r)] as const;
    // Team block first (medal-table order), then the team's best rider at the
    // top of its block, then name.
    const key: [number, number, string] = [
      r.team ? teamOrder.get(r.team) ?? Number.MAX_SAFE_INTEGER : Number.MAX_SAFE_INTEGER,
      r.finalRank,
      displayName(r),
    ];
    return [r.id, key] as const;
  }));
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

  const hasTeams = riders.some((r) => r.team !== null);
  const teamRowspans = hasTeams ? buildTeamRowspans(riders) : [];
  const teamBands = hasTeams ? buildTeamBands(riders) : [];

  const wrap = document.createElement("div");
  wrap.className = "stage-table-wrap";

  const table = document.createElement("table");
  const classes = ["stage-table"];
  if (hasTeams) classes.push("has-teams");
  // Shifts the sticky rider column left over the hidden bib column.
  if (groupByTeam) classes.push("no-bib");
  table.className = classes.join(" ");

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");

  if (hasTeams) {
    const teamTh = document.createElement("th");
    teamTh.className = "col-team";
    teamTh.textContent = "T";
    teamTh.title = "Teams";
    headRow.appendChild(teamTh);
  }

  if (!groupByTeam) {
    const bibTh = document.createElement("th");
    bibTh.className = "col-bib";
    bibTh.textContent = "Bib";
    headRow.appendChild(bibTh);
  }

  const riderTh = document.createElement("th");
  riderTh.className = "col-rider";
  riderTh.textContent = "Rider";
  headRow.appendChild(riderTh);

  const stageThs: HTMLTableCellElement[] = [];
  for (const stage of stages) {
    const th = document.createElement("th");
    th.className = stage.cancelled ? "col-stage col-stage-cancelled" : "col-stage";
    // Columns are narrow, so use the abbreviation and keep the full race name
    // in the title attribute alongside any cancellation note.
    th.textContent = stage.stage_short_label ?? stage.stage_label;
    const cancelledNote = stage.cancelled
      ? `${raceConfig().stagesAreRaces ? "Race" : "Stage"} cancelled`
      : "";
    th.title = stage.stage_short_label
      ? [stage.stage_label, cancelledNote].filter(Boolean).join(" — ")
      : cancelledNote;
    th.addEventListener("mouseenter", (e) => showStageTooltip(e, stage));
    th.addEventListener("mouseleave", hideTooltip);
    headRow.appendChild(th);
    stageThs.push(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  riders.forEach((rider, ri) => {
    const row = document.createElement("tr");
    if (teamBands[ri]) row.classList.add("team-band");

    if (hasTeams) {
      const rowspan = teamRowspans[ri];
      if (rowspan > 0) {
        const teamTd = document.createElement("td");
        teamTd.className = "col-team";
        if (rowspan > 1) teamTd.rowSpan = rowspan;
        if (rider.team) {
          const inner = document.createElement("span");
          inner.className = "col-team-inner";
          inner.textContent = rider.team;
          teamTd.appendChild(inner);
        }
        row.appendChild(teamTd);
      }
      // rowspan === 0: no cell emitted; the spanning cell above covers this row
    }

    if (!groupByTeam) {
      const bibTd = document.createElement("td");
      bibTd.className = "col-bib";
      bibTd.textContent = rider.bibNumber != null ? String(rider.bibNumber) : "—";
      row.appendChild(bibTd);
    }

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
  // Move toggle buttons into the wrap so they anchor to its top-right corner
  // (positioned via .y-axis-toggle.table-mode CSS relative to the wrap).
  for (const btn of [gcTimeToggleBtn, sprintModeToggleBtn, komModeToggleBtn]) {
    wrap.appendChild(btn);
  }
  stageTableEl.appendChild(wrap);

  // Auto table-layout sizes each stage column to its own content, so an
  // early stage with only short values (e.g. "leader") ends up visibly
  // narrower than later stages with wider gaps. Pin every stage column to
  // the widest one so the grid reads evenly.
  const widest = Math.max(...stageThs.map((th) => th.getBoundingClientRect().width));
  for (const th of stageThs) th.style.width = `${widest}px`;
}
