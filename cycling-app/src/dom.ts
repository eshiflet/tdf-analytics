// Every module-level DOM element reference the app touches, resolved once at
// import time from the static markup in index.html. Every other module reads
// its elements from here instead of re-querying the document.

export const raceSelectEl = document.getElementById("race-select") as HTMLSelectElement;
export const chartEl = document.getElementById("chart") as HTMLDivElement;
export const overviewChartEl = document.getElementById("overview-chart") as HTMLDivElement;
export const legendEl = document.getElementById("legend") as HTMLDivElement;
export const sidebarEl = document.getElementById("sidebar") as HTMLElement;
export const tooltipEl = document.getElementById("tooltip") as HTMLDivElement;
export const chartAreaEl = tooltipEl.parentElement as HTMLDivElement;
export const searchEl = document.getElementById("search") as HTMLInputElement;
export const yearSelectEl = document.getElementById("year-select") as HTMLSelectElement;
export const metricSelectEl = document.getElementById("metric-select") as HTMLSelectElement;
export const stageViewSelectEl = document.getElementById("stage-view-select") as HTMLSelectElement;
export const stageTableEl = document.getElementById("stage-table") as HTMLDivElement;
export const gcTimeToggleBtn = document.getElementById("gc-time-toggle") as HTMLButtonElement;
export const sprintModeToggleBtn = document.getElementById("sprint-mode-toggle") as HTMLButtonElement;
export const komModeToggleBtn = document.getElementById("kom-mode-toggle") as HTMLButtonElement;
export const viewStageBtn = document.getElementById("view-stage") as HTMLButtonElement;
export const viewOverviewBtn = document.getElementById("view-overview") as HTMLButtonElement;
export const viewAllRacesBtn = document.getElementById("view-all-races") as HTMLButtonElement;
export const allRacesChartEl = document.getElementById("all-races-chart") as HTMLDivElement;
export const viewRidersBtn = document.getElementById("view-riders") as HTMLButtonElement;
export const ridersChartEl = document.getElementById("riders-chart") as HTMLDivElement;
export const allRacesUnitToggleBtn = document.getElementById("all-races-unit-toggle") as HTMLButtonElement;
export const overviewSummaryEl = document.getElementById("overview-summary") as HTMLElement;
export const subtitleOverview = document.getElementById("subtitle-overview") as HTMLElement;
export const teamFilterBtn = document.getElementById("team-filter-btn") as HTMLButtonElement;
export const teamFilterPanel = document.getElementById("team-filter-panel") as HTMLDivElement;
export const nationFilterBtn = document.getElementById("nation-filter-btn") as HTMLButtonElement;
export const nationFilterPanel = document.getElementById("nation-filter-panel") as HTMLDivElement;
