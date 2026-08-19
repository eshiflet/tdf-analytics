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

/** Does this rider have at least one finish inside `limit` in ANY race of the
 *  season?
 *
 *  For an aggregate race each column IS a separate one-day race, so `gcRank`
 *  is that rider's finishing position in it and "a top-10 result" means
 *  exactly what it sounds like. On a Grand Tour the same field is the running
 *  GC position instead — a completely different claim — which is why the
 *  controls that use this only render when `stagesAreRaces`.
 *
 *  Deliberately reads byStage rather than `finalRank`. The two agree today
 *  (an aggregate's finalRank IS the season's best finish, see ai-context.md),
 *  but that is a property of the exporter, and this reads the thing the
 *  button actually claims to filter on. */
function hasTopFinish(rider: RiderSeries, limit: number): boolean {
  return rider.byStage.some((sp) => sp.gcRank != null && sp.gcRank <= limit);
}

/** Row filter for the table: best-finish limit AND nationality (OR within the
 *  nation list). Both empty = every rider passes. */
function passesTableFilter(rider: RiderSeries): boolean {
  if (state.stageTableTopFilter != null && !hasTopFinish(rider, state.stageTableTopFilter)) {
    return false;
  }
  if (state.stageTableFilterNations.size > 0
      && !(rider.nationality && state.stageTableFilterNations.has(rider.nationality))) {
    return false;
  }
  return true;
}

/** The Top 10 / Top 20 / Nation cluster that sits to the right of the table.
 *
 *  Built here rather than in index.html because it is table-scoped: the
 *  sidebar's visually-identical controls are wired to `state.selected` and are
 *  re-queried by main.ts through `.button-row button`, so reusing those class
 *  names would let a year change strip these buttons' active state. Hence the
 *  parallel `table-filter-*` classes.
 *
 *  `redraw` re-enters drawStageTable, which rebuilds this cluster too — fine,
 *  because every piece of its state lives in `state`, not in the DOM. */
function buildTableControls(riders: RiderSeries[], redraw: () => void): HTMLDivElement {
  const controls = document.createElement("div");
  controls.className = "stage-table-controls";

  const row = document.createElement("div");
  row.className = "table-filter-row";
  for (const limit of [10, 20] as const) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = `Top ${limit}`;
    btn.title = `Riders with at least one top-${limit} finish in any race this season`;
    btn.classList.toggle("active", state.stageTableTopFilter === limit);
    btn.addEventListener("click", () => {
      // Mutually exclusive, and clicking the active one clears it — the pair
      // has no "All" button, so the lit button must be its own way out.
      state.stageTableTopFilter = state.stageTableTopFilter === limit ? null : limit;
      redraw();
    });
    row.appendChild(btn);
  }
  controls.appendChild(row);

  const nations = [...new Set(riders.map((r) => r.nationality).filter((n): n is string => !!n))]
    .sort();

  const dropdown = document.createElement("div");
  dropdown.className = "table-filter-dropdown";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "filter-toggle-btn";
  const count = state.stageTableFilterNations.size;
  toggle.textContent = count > 0 ? `Nation (${count})` : "Nation";
  toggle.classList.toggle("active", count > 0);

  const panel = document.createElement("div");
  panel.className = "filter-panel";
  panel.hidden = true;

  const actions = document.createElement("div");
  actions.className = "filter-panel-actions";
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "filter-panel-clear";
  clear.textContent = "Clear";
  clear.addEventListener("click", () => {
    state.stageTableFilterNations.clear();
    redraw();
  });
  actions.appendChild(clear);
  panel.appendChild(actions);

  for (const nation of nations) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = nation;
    cb.checked = state.stageTableFilterNations.has(nation);
    cb.addEventListener("change", () => {
      if (cb.checked) state.stageTableFilterNations.add(nation);
      else state.stageTableFilterNations.delete(nation);
      // Keep the panel open across a redraw: picking several nations in a row
      // is the normal case, and reopening it every time would be hostile.
      tableFilterPanelOpen = true;
      redraw();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(nation));
    const flag = nationalityFlagEl(nation);
    if (flag) label.appendChild(flag);
    panel.appendChild(label);
  }

  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    tableFilterPanelOpen = panel.hidden;
    panel.hidden = !panel.hidden;
  });
  panel.hidden = !tableFilterPanelOpen;

  dropdown.appendChild(toggle);
  dropdown.appendChild(panel);
  controls.appendChild(dropdown);

  const shown = riders.filter(passesTableFilter).length;
  if (shown !== riders.length) {
    const count = document.createElement("div");
    count.className = "table-filter-count";
    count.textContent = `${shown} of ${riders.length}`;
    controls.appendChild(count);
  }

  return controls;
}

/** Whether the Nation panel is open. Module-level rather than DOM-read because
 *  drawStageTable rebuilds the cluster from scratch on every filter change. */
let tableFilterPanelOpen = false;

/** Closes the table's Nation dropdown on an outside click. main.ts's own
 *  handler only knows about the sidebar's two panels (it closes anything
 *  outside `.filter-dropdown`, which this deliberately is not). */
document.addEventListener("click", (e) => {
  if (!tableFilterPanelOpen) return;
  const target = e.target as HTMLElement;
  if (target.closest(".table-filter-dropdown")) return;
  tableFilterPanelOpen = false;
  stageTableEl.querySelectorAll<HTMLDivElement>(".table-filter-dropdown .filter-panel")
    .forEach((p) => (p.hidden = true));
});

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
  const allRiders = [...state.dataset.riders].sort((a, b) => {
    const ka = sortKeys.get(a.id)!;
    const kb = sortKeys.get(b.id)!;
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    if (ka[1] !== kb[1]) return ka[1] - kb[1];
    return ka[2].localeCompare(kb[2]);
  });
  // Row filters apply only where they are offered (see buildTableControls).
  const filterable = raceConfig().stagesAreRaces;
  if (filterable) {
    // Nationalities are per-season, so carry the selection across a year
    // change but drop any nation that did not race this year — otherwise a
    // filter left on from 2023 can silently empty 1913.
    const present = new Set(allRiders.map((r) => r.nationality).filter((n): n is string => !!n));
    for (const n of state.stageTableFilterNations) {
      if (!present.has(n)) state.stageTableFilterNations.delete(n);
    }
  }
  const riders = filterable ? allRiders.filter(passesTableFilter) : allRiders;

  // Every cell, indexed [riderIndex][stageIndex], precomputed so the
  // per-column color scales can be built before any row is rendered. Each
  // rider's byStage array is walked once into a stage-number lookup, rather
  // than a .find() scan per (rider, stage) pair — the same O(riders x
  // stages^2) trap the bump chart's rank maps already avoid.
  const cellsFor = (rider: RiderSeries): Cell[] => {
    const byStage = new Map<number, RiderStagePoint>();
    for (const sp of rider.byStage) byStage.set(sp.stage, sp);
    return stages.map((s) => cellFor(byStage.get(s.stage_number)));
  };
  const grid: Cell[][] = riders.map(cellsFor);
  // Built from EVERY rider, not just the visible ones: the ramp answers "how
  // good is this result against the field", and filtering to the top 10 must
  // not repaint their wins from green to red by re-spreading the scale over a
  // field that is now all winners.
  const scaleGrid = riders.length === allRiders.length ? grid : allRiders.map(cellsFor);
  const colorScales = stages.map((_, si) => colorScaleForColumn(scaleGrid.map((row) => row[si])));

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
    // No `title` attribute: it renders the NATIVE browser tooltip on top of the
    // custom one below, which is why a one-day race's column showed two
    // tooltips at once. Everything it carried — full race name, cancellation —
    // now lives in showStageTooltip instead.
    if (stage.cancelled && !stage.stage_short_label) {
      th.title = `${raceConfig().stagesAreRaces ? "Race" : "Stage"} cancelled`;
    }
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
  if (riders.length === 0) {
    const empty = document.createElement("div");
    empty.className = "stage-table-empty";
    empty.textContent = "No riders match these filters.";
    wrap.appendChild(empty);
  }

  stageTableEl.appendChild(wrap);
  if (filterable) {
    stageTableEl.appendChild(buildTableControls(allRiders, drawStageTable));
  }

  // Auto table-layout sizes each stage column to its own content, so an
  // early stage with only short values (e.g. "leader") ends up visibly
  // narrower than later stages with wider gaps. Pin every stage column to
  // the widest one so the grid reads evenly.
  //
  // Guarded: a filter can empty the table, and Math.max() of nothing is
  // -Infinity, which sets every width to "-Infinitypx" and throws the header
  // layout away for the rest of the session.
  if (stageThs.length > 0) {
    const widest = Math.max(...stageThs.map((th) => th.getBoundingClientRect().width));
    for (const th of stageThs) th.style.width = `${widest}px`;
  }
}
