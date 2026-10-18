// Restyling the chart's lines, end dots and end labels for selection and
// hover, plus end-label de-collision. Split out of stageChart.ts so the legend
// can drive highlighting without importing the whole chart.
import { d3 } from "../d3";
import { state } from "../state";
import { chartEl } from "../dom";

export function cssEscape(s: string): string {
  return s.replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
}

// Restyle one rider's line based on current selected/highlighted state.
function styleRiderLine(pathEl: SVGPathElement) {
  const el = d3.select(pathEl);
  const id = pathEl.getAttribute("data-id")!;
  const isSelected = state.selected.has(id);
  const isHighlighted = state.highlighted === id;
  el.classed("hidden-line", false);
  el.classed("dimmed", !isSelected && !isHighlighted);
  el.classed("highlighted", isHighlighted);
  el.attr("stroke", isSelected || isHighlighted ? state.colorScale(id) : "var(--line-dim)");
  el.style("stroke-opacity", isHighlighted ? 1 : isSelected ? 0.95 : 0.12);
}

// Restyle one rider's end dot or end label (same visibility rules for both).
function styleRiderMarker(el: SVGCircleElement | SVGTextElement) {
  const id = el.getAttribute("data-id")!;
  const isSelected = state.selected.has(id);
  const isHighlighted = state.highlighted === id;
  d3.select(el)
    .style("opacity", isSelected || isHighlighted ? 1 : 0)
    .attr("fill", isSelected || isHighlighted ? state.colorScale(id) : "var(--line-dim)");
}

// Full sweep across every rider — needed when the selection set changes
// (legend clicks, presets, filters) or after a redraw.
export function updateLineClasses() {
  d3.selectAll<SVGPathElement, unknown>(".lines .rider-line").each(function () {
    styleRiderLine(this as SVGPathElement);
  });
  d3.selectAll<SVGCircleElement, unknown>(".dots .rider-dot").each(function () {
    styleRiderMarker(this as SVGCircleElement);
  });
  d3.selectAll<SVGTextElement, unknown>(".labels .rider-end-label").each(function () {
    styleRiderMarker(this as SVGTextElement);
  });
  layoutEndLabels();
}

/** Pitch between two end labels that do not touch: 10px text plus a hair. */
const LABEL_PITCH = 11;

/** Spread the visible end labels apart so they can be read.
 *
 *  Each label sits at its rider's finishing rank, and on the DEFAULT view —
 *  the latest Tour, Top 20 — twenty riders share ranks 1-20 on an axis that
 *  spans 1 to 180. That put the labels about 2-4px apart in a 10px font, so
 *  the names overlapped into an unreadable smear at the right edge of the
 *  chart. There was no de-collision at all; this is it.
 *
 *  Two passes, the usual shape: push each label down until it clears the one
 *  above, then, if that ran past the bottom, push back up from the end. Order
 *  is preserved, so a label never crosses its neighbour and the reading order
 *  still matches the finishing order.
 *
 *  When they cannot all fit — the classics' "Top 20" selects 136 riders,
 *  because a season standing ties dozens of them on equal points, and 136
 *  labels need 1,496px of a 732px chart — the ones that fit are drawn from the
 *  BEST RANK DOWN and the remainder are hidden. Labelling the leaders is what
 *  a reader wants from this chart, and each unlabelled rider still has his end
 *  dot, his legend row and his hover. An earlier version hid ALL of them past
 *  the threshold, which left the entire classics race-set unlabelled at every
 *  preset over a cliff edge — 70 labels in room for 66 lost all 70.
 *
 *  Runs from updateLineClasses(), which every selection change already calls.
 *  NOT from the hover path: setHighlight() restyles exactly two elements to
 *  stay O(1) across ~200 riders, and re-spreading the field on every mouseover
 *  would hand that back. A hovered rider's label can therefore sit under a
 *  spread one for as long as the pointer rests there. */
function layoutEndLabels() {
  const labels: { el: SVGTextElement; y0: number; y: number }[] = [];
  chartEl.querySelectorAll<SVGTextElement>(".labels .rider-end-label").forEach((el) => {
    const id = el.getAttribute("data-id")!;
    if (!state.selected.has(id)) return;
    const y0 = Number(el.getAttribute("data-y0"));
    if (!Number.isFinite(y0) || y0 < 0) return;     // rider never placed
    labels.push({ el, y0, y: y0 });
  });
  if (labels.length === 0) return;

  const bottom = state.yScale.range()[1];
  labels.sort((a, b) => a.y0 - b.y0);

  // y0 ascends with rank in every metric this chart draws, so "the first that
  // fit" is "the best-ranked that fit" without needing the rank itself.
  const room = Math.max(1, Math.floor(bottom / LABEL_PITCH));
  for (const l of labels.splice(room)) l.el.style.opacity = "0";

  for (let i = 1; i < labels.length; i++) {
    labels[i].y = Math.max(labels[i].y0, labels[i - 1].y + LABEL_PITCH);
  }
  const overshoot = labels[labels.length - 1].y - bottom;
  if (overshoot > 0) {
    labels[labels.length - 1].y = bottom;
    for (let i = labels.length - 2; i >= 0; i--) {
      labels[i].y = Math.min(labels[i].y, labels[i + 1].y - LABEL_PITCH);
    }
  }
  for (const l of labels) l.el.setAttribute("y", String(l.y));
}

// Restyle just one rider's three chart elements (line, end dot, end label).
function restyleRider(id: string) {
  const esc = cssEscape(id);
  // A rider can have multiple line segments now (the solid line plus zero or
  // more dashed "no time recorded" bridges) — restyle all of them, not just
  // the first match.
  chartEl.querySelectorAll<SVGPathElement>(`.lines .rider-line[data-id="${esc}"]`).forEach(styleRiderLine);
  const dot = chartEl.querySelector<SVGCircleElement>(`.dots .rider-dot[data-id="${esc}"]`);
  if (dot) styleRiderMarker(dot);
  const label = chartEl.querySelector<SVGTextElement>(`.labels .rider-end-label[data-id="${esc}"]`);
  if (label) styleRiderMarker(label);
}

// O(1) hover path: only the previously-highlighted rider and the new one
// change appearance, so restyle exactly those two instead of sweeping all
// ~200 lines + dots + labels on every mouseenter/mouseleave.
export function setHighlight(id: string | null) {
  if (state.highlighted === id) return;
  const prev = state.highlighted;
  state.highlighted = id;
  if (prev) restyleRider(prev);
  if (id) restyleRider(id);
}
