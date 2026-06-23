// NOTE: this verifies the BUILT bundle (build/), not src/main.ts directly,
// because main.ts uses Vite's import.meta.glob() which only gets resolved
// by Vite's compiler (at `vite build` or `vite dev` time) — running the raw
// TypeScript source under plain tsx/Node would throw "glob is not a function".
// So: `npx vite build` first, then run this script.
import { JSDOM } from "jsdom";
import fs from "fs";
import path from "path";

const buildDir = new URL("./build/", import.meta.url);
const indexHtml = fs.readFileSync(new URL("./index.html", buildDir), "utf-8");
const bodyMatch = indexHtml.match(/<body>([\s\S]*)<\/body>/);
const bodyHtml = bodyMatch[1].replace(/<script[\s\S]*?<\/script>/, "");
const scriptSrcMatch = indexHtml.match(/<script[^>]*src="([^"]+)"/);
const scriptSrc = scriptSrcMatch[1].replace(/^\.\//, "");

const dom = new JSDOM(`<!doctype html><html><body>${bodyHtml}</body></html>`, {
  url: "http://localhost/",
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

await import(new URL(scriptSrc, buildDir).href);
await new Promise((r) => setTimeout(r, 300));

const doc = window.document;
const topAxisTicks = doc.querySelectorAll(".x-axis-top .tick");
const bottomAxisTicks = doc.querySelectorAll(".x-axis:not(.x-axis-top) .tick");
const vLines = doc.querySelectorAll(".grid-x .tick line");
console.log("top axis ticks:", topAxisTicks.length, "(expect 21)");
console.log("bottom axis ticks:", bottomAxisTicks.length, "(expect 21)");
console.log("top axis tick text sample:", [...topAxisTicks].slice(0, 3).map((t) => t.textContent));
console.log("vertical gridlines:", vLines.length);

const yearSelect = doc.querySelector("#year-select");
const yearOptions = [...yearSelect.options].map((o) => o.value);
console.log("year options:", yearOptions, "default:", yearSelect.value);
const legendCountDefault = doc.querySelectorAll("#legend .legend-item").length;
console.log("legend rows (default year):", legendCountDefault);

const expectedYears = Array.from({ length: 66 }, (_, i) => String(1960 + i));
const hasAllYears = expectedYears.every((y) => yearOptions.includes(y));
console.log("has all 66 years (1960-2025):", hasAllYears);
console.log("dropdown order (first 3, should be latest-first):", yearOptions.slice(0, 3));
console.log("dropdown order (last 3, should end at 1960):", yearOptions.slice(-3));

// switch to 2010 (oldest of the previous batch) and confirm the chart redraws with that year's data
yearSelect.value = "2010";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount2010 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName2010 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (2010):", legendCount2010, "first rider:", firstLegendName2010);

// switch to 2017 (mid-range, uses the simple classification URL convention) too
yearSelect.value = "2017";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount2017 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName2017 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (2017):", legendCount2017, "first rider:", firstLegendName2017);

// switch to 1995 (oldest year, newly added, 20 stages, missing uci_pnt column historically)
yearSelect.value = "1995";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount1995 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName1995 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (1995):", legendCount1995, "first rider:", firstLegendName1995, "(expect Induráin Miguel)");

// switch to 1999 (20 stages, oldest era's other stage-count variant)
yearSelect.value = "1999";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount1999 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName1999 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (1999):", legendCount1999, "first rider:", firstLegendName1999, "(expect Armstrong Lance)");

// switch to 1988 (no prologue that year -- the "Prélude" was unofficial and excluded)
yearSelect.value = "1988";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount1988 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName1988 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (1988):", legendCount1988, "first rider:", firstLegendName1988, "(expect Delgado Pedro)");

// switch to 1980 (has split stages 1a/1b and 7a/7b)
yearSelect.value = "1980";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount1980 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName1980 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (1980):", legendCount1980, "first rider:", firstLegendName1980, "(expect Zoetemelk Joop)");

// switch to 1971 (prologue was a team time trial -- required a custom merge fix)
yearSelect.value = "1971";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount1971 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName1971 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (1971):", legendCount1971, "first rider:", firstLegendName1971, "(expect Merckx Eddy)");

// switch to 1960 (oldest year, newly added, national teams era, no prologue)
yearSelect.value = "1960";
yearSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 200));
const legendCount1960 = doc.querySelectorAll("#legend .legend-item").length;
const firstLegendName1960 = doc.querySelector("#legend .legend-item .legend-name")?.textContent;
console.log("legend rows (1960):", legendCount1960, "first rider:", firstLegendName1960, "(expect Nencini Gastone)");

// hover the top-axis stage-1 tick and confirm the new start/finish/distance
// tooltip populates (1960 stage 1: Lille -> Brussel, flat)
const stage1Tick = [...doc.querySelectorAll(".x-axis-top .tick")][0];
stage1Tick.dispatchEvent(new window.MouseEvent("mousemove", { bubbles: true, clientX: 100, clientY: 50 }));
await new Promise((r) => setTimeout(r, 50));
const tooltipEl = doc.getElementById("tooltip");
const tooltipText = tooltipEl.textContent.replace(/\s+/g, " ").trim();
const tooltipHidden = tooltipEl.hidden;
console.log("stage tooltip (1960 stage1):", JSON.stringify(tooltipText), "hidden:", tooltipHidden);

const pass =
  topAxisTicks.length === 21 &&
  bottomAxisTicks.length === 21 &&
  hasAllYears &&
  yearOptions[0] === "2025" &&
  yearOptions[yearOptions.length - 1] === "1960" &&
  !tooltipHidden &&
  tooltipText.includes("Lille") &&
  tooltipText.includes("Brussel") &&
  tooltipText.includes("km") &&
  tooltipText.includes("F") &&
  legendCount2010 > 0 &&
  firstLegendName2010 === "Contador Alberto" &&
  legendCount2017 > 0 &&
  firstLegendName2017 === "Froome Chris" &&
  legendCount1995 > 0 &&
  firstLegendName1995 === "Induráin Miguel" &&
  legendCount1999 > 0 &&
  firstLegendName1999 === "Armstrong Lance" &&
  legendCount1988 > 0 &&
  firstLegendName1988 === "Delgado Pedro" &&
  legendCount1980 > 0 &&
  firstLegendName1980 === "Zoetemelk Joop" &&
  legendCount1971 > 0 &&
  firstLegendName1971 === "Merckx Eddy" &&
  legendCount1960 > 0 &&
  firstLegendName1960 === "Nencini Gastone";
console.log(pass ? "PASS" : "FAIL");
