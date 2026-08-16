// Riders view: a searchable/filterable grid of every rider in the selected
// race(s), with a click-through to the per-rider detail page (riderDetail.ts).
// riders.ts and riderDetail.ts call each other for grid↔detail navigation,
// and both call back into main.ts for cross-view navigation (setRace,
// loadDataset, switchView) — a real but safe circular import, since every
// cross-reference happens inside event handlers, never at module load time.
// See architecture.md's "Frontend module map" for the full rationale.
import type { RaceId } from "../raceRegistry";
import { RACE_IDS, RACE_ABBR, RACE_SHORT_LABEL, URLS_BY_RACE } from "../raceRegistry";
import { state } from "../state";
import { ridersChartEl } from "../dom";
import { updateHash } from "../hashRouting";
import { showLoadError } from "../main";
import { debounce } from "../utils";
import { displayName, foldForSearch, nationalityFlagEl, searchHaystack } from "../riderDisplay";
import type { RiderEntry } from "../riderIndexData";
import {
  riderIndexByRace, allTeamsSortedByRace, allNationalitiesSortedByRace,
  riderIndexBuilt, ensureRiderIndexFor,
} from "../riderIndexData";
import type { JerseyCategory } from "../jerseyIcons";
import { jerseyCategoriesForRace, jerseyIconSvgForRace, jerseyIconTitle, jerseyIconsElMultiRace, jerseyYearsWon } from "../jerseyIcons";
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
        const clone: RiderEntry = { ...entry, years: new Map(entry.years), teams: new Set(entry.teams) };
        // `constituents` is a non-enumerable lazy getter, so the spread above
        // skips it (which is the point — spreading 11,934 classics riders must
        // not build them all). Carry the descriptor across so the clone keeps
        // the property, still lazy and sharing the original's memo.
        const lazyConstituents = Object.getOwnPropertyDescriptor(entry, "constituents");
        if (lazyConstituents) Object.defineProperty(clone, "constituents", lazyConstituents);
        mergedById.set(id, clone);
      }
    }
  }
  const entries = [...mergedById.values()];
  mergedRidersCache = { racesKey, entries };
  return entries;
}

/** Does a rider satisfy every active jersey toggle?
 *
 *  With no year selected the question is career-wide: won each selected
 *  classification at least once, ever. Selecting years makes it a question
 *  about those years specifically — the rider must have won ALL the selected
 *  jerseys within a SINGLE one of the selected years. So "yellow + 2021, 2023"
 *  is the two riders who actually wore yellow in one of those years, and
 *  "yellow + green" is one rider who took both in the same season rather than
 *  one in each of two years a decade apart. Applied across races, that same
 *  rule asks for a Giro/Tour double in one season. */
function matchesJerseyFilter(entry: RiderEntry, selectedRaces: RaceId[]): boolean {
  // Toggles belonging to a race the user has since deselected are ignored.
  const active = [...state.ridersFilterJerseys]
    .map((key) => key.split(":") as [RaceId, JerseyCategory])
    .filter(([raceId]) => selectedRaces.includes(raceId));
  if (active.length === 0) return true;
  const yearsWonPerToggle = active.map(([raceId, category]) => {
    const raceEntry = riderIndexByRace[raceId].get(entry.id);
    return raceEntry ? jerseyYearsWon(raceEntry)[category] : [];
  });
  if (state.ridersFilterYears.size === 0) {
    return yearsWonPerToggle.every((years) => years.length > 0);
  }
  return [...state.ridersFilterYears]
    .some((year) => yearsWonPerToggle.every((years) => years.includes(year)));
}

// Both name forms, accent-folded, in one haystack. Folding is ~14,000 string
// normalizations per keystroke otherwise; the names never change once loaded,
// so each entry pays for it once.
const searchKeyCache = new WeakMap<RiderEntry, string>();
function riderSearchKey(entry: RiderEntry): string {
  let key = searchKeyCache.get(entry);
  if (key === undefined) {
    key = searchHaystack(`${entry.name}\n${displayName(entry)}`);
    searchKeyCache.set(entry, key);
  }
  return key;
}

export function filteredRiders(): RiderEntry[] {
  const q = foldForSearch(state.ridersSearchQuery);
  const years = state.ridersFilterYears;
  const selectedRaces = selectedRacesForRiders();
  return mergedRidersForSelectedRaces()
    .filter((e) => {
      if (q && !riderSearchKey(e).includes(q)) return false;
      // Years are OR'd: "2021, 2023" means either year, not both.
      if (years.size > 0 && ![...years].some((y) => e.years.has(y))) return false;
      if (state.ridersFilterTeam && !e.teams.has(state.ridersFilterTeam)) return false;
      if (state.ridersFilterNationality && e.nationality !== state.ridersFilterNationality) return false;
      if (!matchesJerseyFilter(e, selectedRaces)) return false;
      return true;
    })
    .sort((a, b) => (a.lastName ?? a.name).localeCompare(b.lastName ?? b.name));
}

// "Click outside to close" handlers for the filter dropdowns. drawRidersPage()
// rebuilds its controls from scratch on every call, so the previous render's
// handlers are torn down here instead of piling up on document, each one
// holding a detached panel alive.
const closeDropdownHandlers: ((e: MouseEvent) => void)[] = [];
function registerCloseOnOutsideClick(handler: (e: MouseEvent) => void) {
  document.addEventListener("click", handler);
  closeDropdownHandlers.push(handler);
}

export async function drawRidersPage() {
  state.currentRiderId = null;
  updateHash();
  ridersChartEl.innerHTML = "";
  for (const handler of closeDropdownHandlers) document.removeEventListener("click", handler);
  closeDropdownHandlers.length = 0;

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

  // ── Years multi-select dropdown ───────────────────────────────────────────
  // Multi-select rather than a plain <select> because a year is a real
  // constraint on the jersey filters (see matchesJerseyFilter), which makes
  // "yellow jersey, 2021 and 2023" a question worth being able to ask.
  // Drop any year that the currently-selected races don't actually cover.
  for (const y of state.ridersFilterYears) {
    if (!allYears.includes(String(y))) state.ridersFilterYears.delete(y);
  }

  const yearDropdownWrap = document.createElement("div");
  yearDropdownWrap.className = "filter-dropdown";

  const yearDropdownBtn = document.createElement("button");
  yearDropdownBtn.type = "button";
  yearDropdownBtn.className = "riders-multi-dropdown-btn";
  function updateYearDropdownBtn() {
    const picked = [...state.ridersFilterYears].sort((a, b) => b - a);
    // Past three years the list is wider than the control; count instead.
    const label = picked.length === 0 ? "All years"
      : picked.length <= 3 ? picked.join(", ")
      : `${picked.length} years`;
    yearDropdownBtn.textContent = label + " ▾";
    yearDropdownBtn.classList.toggle("active", picked.length > 0);
  }
  updateYearDropdownBtn();

  const yearPanel = document.createElement("div");
  yearPanel.className = "filter-panel";
  yearPanel.hidden = true;

  const yearShowAll = document.createElement("div");
  yearShowAll.className = "filter-panel-actions";
  const yearShowAllBtn = document.createElement("button");
  yearShowAllBtn.type = "button";
  yearShowAllBtn.className = "filter-panel-clear";
  yearShowAllBtn.textContent = "Show all";
  yearShowAllBtn.addEventListener("click", () => {
    state.ridersFilterYears.clear();
    yearPanel.querySelectorAll<HTMLInputElement>("input[type=checkbox]")
      .forEach((cb) => (cb.checked = false));
    updateYearDropdownBtn();
    refreshGrid();
  });
  yearShowAll.appendChild(yearShowAllBtn);
  yearPanel.appendChild(yearShowAll);

  for (const year of allYears) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = year;
    cb.checked = state.ridersFilterYears.has(Number(year));
    cb.addEventListener("change", () => {
      if (cb.checked) state.ridersFilterYears.add(Number(year));
      else state.ridersFilterYears.delete(Number(year));
      updateYearDropdownBtn();
      // Unlike the race panel this stays open: picking several years is the
      // point, and no data needs reloading, so the grid updates underneath.
      refreshGrid();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(year));
    yearPanel.appendChild(label);
  }

  yearDropdownBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    yearPanel.hidden = !yearPanel.hidden;
  });
  registerCloseOnOutsideClick((e) => {
    if (!yearDropdownWrap.contains(e.target as Node)) yearPanel.hidden = true;
  });

  yearDropdownWrap.append(yearDropdownBtn, yearPanel);

  // ── Races multi-select dropdown ───────────────────────────────────────────
  const raceDropdownWrap = document.createElement("div");
  raceDropdownWrap.className = "filter-dropdown";

  const raceDropdownBtn = document.createElement("button");
  raceDropdownBtn.type = "button";
  raceDropdownBtn.className = "riders-multi-dropdown-btn";
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
  registerCloseOnOutsideClick((e) => {
    if (!raceDropdownWrap.contains(e.target as Node)) racePanel.hidden = true;
  });

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
    jerseyCategoriesForRace(race).forEach((category) => {
      const key = `${race}:${category}`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "jersey-filter-btn";
      btn.classList.toggle("active", state.ridersFilterJerseys.has(key));
      btn.title = jerseyIconTitle(category, race);
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

  controls.append(searchInput, yearDropdownWrap, raceDropdownWrap, teamSel, nationalitySel, jerseyFilterGroup, clearBtn, countLabel);
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
      // displayName is called twice per rider otherwise — once for the label,
      // once for the tooltip.
      const label = displayName(entry);
      btn.appendChild(document.createTextNode(label));
      const flag = nationalityFlagEl(entry.nationality);
      if (flag) btn.appendChild(flag);
      for (const jersey of jerseyIconsElMultiRace(entry, racesToLoad, state.ridersFilterYears)) {
        btn.appendChild(jersey);
      }
      btn.title = label;
      // setAttribute rather than `btn.dataset.id`: the DOMStringMap proxy is
      // measurably slower, and this runs 14,260 times per rebuild.
      btn.setAttribute("data-id", entry.id);
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
    state.ridersFilterYears.clear();
    state.ridersFilterTeam = "";
    state.ridersFilterNationality = "";
    state.ridersFilterJerseys.clear();
    state.ridersFilterRaces.clear();
    searchInput.value = "";
    teamSel.value = "";
    nationalitySel.value = "";
    for (const btn of jerseyFilterBtns) btn.classList.remove("active");
    drawRidersPage().catch(showLoadError);
  });
  refreshGrid();
}
