// Riders view: a searchable/filterable grid of every rider in the selected
// race(s), with a click-through to the per-rider detail page (riderDetail.ts).
// riders.ts and riderDetail.ts call each other for grid↔detail navigation,
// and both call back into main.ts for cross-view navigation (setRace,
// loadDataset, switchView) — a real but safe circular import, since every
// cross-reference happens inside event handlers, never at module load time.
// See architecture.md's "Frontend module map" for the full rationale.
import type { RaceId } from "../raceRegistry";
import { RACE_IDS, RACE_ABBR, RACE_SHORT_LABEL, RACES, URLS_BY_RACE } from "../raceRegistry";
import { state } from "../state";
import { ridersChartEl } from "../dom";
import { updateHash } from "../hashRouting";
import { showLoadError } from "../main";
import { debounce } from "../utils";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import type { RiderEntry } from "../riderIndexData";
import {
  riderIndexByRace, allTeamsSortedByRace, allNationalitiesSortedByRace,
  riderIndexBuilt, ensureRiderIndexFor,
} from "../riderIndexData";
import type { JerseyCategory } from "../jerseyIcons";
import { JERSEY_LABELS, JERSEY_SIMPLE_LABEL, jerseyIconSvgForRace, jerseyIconsElMultiRace, jerseyYearsWon } from "../jerseyIcons";
import { drawRiderDetail } from "./riderDetail";

export function selectedRacesForRiders(): RaceId[] {
  return state.ridersFilterRaces.size === 0 ? [...RACE_IDS] : RACE_IDS.filter((r) => state.ridersFilterRaces.has(r));
}

// Merging clones every rider entry (new Map/Set per rider) across all selected
// races, which is wasted work when only the search text or a non-race filter
// changed. Cache the merge, keyed on the selected race set — safe because
// drawRidersPage() always awaits ensureRiderIndexFor() for every selected race
// before filteredRiders() can run, and a race's index never mutates afterward.
let mergedRidersCache: { racesKey: string; entries: RiderEntry[] } | null = null;

export function mergedRidersForSelectedRaces(): RiderEntry[] {
  const races = selectedRacesForRiders();
  const racesKey = races.join(",");
  if (mergedRidersCache && mergedRidersCache.racesKey === racesKey) {
    return mergedRidersCache.entries;
  }
  const mergedById = new Map<string, RiderEntry>();
  for (const race of races) {
    for (const [id, entry] of riderIndexByRace[race]) {
      if (mergedById.has(id)) {
        const existing = mergedById.get(id)!;
        for (const [year, yearData] of entry.years) {
          if (!existing.years.has(year)) existing.years.set(year, yearData);
        }
        for (const team of entry.teams) existing.teams.add(team);
      } else {
        mergedById.set(id, { ...entry, years: new Map(entry.years), teams: new Set(entry.teams) });
      }
    }
  }
  const entries = [...mergedById.values()];
  mergedRidersCache = { racesKey, entries };
  return entries;
}

export function filteredRiders(): RiderEntry[] {
  const q = state.ridersSearchQuery.toLowerCase();
  const yr = state.ridersFilterYear ? parseInt(state.ridersFilterYear) : null;
  const selectedRaces = selectedRacesForRiders();
  return mergedRidersForSelectedRaces()
    .filter((e) => {
      if (q && !e.name.toLowerCase().includes(q) && !displayName(e).toLowerCase().includes(q)) return false;
      if (yr !== null && !e.years.has(yr)) return false;
      if (state.ridersFilterTeam && !e.teams.has(state.ridersFilterTeam)) return false;
      if (state.ridersFilterNationality && e.nationality !== state.ridersFilterNationality) return false;
      if (state.ridersFilterJerseys.size > 0) {
        for (const key of state.ridersFilterJerseys) {
          const [raceId, category] = key.split(":") as [RaceId, JerseyCategory];
          if (!selectedRaces.includes(raceId)) continue;
          const raceEntry = riderIndexByRace[raceId].get(e.id);
          if (!raceEntry || jerseyYearsWon(raceEntry)[category].length === 0) return false;
        }
      }
      return true;
    })
    .sort((a, b) => (a.lastName ?? a.name).localeCompare(b.lastName ?? b.name));
}

export async function drawRidersPage() {
  state.currentRiderId = null;
  updateHash();
  ridersChartEl.innerHTML = "";

  const racesToLoad = selectedRacesForRiders();
  const needsLoad = racesToLoad.some((r) => !riderIndexBuilt[r]);
  if (needsLoad) {
    const loading = document.createElement("div");
    loading.className = "riders-count-label";
    loading.textContent = "Loading riders…";
    ridersChartEl.appendChild(loading);
    await Promise.all(racesToLoad.map((r) => ensureRiderIndexFor(r)));
    // Bail out if the user navigated away, or if a rider detail took over.
    if (state.currentView !== "riders" || state.currentRiderId !== null) return;
    ridersChartEl.innerHTML = "";
  }

  // Compute year/team/nationality options from all currently-selected races.
  const allYears = [...new Set(racesToLoad.flatMap((r) => Object.keys(URLS_BY_RACE[r])))]
    .sort().reverse();
  const allTeams = [...new Set(racesToLoad.flatMap((r) => allTeamsSortedByRace[r]))].sort();
  const allNats = [...new Set(racesToLoad.flatMap((r) => allNationalitiesSortedByRace[r]))].sort();
  const controls = document.createElement("div");
  controls.className = "riders-controls";

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.placeholder = "Search rider name…";
  searchInput.className = "riders-search-input";
  searchInput.value = state.ridersSearchQuery;

  const yearSel = document.createElement("select");
  yearSel.className = "riders-filter-select";
  [["", "All years"], ...allYears.map((y) => [y, y])].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    yearSel.appendChild(opt);
  });
  yearSel.value = allYears.includes(state.ridersFilterYear) ? state.ridersFilterYear : "";
  if (!allYears.includes(state.ridersFilterYear)) state.ridersFilterYear = "";

  // ── Races multi-select dropdown ───────────────────────────────────────────
  const raceDropdownWrap = document.createElement("div");
  raceDropdownWrap.className = "filter-dropdown";

  const raceDropdownBtn = document.createElement("button");
  raceDropdownBtn.type = "button";
  raceDropdownBtn.className = "riders-race-dropdown-btn";
  function updateRaceDropdownBtn() {
    const label = state.ridersFilterRaces.size === 0
      ? "All races"
      : RACE_IDS.filter((r) => state.ridersFilterRaces.has(r)).map((r) => RACE_ABBR[r]).join(", ");
    raceDropdownBtn.textContent = label + " ▾";
    raceDropdownBtn.classList.toggle("active", state.ridersFilterRaces.size > 0);
  }
  updateRaceDropdownBtn();

  const racePanel = document.createElement("div");
  racePanel.className = "filter-panel";
  racePanel.hidden = true;

  const raceShowAll = document.createElement("div");
  raceShowAll.className = "filter-panel-actions";
  const raceShowAllBtn = document.createElement("button");
  raceShowAllBtn.type = "button";
  raceShowAllBtn.className = "filter-panel-clear";
  raceShowAllBtn.textContent = "Show all";
  raceShowAllBtn.addEventListener("click", () => {
    state.ridersFilterRaces.clear();
    racePanel.querySelectorAll<HTMLInputElement>("input[type=checkbox]")
      .forEach((cb) => (cb.checked = false));
    updateRaceDropdownBtn();
    racePanel.hidden = true;
    drawRidersPage().catch(showLoadError);
  });
  raceShowAll.appendChild(raceShowAllBtn);
  racePanel.appendChild(raceShowAll);

  for (const raceId of RACE_IDS) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = raceId;
    cb.checked = state.ridersFilterRaces.has(raceId);
    cb.addEventListener("change", () => {
      if (cb.checked) state.ridersFilterRaces.add(raceId);
      else state.ridersFilterRaces.delete(raceId);
      // If the user unchecks all boxes, treat it as "all races".
      if (state.ridersFilterRaces.size === 0) {
        racePanel.querySelectorAll<HTMLInputElement>("input[type=checkbox]")
          .forEach((c) => (c.checked = false));
      }
      updateRaceDropdownBtn();
      racePanel.hidden = true;
      drawRidersPage().catch(showLoadError);
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(RACE_ABBR[raceId]));
    racePanel.appendChild(label);
  }

  raceDropdownBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    racePanel.hidden = !racePanel.hidden;
  });
  // Close the panel when clicking outside it.
  const closeRacePanel = (e: MouseEvent) => {
    if (!raceDropdownWrap.contains(e.target as Node)) racePanel.hidden = true;
  };
  document.addEventListener("click", closeRacePanel);

  raceDropdownWrap.append(raceDropdownBtn, racePanel);

  const teamSel = document.createElement("select");
  teamSel.className = "riders-filter-select";
  [["", "All teams"], ...allTeams.map((t) => [t, t])].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    teamSel.appendChild(opt);
  });
  teamSel.value = allTeams.includes(state.ridersFilterTeam) ? state.ridersFilterTeam : "";
  if (!allTeams.includes(state.ridersFilterTeam)) state.ridersFilterTeam = "";

  const nationalitySel = document.createElement("select");
  nationalitySel.className = "riders-filter-select";
  [["", "All nationalities"], ...allNats.map((n) => [n, n])].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    nationalitySel.appendChild(opt);
  });
  nationalitySel.value = allNats.includes(state.ridersFilterNationality) ? state.ridersFilterNationality : "";
  if (!allNats.includes(state.ridersFilterNationality)) state.ridersFilterNationality = "";

  // Jersey filter toggles grouped by race. AND semantics: selecting more than
  // one narrows to riders who've won every selected category in that race.
  const jerseyFilterGroup = document.createElement("div");
  jerseyFilterGroup.className = "jersey-filter-group";
  const jerseyFilterBtns: HTMLButtonElement[] = [];
  racesToLoad.forEach((race, raceIdx) => {
    if (raceIdx > 0) {
      const sep = document.createElement("div");
      sep.className = "jersey-filter-sep";
      const spacer = document.createElement("div");
      spacer.className = "jersey-filter-sep-spacer";
      spacer.setAttribute("aria-hidden", "true");
      spacer.textContent = " "; // matches jersey-filter-race-label's line height exactly
      const dash = document.createElement("div");
      dash.className = "jersey-filter-sep-dash";
      dash.textContent = "-";
      sep.append(spacer, dash);
      jerseyFilterGroup.appendChild(sep);
    }
    const raceGroup = document.createElement("div");
    raceGroup.className = "jersey-filter-race-group";
    const raceLabel = document.createElement("div");
    raceLabel.className = "jersey-filter-race-label";
    raceLabel.textContent = RACE_SHORT_LABEL[race];
    raceGroup.appendChild(raceLabel);
    const raceBtns = document.createElement("div");
    raceBtns.className = "jersey-filter-race-btns";
    raceGroup.appendChild(raceBtns);
    jerseyFilterGroup.appendChild(raceGroup);
    (Object.keys(JERSEY_LABELS) as JerseyCategory[]).forEach((category) => {
      if (category === "youth" && !RACES[race].hasYouth) return;
      const key = `${race}:${category}`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "jersey-filter-btn";
      btn.classList.toggle("active", state.ridersFilterJerseys.has(key));
      btn.title = `${RACE_ABBR[race]} - ${JERSEY_SIMPLE_LABEL[category]}`;
      btn.innerHTML = jerseyIconSvgForRace(category, race);
      btn.dataset.key = key;
      raceBtns.appendChild(btn);
      jerseyFilterBtns.push(btn);
    });
  });

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "riders-clear-btn";
  clearBtn.textContent = "Clear All";

  const countLabel = document.createElement("span");
  countLabel.className = "riders-count-label";

  controls.append(searchInput, yearSel, raceDropdownWrap, teamSel, nationalitySel, jerseyFilterGroup, clearBtn, countLabel);
  ridersChartEl.appendChild(controls);

  const grid = document.createElement("div");
  grid.className = "riders-grid";
  ridersChartEl.appendChild(grid);

  function refreshGrid() {
    const results = filteredRiders();
    countLabel.textContent = `${results.length.toLocaleString()} rider${results.length !== 1 ? "s" : ""}`;
    grid.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const entry of results) {
      const btn = document.createElement("button");
      btn.className = "rider-name-btn";
      btn.appendChild(document.createTextNode(displayName(entry)));
      const flag = nationalityFlagEl(entry.nationality);
      if (flag) btn.appendChild(flag);
      for (const jersey of jerseyIconsElMultiRace(entry, racesToLoad)) btn.appendChild(jersey);
      btn.title = displayName(entry);
      btn.dataset.id = entry.id;
      frag.appendChild(btn);
    }
    grid.appendChild(frag);
  }

  // One delegated listener instead of one closure per button (~5,400 of them).
  grid.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>(".rider-name-btn");
    if (btn?.dataset.id) drawRiderDetail(btn.dataset.id);
  });

  // Debounced: refreshGrid rebuilds the whole grid, so don't do it per keystroke.
  const debouncedSearch = debounce(() => { state.ridersSearchQuery = searchInput.value; refreshGrid(); }, 150);
  searchInput.addEventListener("input", debouncedSearch);
  yearSel.addEventListener("change", () => { state.ridersFilterYear = yearSel.value; refreshGrid(); });
  teamSel.addEventListener("change", () => { state.ridersFilterTeam = teamSel.value; refreshGrid(); });
  nationalitySel.addEventListener("change", () => { state.ridersFilterNationality = nationalitySel.value; refreshGrid(); });
  for (const btn of jerseyFilterBtns) {
    btn.addEventListener("click", () => {
      const key = btn.dataset.key!;
      if (state.ridersFilterJerseys.has(key)) state.ridersFilterJerseys.delete(key);
      else state.ridersFilterJerseys.add(key);
      btn.classList.toggle("active", state.ridersFilterJerseys.has(key));
      refreshGrid();
    });
  }
  clearBtn.addEventListener("click", () => {
    state.ridersSearchQuery = "";
    state.ridersFilterYear = "";
    state.ridersFilterTeam = "";
    state.ridersFilterNationality = "";
    state.ridersFilterJerseys.clear();
    state.ridersFilterRaces.clear();
    searchInput.value = "";
    yearSel.value = "";
    teamSel.value = "";
    nationalitySel.value = "";
    for (const btn of jerseyFilterBtns) btn.classList.remove("active");
    document.removeEventListener("click", closeRacePanel);
    drawRidersPage().catch(showLoadError);
  });
  refreshGrid();
}
