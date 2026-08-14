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

  // All Years Summary is meaningless for a season of unrelated races.
  const allRacesBtn = doc.getElementById("view-all-races");
  check("classics hides All Years Summary", allRacesBtn.hidden === true,
        `hidden=${allRacesBtn.hidden}`);

  // Sprint/KOM are not contested; the metric select must not offer them.
  const metrics = [...doc.getElementById("metric-select").options].map((o) => o.value);
  check("classics offers only the result metric",
        metrics.length === 1 && metrics[0] === "gc", metrics.join(","));
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
}

{
  const doc = await boot("#2024/stage/gc/table");
  const ths = [...doc.querySelectorAll("#stage-table thead th")].map((t) => t.textContent.trim());
  check("stage-race table still shows the bib column", ths.includes("Bib"), ths.slice(0, 3).join(","));
}

// 8. A cancelled race stays in the season rather than vanishing from it.
{
  const doc = await boot("#classics/2020/overview");
  const bars = doc.querySelectorAll("#overview-chart .overview-bar").length;
  check("classics 2020 overview renders every race", bars >= 8, `${bars} bars`);
}

console.log(failures.length === 0 ? "PASS" : `FAIL (${failures.length}): ${failures.join(", ")}`);
process.exit(failures.length === 0 ? 0 : 1);
