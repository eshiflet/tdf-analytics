// Deep-link / view regression checks against the BUILT bundle (like verify.mjs,
// run `npx vite build` first). Each scenario boots a fresh JSDOM at a given
// URL hash and asserts the right view rendered. The bundle is re-imported with
// a cache-busting query so init() re-runs against the new DOM.
//
// Covers regressions verify.mjs doesn't:
//   - deep link that equals the default state (#<latest>/stage/gc) must still
//     load data (applyHash treats it as "already in sync" and skips loading)
//   - riders grid + rider detail (exercises the riders_index.json format)
//   - all-races + overview deep links
import { JSDOM } from "jsdom";
import fs from "fs";

const buildDir = new URL("./build/", import.meta.url);
const indexHtml = fs.readFileSync(new URL("./index.html", buildDir), "utf-8");
const bodyHtml = indexHtml
  .match(/<body>([\s\S]*)<\/body>/)[1]
  .replace(/<script[\s\S]*?<\/script>/, "");
const scriptSrc = indexHtml
  .match(/<script[^>]*src="([^"]+)"/)[1]
  .replace(/^\.\//, "")
  .replace(/^\/tdf-analytics\//, "");

// Vite hashes the emitted asset names, so build/assets/riders_index-C1EbTERE.json
// carries nothing to say which race it is. Map them back by byte size against
// the sources they were copied from — verbatim copies, and all five sizes are
// distinct. Needed only by bootProgressive(), but built once here so a rename
// fails loudly rather than silently matching nothing (which is exactly how the
// first version of that scenario passed without ever applying a delay).
const RIDER_INDEX_ASSET_BY_RACE = (() => {
  const bySize = new Map();
  for (const f of fs.readdirSync(new URL("assets/", buildDir))) {
    if (!/^riders_index-.*\.json$/.test(f)) continue;
    bySize.set(fs.statSync(new URL(`assets/${f}`, buildDir)).size, f);
  }
  const out = {};
  for (const race of ["tour", "giro", "vuelta", "classics", "gravel"]) {
    const size = fs.statSync(new URL(`src/data/${race}/riders_index.json`,
      import.meta.url)).size;
    const hit = bySize.get(size);
    if (!hit) throw new Error(`no built riders_index matches ${race} (${size} bytes)`);
    out[race] = hit;
  }
  return out;
})();

// Artificial per-race latency in ms, applied only by bootProgressive().
let fetchDelays = null;

globalThis.fetch = async (url) => {
  const rel = String(url).replace(/^\/tdf-analytics\//, "");
  const data = fs.readFileSync(new URL(rel, buildDir), "utf-8");
  if (fetchDelays) {
    for (const [race, ms] of Object.entries(fetchDelays)) {
      if (rel.endsWith(RIDER_INDEX_ASSET_BY_RACE[race])) {
        await new Promise((r) => setTimeout(r, ms));
        break;
      }
    }
  }
  return new Response(data, { status: 200, headers: { "Content-Type": "application/json" } });
};

let importCounter = 0;

async function boot(hash, midLoad, settleUntil) {
  const dom = new JSDOM(`<!doctype html><html><body>${bodyHtml}</body></html>`, {
    url: `http://localhost/${hash}`,
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.HTMLElement.prototype.getBoundingClientRect = function () {
    return { width: 900, height: 600, top: 0, left: 0, right: 900, bottom: 600 };
  };
  globalThis.window = window;
  globalThis.document = window.document;
  globalThis.HTMLElement = window.HTMLElement;
  globalThis.SVGElement = window.SVGElement;
  globalThis.Node = window.Node;
  globalThis.getComputedStyle = window.getComputedStyle;
  globalThis.MutationObserver = window.MutationObserver;
  globalThis.requestAnimationFrame = window.requestAnimationFrame || ((cb) => setTimeout(cb, 0));
  globalThis.cancelAnimationFrame = window.cancelAnimationFrame || clearTimeout;
  // Node caches ES modules by full URL; a unique query forces a fresh
  // evaluation of the bundle (and its init()) for each scenario's DOM.
  await import(`${new URL(scriptSrc, buildDir).href}?scenario=${importCounter++}`);
  if (midLoad) {
    // Runs while later indexes are still in flight, so a scenario can act on
    // the partially-rendered view the way a user would.
    //
    // WAITS for its precondition rather than assuming a wall-clock delay is
    // enough. The first version fired at a fixed 60ms and threw if the view
    // was not ready — which is a correct thing to check and a terrible thing
    // to bet a build on: it passed on this laptop and failed in CI, where the
    // runner had rendered one race by then instead of two. Polling keeps the
    // guarantee (the scenario still refuses to pass while proving nothing)
    // without making it a race against the machine.
    const deadline = Date.now() + (midLoad.timeout ?? 5000);
    while (!midLoad.until(window.document) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 10));
    }
    if (!midLoad.until(window.document)) {
      throw new Error(midLoad.describe ?? "midLoad precondition never held");
    }
    midLoad.run(window.document);
  }
  // Settling is a CONDITION where the caller can name one, and a fixed wait
  // only as a fallback. A flat 400ms is fine for the ordinary scenarios but
  // cannot survive a slow machine once artificial fetch delays are in play —
  // it is the second wall-clock assumption that broke this suite in CI.
  if (settleUntil) {
    const deadline = Date.now() + 8000;
    while (!settleUntil(window.document) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 10));
    }
    // The condition covers the slow, machine-dependent part (indexes loading).
    // The chart itself is drawn one deferred tick after that, and NOT waiting
    // for it here would be the only alternative to making the condition assert
    // the chart's contents — which would be the same statement as the check
    // below, and would therefore never fail.
    await new Promise((r) => setTimeout(r, 200));
  } else {
    await new Promise((r) => setTimeout(r, 400));
  }
  return window.document;
}

/** boot() with control over WHICH rider index lands first, and a hook that runs
 *  partway through the load.
 *
 *  The plain harness reads every file with fs.readFileSync behind an
 *  already-resolved Response, so all five indexes arrive in RACE_IDS order,
 *  every run. drawRiderDetail is progressive — it renders on the first index
 *  that contains the rider and folds the rest in as they arrive — so the one
 *  thing that can actually go wrong there, arrival order differing from
 *  registry order, is precisely what the harness cannot produce. A real
 *  ordering bug shipped and passed all 58 checks.
 */
async function bootProgressive(hash, delays, midLoad, settleUntil) {
  fetchDelays = delays;
  try {
    return await boot(hash, midLoad, settleUntil);
  } finally {
    fetchDelays = null;
  }
}

/** Race toggles that actually have data — the ones a user could click. */
function liveRaceToggles(doc) {
  return [...doc.querySelectorAll(".race-toggle-btn")]
    .filter((b) => !b.classList.contains("no-data"));
}

const failures = [];
function check(name, cond, detail) {
  console.log(`${cond ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!cond) failures.push(name);
}

// 1. Deep link matching the default state must still render the chart.
{
  const doc = await boot("#2025/stage/gc");
  const lines = doc.querySelectorAll(".lines .rider-line").length;
  const legend = doc.querySelectorAll("#legend .legend-item").length;
  check("default-state deep link renders chart", lines > 100 && legend > 100,
    `${lines} lines, ${legend} legend rows`);
}

// 2. Non-default stage deep link (year + metric).
{
  const doc = await boot("#1975/stage/kom");
  const lines = doc.querySelectorAll(".lines .rider-line").length;
  check("year/metric deep link renders chart", lines > 50, `${lines} lines`);
  check("year select follows deep link", doc.querySelector("#year-select").value === "1975");
}

// 3. Riders grid (exercises riders_index.json loading + team table).
{
  const doc = await boot("#riders");
  // The grid is VIRTUALISED (2026-09-11): only the rows in view plus a little
  // overscan are in the DOM, so counting buttons no longer answers "how many
  // riders match". The count label does, and it is what the user reads — a
  // better oracle than a node count, not merely a substitute for one.
  const matched = () => {
    const label = doc.querySelector(".riders-count-label")?.textContent ?? "";
    return Number((label.match(/^([\d,]+)/)?.[1] ?? "0").replace(/,/g, ""));
  };
  const rendered = () => doc.querySelectorAll(".rider-name-btn").length;
  const btns = matched();
  // By id, not by position among .riders-filter-select: this check silently
  // moved to the nationality select (and failed at 70 options) when the year
  // filter became a multi-select dropdown and left that class behind.
  const teamOptions = doc.querySelector("#riders-team-filter")?.options.length ?? 0;
  const natOptions = doc.querySelector("#riders-nationality-filter")?.options.length ?? 0;
  const filterBoxes = doc.querySelectorAll(".filter-panel input[type=checkbox]").length;
  check("riders grid reports every rider", btns > 5000, `${btns} riders matched`);
  // ...and renders a window rather than all of them. Both halves matter: the
  // first says nobody is missing, the second is the whole point of the change.
  check("riders grid renders a window, not the whole field",
    rendered() > 0 && rendered() < 2000, `${rendered()} buttons in the DOM for ${btns} riders`);
  check("team filter populated from team table", teamOptions > 600, `${teamOptions} team options`);
  check("nationality filter populated", natOptions > 50, `${natOptions} nationality options`);
  // Years and races are both checkbox panels now; every year plus 4 races.
  check("year filter offers a checkbox per year", filterBoxes > 100,
    `${filterBoxes} year+race checkboxes`);

  // Actually APPLY the team filter. The dropdown being populated was checked
  // above and proves nothing about the matching, which no longer reads a
  // precomputed per-rider Set (30,122 of them, ~15% of the index build) but
  // scans each rider's years — see rodeForTeam(). Pick a real team off the
  // dropdown rather than hardcoding a name that a re-ingest could rename.
  const teamSel = doc.querySelector("#riders-team-filter");
  const setTeam = async (v) => {
    teamSel.value = v;
    teamSel.dispatchEvent(new (globalThis.window.Event)("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 50));   // the redraw is async
    return matched();
  };

  // Independent oracle: count the riders carrying a team in the SOURCE index
  // files, decoding the team-index tables by hand. Checking the grid against
  // the filter's own logic would only restate it — and this caught a real
  // regression that "the dropdown is populated" never could: deriving the team
  // set from each rider's years instead of storing it returned 2 riders where
  // the data has 8, because mergedRidersForSelectedRaces() drops a rider's
  // year when an earlier race already claimed it (see the note there).
  const sourceIndexes = ["tour", "giro", "vuelta", "classics", "gravel"].map((race) =>
    JSON.parse(fs.readFileSync(
      new URL(`src/data/${race}/riders_index.json`, import.meta.url), "utf-8")));
  // Simulate mergedRidersForSelectedRaces() exactly: walk the races in
  // RACE_IDS order and keep the FIRST entry for each (rider, year). That is
  // what makes the per-rider team Set load-bearing — a rider's classics team
  // for 1933 is unreachable from the merged years if they also rode the Tour
  // that year, because the Tour's 1933 entry wins and carries the Tour team.
  // Simulate mergedRidersForSelectedRaces() exactly: walk the races in
  // RACE_IDS order and keep the FIRST entry for each (rider, year). That is
  // what makes the per-rider team Set load-bearing — a rider's classics team
  // for 1933 is unreachable from the merged years if they also rode the Tour
  // that year, because the Tour's 1933 entry wins and carries the Tour team.
  //
  // Built as ONE pass over the riders, bucketed by team. Asking the question
  // per team instead was O(teams x riders) and took the suite past two minutes.
  const rosterByTeam = new Map();          // team -> { found:Set, viaYears:Set }
  const bucket = (t) => {
    let b = rosterByTeam.get(t);
    if (!b) rosterByTeam.set(t, b = { found: new Set(), viaYears: new Set() });
    return b;
  };
  {
    const allSlugs = new Set(sourceIndexes.flatMap((raw) => Object.keys(raw.riders)));
    for (const slug of allSlugs) {
      const mergedTeamByYear = new Map();
      const carried = new Set();
      for (const raw of sourceIndexes) {
        const rec = raw.riders[slug];
        if (!rec) continue;
        // Grand Tours: y[year] = [finalRank, teamIdx, …]. Aggregates:
        // ym[year] = [teamIdx, raceIdx, rank, …]. Team index sits at 1 and 0.
        for (const [y, t] of Object.entries(rec.y ?? {})) {
          const name = t[1] >= 0 ? raw.teams[t[1]] : null;
          if (name) carried.add(name);
          if (!mergedTeamByYear.has(y)) mergedTeamByYear.set(y, name);
        }
        for (const [y, t] of Object.entries(rec.ym ?? {})) {
          const name = t[0] >= 0 ? raw.teams[t[0]] : null;
          if (name) carried.add(name);
          if (!mergedTeamByYear.has(y)) mergedTeamByYear.set(y, name);
        }
      }
      const reachable = new Set([...mergedTeamByYear.values()].filter(Boolean));
      for (const t of carried) {
        bucket(t).found.add(slug);
        if (reachable.has(t)) bucket(t).viaYears.add(slug);
      }
    }
  }

  // TWO teams, because one cannot cover both paths. The cross-race team proves
  // the per-rider set is doing work the merged years cannot; the biggest team
  // is Grand-Tour-heavy and covers the `y` branch of the index build, which the
  // cross-race team leaves untested (dropping teams.add() there survived an
  // otherwise-passing suite).
  let team = null, expected = new Set(), best = -1;
  let bigTeam = null, bigExpected = new Set();
  for (const [name, { found, viaYears }] of rosterByTeam) {
    const missed = found.size - viaYears.size;
    if (missed > best) { best = missed; team = name; expected = found; }
    if (found.size > bigExpected.size) { bigTeam = name; bigExpected = found; }
  }
  check("the team chosen actually exercises cross-race attribution",
    best > 0, `${JSON.stringify(team)}: ${best} rider(s) unreachable from merged years alone`);

  const filteredCount = await setTeam(team);
  check("selecting a team narrows the grid",
    filteredCount > 0 && filteredCount < btns,
    `${filteredCount} of ${btns} for ${JSON.stringify(team)}`);
  check("team filter matches the riders the source data assigns to that team",
    filteredCount === expected.size,
    `grid ${filteredCount} vs source ${expected.size} for ${JSON.stringify(team)}`);

  const bigCount = await setTeam(bigTeam);
  check("the biggest team's roster matches the source too",
    bigCount === bigExpected.size,
    `grid ${bigCount} vs source ${bigExpected.size} for ${JSON.stringify(bigTeam)}`);

  check("clearing the team filter restores the whole grid",
    (await setTeam("")) === btns, `${matched()} vs ${btns}`);
}

// 4. Rider detail deep link (career chart, teams resolved from string table).
{
  const doc = await boot("#riders/eddy-merckx");
  const name = doc.querySelector(".rider-detail-name")?.textContent;
  await new Promise((r) => setTimeout(r, 100)); // career chart draws on a deferred tick
  // Class renamed to career-gc-{race} in the cross-race refactor
  const dots = doc.querySelectorAll("[class^='career-gc-']").length;
  // .rider-detail-name also carries a trailing nationality flag emoji.
  check("rider detail deep link shows rider", name?.startsWith("Eddy Merckx") ?? false, `name=${JSON.stringify(name)}`);
  check("career chart has GC dots", dots >= 6, `${dots} dots`);

  // drawRiderDetail is PROGRESSIVE: it renders on the first index that
  // contains the rider and folds the rest in as they arrive. That fills its
  // byRace map in ARRIVAL order, i.e. network timing — so everything below is
  // guarding against output that reshuffles itself between loads. The first
  // version of that change shipped "…, 1 Gravel, 16 Classics" one run and
  // "…, 16 Classics, 1 Gravel" the next.
  const meta = doc.querySelector(".rider-detail-meta")?.textContent ?? "";
  const order = ["TDF", "Giro", "Vuelta", "Classics"]
    .map((r) => meta.indexOf(r)).filter((i) => i >= 0);
  check("rider meta names every race the rider contested",
    order.length === 4, `meta=${JSON.stringify(meta)}`);
  check("rider meta is in registry order, not arrival order",
    order.every((v, i) => i === 0 || v > order[i - 1]), `meta=${JSON.stringify(meta)}`);

  // Every race with data must end up toggled ON, and one with none must stay
  // .no-data — a late arrival must not leave its own button unwired.
  const toggles = [...doc.querySelectorAll(".race-toggle-btn")]
    .map((b) => `${b.textContent}:${b.classList.contains("active") ? "on"
      : b.classList.contains("no-data") ? "none" : "off"}`);
  check("every contested race is toggled on, the uncontested one is not",
    toggles.join(",") === "T:on,G:on,V:on,C:on,X:none", toggles.join(","));

  // The classification toggles only exist because a Grand Tour index arrived;
  // a classics-only rider gets none. Whichever index landed first, all three
  // must be present and lit by the time loading settles.
  const classifs = [...doc.querySelectorAll(".classif-toggle-btn")]
    .map((b) => `${b.textContent}:${b.classList.contains("active") ? "on" : "off"}`);
  check("sprint/KOM toggles survive a late Grand Tour arrival",
    classifs.join(",") === "GC:on,Sprint:on,KOM:on", classifs.join(","));

  // Dots from more than one race prove the fold-in actually merged, rather
  // than the last render replacing the earlier ones.
  const racesPlotted = new Set([...doc.querySelectorAll("[class^='career-gc-']")]
    .map((e) => e.getAttribute("class").replace("career-gc-", "")));
  check("career chart merges every race, not just the last to arrive",
    racesPlotted.size === 4, [...racesPlotted].sort().join(","));
}

// 4b. A rider in exactly ONE race — 61% of them. The progressive path must
//     render a single-race rider without waiting for the other four, and
//     without offering toggles for classifications that race does not award.
{
  const doc = await boot("#riders/todd-murray");   // gravel only
  await new Promise((r) => setTimeout(r, 100));
  const meta = doc.querySelector(".rider-detail-meta")?.textContent ?? "";
  check("single-race rider names only its own race",
    /^\d+ Gravel/.test(meta), `meta=${JSON.stringify(meta)}`);
  const toggles = [...doc.querySelectorAll(".race-toggle-btn")]
    .filter((b) => !b.classList.contains("no-data")).map((b) => b.textContent);
  check("single-race rider lights exactly one race toggle",
    toggles.join(",") === "X", toggles.join(","));
  check("a race with no sprint/KOM offers no such toggles",
    doc.querySelectorAll(".classif-toggle-btn").length === 0,
    `${doc.querySelectorAll(".classif-toggle-btn").length} toggles`);
}

// 4c. Progressive loading with the indexes arriving OUT of registry order.
//     drawRiderDetail renders on the first index containing the rider and
//     folds the rest in, so its byRace map fills in arrival order. Everything
//     user-visible has to be re-sorted into registry order on the way out, and
//     a race the user switched off has to stay off when a later index lands.
//     Both of those broke in the first version of the progressive change, and
//     both passed every check here until this scenario existed.
{
  // classics lands first; the four the rider also rode arrive 80ms later.
  const doc = await bootProgressive("#riders/eddy-merckx",
    // classics first, tour just behind it, the rest much later. Two must have
    // landed before the click below: switching off the ONLY active race is
    // refused by design, so a single-race moment makes the click a no-op and
    // the scenario proves nothing.
    { tour: 20, giro: 120, vuelta: 120, gravel: 120 },
    // Once classics and tour have rendered and giro/vuelta are still in
    // flight, switch classics off the way a user would. It must not come back
    // on when the later indexes arrive and rebuild the toggle bar.
    {
      until: (d) => liveRaceToggles(d).length >= 2,
      describe: "no second race ever rendered — the scenario cannot exercise "
        + "a mid-load toggle, so raise the delays on giro/vuelta",
      run: (d) => liveRaceToggles(d).find((b) => b.textContent === "C")
        .dispatchEvent(new (globalThis.window.MouseEvent)("click", { bubbles: true })),
    },
    // Settled = all four of this rider's races have a toggle. Waiting for that
    // rather than for a stopwatch is what lets the assertions below be about
    // ordering instead of about how fast the machine is.
    (d) => liveRaceToggles(d).length >= 4);

  const meta = doc.querySelector(".rider-detail-meta")?.textContent ?? "";
  const order = ["TDF", "Giro", "Vuelta", "Classics"]
    .map((r) => meta.indexOf(r)).filter((i) => i >= 0);
  check("out-of-order arrival still yields registry order",
    order.length === 4 && order.every((v, i) => i === 0 || v > order[i - 1]),
    `meta=${JSON.stringify(meta)}`);

  const off = [...doc.querySelectorAll(".race-toggle-btn")]
    .filter((b) => b.classList.contains("inactive")).map((b) => b.textContent);
  check("a race switched off mid-load stays off when later indexes land",
    off.join(",") === "C", `inactive=[${off.join(",")}]`);

  const plotted = new Set([...doc.querySelectorAll("[class^='career-gc-']")]
    .map((e) => e.getAttribute("class").replace("career-gc-", "")));
  check("the switched-off race is excluded from the redrawn chart",
    !plotted.has("classics") && plotted.size === 3, [...plotted].sort().join(","));
}

// 4d. Navigating away BEFORE any index has arrived. All five still resolve and
//     all five still run their handler; each has to notice the user is no
//     longer on this rider — or on the riders view at all — and render nothing.
//     Under the old Promise.all there was one render at the end and so one
//     chance to get this wrong. There are now five, and the guard needs the
//     VIEW as well as the rider id: switching views leaves currentRiderId set,
//     so checking the id alone let a late index build a detail header inside
//     the panel the user had already left.
{
  const doc = await bootProgressive("#riders/eddy-merckx",
    { classics: 200, tour: 200, giro: 200, vuelta: 200, gravel: 200 },
    // Nothing must have rendered yet, so this one waits for a settling period
    // rather than a state: it is asserting an ABSENCE, which no amount of
    // polling can bring about sooner.
    {
      until: () => true,
      run: (d) => {
        if (d.querySelector(".rider-detail-header")) throw new Error(
          "an index arrived before the navigation — raise the delays");
        globalThis.window.location.hash = "#allraces";
      },
    },
    // Settled = the view navigated to has drawn. The detail must still be
    // absent at that point, which is the actual assertion.
    (d) => d.querySelectorAll("#all-races-chart svg g .overview-panel-label").length === 4);

  check("an index landing after navigation renders nothing",
    doc.querySelectorAll(".rider-detail-header").length === 0,
    `${doc.querySelectorAll(".rider-detail-header").length} header(s) left behind`);
  check("navigating away mid-load does not rewrite the URL back",
    globalThis.window.location.hash === "#allraces",
    `hash=${globalThis.window.location.hash}`);
  check("the view navigated to is the one that renders",
    doc.querySelectorAll("#all-races-chart svg g .overview-panel-label").length === 4,
    `${doc.querySelectorAll("#all-races-chart svg g .overview-panel-label").length} panels`);
}

// 5. All Races deep link.
{
  const doc = await boot("#allraces");
  const panels = doc.querySelectorAll("#all-races-chart svg g .overview-panel-label").length;
  check("all-races deep link renders 4 panels", panels === 4, `${panels} panel labels`);
}

// 6. Race Overview deep link.
{
  const doc = await boot("#1990/overview");
  const bars = doc.querySelectorAll("#overview-chart .overview-bar").length;
  check("overview deep link renders bars", bars > 20, `${bars} bars`);
}

// 7. One-day classics: an aggregate race whose "stages" are separate races,
//    with no All Years Summary and no sprint/KOM. Worth its own case because
//    every one of those differences is a capability flag that a future change
//    could silently drop.
{
  const doc = await boot("#classics/2021/stage/gc");
  const lines = doc.querySelectorAll("#chart svg path.rider-line").length;
  check("classics deep link renders chart", lines > 0, `${lines} lines`);

  // Ticks must be the abbreviations, not "1..11" and not the full race names.
  const ticks = [...doc.querySelectorAll("#chart .x-axis .tick text")].map((t) => t.textContent);
  check("classics x-axis uses race abbreviations",
        ticks.includes("PR") && ticks.includes("LBL"),
        ticks.slice(0, 11).join(" "));

  // Season TOTALS are meaningless for eleven unrelated races, so that nav slot
  // carries the per-race history instead — shown, but relabelled.
  const allRacesBtn = doc.getElementById("view-all-races");
  check("classics repurposes the cross-year slot as Race History",
        allRacesBtn.hidden === false && allRacesBtn.textContent === "Race History",
        `hidden=${allRacesBtn.hidden} label=${allRacesBtn.textContent}`);

  // Sprint/KOM are not contested, so neither may be offered — but the "points"
  // path is reused for the cumulative SEASON STANDING, labelled accordingly.
  const opts = [...doc.getElementById("metric-select").options];
  const labels = opts.map((o) => `${o.value}:${o.textContent}`);
  check("classics offers result + season points, not sprint/KOM",
        labels.join(",") === "gc:Result,points:Season Points", labels.join(","));
}

// 7b. by-Stage Table: an aggregate race drops the bib column and groups by
//     team in medal-table order; a stage race keeps bib ordering untouched.
{
  const doc = await boot("#classics/2021/stage/gc/table");
  const ths = [...doc.querySelectorAll("#stage-table thead th")].map((t) => t.textContent.trim());
  check("classics table hides the bib column", !ths.includes("Bib"), ths.slice(0, 3).join(","));
  check("classics table keeps a team column", ths[0] === "T", ths[0]);

  // Each team must occupy ONE contiguous block.
  const teamOfRow = [...doc.querySelectorAll("#stage-table tbody tr")].map((tr) => {
    const cell = tr.querySelector(".col-team-inner");
    return cell ? cell.textContent.trim() : null;
  });
  const starts = teamOfRow.filter(Boolean);
  check("classics table groups each team once", new Set(starts).size === starts.length,
        `${starts.length} blocks, ${new Set(starts).size} distinct`);

  // Medal-table order: the first team must have at least as many wins as the last.
  check("classics table leads with a winning team",
        starts.length > 1 && starts[0] === "Deceuninck - Quick Step", starts[0]);

  // The sticky rider column must shift left over the hidden bib column, or it
  // strands a 52px hole beside the team column when scrolled horizontally.
  const tbl = doc.querySelector(".stage-table");
  check("classics table marks itself no-bib", tbl.classList.contains("no-bib"), tbl.className);

  // Alternating team wash: every flip must coincide with a team change, and
  // there must be more than one band (otherwise nothing is being delineated).
  const trs = [...doc.querySelectorAll("#stage-table tbody tr")];
  let flips = 0, misaligned = 0, curTeam = null, prevBand = null;
  for (const tr of trs) {
    const cell = tr.querySelector(".col-team-inner");
    if (cell) curTeam = cell.textContent.trim();
    const band = tr.classList.contains("team-band");
    if (prevBand !== null && band !== prevBand) {
      flips++;
      if (!cell) misaligned++; // flipped mid-team rather than at a boundary
    }
    prevBand = band;
  }
  check("classics table bands alternate per team block", flips > 5, `${flips} flips`);
  check("classics table bands flip only at team boundaries", misaligned === 0,
        `${misaligned} mid-team flips`);
}

{
  const doc = await boot("#2024/stage/gc/table");
  const ths = [...doc.querySelectorAll("#stage-table thead th")].map((t) => t.textContent.trim());
  check("stage-race table still shows the bib column", ths.includes("Bib"), ths.slice(0, 3).join(","));
}

// 7c. A season where NO rider has a known team (1892-1894 Liege) still renders
//     its race column. Those years get neither a team nor a bib column, and the
//     sticky rider column's `left` offset must collapse to 0 to match — at the
//     inherited 52px it shifts right and, being opaque, paints over the single
//     race column, so the table looks like it has no races at all.
//
//     NOTE: jsdom does no layout, so this asserts the DOM and the class
//     combination the CSS keys off — it cannot catch the overlap itself. The
//     visual half needs a real browser.
{
  const doc = await boot("#classics/1892/stage/gc/table");
  const tbl = doc.querySelector(".stage-table");
  check("zero-team season omits the team column",
        !tbl.classList.contains("has-teams"), tbl.className);
  const ths = [...doc.querySelectorAll("#stage-table thead th")].map((t) => t.textContent.trim());
  check("zero-team season still renders its race column",
        ths.includes("LBL"), ths.join(","));
  const cells = [...(doc.querySelector("#stage-table tbody tr")?.cells || [])]
    .map((c) => c.textContent.trim());
  check("zero-team season still renders a placing", cells.includes("1"), cells.join("|"));
}

// 7d. One tooltip per column header, not two. A `title` attribute renders the
//     NATIVE browser tooltip on top of the custom one, which is exactly what
//     went wrong when the abbreviations were introduced.
{
  const doc = await boot("#classics/2024/stage/gc/table");
  const ths = [...doc.querySelectorAll("#stage-table thead th.col-stage")];
  const titled = ths.filter((t) => t.title).map((t) => t.textContent.trim());
  check("classics headers set no native title", titled.length === 0, titled.join(","));

  const lbl = ths.find((t) => t.textContent.trim() === "LBL");
  lbl.dispatchEvent(new doc.defaultView.MouseEvent("mouseenter", { bubbles: true }));
  const tip = doc.getElementById("tooltip");
  // Read the child <div>s rather than splitting textContent on newlines: the
  // divs render as separate lines but textContent runs adjacent ones together,
  // so line-splitting reports a layout that isn't what the user sees.
  const lines = [...tip.querySelectorAll("div")].map((d) => d.textContent.trim()).filter(Boolean);
  check("classics tooltip leads with the full race name",
        lines[0] === "Liege-Bastogne-Liege", lines[0]);
  // MM/DD/YYYY, formatted by string split so it cannot drift a day through a
  // timezone — a bare ISO date parses as UTC midnight.
  check("classics tooltip shows the race date under the name",
        lines[1] === "04/21/2024", lines[1]);
  check("classics tooltip has name/date/start/finish/distance",
        lines.length === 5 && /km/.test(lines[4]), lines.join(" | "));
}

// 7e. Season standings: cumulative points must never decrease, and a rider who
//     skipped the FINAL race must still appear in the standings — van der Poel
//     was 2nd on 2024 points without riding Il Lombardia.
{
  const doc = await boot("#classics/2024/stage/points");
  const legend = [...doc.querySelectorAll("#legend .legend-item, #legend .legend-row")]
    .map((e) => e.textContent);
  const hasMvdp = legend.some((t) => /van der Poel/.test(t));
  check("season standings include a rider who skipped the last race",
        hasMvdp, `${legend.length} legend rows`);
}

// 7f. Race History: one small-multiple panel per race. Faceted rather than
//     overlaid because categorical color tops out at eight hues and there are
//     eleven races.
{
  const doc = await boot("#classics/allraces");
  await new Promise((r) => setTimeout(r, 300));   // lazy race_history.json fetch
  const cells = doc.querySelectorAll("#all-races-chart .history-cell");
  check("race history renders one panel per race", cells.length === 11, `${cells.length} panels`);
  const titles = [...cells].map((c) => c.querySelector(".history-title")?.textContent ?? "");
  check("race history panels are titled with race and span",
        /Paris-Roubaix\s+1896/.test(titles.join("|")), titles[1] ?? "");
  // km/mi now serves the race history too — it opens on Winning speed, which
  // has a unit to convert, so the button must be offered rather than hidden.
  const unitBtn = doc.getElementById("all-races-unit-toggle");
  check("race history offers the km/mi toggle",
        unitBtn.hidden === false, `hidden=${unitBtn.hidden} label=${unitBtn.textContent}`);
  // Switching to Finishers — a count with no unit — takes the button away.
  const metricBtns = [...doc.querySelectorAll("#all-races-chart .classif-toggle-btn")];
  const finishers = metricBtns.find((b) => b.textContent.trim() === "Finishers");
  finishers?.click();
  check("race history hides km/mi for the unit-less metric",
        unitBtn.hidden === true, `hidden=${unitBtn.hidden}`);
}

// 8. A cancelled race stays in the season rather than vanishing from it.
{
  const doc = await boot("#classics/2020/overview");
  const bars = doc.querySelectorAll("#overview-chart .overview-bar").length;
  check("classics 2020 overview renders every race", bars >= 8, `${bars} bars`);
}

// 7f. by-Stage Table row filters (aggregate races only): Top 10 / Top 20 keep
//     riders with at least one finish inside that position in ANY race of the
//     season, and Nation intersects with them.
{
  const doc = await boot("#classics/2021/stage/gc/table");
  const rows = () => doc.querySelectorAll("#stage-table tbody tr").length;
  const btn = (label) =>
    [...doc.querySelectorAll(".table-filter-row button")].find((b) => b.textContent === label);

  check("classics table offers Top 10 / Top 20 / All / Nation",
        !!btn("Top 10") && !!btn("Top 20") && !!btn("All")
          && !!doc.querySelector(".table-filter-dropdown .filter-toggle-btn"),
        [...doc.querySelectorAll(".stage-table-controls button")].map((b) => b.textContent).join(","));

  // Controls sit to the LEFT of the grid — the slot the sidebar occupies in
  // graph mode, so they don't jump across the screen on a sub-view switch.
  check("table controls precede the grid",
        [...doc.getElementById("stage-table").children].map((c) => c.className).join(",")
          === "stage-table-controls,stage-table-wrap",
        [...doc.getElementById("stage-table").children].map((c) => c.className).join(","));

  check("All is lit by default", btn("All").classList.contains("active"),
        [...doc.querySelectorAll(".table-filter-row button")]
          .filter((b) => b.classList.contains("active")).map((b) => b.textContent).join(","));

  const all = rows();
  const countText = () => doc.querySelector(".table-filter-count")?.textContent ?? null;
  // Present even with no filter on, so the field size is readable without
  // having to filter first.
  check("unfiltered count reads '<n> riders'", countText() === `${all} riders`, countText());

  btn("Top 10").click();
  const top10 = rows();
  check("filtered count reads '<n> of <m>'", countText() === `${top10} of ${all}`, countText());
  btn("Top 20").click();
  const top20 = rows();

  // The real invariant: each is a strict subset of the next, and neither is
  // the whole field. A filter that silently matched everything would still
  // "work" by row count alone.
  check("Top 10 narrows the field", top10 > 0 && top10 < all, `${top10} of ${all}`);
  check("Top 20 is wider than Top 10 but still filtered",
        top20 > top10 && top20 < all, `${top20} vs ${top10}, all ${all}`);
  check("Top 10/20 are mutually exclusive",
        !btn("Top 10").classList.contains("active") && btn("Top 20").classList.contains("active"),
        `top10=${btn("Top 10").classList.contains("active")} top20=${btn("Top 20").classList.contains("active")}`);

  // Radio, not toggle: re-clicking the lit button must NOT clear it — "All" is
  // the only way back, exactly as the graph view's Quick select behaves.
  btn("Top 20").click();
  check("re-clicking the lit button is a no-op",
        rows() === top20 && btn("Top 20").classList.contains("active"), `${rows()} of ${all}`);
  btn("All").click();
  check("All restores the whole field",
        rows() === all && btn("All").classList.contains("active"), `${rows()} of ${all}`);

  // Colour ramp must stay anchored to the WHOLE field, so filtering cannot
  // repaint a win from green to red.
  const winnerBg = (r) => {
    const tr = [...doc.querySelectorAll("#stage-table tbody tr")]
      .find((x) => x.querySelector(".stage-table-name")?.textContent === r);
    return [...tr.querySelectorAll("td")].map((td) => td.style.background).join("|");
  };
  const someone = doc.querySelector("#stage-table tbody tr .stage-table-name").textContent;
  const before = winnerBg(someone);
  btn("Top 10").click();
  check("filtering does not repaint the cells it keeps", winnerBg(someone) === before,
        before.slice(0, 40));

  // "All" must mean all rows, so it drops the Nation filter too — otherwise the
  // lit button would claim the whole field while a nation still hid most of it.
  // Belgium specifically: it has top-10 finishers in every classics season, so
  // the intersection is non-empty. The alphabetically-first nation is Argentina,
  // which has none in 2021 — picking blindly tests nothing.
  const nationCb = [...doc.querySelectorAll(".table-filter-dropdown .filter-panel input[type=checkbox]")]
    .find((c) => c.value === "Belgium");
  nationCb.checked = true;
  nationCb.dispatchEvent(new doc.defaultView.Event("change", { bubbles: true }));
  const withNation = rows();
  check("Nation intersects with the active limit (AND, not override)",
        withNation < top10 && withNation > 0
          && btn("Top 10").classList.contains("active"),
        `${withNation} with nation vs ${top10} top-10`);

  btn("All").click();
  check("All also clears the Nation filter",
        rows() === all
          && doc.querySelector(".table-filter-dropdown .filter-toggle-btn").textContent === "Nation",
        `${rows()} of ${all}, btn=${doc.querySelector(".table-filter-dropdown .filter-toggle-btn").textContent}`);
}

// 7g. A stage race must NOT get the row filters: its gcRank is a running GC
//     position, so "a top-10 result" would be a different claim entirely.
{
  const doc = await boot("#2021/stage/gc/table");
  check("stage race omits the table row filters",
        doc.querySelectorAll(".stage-table-controls").length === 0
          && doc.querySelectorAll("#stage-table tbody tr").length > 100,
        `${doc.querySelectorAll(".stage-table-controls").length} control blocks`);
}

// 8. An unrecognized hash must not leave a stale view under a URL that
//    describes something else. 1915 is a war year with no Tour, so applying
//    #1915 renders nothing — and the URL has to snap back to the 1914 chart
//    that is still on screen rather than keep claiming 1915.
{
  const doc = await boot("#1914/stage/gc");
  const win = doc.defaultView;
  const yearBefore = doc.querySelector("#year-select").value;
  win.location.hash = "#1915/stage/gc";
  const deadline = Date.now() + 3000;
  while (win.location.hash !== "#1914/stage/gc" && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 10));
  }
  check("a year the race never ran snaps the URL back to what is displayed",
        win.location.hash === "#1914/stage/gc"
          && doc.querySelector("#year-select").value === yearBefore,
        `hash=${win.location.hash} year=${doc.querySelector("#year-select").value}`);
}

// 8b. A slug no index has heard of must SAY so. An empty panel is
//     indistinguishable from one still loading, and this is reachable from a
//     shared link to a rider whose slug has since been renamed.
{
  const doc = await boot("#riders/no-such-rider-xyz");
  const panel = doc.querySelector("#riders-chart");
  check("an unknown rider slug reports itself instead of rendering blank",
        /No rider matches this link/.test(panel.textContent)
          && panel.querySelector(".rider-back-btn") !== null,
        `"${panel.textContent.replace(/\s+/g, " ").trim().slice(0, 60)}"`);
}

// 8c. Virtualisation must not eject a keyboard user. Tabbing down the grid
//     scrolls each focused button into view, which re-renders the window and
//     used to destroy the focused node, dropping focus to <body> — so Tab
//     could never get past the first window.
{
  const doc = await boot("#riders");
  const grid = doc.querySelector(".riders-grid");
  const before = [...doc.querySelectorAll(".rider-name-btn")];
  const target = before[Math.floor(before.length / 2)];
  const targetId = target.getAttribute("data-id");
  target.focus();
  const focusedBefore = doc.activeElement === target;

  // Far enough to move the window by a row, near enough that this rider is
  // still in it — which is exactly the tab-into-the-next-row case. (The first
  // version of this check scrolled 58px, which under JSDOM's zero clientHeight
  // left `first` at 0: renderWindow returned early, nothing was replaced, and
  // the check passed against the unfixed build. A scroll that does not move
  // the window proves nothing here.)
  grid.scrollTop = 145;
  grid.dispatchEvent(new (globalThis.window.Event)("scroll", { bubbles: false }));
  await new Promise((r) => setTimeout(r, 300));

  const active = doc.activeElement;
  check("scrolling the riders grid keeps keyboard focus on the same rider",
    focusedBefore && active !== doc.body && active.getAttribute("data-id") === targetId,
    `focused ${targetId} → ${active === doc.body ? "<body>" : active.getAttribute("data-id")}`);
}

// ── Alphabetical order ───────────────────────────────────────────────────
//
// Two sorting bugs, one cause: ordering names with a bare .sort() or a plain
// localeCompare. `.sort()` compares UTF-16 code units, so "Île-de-France" sat
// at position 1949 of 1950 in the team filter, below every team starting with
// a Latin letter. localeCompare gives leading punctuation full weight, so
// Albert 't Jolyn — a real Belgian surname, the same shape as "In 't Ven" —
// sorted ahead of Abdoujaparov at the top of a list of 14,000 riders.
{
  const { compareNames } = await import(`${new URL(scriptSrc, buildDir)}?names`)
    .then((m) => m, () => ({}));
  // compareNames is not exported from the bundle entry, so assert the
  // behaviour through an equivalent collator: this is a guard on the CHOICE of
  // collation, which is the thing that was wrong.
  const cmp = new Intl.Collator(undefined, { ignorePunctuation: true }).compare;

  const riders = ["Zabel", "'t Jolyn", "Abdoujaparov", "In 't Ven", "Thomas"];
  const sorted = [...riders].sort(cmp);
  check("a surname starting with an apostrophe does not sort to the top",
    sorted[0] === "Abdoujaparov" && sorted.indexOf("'t Jolyn") > sorted.indexOf("Thomas"),
    sorted.join(" | "));

  const teams = ["Île-de-France", "Ineos", "Astana", "Zabel Team"];
  const tsorted = [...teams].sort(cmp);
  check("an accented team name sorts under its letter, not after Z",
    tsorted.indexOf("Île-de-France") < tsorted.indexOf("Ineos")
      && tsorted[tsorted.length - 1] === "Zabel Team",
    tsorted.join(" | "));

  check("the bare sort this replaced really was wrong",
    [...teams].sort()[teams.length - 1] === "Île-de-France",
    "if this fails the bug is gone for another reason and the guard is stale");
}

// The race-history "n" metric is a property of THIS ARCHIVE for the off-road
// set, not of the race. An `open_field` edition keeps the top 100 of a field
// that ran to 1,289 men at Leadville 2015; an `elite_division` one keeps a
// whole category and nothing else, 43 riders in 2016. Labelled "Finishers",
// those two sit side by side as a line falling off a cliff in 2016 and read as
// a race that collapsed.
{
  const doc = await boot("#gravel/allraces");
  const labels = [...doc.querySelectorAll(".race-toggle-group button")]
    .map((b) => b.textContent.trim());
  check("off-road race history does not call its count Finishers",
    labels.includes("Riders in archive") && !labels.includes("Finishers"),
    labels.join(" | "));

  const btn = [...doc.querySelectorAll("button")]
    .find((b) => b.textContent.trim() === "Riders in archive");
  btn?.click();
  const caveat = doc.querySelector(".history-caveat")?.textContent ?? "";
  check("off-road count carries the caveat that explains its steps",
    caveat.includes("Not the size of the field") && caveat.includes("1,289"),
    caveat ? `${caveat.slice(0, 48)}…` : "no caveat rendered");
}

// The classics store PCS's published field, so there the count really is the
// finishers and the caveat would be false. One label cannot serve both.
{
  const doc = await boot("#classics/allraces");
  const labels = [...doc.querySelectorAll(".race-toggle-group button")]
    .map((b) => b.textContent.trim());
  check("the classics still call their count Finishers",
    labels.includes("Finishers"), labels.join(" | "));

  const btn = [...doc.querySelectorAll("button")]
    .find((b) => b.textContent.trim() === "Finishers");
  btn?.click();
  check("the classics get no off-road caveat",
    doc.querySelector(".history-caveat") === null,
    doc.querySelector(".history-caveat")?.textContent ?? "none");
}

// A PARTIAL elevation sum is not a total. 74 race-seasons printed one:
// the classics in 1950 know one race in eight and showed that figure labelled
// "Total Elevation", understating the season eightfold while looking
// authoritative. The old guard asked whether ANY stage had a figure, which was
// written when the off-road set had none at all — PCS gravel elevation arrived
// on 2026-09-09 and turned that assumption into the bug.
{
  const doc = await boot("#classics/1950/overview");
  const vals = [...doc.querySelectorAll(".overview-summary-value")];
  const elev = vals[vals.length - 1];
  check("a season known for 1 race in 8 shows no elevation total",
    elev?.textContent.trim() === "\u2014", elev?.textContent.trim());
  check("and says how many it does know, rather than only a dash",
    /1 of 8/.test(elev?.getAttribute("title") ?? ""),
    elev?.getAttribute("title") ?? "no title");
}

// The rule must not eat a real total. A full season still shows one.
{
  const doc = await boot("#2026/overview");
  const vals = [...doc.querySelectorAll(".overview-summary-value")];
  const elev = vals[vals.length - 1];
  check("a fully measured season still totals its elevation",
    /\d,\d{3} m$/.test(elev?.textContent.trim() ?? ""), elev?.textContent.trim());
}

// Nothing known at all is a plain dash: there is no count worth offering.
{
  const doc = await boot("#gravel/2025/overview");
  const vals = [...doc.querySelectorAll(".overview-summary-value")];
  const elev = vals[vals.length - 1];
  check("a season with no elevation anywhere shows a bare dash",
    elev?.textContent.trim() === "\u2014" && !elev?.getAttribute("title"),
    `${elev?.textContent.trim()} title=${elev?.getAttribute("title") ?? "none"}`);
}

// The Riders search matches BOTH orderings of a name — "Eddy Merckx" as the
// page renders it, and "Merckx Eddy" as PCS prints it. The second one is the
// only thing the index's `n` field is still for, and since 2026-09-19 `n` is
// OMITTED wherever it is exactly `ln + " " + fn` and rebuilt on load by
// rawName(). So this is the check that the drop is lossless: break the
// reconstruction and the reversed query finds nobody, while every other
// assertion in this file keeps passing.
{
  const doc = await boot("#riders");
  const input = doc.querySelector(".riders-search-input");
  const label = () => doc.querySelector(".riders-count-label")?.textContent ?? "";
  const matched = () => Number((label().match(/^([\d,]+)/)?.[1] ?? "0").replace(/,/g, ""));
  // The input is debounced at 150ms; 400 leaves room without racing it.
  const type = async (q) => {
    input.value = q;
    input.dispatchEvent(new doc.defaultView.Event("input", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
    return matched();
  };
  const forward = await type("Eddy Merckx");
  check("Riders search finds a rider by the name the page displays",
    forward >= 1 && forward < 20, `"Eddy Merckx" matched ${forward}`);
  const reversed = await type("Merckx Eddy");
  check("...and by PCS's reversed ordering, which only the index `n` carries",
    reversed >= 1 && reversed < 20, `"Merckx Eddy" matched ${reversed}`);
  // A rider with no first name keeps a literal `n`; searching it must still work.
  const surnameOnly = await type("Legaux");
  check("a surname-only rider, whose `n` is never dropped, is still searchable",
    surnameOnly >= 1, `"Legaux" matched ${surnameOnly}`);
}

// PCS writes an unrecorded first name as a placeholder and we store it
// verbatim: "Pujol ?", "Lecrenier ???", "Van Muyten .". Until 2026-09-19 every
// view printed it, so a reader saw the source's punctuation as part of a man's
// name. displayName() now renders the bare surname whenever that is all we
// know. 16 riders across the archive; these are two of them, in two different
// views, because displayName() feeds the chart legend and the results table
// from one place and a regression in either would be invisible from the other.
{
  const doc = await boot("#1903/stage/gc");
  const names = [...doc.querySelectorAll("#legend .legend-item")]
    .map((el) => el.textContent.trim());
  const pujol = names.filter((n) => /Pujol/.test(n));
  check("a first name PCS never recorded is not rendered as a placeholder",
    pujol.length > 0 && pujol.every((n) => !/[?.]/.test(n)), pujol.join(" | ") || "no Pujol row");
  // The whole legend, not just the one rider: a "?" or a free-standing "." is
  // never part of a name, whoever it belongs to. NOT anchored to the end —
  // each legend row ends in a flag emoji, so an end-anchored test here passed
  // against the placeholder it was written to catch (verified by mutation).
  const placeholders = names.filter((n) => /\?|\s\.(?!\w)/.test(n));
  check("...and no other name in the field carries one either",
    placeholders.length === 0, placeholders.slice(0, 5).join(" | ") || "none");
}

{
  const doc = await boot("#classics/1892/stage/gc/table");
  const cells = [...doc.querySelectorAll("td")].map((el) => el.textContent.trim());
  const lecrenier = cells.filter((c) => /Lecrenier/.test(c));
  check("the results table drops the placeholder too",
    lecrenier.length > 0 && lecrenier.every((c) => !/\?/.test(c)),
    lecrenier.join(" | ") || "no Lecrenier cell");
}

// The chart's end labels sit at their rider's finishing rank, and on the
// DEFAULT view twenty riders share ranks 1-20 on an axis spanning 1 to 180 —
// about 2-4px apart in a 10px font. They overlapped into an unreadable smear
// until layoutEndLabels() spread them (2026-09-19). jsdom implements neither
// getBBox nor getComputedTextLength, so these read the ATTRIBUTES the layout
// writes rather than measuring pixels: a `y` that is too close to its
// neighbour is the defect, whether or not this DOM can paint it.
{
  const doc = await boot("#2026/stage/gc");
  const shown = [...doc.querySelectorAll(".labels .rider-end-label")]
    .filter((el) => el.style.opacity === "1")
    .map((el) => Number(el.getAttribute("y")))
    .sort((a, b) => a - b);
  check("the default view labels the whole Top 20", shown.length === 20,
    `${shown.length} labels shown`);
  const gaps = shown.slice(1).map((y, i) => y - shown[i]);
  const tightest = gaps.length ? Math.min(...gaps) : Infinity;
  // 11px is LABEL_PITCH in stageChart.ts; allow a hair for float arithmetic.
  check("no two end labels sit on top of each other",
    tightest >= 10.99, `closest pair ${tightest.toFixed(1)}px apart`);

  // The right margin used to be a constant 36, leaving 30px after the label's
  // 6px offset while the widest surname in this field renders at ~70px — so
  // every label past about five characters was cut off by the SVG's edge, and
  // the smear hid it. The margin is now measured from the longest label.
  const svg = doc.querySelector("#chart svg");
  const svgWidth = Number(svg.getAttribute("width"));
  const labelX = Math.max(...[...doc.querySelectorAll(".labels .rider-end-label")]
    .map((el) => Number(el.getAttribute("x"))));
  const longest = Math.max(...[...doc.querySelectorAll(".labels .rider-end-label")]
    .map((el) => el.textContent.length));
  // Same per-character estimate the code falls back to without a text metric.
  const needs = longest * 5.6;
  const room = svgWidth - labelX - Number(svg.querySelector("g").getAttribute("transform")
    .match(/translate\(([\d.]+)/)[1]);
  check("there is room at the right edge for the longest name",
    room >= needs, `${room.toFixed(0)}px of room for ~${needs.toFixed(0)}px of text ` +
    `("${longest}" chars)`);
}

// Selecting and re-selecting must not walk the labels down the chart: the
// layout re-spreads from each label's recorded natural y (data-y0), not from
// wherever the last pass left it.
{
  const doc = await boot("#2026/stage/gc");
  const read = () => [...doc.querySelectorAll(".labels .rider-end-label")]
    .filter((el) => el.style.opacity === "1")
    .map((el) => `${el.getAttribute("data-id")}:${Number(el.getAttribute("y")).toFixed(1)}`)
    .sort().join("|");
  const before = read();
  const press = (label) => [...doc.querySelectorAll("button")]
    .find((b) => b.textContent.trim() === label)?.click();
  for (let i = 0; i < 3; i++) { press("Top 10"); press("All"); press("Top 20"); }
  check("re-selecting does not drift the labels down the chart",
    before === read() && before.length > 0,
    before === read() ? `${before.split("|").length} labels stable` : "positions moved");
}

console.log(failures.length === 0 ? "PASS" : `FAIL (${failures.length}): ${failures.join(", ")}`);
process.exit(failures.length === 0 ? 0 : 1);
