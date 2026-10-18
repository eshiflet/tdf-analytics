// Rider detail view: cross-race career chart for one rider, with toggles to
// show/hide each race and each classification (GC/Sprint/KOM) independently.
// Not filtered to the current race — shows every race the rider has results
// in. See riders.ts's header comment for the circular-import note (this file
// and riders.ts call each other for grid↔detail navigation).
import type { RaceId } from "../raceRegistry";
import { RACE_IDS, RACES, RACE_SHORT_LABEL } from "../raceRegistry";
import { state } from "../state";
import { ridersChartEl, yearSelectEl, metricSelectEl } from "../dom";
import { replaceHash, updateHash } from "../hashRouting";
import { canonicalRiderId } from "../riderAliases";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import type { RiderEntry } from "../riderIndexData";
import { riderIndexByRace, ensureRiderIndexFor, crossRaceFor } from "../riderIndexData";
import { buildLegend } from "./stageLegend";
import { setRace, loadDataset, switchView, showLoadError } from "../main";
import { drawRidersPage } from "./riders";
import { BADGE, createCareerChart } from "./riderCareerChart";
import type { ClassifId, CrossPt } from "./riderCareerChart";

/**
 * PROGRESSIVE. This used to `await Promise.all` over all five rider indexes
 * before putting anything on screen, so first paint was gated on the SLOWEST
 * of them, and a deep link to `#riders/<slug>` showed a blank panel for the
 * whole wait — with no loading message, unlike the Riders grid.
 *
 * Measured 2026-08-22 on a cold document: 438 ms to header, 457 ms to chart,
 * of which only 48 ms was network. The five builds cost 208 ms (classics),
 * 79 (vuelta), 69 (giro), 68 (tour), 34 (gravel), and running them in parallel
 * bought about 4% — it is all main-thread work.
 *
 * So the view now draws as soon as the FIRST index containing this rider
 * resolves, and folds each later one in as it arrives. 61% of riders appear in
 * exactly one race and reach their final state in a single render.
 *
 * It also no longer loads all five. The cross-race bitmask in the current
 * race's index names the other sets this rider actually rode, so the rest are
 * never fetched — see the two-phase load at the bottom of this function.
 *
 * Three things this has to keep right, none of them visible until they break:
 *   - a race the user toggled OFF must stay off when a later index lands
 *   - "rider not found" cannot be concluded until every index this rider could
 *     be in has resolved, which is why that bail-out is after the final
 *     Promise.all, not inside the per-index handler
 *   - navigating away mid-load must abandon the render, hence the
 *     currentRiderId re-check after every await
 */
export async function drawRiderDetail(riderId: string): Promise<void> {
  // Claim the slot before the first await so drawRidersPage can bail if it
  // resumes from its own await and sees a detail is now in flight.
  state.currentRiderId = riderId;
  ridersChartEl.innerHTML = "";

  const byRace = new Map<RaceId, RiderEntry>();
  const activeRaces = new Set<RaceId>();
  const activeClassifs = new Set<ClassifId>(["gc"]);

  // Both of these are filled in ARRIVAL order now, which is network timing.
  // Everything user-visible has to read them in RACE_IDS order instead, or the
  // summary line and the chart's draw order shuffle themselves between loads.
  const racesWithData = () => RACE_IDS.filter((r) => byRace.has(r));
  const racesToDraw   = () => RACE_IDS.filter((r) => activeRaces.has(r));

  let header: HTMLDivElement | null = null;
  let toggleGroup: HTMLDivElement;
  let chartContainer: HTMLDivElement;

  // ── Header ──────────────────────────────────────────────────────────────────
  function renderHeader() {
    header!.innerHTML = "";
    // Prefer the entry from currentRace for name/nationality, falling back to
    // the first found. Recomputed on every arrival, so an early stand-in is
    // replaced once the preferred race's index lands.
    const primaryEntry = byRace.get(state.currentRace) ?? byRace.get(racesWithData()[0])!;

    const backBtn = document.createElement("button");
    backBtn.className = "rider-back-btn";
    backBtn.textContent = "← All Riders";
    backBtn.addEventListener("click", () => drawRidersPage());

    const nameEl = document.createElement("h2");
    nameEl.className = "rider-detail-name";
    nameEl.appendChild(document.createTextNode(displayName(primaryEntry)));
    const detailFlag = nationalityFlagEl(primaryEntry.nationality);
    if (detailFlag) nameEl.appendChild(detailFlag);

    // Which of this rider's years were annulled, across every race he appears
    // in, from PCS's own struck-through ranks. This REPLACED a hand-curated
    // "Some race results revoked for doping" note covering five riders: the
    // years are strictly more informative — Armstrong reads 1999-2005, 2009
    // and 2010 across three Grand Tours where the prose said "some" — and
    // nobody has to maintain a list. It keeps that note's italics.
    const dqYears = [...new Set(
      racesWithData().flatMap((race) => byRace.get(race)?.dqYears ?? []),
    )].sort((a, b) => a - b);
    if (dqYears.length) {
      const dqEl = document.createElement("span");
      dqEl.className = "rider-detail-dq";
      dqEl.textContent = `\u2298 result annulled: ${dqYears.join(", ")}`;
      dqEl.title = "Struck through by the source: these results were annulled "
                 + "after the fact. The rides are kept here, the placings were taken away.";
      nameEl.appendChild(dqEl);
    }


    const metaEl = document.createElement("div");
    metaEl.className = "rider-detail-meta";
    const metaParts: string[] = [];
    for (const race of racesWithData()) {
      const entry = byRace.get(race)!;
      const yrs = [...entry.years.keys()].sort((a, b) => a - b);
      const finished = yrs.filter((yr) => entry.years.get(yr)!.finalRank < 9999);
      const best = finished.length > 0
        ? Math.min(...finished.map((yr) => entry.years.get(yr)!.finalRank))
        : null;
      // "TDF" is kept for the Tour rather than the registry's "Tour" so this
      // summary line reads exactly as it always has.
      const raceName = race === "tour" ? "TDF" : RACE_SHORT_LABEL[race];
      let part = `${yrs.length} ${raceName}`;
      if (best !== null) part += ` · Best #${best}`;
      metaParts.push(part);
    }
    metaEl.textContent = metaParts.join(", ");
    header!.append(backBtn, nameEl, metaEl);
  }

  // ── Toggle bar: race buttons (T/G/V) + divider + classification buttons ───────
  function renderToggles() {
    toggleGroup.innerHTML = "";
    // Sprint/KOM only exist if at least one race this rider has data in
    // contests them — a classics-only rider gets neither the toggles nor the
    // legend rows, rather than two controls that can never show anything.
    const hasSprintKom = racesWithData().some((r) => RACES[r].hasSprintKom);
    const classifIds: ClassifId[] = hasSprintKom ? ["gc", "sprint", "kom"] : ["gc"];
    // A classification that only becomes available when a later index lands
    // defaults to on. The user cannot have switched off a control that did not
    // exist yet, so this never overrides a choice.
    for (const c of classifIds) activeClassifs.add(c);

    // Race toggles
    for (const race of RACE_IDS) {
      const btn = document.createElement("button");
      btn.className = "race-toggle-btn";
      const hasData = byRace.has(race);
      const badge = BADGE[race];
      btn.textContent = badge.label;
      btn.title = RACES[race].name;
      btn.style.setProperty("--race-color", badge.bg);
      btn.style.setProperty("--race-text", badge.text);
      if (!hasData) {
        btn.classList.add("no-data");
      } else {
        // Read the live set rather than assuming active: this bar is rebuilt
        // every time an index lands, and a race the user switched off has to
        // come back switched off.
        btn.classList.add(activeRaces.has(race) ? "active" : "inactive");
        btn.addEventListener("click", () => {
          if (activeRaces.has(race)) {
            if (activeRaces.size === 1) return;
            activeRaces.delete(race);
            btn.classList.replace("active", "inactive");
          } else {
            activeRaces.add(race);
            btn.classList.replace("inactive", "active");
          }
          redrawChart();
        });
      }
      toggleGroup.appendChild(btn);
    }

    // Divider — only meaningful when there are classification toggles to
    // separate the race toggles from.
    if (classifIds.length > 1) {
      const divider = document.createElement("span");
      divider.className = "toggle-divider";
      divider.textContent = "|";
      toggleGroup.appendChild(divider);
    }

    // Classification toggles
    for (const classif of (classifIds.length > 1 ? classifIds : [])) {
      const label = classif === "gc" ? "GC" : classif === "sprint" ? "Sprint" : "KOM";
      const btn = document.createElement("button");
      btn.className = `classif-toggle-btn ${activeClassifs.has(classif) ? "active" : "inactive"}`;
      btn.textContent = label;
      btn.addEventListener("click", () => {
        if (activeClassifs.has(classif)) {
          if (activeClassifs.size === 1) return;
          activeClassifs.delete(classif);
          btn.classList.replace("active", "inactive");
        } else {
          activeClassifs.add(classif);
          btn.classList.replace("inactive", "active");
        }
        redrawChart();
      });
      toggleGroup.appendChild(btn);
    }
  }

  /** Build the shell on the first arrival, then refresh it on every later one. */
  function renderAll() {
    if (!header) {
      header = document.createElement("div");
      header.className = "rider-detail-header";
      toggleGroup = document.createElement("div");
      toggleGroup.className = "race-toggle-group";
      chartContainer = document.createElement("div");
      chartContainer.className = "rider-career-chart";
      drawCareerChart = createCareerChart(chartContainer, doNavigate);
      ridersChartEl.append(header, toggleGroup, chartContainer);
      updateHash();
    }
    renderHeader();
    renderToggles();
    redrawChart();
  }

  // Shared dot-click handler: switch race + year + metric then load stage chart
  function doNavigate(d: CrossPt, metric: "gc" | "points" | "kom") {
    setRace(d.race);
    state.currentYear = String(d.year);
    yearSelectEl.value = state.currentYear;
    state.currentMetric = metric;
    metricSelectEl.value = metric;
    loadDataset(state.currentYear).then(() => {
      state.selected = new Set([riderId]);
      buildLegend();
      switchView("stage");
    }).catch(showLoadError);
  }

  let drawCareerChart: ReturnType<typeof createCareerChart>;

  function redrawChart() {
    drawCareerChart({ races: racesToDraw(), byRace, classifs: activeClassifs });
  }


  // Fold each index in as it lands rather than waiting for the slowest.
  const foldIn = (race: RaceId) =>
    ensureRiderIndexFor(race).then(() => {
      // Both halves matter. currentRiderId alone was not enough: switching to
      // another VIEW mid-load leaves it set, so a late index went on appending
      // a detail header into the (now hidden) riders panel. Under the old
      // Promise.all there was one render at the end and one chance to get this
      // wrong; there are now five.
      if (state.currentView !== "riders" || state.currentRiderId !== riderId) return;
      const entry = riderIndexByRace[race].get(riderId);
      if (!entry) return;                             // nothing to add
      byRace.set(race, entry);
      activeRaces.add(race);
      renderAll();
    });

  // TWO PHASES, not five parallel fetches. This page is cross-race, so it used
  // to load every index to find out which races the rider actually rode —
  // 1,185 KB gzipped and five main-thread builds, when 61% of riders are in
  // exactly one set and only 31 of 17,736 are in all five.
  //
  // Phase 1 is the current race's index, which this page needs regardless and
  // which carries the cross-race bitmask (see crossRaceFor). Phase 2 fetches
  // only the sets that bitmask names, still in parallel with each other.
  //
  // The trade is one extra round trip on a cold deep link for a rider who does
  // race elsewhere, against 480 KB less transfer on average — and phase 1 is
  // usually already resolved, because arriving from the Riders grid means that
  // index is built.
  const entryRace = state.currentRace;
  await foldIn(entryRace);
  if (state.currentView !== "riders" || state.currentRiderId !== riderId) return;

  // null means no built index has heard of this rider — a deep link into a
  // race they never rode, or a slug that has since been renamed. Fall back to
  // loading everything rather than concluding they raced nowhere.
  const known = crossRaceFor(riderId);
  await Promise.all(
    (known ?? RACE_IDS).filter((r) => r !== entryRace).map(foldIn),
  );

  // Only now can "no such rider" be distinguished from "not loaded yet".
  if (state.currentView !== "riders" || state.currentRiderId !== riderId) return;
  if (byRace.size !== 0) return;

  // Before giving up: this slug may have been MERGED into another rider rather
  // than never having existed. 142 ids have been absorbed that way, and every
  // link to one is otherwise dead — including the bug report that prompted the
  // merge pass, which was a link to `rider/torbj-r`.
  const canonical = await canonicalRiderId(riderId);
  // The fetch above is an await like any other: the user may have navigated on.
  if (state.currentView !== "riders" || state.currentRiderId !== riderId) return;
  if (canonical) {
    await drawRiderDetail(canonical);
    // AFTER the redraw, so computeHash() reads the new id off state. Replaces
    // rather than pushes — see replaceHash().
    if (state.currentRiderId === canonical) replaceHash();
    return;
  }
  renderUnknownRider();
}

/** Every built index has been searched and none has heard of this slug. An
 *  empty panel is indistinguishable from one still loading, so say so and
 *  offer the way back — this is reachable from a shared link to a rider whose
 *  slug has since been renamed, not only from a typo. */
function renderUnknownRider() {
  ridersChartEl.innerHTML = "";

  const msg = document.createElement("div");
  msg.className = "stage-table-empty";
  msg.textContent = "No rider matches this link.";

  const backBtn = document.createElement("button");
  backBtn.className = "rider-back-btn";
  backBtn.textContent = "\u2190 All Riders";
  backBtn.addEventListener("click", () => drawRidersPage());

  const backWrap = document.createElement("div");
  backWrap.style.textAlign = "center";
  backWrap.appendChild(backBtn);

  ridersChartEl.appendChild(msg);
  ridersChartEl.appendChild(backWrap);
}
