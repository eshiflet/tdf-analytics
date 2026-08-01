// ─── Race registry ───────────────────────────────────────────────────────────
// Single source of truth for per-race identity, colors, and capabilities.
// Adding a race = add an entry here + drop its data files in ./data/<slug>/
// (gc_by_stage_*.json, all_races_summary.json, riders_index.json) — the
// wildcard globs below pick them up automatically. The slug is used in the
// data path, the race dropdown, and the URL hash.

export type RaceId = "tour" | "giro" | "vuelta";
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
  },
};

export const RACE_IDS = Object.keys(RACES) as RaceId[];
export const RACE_ABBR: Record<RaceId, string> = { tour: "Tour de France", giro: "Giro d'Italia", vuelta: "Vuelta a España" };
export const RACE_SHORT_LABEL: Record<RaceId, string> = { tour: "Tour", giro: "Giro", vuelta: "Vuelta" };

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
