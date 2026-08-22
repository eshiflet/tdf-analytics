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

async function boot(hash, midLoad) {
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
    await new Promise((r) => setTimeout(r, midLoad.at));
    midLoad.run(window.document);
  }
  await new Promise((r) => setTimeout(r, 400));
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
async function bootProgressive(hash, delays, midLoad) {
  fetchDelays = delays;
  try {
    const doc = await boot(hash, midLoad);
    return doc;
  } finally {
    fetchDelays = null;
  }
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
  const btns = doc.querySelectorAll(".rider-name-btn").length;
  // By id, not by position among .riders-filter-select: this check silently
  // moved to the nationality select (and failed at 70 options) when the year
  // filter became a multi-select dropdown and left that class behind.
  const teamOptions = doc.querySelector("#riders-team-filter")?.options.length ?? 0;
  const natOptions = doc.querySelector("#riders-nationality-filter")?.options.length ?? 0;
  const filterBoxes = doc.querySelectorAll(".filter-panel input[type=checkbox]").length;
  check("riders grid renders all riders", btns > 5000, `${btns} rider buttons`);
  check("team filter populated from team table", teamOptions > 600, `${teamOptions} team options`);
  check("nationality filter populated", natOptions > 50, `${natOptions} nationality options`);
  // Years and races are both checkbox panels now; every year plus 4 races.
  check("year filter offers a checkbox per year", filterBoxes > 100,
    `${filterBoxes} year+race checkboxes`);
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
    // Partway through, with classics and tour rendered and giro/vuelta still
    // in flight, switch classics off the way a user would. It must not come
    // back on when the later indexes arrive and rebuild the toggle bar.
    { at: 60, run: (d) => {
        const btns = [...d.querySelectorAll(".race-toggle-btn")];
        const live = btns.filter((b) => !b.classList.contains("no-data"));
        if (live.length < 2) throw new Error(
          `scenario is not exercising progressive load: ${live.length} race(s) rendered at 60ms`);
        live.find((b) => b.textContent === "C").dispatchEvent(
          new (globalThis.window.MouseEvent)("click", { bubbles: true }));
      } });

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
    { at: 40, run: (d) => {
        if (d.querySelector(".rider-detail-header")) throw new Error(
          "an index arrived before the navigation — raise the delays");
        globalThis.window.location.hash = "#allraces";
      } });

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

console.log(failures.length === 0 ? "PASS" : `FAIL (${failures.length}): ${failures.join(", ")}`);
process.exit(failures.length === 0 ? 0 : 1);
