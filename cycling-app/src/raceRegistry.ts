// ─── Race registry ───────────────────────────────────────────────────────────
// Single source of truth for per-race identity, colors, and capabilities.
// Adding a race = add an entry here + drop its data files in ./data/<slug>/
// (gc_by_stage_*.json, all_races_summary.json, riders_index.json) — the
// wildcard globs below pick them up automatically. The slug is used in the
// data path, the race dropdown, and the URL hash.

export type RaceId = "tour" | "giro" | "vuelta" | "classics" | "gravel";
export type JerseyCategoryId = "gc" | "sprint" | "kom" | "youth";

export interface RaceConfig {
  name: string;
  /** Line/dot colors on the rider-detail career chart. */
  chart: { gc: string; sprint: string; kom: string };
  /** Jersey icon fills; kom is a solid jersey or white with polka dots. */
  jersey: { gc: string; sprint: string; kom: { solid: string } | { dots: string } };
  jerseyTooltips: Record<JerseyCategoryId, string>;
  /** Shaded no-race bands on the All Races Overview. */
  warBands: { start: number; end: number; label: string }[];
  /** Youth-classification wins tracked in the pipeline for this race? */
  hasYouth: boolean;

  // ── Capability flags ──────────────────────────────────────────────────────
  // A "race" here can be a Grand Tour (an edition is one race, its stages are
  // days) or the one-day classics aggregate (an edition is a SEASON, and each
  // "stage" is a separate race). The flags below are what lets one set of
  // views serve both shapes. Adding them was the last open item in
  // ai-context.md's "Planned direction" note.

  /** Does an edition accumulate a general classification across its stages?
   *  False for the classics, where each "stage" is a standalone race and a
   *  rider's rank is their placing that day, not a running total. Drives the
   *  GC Time toggle (a season has no total time) and the wording of the
   *  GC metric. */
  hasCumulativeGc: boolean;
  /** Sprint/KOM classifications contested? The classics award neither, so
   *  both metric options are hidden rather than showing empty charts. Also
   *  gates the Tour-specific "competition started in 1953/1933" overlays. */
  hasSprintKom: boolean;
  /** Offer a cumulative season-points standing instead of Sprint/KOM. Only
   *  meaningful for an aggregate race: a rider's placing in one classic says
   *  nothing about the next, so the bump chart's line is noise until the
   *  y-axis accumulates something. Reuses the "points" metric path, which
   *  already does cumulative totals and per-stage standings. */
  hasSeasonPoints: boolean;
  /** Cross-year per-RACE history available (race_history.json): one small
   *  multiple per constituent race across its own lifetime. The aggregate
   *  counterpart to hasAllYears — a season's totals mean nothing, but each
   *  race's own trend across 130 years does. */
  hasRaceHistory: boolean;
  /** Cross-year All Years Summary available? Needs an all_races_summary.json,
   *  which the classics deliberately has no equivalent of — totals across a
   *  season of unrelated races aren't a meaningful series. */
  hasAllYears: boolean;
  /** Are this race's "stages" actually separate races? When true, views label
   *  them by stage_label alone ("Paris-Roubaix") instead of prefixing "Stage",
   *  and the x-axis reads "Race" rather than "Stage". */
  stagesAreRaces: boolean;
}

export const RACES: Record<RaceId, RaceConfig> = {
  tour: {
    name: "Tour de France",
    chart: { gc: "var(--accent)", sprint: "#22c55e", kom: "#ef4444" },
    jersey: { gc: "#FFD400", sprint: "#3FA535", kom: { dots: "#E4002B" } },
    jerseyTooltips: {
      gc: "Yellow jersey — GC winner", sprint: "Green jersey — Sprint winner",
      kom: "Polka dot jersey — KOM winner", youth: "White jersey — Young rider winner",
    },
    warBands: [
      { start: 1914.5, end: 1918.5, label: "WWI" },
      { start: 1939.5, end: 1946.5, label: "WWII" },
    ],
    hasYouth: true,
    hasCumulativeGc: true,
    hasSprintKom: true,
    hasSeasonPoints: false,
    hasRaceHistory: false,
    hasAllYears: true,
    stagesAreRaces: false,
  },
  giro: {
    name: "Giro d'Italia",
    chart: { gc: "#E4007C", sprint: "#8B1FA1", kom: "#0083CA" },
    jersey: { gc: "#E4007C", sprint: "#8B1FA1", kom: { solid: "#0083CA" } },
    jerseyTooltips: {
      gc: "Pink jersey — GC winner", sprint: "Purple jersey — Sprint winner",
      kom: "Blue jersey — KOM winner", youth: "White jersey — Young rider winner",
    },
    warBands: [
      { start: 1914.5, end: 1918.5, label: "WWI" },
      { start: 1940.5, end: 1945.5, label: "WWII" },
    ],
    hasYouth: false,
    hasCumulativeGc: true,
    hasSprintKom: true,
    hasSeasonPoints: false,
    hasRaceHistory: false,
    hasAllYears: true,
    stagesAreRaces: false,
  },
  vuelta: {
    name: "Vuelta a España",
    chart: { gc: "#E30613", sprint: "#3FA535", kom: "#0057B8" },
    jersey: { gc: "#E30613", sprint: "#3FA535", kom: { dots: "#0057B8" } },
    jerseyTooltips: {
      gc: "Red jersey — GC winner", sprint: "Green jersey — Sprint winner",
      kom: "Polka dot jersey — KOM winner", youth: "White jersey — Young rider winner",
    },
    warBands: [
      { start: 1935.5, end: 1944.5, label: "Civil War / WWII" },
    ],
    hasYouth: false,
    hasCumulativeGc: true,
    hasSprintKom: true,
    hasSeasonPoints: false,
    hasRaceHistory: false,
    hasAllYears: true,
    stagesAreRaces: false,
  },
  // The one-day classics are an AGGREGATE, not a single race: an "edition" is
  // one season, and each "stage" is a separate monument/classic ordered by the
  // date it was actually run (which is what gets 2020's COVID-reshuffled
  // calendar right without a hardcoded order). In the DB these are 11
  // independent races with race_type='one_day'; the combining happens in
  // export_gc.py --race classics.
  classics: {
    name: "One-day Classics",
    // One neutral gray for all of them. Every race-identifying hue in this app
    // is already spoken for (Tour yellow, Giro pink, Vuelta red) as is every
    // classification color (green sprint, red/blue KOM), and colouring 11
    // races separately would need 11 more. Gray reads as "many races,
    // aggregated" and stays legible against the dark background.
    chart: { gc: "#9ca3af", sprint: "#9ca3af", kom: "#9ca3af" },
    jersey: { gc: "#9ca3af", sprint: "#9ca3af", kom: { solid: "#9ca3af" } },
    jerseyTooltips: {
      gc: "Classics win", sprint: "Classics win",
      kom: "Classics win", youth: "Classics win",
    },
    // No war bands: the classics series here starts in 1990.
    warBands: [],
    hasYouth: false,
    hasCumulativeGc: false,
    hasSprintKom: false,
    hasSeasonPoints: true,
    hasRaceHistory: true,
    hasAllYears: false,
    stagesAreRaces: true,
  },
  // The Life Time off-road races are an AGGREGATE on the same pattern as the
  // classics: an "edition" is a season, each "stage" is a separate race
  // ordered by the date it ran. In the DB they are six independent races with
  // race_type='gravel'; export_gravel.py combines them.
  //
  // Unlike the classics, a season here is not a fixed set. These races were
  // founded decades apart and only became a series in 2022, so 1994 holds one
  // race (Leadville), 2001 holds two, and 2026 holds six. That is a fact about
  // the sport, and the date ordering renders it without special-casing.
  gravel: {
    name: "Gravel & MTB",
    // Brown — dirt. Chosen the same way the classics' gray was: every
    // race-identifying hue in the app is spoken for (Tour yellow, Giro pink,
    // Vuelta red, classics gray) as is every classification colour, and these
    // six races need ONE shared identity rather than six more hues. Brown is
    // the surface they all share and stays legible on the dark background.
    chart: { gc: "#b4794a", sprint: "#b4794a", kom: "#b4794a" },
    jersey: { gc: "#b4794a", sprint: "#b4794a", kom: { solid: "#b4794a" } },
    jerseyTooltips: {
      gc: "Off-road win", sprint: "Off-road win",
      kom: "Off-road win", youth: "Off-road win",
    },
    // No war bands: the archive starts in 1994.
    warBands: [],
    hasYouth: false,
    hasCumulativeGc: false,
    hasSprintKom: false,
    // Unlike the classics: these races award no points anyone records across
    // the set, so there is no season standing to accumulate. See
    // export_gravel.py.
    hasSeasonPoints: false,
    hasRaceHistory: true,
    hasAllYears: false,
    stagesAreRaces: true,
  },
};

export const RACE_IDS = Object.keys(RACES) as RaceId[];
export const RACE_ABBR: Record<RaceId, string> = { tour: "Tour de France", giro: "Giro d'Italia", vuelta: "Vuelta a España", classics: "One-day Classics", gravel: "Gravel & MTB" };
export const RACE_SHORT_LABEL: Record<RaceId, string> = { tour: "Tour", giro: "Giro", vuelta: "Vuelta", classics: "Classics", gravel: "Gravel" };

export function isRaceId(s: string | undefined): s is RaceId {
  return s !== undefined && s in RACES;
}

export function emptyPerRace<T>(make: () => T): Record<RaceId, T> {
  return Object.fromEntries(RACE_IDS.map((r) => [r, make()])) as Record<RaceId, T>;
}

// Auto-discover per-year datasets for every race with one wildcard glob:
// ./data/<slug>/gc_by_stage_<year>.json → hashed asset URL.
const yearUrlModules = import.meta.glob<string>("./data/*/gc_by_stage_*.json", {
  query: "?url",
  import: "default",
  eager: true,
});
export const URLS_BY_RACE = emptyPerRace<Record<string, string>>(() => ({}));
for (const [path, url] of Object.entries(yearUrlModules)) {
  const match = path.match(/\.\/data\/([^/]+)\/gc_by_stage_(\d+)\.json$/);
  if (match && isRaceId(match[1])) URLS_BY_RACE[match[1]][match[2]] = url;
}

export function getYearsForRace(race: RaceId): string[] {
  return Object.keys(URLS_BY_RACE[race]).sort().reverse();
}

export interface RaceSummary { year: number; totalDistanceKm: number | null; totalElevationM: number | null; gcWinnerTimeSeconds: number | null; slowestFinisherTimeSeconds: number | null; }
// Small summary files, eagerly bundled — one glob picks up every race's file.
const summaryModules = import.meta.glob<RaceSummary[]>("./data/*/all_races_summary.json", {
  import: "default",
  eager: true,
});
export const ALL_RACES_BY_RACE = emptyPerRace<RaceSummary[]>(() => []);
for (const [path, summary] of Object.entries(summaryModules)) {
  const match = path.match(/\.\/data\/([^/]+)\/all_races_summary\.json$/);
  if (match && isRaceId(match[1])) ALL_RACES_BY_RACE[match[1]] = summary;
}
