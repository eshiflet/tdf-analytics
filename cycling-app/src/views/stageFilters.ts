// By Stage Team/Nation filter dropdowns and the selection they drive.
import { state } from "../state";
import { teamFilterBtn, teamFilterPanel, nationFilterBtn, nationFilterPanel } from "../dom";
import { compareNames, nationalityFlagEl } from "../riderDisplay";
import { updateLineClasses } from "./stageHighlight";
import { refreshLegendState } from "./stageLegend";

/** Recomputes `selected` from the active team/nation filters (OR within a
 *  facet, AND across facets). No-op if neither filter has a selection, so it
 *  never fights with the Top 10/20/All quick-select buttons when unused. */
export function applyStageTeamNationFilter() {
  if (!state.dataset) return;
  if (state.stageFilterTeams.size === 0 && state.stageFilterNations.size === 0) return;
  state.selected = new Set(
    state.dataset.riders
      .filter(
        (r) =>
          (state.stageFilterTeams.size === 0 || (r.team && state.stageFilterTeams.has(r.team))) &&
          (state.stageFilterNations.size === 0 || (r.nationality && state.stageFilterNations.has(r.nationality))),
      )
      .map((r) => r.id),
  );
  document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
    b.classList.remove("active"),
  );
}

export function updateFilterButtonLabel(btn: HTMLButtonElement, base: string, count: number) {
  btn.textContent = count > 0 ? `${base} (${count})` : base;
  btn.classList.toggle("active", count > 0);
}

export function closeFilterPanels() {
  teamFilterPanel.hidden = true;
  nationFilterPanel.hidden = true;
}

export function clearStageTeamNationFilters() {
  state.stageFilterTeams.clear();
  state.stageFilterNations.clear();
  updateFilterButtonLabel(teamFilterBtn, "Team", 0);
  updateFilterButtonLabel(nationFilterBtn, "Nation", 0);
  teamFilterPanel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(
    (cb) => (cb.checked = false),
  );
  nationFilterPanel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(
    (cb) => (cb.checked = false),
  );
  closeFilterPanels();
}

function buildFilterPanel(
  panel: HTMLDivElement,
  options: string[],
  activeSet: Set<string>,
  btn: HTMLButtonElement,
  baseLabel: string,
  showFlags = false,
) {
  panel.innerHTML = "";

  const actions = document.createElement("div");
  actions.className = "filter-panel-actions";
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "filter-panel-clear";
  clear.textContent = "Clear";
  clear.addEventListener("click", () => {
    activeSet.clear();
    panel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach((cb) => (cb.checked = false));
    updateFilterButtonLabel(btn, baseLabel, activeSet.size);
    applyStageTeamNationFilter();
    refreshLegendState();
    updateLineClasses();
  });
  actions.appendChild(clear);
  panel.appendChild(actions);

  for (const option of options) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = option;
    cb.checked = activeSet.has(option);
    cb.addEventListener("change", () => {
      if (cb.checked) activeSet.add(option);
      else activeSet.delete(option);
      updateFilterButtonLabel(btn, baseLabel, activeSet.size);
      applyStageTeamNationFilter();
      refreshLegendState();
      updateLineClasses();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(option));
    if (showFlags) {
      const flag = nationalityFlagEl(option);
      if (flag) label.appendChild(flag);
    }
    panel.appendChild(label);
  }
}

/** Rebuilds the Team/Nation dropdown contents for the current dataset and
 *  resets both filters (team/nation membership is specific to each year). */
export function buildStageFilters() {
  if (!state.dataset) return;
  const hadActiveFilter = state.stageFilterTeams.size > 0 || state.stageFilterNations.size > 0;

  const teams = [...new Set(state.dataset.riders.map((r) => r.team).filter((t): t is string => !!t))].sort(compareNames);
  const nations = [...new Set(state.dataset.riders.map((r) => r.nationality).filter((n): n is string => !!n))].sort(compareNames);

  // Carry the filter *values* over across a year change, dropping only the
  // ones that don't exist in the new year's teams/nations (e.g. a team name
  // from 2024 that didn't race in 2022).
  state.stageFilterTeams = new Set([...state.stageFilterTeams].filter((t) => teams.includes(t)));
  state.stageFilterNations = new Set([...state.stageFilterNations].filter((n) => nations.includes(n)));

  updateFilterButtonLabel(teamFilterBtn, "Team", state.stageFilterTeams.size);
  updateFilterButtonLabel(nationFilterBtn, "Nation", state.stageFilterNations.size);

  buildFilterPanel(teamFilterPanel, teams, state.stageFilterTeams, teamFilterBtn, "Team");
  buildFilterPanel(nationFilterPanel, nations, state.stageFilterNations, nationFilterBtn, "Nation", true);

  if (state.stageFilterTeams.size > 0 || state.stageFilterNations.size > 0) {
    applyStageTeamNationFilter();
  } else if (hadActiveFilter) {
    // Every previously-selected team/nation was absent from this year —
    // nothing carries over, so behave like the "None" button was pressed.
    state.selected = new Set();
    document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
      b.classList.remove("active"),
    );
  }
}
