// Shared mutable app state. ES modules can't reassign an imported `let`
// binding from outside the module that declared it, so every mutable field
// lives as a property on this one exported object instead — every module
// reads/writes `state.foo`, and only `state` itself is ever imported
// (never reassigned), which keeps this valid across files. See
// architecture.md's "Frontend module map" for the rationale.
import type { GcDataset } from "./types";
import type { RaceId } from "./raceRegistry";
import { RACES, getYearsForRace } from "./raceRegistry";
import type { ScaleOrdinal, ScaleLinear } from "./d3";

export const state = {
  currentRace: "tour" as RaceId,
  YEARS: getYearsForRace("tour"),
  currentYear: "",
  currentMetric: "gc" as "gc" | "points" | "kom",
  // "by Stage" sub-view: the bump-chart line graph, or a spreadsheet-style
  // table of every rider (ordered by bib number) x every stage.
  stageViewMode: "graph" as "graph" | "table",
  currentPreset: "20",
  sprintDisplayMode: "rank" as "rank" | "points",
  komDisplayMode: "rank" as "rank" | "points",
  // Only meaningful when currentMetric === "gc" — toggles the "by Stage"
  // chart between ranking-based ("position") and gap-to-leader-based ("time").
  gcDisplayMode: "position" as "position" | "time",

  dataset: undefined as unknown as GcDataset,
  selected: new Set<string>(),
  highlighted: null as string | null,
  // Team/Nation filter state for the "by Stage" view — reset whenever the
  // dataset (year) changes since team/nation membership is year-specific.
  stageFilterTeams: new Set<string>(),
  stageFilterNations: new Set<string>(),
  // Row filters for the "by Stage" TABLE, kept separate from the graph's
  // filters above on purpose: those rewrite `state.selected`, which is the
  // user's hand-picked set of chart lines, and driving that from the table
  // would silently discard it. These only hide rows.
  //   stageTableTopFilter: 10 | 20 = keep riders with at least one finish
  //   inside that position in ANY race this season; null = no limit.
  stageTableTopFilter: null as null | 10 | 20,
  stageTableFilterNations: new Set<string>(),
  // Rider whose career chart is open on the Riders view (null = grid). Only
  // consulted for hash routing while currentView === "riders".
  currentRiderId: null as string | null,
  colorScale: undefined as unknown as ScaleOrdinal<string, string>,

  // Per-dataset points/KOM rankings, recomputed on year change.
  pointsRankAtStage: new Map<number, Map<string, number>>(),
  finalPointsRank: new Map<string, number>(),
  ridersAtFinalPointsRank: new Map<number, { riders: GcDataset["riders"]; points: number }>(),

  komRankAtStage: new Map<number, Map<string, number>>(),
  finalKomRank: new Map<string, number>(),
  ridersAtFinalKomRank: new Map<number, { riders: GcDataset["riders"]; points: number }>(),

  currentView: "stage" as "stage" | "overview" | "allraces" | "riders",
  allRacesUnit: "metric" as "metric" | "imperial",
  overviewUnit: "metric" as "metric" | "imperial",

  // Suppresses hash writes while a hash is being applied, so the intermediate
  // draw calls inside applyHash() don't push partial states onto the history.
  applyingHash: false,

  // Chart x/y scales from the last drawChart() — read by showTooltip() to map
  // a hover's pixel position back to a stage number.
  xScale: undefined as unknown as ScaleLinear<number, number>,
  yScale: undefined as unknown as ScaleLinear<number, number>,

  // ── Riders page filter state ──────────────────────────────────────────────
  ridersSearchQuery: "",
  // empty = all years shown. OR semantics across years ("2021, 2023" = either),
  // and a year here also scopes the jersey filters and the grid's jersey icons
  // to what was actually won in one of these years.
  ridersFilterYears: new Set<number>(),
  ridersFilterTeam: "",
  ridersFilterNationality: "",
  // AND semantics: a rider must have won every selected category, not just
  // one. Keys are "raceId:category" format (e.g. "tour:gc", "giro:sprint").
  ridersFilterJerseys: new Set<string>(),
  // empty = all races shown; non-empty = only the listed races
  ridersFilterRaces: new Set<RaceId>(),
};

state.currentYear = state.YEARS[0];

export function raceConfig() {
  return RACES[state.currentRace];
}
