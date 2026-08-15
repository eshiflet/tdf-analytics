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

globalThis.fetch = async (url) => {
  const rel = String(url).replace(/^\/tdf-analytics\//, "");
  const data = fs.readFileSync(new URL(rel, buildDir), "utf-8");
  return new Response(data, { status: 200, headers: { "Content-Type": "application/json" } });
};

let importCounter = 0;

async function boot(hash) {
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
  await new Promise((r) => setTimeout(r, 400));
  return window.document;
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
  const teamOptions = doc.querySelectorAll(".riders-filter-select")[1]?.options.length ?? 0;
  check("riders grid renders all riders", btns > 5000, `${btns} rider buttons`);
  check("team filter populated from team table", teamOptions > 600, `${teamOptions} team options`);
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
  // km/mi belongs to the season-totals view and must not leak in here.
  check("race history hides the km/mi toggle",
        doc.getElementById("all-races-unit-toggle").hidden === true, "");
}

// 8. A cancelled race stays in the season rather than vanishing from it.
{
  const doc = await boot("#classics/2020/overview");
  const bars = doc.querySelectorAll("#overview-chart .overview-bar").length;
  check("classics 2020 overview renders every race", bars >= 8, `${bars} bars`);
}

console.log(failures.length === 0 ? "PASS" : `FAIL (${failures.length}): ${failures.join(", ")}`);
process.exit(failures.length === 0 ? 0 : 1);
