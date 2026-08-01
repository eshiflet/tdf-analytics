// App entry point and orchestration layer: wires up the DOM controls, owns
// the top-level init/view-switch/hash-apply flow, and calls into the view
// modules (views/*.ts) to actually render. See architecture.md's "Frontend
// module map" for the full file layout and why loadDataset()/applyHash()
// live here rather than in dataLoading.ts/hashRouting.ts — both call into
// nearly every view module to trigger redraws, which makes them orchestration
// rather than leaf logic.
import { d3 } from "./d3";
import type { RaceId } from "./raceRegistry";
import { RACE_IDS, RACES, isRaceId, URLS_BY_RACE, getYearsForRace } from "./raceRegistry";
import { state } from "./state";
import {
  raceSelectEl, chartEl, overviewChartEl, legendEl, sidebarEl, searchEl,
  yearSelectEl, metricSelectEl, gcTimeToggleBtn, sprintModeToggleBtn, komModeToggleBtn,
  viewStageBtn, viewOverviewBtn, viewAllRacesBtn, allRacesChartEl, viewRidersBtn,
  ridersChartEl, allRacesUnitToggleBtn, overviewSummaryEl, subtitleStage, subtitleOverview,
  teamFilterBtn, teamFilterPanel, nationFilterBtn, nationFilterPanel,
} from "./dom";
import { getDataset } from "./dataLoading";
import { PALETTE } from "./formatters";
import { computeHash, updateHash } from "./hashRouting";
import { debounce } from "./utils";
import { displayName } from "./riderDisplay";
import {
  drawChart, buildLegend, refreshLegendState, updateLineClasses, applyDefaultSelection,
  computePointsRankings, buildStageFilters, closeFilterPanels, clearStageTeamNationFilters,
  applyStageTeamNationFilter, cssEscape,
} from "./views/stageChart";
import { drawOverview } from "./views/overview";
import { drawAllRacesOverview } from "./views/allRaces";
import { drawRidersPage } from "./views/riders";
import { drawRiderDetail } from "./views/riderDetail";

export function showLoadError(err: unknown) {
  chartEl.innerHTML = `<p style="color:#ff6b6b">Failed to load data: ${err}</p>`;
  console.error(err);
}

function rebuildYearOptions() {
  yearSelectEl.innerHTML = "";
  for (const year of state.YEARS) {
    const opt = document.createElement("option");
    opt.value = year;
    opt.textContent = year;
    yearSelectEl.appendChild(opt);
  }
  yearSelectEl.value = state.currentYear;
}

function buildYearSelect() {
  rebuildYearOptions();
  yearSelectEl.addEventListener("change", () => {
    state.currentYear = yearSelectEl.value;
    updateHash();
    loadDataset(state.currentYear).catch(showLoadError);
  });
}

/** Switch the active race: updates the dropdowns, year list, and per-race
 *  filter state. Callers handle hash + data loading. */
export function setRace(race: RaceId) {
  state.currentRace = race;
  raceSelectEl.value = race;
  state.YEARS = getYearsForRace(race);
  state.currentYear = state.YEARS[0];
  rebuildYearOptions();
  // Reset riders filter state so stale year/team selections don't carry over
  state.ridersFilterYear = "";
  state.ridersFilterTeam = "";
  state.ridersFilterNationality = "";
  state.ridersFilterJerseys.clear();
}

function buildRaceSelect() {
  // Options come from the race registry, not hardcoded markup.
  raceSelectEl.innerHTML = "";
  for (const raceId of RACE_IDS) {
    const opt = document.createElement("option");
    opt.value = raceId;
    opt.textContent = RACES[raceId].name;
    raceSelectEl.appendChild(opt);
  }
  raceSelectEl.value = state.currentRace;
  raceSelectEl.addEventListener("change", () => {
    setRace(raceSelectEl.value as RaceId);
    updateHash();
    loadDataset(state.currentYear).catch(showLoadError);
  });
}

function buildMetricSelect() {
  metricSelectEl.value = state.currentMetric;
  updateGcTimeToggle();
  updateSprintModeToggle();
  updateKomModeToggle();
  metricSelectEl.addEventListener("change", () => {
    state.currentMetric = metricSelectEl.value as "gc" | "points" | "kom";
    if (state.currentMetric !== "gc") state.gcDisplayMode = "position";
    if (state.currentMetric !== "points") state.sprintDisplayMode = "rank";
    if (state.currentMetric !== "kom") state.komDisplayMode = "rank";
    updateGcTimeToggle();
    updateSprintModeToggle();
    updateKomModeToggle();
    updateHash();
    applyDefaultSelection(20);
    document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
      b.classList.remove("active"),
    );
    document.querySelector<HTMLButtonElement>('.button-row button[data-preset="20"]')?.classList.add("active");
    applyStageTeamNationFilter();
    buildLegend();
    drawChart();
  });
}

/** Shows/hides the GC Time toggle (only relevant in GC Position "by Stage"
 *  view) and reflects whether it's currently engaged. */
function updateGcTimeToggle() {
  gcTimeToggleBtn.hidden = !(state.currentView === "stage" && state.currentMetric === "gc");
  gcTimeToggleBtn.textContent = state.gcDisplayMode === "time"
    ? "GC Time → GC Position"
    : "GC Position → GC Time";
}

function updateSprintModeToggle() {
  sprintModeToggleBtn.hidden = !(state.currentView === "stage" && state.currentMetric === "points");
  sprintModeToggleBtn.textContent = state.sprintDisplayMode === "points"
    ? "Points → Rank"
    : "Rank → Points";
}

function updateKomModeToggle() {
  komModeToggleBtn.hidden = !(state.currentView === "stage" && state.currentMetric === "kom");
  komModeToggleBtn.textContent = state.komDisplayMode === "points"
    ? "Points → Rank"
    : "Rank → Points";
}

function updateUnitToggle() {
  allRacesUnitToggleBtn.hidden = state.currentView !== "allraces";
  allRacesUnitToggleBtn.textContent = state.allRacesUnit === "metric" ? "km → mi" : "mi → km";
}

export async function loadDataset(year: string) {
  state.dataset = await getDataset(year);
  state.colorScale = d3
    .scaleOrdinal<string, string>()
    .domain(state.dataset.riders.map((r) => r.id))
    .range(PALETTE);

  computePointsRankings();
  if (state.currentPreset === "all") {
    state.selected = new Set(state.dataset.riders.map((r) => r.id));
  } else if (state.currentPreset === "none") {
    state.selected = new Set();
  } else {
    applyDefaultSelection(parseInt(state.currentPreset, 10));
  }

  state.highlighted = null;
  searchEl.value = "";
  document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
    b.classList.remove("active"),
  );
  document.querySelector<HTMLButtonElement>(`.button-row button[data-preset="${state.currentPreset}"]`)?.classList.add(
    "active",
  );

  viewOverviewBtn.textContent = `${state.currentYear} Race Overview`;

  buildStageFilters();
  closeFilterPanels();
  buildLegend();
  if (state.currentView === "stage") drawChart();
  else if (state.currentView === "overview") drawOverview();
  else if (state.currentView === "allraces") drawAllRacesOverview();
}

export function switchView(view: "stage" | "overview" | "allraces" | "riders") {
  state.currentView = view;
  updateGcTimeToggle();
  updateSprintModeToggle();
  updateKomModeToggle();
  updateUnitToggle();
  viewStageBtn.classList.toggle("active", view === "stage");
  viewOverviewBtn.classList.toggle("active", view === "overview");
  viewAllRacesBtn.classList.toggle("active", view === "allraces");
  viewRidersBtn.classList.toggle("active", view === "riders");
  if (subtitleStage) subtitleStage.hidden = view !== "stage";
  subtitleOverview.hidden = view !== "overview";
  chartEl.classList.toggle("hidden", view !== "stage");
  sidebarEl.classList.toggle("hidden", view !== "stage");
  overviewChartEl.classList.toggle("visible", view === "overview");
  overviewSummaryEl.hidden = view !== "overview";
  allRacesChartEl.classList.toggle("visible", view === "allraces");
  ridersChartEl.classList.toggle("visible", view === "riders");
  if (view === "stage") drawChart();
  else if (view === "overview") drawOverview();
  else if (view === "allraces") drawAllRacesOverview();
  else drawRidersPage().catch(showLoadError);
  updateHash();
}

/** Applies the current location.hash to app state. Returns false if the hash
 *  was empty/unrecognized and the caller should fall back to defaults. */
async function applyHash(): Promise<boolean> {
  const hash = window.location.hash;
  if (!hash || hash === "#") return false;
  if (hash === computeHash()) return true; // already in sync (our own write)
  const parts = hash.slice(1).split("/");
  // Optional leading race segment; its absence means "tour" (backward compat
  // with pre-multi-race links).
  const race: RaceId = isRaceId(parts[0]) ? (parts[0] as RaceId) : "tour";
  if (isRaceId(parts[0])) parts.shift();
  state.applyingHash = true;
  try {
    if (race !== state.currentRace) setRace(race);
    if (parts[0] === "allraces") {
      switchView("allraces");
      return true;
    }

    if (parts[0] === "riders") {
      if (parts[1]) {
        const id = `rider/${parts[1]}`;
        switchView("riders");
        await drawRiderDetail(id);
        return true;
      }
      switchView("riders");
      return true;
    }

    const [year, view, metric] = parts;
    if (!URLS_BY_RACE[state.currentRace][year]) return false;
    state.currentYear = year;
    yearSelectEl.value = year;
    if (view !== "overview") {
      state.currentMetric = (metric === "points" || metric === "sprint-points") ? "points"
        : (metric === "kom" || metric === "kom-points") ? "kom" : "gc";
      state.gcDisplayMode = metric === "gc-time" ? "time" : "position";
      state.sprintDisplayMode = metric === "sprint-points" ? "points" : "rank";
      state.komDisplayMode = metric === "kom-points" ? "points" : "rank";
      metricSelectEl.value = state.currentMetric;
    }
    await loadDataset(year);
    switchView(view === "overview" ? "overview" : "stage");
    return true;
  } finally {
    state.applyingHash = false;
  }
}

function wireControls() {
  document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!state.dataset) return; // initial fetch in flight; selection state comes with it
      document.querySelectorAll<HTMLButtonElement>(".button-row button").forEach((b) =>
        b.classList.remove("active"),
      );
      btn.classList.add("active");
      const preset = btn.dataset.preset;
      state.currentPreset = preset ?? "20";
      if (preset === "all") {
        state.selected = new Set(state.dataset.riders.map((r) => r.id));
        // "All" already selects every rider, which subsumes any Team/Nation
        // filter — clear both so the filter buttons don't show a stale state.
        clearStageTeamNationFilters();
      } else if (preset === "none") {
        state.selected = new Set();
        // "None" doubles as a Clear All for the Team/Nation filters.
        clearStageTeamNationFilters();
      } else {
        const n = parseInt(preset ?? "20", 10);
        applyDefaultSelection(n);
      }
      refreshLegendState();
      updateLineClasses();
    });
  });

  teamFilterBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = teamFilterPanel.hidden;
    closeFilterPanels();
    teamFilterPanel.hidden = !willOpen;
  });
  nationFilterBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = nationFilterPanel.hidden;
    closeFilterPanels();
    nationFilterPanel.hidden = !willOpen;
  });
  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".filter-dropdown")) closeFilterPanels();
  });

  searchEl.addEventListener("input", () => {
    if (!state.dataset) return; // initial fetch in flight; nothing to search yet
    const q = searchEl.value.trim().toLowerCase();
    if (!q) {
      state.highlighted = null;
      updateLineClasses();
      refreshLegendState();
      return;
    }
    const match = state.dataset.riders.find((r) => r.name.toLowerCase().includes(q) || displayName(r).toLowerCase().includes(q));
    if (match) {
      state.selected.add(match.id);
      state.highlighted = match.id;
      const legendRow = legendEl.querySelector<HTMLDivElement>(`[data-id="${cssEscape(match.id)}"]`);
      legendRow?.scrollIntoView({ block: "nearest" });
    }
    refreshLegendState();
    updateLineClasses();
  });

  viewStageBtn.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).tagName === "SELECT") return; // let metric-select handle its own clicks
    switchView("stage");
  });
  viewOverviewBtn.addEventListener("click", () => switchView("overview"));
  viewAllRacesBtn.addEventListener("click", () => switchView("allraces"));
  viewRidersBtn.addEventListener("click", () => switchView("riders"));

  gcTimeToggleBtn.addEventListener("click", () => {
    state.gcDisplayMode = state.gcDisplayMode === "time" ? "position" : "time";
    updateGcTimeToggle();
    updateHash();
    drawChart();
  });

  sprintModeToggleBtn.addEventListener("click", () => {
    state.sprintDisplayMode = state.sprintDisplayMode === "points" ? "rank" : "points";
    updateSprintModeToggle();
    updateHash();
    drawChart();
  });

  komModeToggleBtn.addEventListener("click", () => {
    state.komDisplayMode = state.komDisplayMode === "points" ? "rank" : "points";
    updateKomModeToggle();
    updateHash();
    drawChart();
  });

  allRacesUnitToggleBtn.addEventListener("click", () => {
    state.allRacesUnit = state.allRacesUnit === "metric" ? "imperial" : "metric";
    updateUnitToggle();
    drawAllRacesOverview();
  });
}

function init() {
  try {
    buildRaceSelect();
    buildYearSelect();
    buildMetricSelect();
    wireControls();
    // Single resize handler for the lifetime of the page — redraws whichever
    // view is active. (Previously re-registered on every drawChart() call,
    // leaking a listener per year/metric switch.)
    window.addEventListener("resize", debounce(() => {
      if (state.currentView === "stage") drawChart();
      else if (state.currentView === "overview") drawOverview();
      else if (state.currentView === "allraces") drawAllRacesOverview();
    }, 200));
    window.addEventListener("hashchange", () => {
      applyHash().catch(showLoadError);
    });
    applyHash()
      .then((handled) => {
        if (!handled) {
          // No (or unrecognized) hash: seed the URL without adding a history
          // entry, then fall through to the default load below.
          window.history.replaceState(null, "", computeHash());
        }
        // Load whenever no dataset is in memory yet. This covers three cases:
        // empty/unrecognized hash, deep links landing on riders/allraces (which
        // need a dataset for later stage/overview navigation), and deep links
        // that exactly match the default state — applyHash() treats those as
        // "already in sync" and returns without loading anything.
        if (!state.dataset) return loadDataset(state.currentYear);
      })
      .catch(showLoadError);
  } catch (err) {
    showLoadError(err);
  }
}

init();
