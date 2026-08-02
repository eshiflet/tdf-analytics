// ─── Hash routing ────────────────────────────────────────────────────────────
// Formats: #<year>/stage/<metric>[/table] (metric: gc | gc-time | points | kom)
//          · #<year>/overview · #allraces · #riders · #riders/<rider-slug>
// State changes push a hash entry (so back/forward walk through app states);
// hashchange applies the hash back onto app state. The compare-with-
// computeHash() guard on both sides breaks the write→event→write loop.
//
// applyHash() itself stays in main.ts, not here — it calls setRace/switchView/
// loadDataset/drawRiderDetail to actually apply the parsed state, which makes
// it orchestration rather than routing logic.
import { state } from "./state";

export function computeHash(): string {
  // "tour" stays implicit so pre-multi-race links (#2026/stage/gc) remain
  // canonical; other races get a leading race segment (#giro/2026/stage/gc).
  const race = state.currentRace === "tour" ? "" : `${state.currentRace}/`;
  if (state.currentView === "riders") {
    return state.currentRiderId
      ? `#${race}riders/${state.currentRiderId.replace(/^rider\//, "")}`
      : `#${race}riders`;
  }
  if (state.currentView === "allraces") return `#${race}allraces`;
  if (state.currentView === "overview") return `#${race}${state.currentYear}/overview`;
  const metricSeg = state.currentMetric === "gc" && state.gcDisplayMode === "time" ? "gc-time"
    : state.currentMetric === "points" && state.sprintDisplayMode === "points" ? "sprint-points"
    : state.currentMetric === "kom" && state.komDisplayMode === "points" ? "kom-points"
    : state.currentMetric;
  // Trailing "/table" only when the table sub-view is active, so every
  // pre-existing #<year>/stage/<metric> link still means the graph.
  const subViewSeg = state.stageViewMode === "table" ? "/table" : "";
  return `#${race}${state.currentYear}/stage/${metricSeg}${subViewSeg}`;
}

export function updateHash() {
  if (state.applyingHash) return;
  const h = computeHash();
  if (window.location.hash !== h) window.location.hash = h;
}
