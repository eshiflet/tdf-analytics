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
import { state, raceConfig } from "./state";
import {
  raceSelectEl, chartEl, overviewChartEl, legendEl, sidebarEl, searchEl,
  yearSelectEl, metricSelectEl, stageViewSelectEl, stageTableEl,
  gcTimeToggleBtn, sprintModeToggleBtn, komModeToggleBtn,
  viewStageBtn, viewOverviewBtn, viewAllRacesBtn, allRacesChartEl, viewRidersBtn,
  ridersChartEl, allRacesUnitToggleBtn, overviewUnitToggleBtn, overviewSummaryEl,
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
import { drawStageTable } from "./views/stageTable";
import { drawOverview } from "./views/overview";
import { drawAllRacesOverview } from "./views/allRaces";
import { drawClassicsHistory } from "./views/classicsHistory";
import { drawRidersPage } from "./views/riders";
import { drawRiderDetail } from "./views/riderDetail";

/** The cross-year nav slot: per-race history for an aggregate race, season
 *  totals for a stage race. */
function drawCrossYear() {
  if (raceConfig().hasRaceHistory) drawClassicsHistory().catch(showLoadError);
  else drawAllRacesOverview();
}

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

/** Reflects the active race's capability flags in the chrome: which metrics
 *  the dropdown offers, and whether All Years Summary is reachable. Also
 *  sanitizes any state the new race can't represent — switching from the Giro
 *  (KOM selected) to the classics (no KOM contested) must not leave the
 *  dropdown on a metric with no data behind it. */
function applyRaceCapabilities() {
  const cfg = raceConfig();

  // Options are rebuilt rather than hidden so the select can never hold a
  // value this race doesn't serve.
  const options: { value: "gc" | "points" | "kom"; label: string }[] = [
    // Without a cumulative GC the metric is a per-race placing, not a
    // standing, so "GC" would be actively misleading.
    { value: "gc", label: cfg.hasCumulativeGc ? "GC" : "Result" },
  ];
  if (cfg.hasSprintKom) {
    options.push({ value: "points", label: "Sprint" });
    options.push({ value: "kom", label: "KOM" });
  } else if (cfg.hasSeasonPoints) {
    // Same "points" metric path — cumulative totals and per-stage standings —
    // just fed by season points instead of a sprint classification.
    options.push({ value: "points", label: "Season Points" });
  }
  if (!options.some((o) => o.value === state.currentMetric)) state.currentMetric = "gc";
  metricSelectEl.innerHTML = "";
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o.value;
    opt.textContent = o.label;
    metricSelectEl.appendChild(opt);
  }
  metricSelectEl.value = state.currentMetric;

  // One nav slot, two views: a stage race totals its own seasons, an aggregate
  // race charts each constituent race's own history instead.
  const crossYear = cfg.hasAllYears || cfg.hasRaceHistory;
  viewAllRacesBtn.hidden = !crossYear;
  viewAllRacesBtn.textContent = cfg.hasRaceHistory ? "Race History" : "All Years Summary";
  if (!crossYear && state.currentView === "allraces") state.currentView = "stage";
  // A season of unrelated races has no total time to plot against.
  if (!cfg.hasCumulativeGc) state.gcDisplayMode = "position";
}

/** Switch the active race: updates the dropdowns, year list, and per-race
 *  filter state. Callers handle hash + data loading. */
export function setRace(race: RaceId) {
  state.currentRace = race;
  raceSelectEl.value = race;
  state.YEARS = getYearsForRace(race);
  state.currentYear = state.YEARS[0];
  rebuildYearOptions();
  applyRaceCapabilities();
  // Reset riders filter state so stale year/team selections don't carry over
  state.ridersFilterYear = "";
  state.ridersFilterTeam = "";
  state.ridersFilterNationality = "";
  state.ridersFilterJerseys.clear();
}

function buildRaceSelect() {
  // Options come from the race registry, not hardcoded markup. A registry
  // entry with no exported year files is skipped rather than offered — it
  // would set currentYear to undefined and break the year dropdown. This is
  // what lets a race's registry entry land before its data does.
  raceSelectEl.innerHTML = "";
  for (const raceId of RACE_IDS) {
    if (getYearsForRace(raceId).length === 0) continue;
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

/** Renders whichever "by Stage" sub-view is active (graph or table) and
 *  shows/hides the chart/sidebar/table containers to match. The single call
 *  site for anything that used to just call drawChart() directly. */
function renderStage() {
  const isTable = state.stageViewMode === "table";
  chartEl.classList.toggle("hidden", isTable);
  sidebarEl.classList.toggle("hidden", isTable);
  stageTableEl.classList.toggle("visible", isTable);
  if (isTable) drawStageTable();
  else drawChart();
}

function buildStageViewSelect() {
  stageViewSelectEl.value = state.stageViewMode;
  stageViewSelectEl.addEventListener("change", () => {
    state.stageViewMode = stageViewSelectEl.value as "graph" | "table";
    updateGcTimeToggle();
    updateSprintModeToggle();
    updateKomModeToggle();
    // Always navigate to stage view — this is the entry point from overview/allraces
    // too, so selecting either option always takes you there.
    switchView("stage");
  });
}

function buildMetricSelect() {
  // Seeds the option list for the initial race (setRace covers every later
  // switch), so the dropdown starts consistent with that race's capabilities.
  applyRaceCapabilities();
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
    renderStage();
  });
}

/** Shows/hides the GC Time toggle (only relevant in GC Position "by Stage"
 *  view) and reflects whether it's currently engaged. Also used by the Table
 *  sub-view to switch cell values — same button, repositioned via the
 *  "table-mode" class since the graph's rotated left-edge placement doesn't
 *  make sense next to a table. */
function updateGcTimeToggle() {
  gcTimeToggleBtn.hidden = !(state.currentView === "stage" && state.currentMetric === "gc"
    && raceConfig().hasCumulativeGc);
  gcTimeToggleBtn.classList.toggle("table-mode", state.stageViewMode === "table");
  gcTimeToggleBtn.textContent = state.gcDisplayMode === "time"
    ? "GC Time → GC Position"
    : "GC Position → GC Time";
}

function updateSprintModeToggle() {
  sprintModeToggleBtn.hidden = !(state.currentView === "stage" && state.currentMetric === "points");
  sprintModeToggleBtn.classList.toggle("table-mode", state.stageViewMode === "table");
  sprintModeToggleBtn.textContent = state.sprintDisplayMode === "points"
    ? "Points → Rank"
    : "Rank → Points";
}

function updateKomModeToggle() {
  komModeToggleBtn.hidden = !(state.currentView === "stage" && state.currentMetric === "kom");
  komModeToggleBtn.classList.toggle("table-mode", state.stageViewMode === "table");
  komModeToggleBtn.textContent = state.komDisplayMode === "points"
    ? "Points → Rank"
    : "Rank → Points";
}

function updateUnitToggle() {
  // km/mi applies to the season-totals view only. The per-race history has its
  // own metric switch (speed / distance / finishers) and no unit toggle.
  allRacesUnitToggleBtn.hidden =
    state.currentView !== "allraces" || raceConfig().hasRaceHistory;
  allRacesUnitToggleBtn.textContent = state.allRacesUnit === "metric" ? "km → mi" : "mi → km";
  overviewUnitToggleBtn.hidden = state.currentView !== "overview";
  overviewUnitToggleBtn.textContent = state.overviewUnit === "metric" ? "km → mi" : "mi → km";
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
  if (state.currentView === "stage") renderStage();
  else if (state.currentView === "overview") drawOverview();
  else if (state.currentView === "allraces") drawCrossYear();
}

export function switchView(view: "stage" | "overview" | "allraces" | "riders") {
  // Guard rather than trust the caller: a stale deep link or a race switch can
  // ask for a view this race doesn't have (the classics have no All Years
  // Summary), and drawAllRacesOverview would render an empty chart.
  if (view === "allraces" && !(raceConfig().hasAllYears || raceConfig().hasRaceHistory)) view = "stage";
  state.currentView = view;
  // Keep the select in sync: on stage, show the active mode; elsewhere, reset
  // to the hidden placeholder so any re-selection always fires 'change' and
  // navigates back to the stage view (even if the mode hasn't changed).
  stageViewSelectEl.value = view === "stage" ? state.stageViewMode : "";
  updateGcTimeToggle();
  updateSprintModeToggle();
  updateKomModeToggle();
  updateUnitToggle();
  viewStageBtn.classList.toggle("active", view === "stage");
  viewOverviewBtn.classList.toggle("active", view === "overview");
  viewAllRacesBtn.classList.toggle("active", view === "allraces");
  viewRidersBtn.classList.toggle("active", view === "riders");
  chartEl.classList.toggle("hidden", view !== "stage");
  sidebarEl.classList.toggle("hidden", view !== "stage");
  stageTableEl.classList.toggle("visible", view === "stage" && state.stageViewMode === "table");
  overviewChartEl.classList.toggle("visible", view === "overview");
  overviewSummaryEl.hidden = view !== "overview";
  allRacesChartEl.classList.toggle("visible", view === "allraces");
  ridersChartEl.classList.toggle("visible", view === "riders");
  if (view === "stage") renderStage();
  else if (view === "overview") drawOverview();
  else if (view === "allraces") drawCrossYear();
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
      // #classics/allraces has no view to show; fall back to defaults rather
      // than landing on a blank chart.
      if (!(raceConfig().hasAllYears || raceConfig().hasRaceHistory)) return false;
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

    const [year, view, metric, subView] = parts;
    if (!URLS_BY_RACE[state.currentRace][year]) return false;
    state.currentYear = year;
    yearSelectEl.value = year;
    if (view !== "overview") {
      state.currentMetric = (metric === "points" || metric === "sprint-points") ? "points"
        : (metric === "kom" || metric === "kom-points") ? "kom" : "gc";
      state.gcDisplayMode = metric === "gc-time" ? "time" : "position";
      state.sprintDisplayMode = metric === "sprint-points" ? "points" : "rank";
      state.komDisplayMode = metric === "kom-points" ? "points" : "rank";
      state.stageViewMode = subView === "table" ? "table" : "graph";
      metricSelectEl.value = state.currentMetric;
      stageViewSelectEl.value = state.stageViewMode;
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
    renderStage();
  });

  sprintModeToggleBtn.addEventListener("click", () => {
    state.sprintDisplayMode = state.sprintDisplayMode === "points" ? "rank" : "points";
    updateSprintModeToggle();
    updateHash();
    renderStage();
  });

  komModeToggleBtn.addEventListener("click", () => {
    state.komDisplayMode = state.komDisplayMode === "points" ? "rank" : "points";
    updateKomModeToggle();
    updateHash();
    renderStage();
  });

  allRacesUnitToggleBtn.addEventListener("click", () => {
    state.allRacesUnit = state.allRacesUnit === "metric" ? "imperial" : "metric";
    updateUnitToggle();
    drawAllRacesOverview();
  });

  overviewUnitToggleBtn.addEventListener("click", () => {
    state.overviewUnit = state.overviewUnit === "metric" ? "imperial" : "metric";
    updateUnitToggle();
    drawOverview();
  });
}

/** Normalizes the URL once, on load, so the hash is the only thing describing
 *  app state.
 *
 *  The static per-race landing pages (tour/, giro/, vuelta/, classics/,
 *  generated by generate-race-pages.mjs) are just the SPA shell served at a
 *  distinct, crawlable path. Two things follow:
 *
 *  1. They carry no hash, so seed one from the path — landing on /giro/ must
 *     open the Giro, not the hash-routing default (Tour).
 *  2. The path then has to GO, because nothing ever updates it again. Switch
 *     race and only the hash changes, so landing on /vuelta/ and clicking
 *     through to the Tour's All Years Summary left the self-contradicting
 *     "/vuelta/#allraces" — a path saying Vuelta and a hash saying Tour, with
 *     the hash being the one that's true.
 *
 *  Rewriting the path back to the app root leaves a single canonical shape,
 *  "<base>/#<race>/<view>", and costs nothing: the landing pages still exist
 *  and are still crawled, they just stop leaking into the URL afterwards. */
function normalizeUrl() {
  // Built from the registry so a new race's landing page works without
  // touching this regex.
  const match = window.location.pathname.match(new RegExp(`/(${RACE_IDS.join("|")})/?$`));
  if (!match || !isRaceId(match[1])) return;   // already at the app root
  const hash = window.location.hash || `#${match[1]}`;
  window.history.replaceState(
    null, "", import.meta.env.BASE_URL + window.location.search + hash);
}

function init() {
  try {
    normalizeUrl();
    buildRaceSelect();
    buildYearSelect();
    buildMetricSelect();
    buildStageViewSelect();
    wireControls();
    // Single resize handler for the lifetime of the page — redraws whichever
    // view is active. (Previously re-registered on every drawChart() call,
    // leaking a listener per year/metric switch.)
    window.addEventListener("resize", debounce(() => {
      if (state.currentView === "stage" && state.stageViewMode === "graph") drawChart();
      else if (state.currentView === "overview") drawOverview();
      else if (state.currentView === "allraces") drawCrossYear();
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
