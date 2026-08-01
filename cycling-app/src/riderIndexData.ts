// ─── Rider Index ─────────────────────────────────────────────────────────────
// Loads and caches the compact prebuilt riders_index.json per race (see
// pipeline/export_riders_index.py) — one small file instead of reading all
// 113 per-year datasets just to populate the Riders page. Lazy-loaded as its
// own chunk the first time the Riders view opens, so it never weighs down
// first paint (the default view is the stage chart).
import type { RaceId } from "./raceRegistry";
import { emptyPerRace, isRaceId } from "./raceRegistry";
import { state } from "./state";
import { fetchJson } from "./dataLoading";

export interface RiderEntry {
  id: string;
  name: string;
  firstName?: string;
  lastName?: string;
  nationality: string | null;
  youthWinYears: number[];
  years: Map<number, { finalRank: number; sprintRank: number; komRank: number; team: string | null }>;
  teams: Set<string>;
}

export const riderIndexByRace = emptyPerRace<Map<string, RiderEntry>>(() => new Map());
export const allTeamsSortedByRace = emptyPerRace<string[]>(() => []);
export const allNationalitiesSortedByRace = emptyPerRace<string[]>(() => []);

// Convenience accessors for the current race
export function riderIndex() { return riderIndexByRace[state.currentRace]; }
export function allTeamsSorted() { return allTeamsSortedByRace[state.currentRace]; }
export function allNationalitiesSorted() { return allNationalitiesSortedByRace[state.currentRace]; }

// URL-only glob (see raceRegistry's year-data comment for why we fetch
// instead of importing the JSON as a module).
const riderIndexUrlModules = import.meta.glob<string>("./data/*/riders_index.json", {
  query: "?url",
  import: "default",
  eager: true,
});
export const RIDERS_INDEX_URL = emptyPerRace<string>(() => "");
for (const [path, url] of Object.entries(riderIndexUrlModules)) {
  const match = path.match(/\.\/data\/([^/]+)\/riders_index\.json$/);
  if (match && isRaceId(match[1])) RIDERS_INDEX_URL[match[1]] = url;
}

// Compact prebuilt index: { teams: [names], riders: { slug: { n, c, y: { year: tuple } } } }
// Rider keys are slugs (id minus the "rider/" prefix, re-added on load) and
// teams are integer indexes into the shared string table (-1 = no team) —
// both cut the payload versus repeating the strings inline.
// Year tuple: [gcRank, teamIdx] when the rider had no sprint/KOM ranking that
// year (the common case), or [gcRank, teamIdx, sprintRank, komRank] with 0
// standing in for an absent rank. Normalized to 9999 sentinels on load.
type RawYearTuple =
  | [number, number]
  | [number, number, number, number];
type RawRiderIndex = {
  teams: string[];
  riders: Record<string, { n: string; fn?: string; ln?: string; c: string | null; yw?: number[]; y: Record<string, RawYearTuple> }>;
};

export const riderIndexBuilt = emptyPerRace<boolean>(() => false);

export async function ensureRiderIndexFor(race: RaceId): Promise<void> {
  if (riderIndexBuilt[race]) return;
  const raw = await fetchJson<RawRiderIndex>(RIDERS_INDEX_URL[race]);
  const teamTable = raw.teams;
  const index = riderIndexByRace[race];
  for (const [slug, rec] of Object.entries(raw.riders)) {
    const id = `rider/${slug}`;
    const years = new Map<number, { finalRank: number; sprintRank: number; komRank: number; team: string | null }>();
    const teams = new Set<string>();
    for (const [yearStr, [finalRank, teamIdx, sprintRank, komRank]] of Object.entries(rec.y)) {
      const team = teamIdx >= 0 ? teamTable[teamIdx] : null;
      years.set(parseInt(yearStr), {
        finalRank,
        sprintRank: sprintRank || 9999,
        komRank: komRank || 9999,
        team,
      });
      if (team) teams.add(team);
    }
    index.set(id, { id, name: rec.n, firstName: rec.fn, lastName: rec.ln, nationality: rec.c ?? null, youthWinYears: rec.yw ?? [], years, teams });
  }
  allTeamsSortedByRace[race] = [...teamTable].sort();
  allNationalitiesSortedByRace[race] = [...new Set(
    [...index.values()].map((r) => r.nationality).filter((n): n is string => !!n),
  )].sort();
  riderIndexBuilt[race] = true;
}

export async function ensureRiderIndex(): Promise<void> {
  return ensureRiderIndexFor(state.currentRace);
}
