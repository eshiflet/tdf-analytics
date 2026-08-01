// Generic hover-tooltip plumbing shared by every view. Rider-specific tooltip
// content (showTooltip, keyed off the stage chart's x/y scales) lives in
// views/stageChart.ts instead — it's tightly coupled to that view's state,
// not a leaf utility.
import type { StageInfo } from "./types";
import { tooltipEl, chartAreaEl } from "./dom";

export function showStageTooltip(event: MouseEvent, stage: StageInfo) {
  const distance = stage.distance_km != null ? `${Math.round(stage.distance_km)} km` : "—";
  const vertical = stage.vertical_meters != null ? `${stage.vertical_meters} m` : "—";
  const type = stage.route_type ?? "—";

  tooltipEl.innerHTML = `
    <div>${stage.start_location ?? "—"}</div>
    <div>${stage.finish_location ?? "—"}</div>
    <div>${distance}, ${vertical}, ${type}</div>
  `;
  positionTooltip(event);
}

export function hideTooltip() {
  tooltipEl.hidden = true;
}

// Shows the tooltip at the pointer, flipping to the left of the cursor when
// it would overflow the right edge of the window. Offsets are computed from
// chartAreaEl because that's the tooltip's positioning parent (.chart-area is
// position:relative) — measuring any other container skews the placement by
// that container's padding offset.
export function positionTooltip(event: MouseEvent) {
  tooltipEl.hidden = false;
  const areaRect = chartAreaEl.getBoundingClientRect();
  tooltipEl.style.top = `${event.clientY - areaRect.top - 10}px`;
  const tw = tooltipEl.offsetWidth;
  tooltipEl.style.left = window.innerWidth - event.clientX < tw + 24
    ? `${event.clientX - areaRect.left - tw - 10}px`
    : `${event.clientX - areaRect.left + 24}px`;
}
