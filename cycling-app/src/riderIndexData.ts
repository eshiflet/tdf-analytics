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

export interface ConstituentResult {
  /** Display name of the individual race, e.g. "Paris-Roubaix". */
  race: string;
  /** Finishing position in that race; 9999 for DNF/DNS. */
  rank: number;
  team: string | null;
}

export interface RiderEntry {
  id: string;
  name: string;
  firstName?: string;
  lastName?: string;
  nationality: string | null;
  youthWinYears: number[];
  years: Map<number, { finalRank: number; sprintRank: number; komRank: number; team: string | null }>;
  teams: Set<string>;
  /** Only present for aggregate races (the one-day classics), where a single
   *  season holds up to 11 independent results and `years` can only carry one.
   *  `years` still holds the rider's BEST finish that season, which is what
   *  the Riders grid sorts and filters on; this is the per-race breakdown the
   *  career chart plots.
   *
   *  Built on FIRST READ, not at load — see defineLazyConstituents(). Reading
   *  it is transparent; just don't reach for it in a loop over every rider. */
  constituents?: Map<number, ConstituentResult[]>;
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
/** Aggregate races only: one [raceIdx, rank] pair per constituent race the
 *  rider contested that season. raceIdx indexes the top-level `races` string
 *  table, the same trick `teams` uses. The team is NOT repeated here — it is
 *  already in that year's `y` tuple and is identical across the season. */
type RawConstituent = [number, number];
/** Aggregate races only: [teamIdx, raceIdx, rank, raceIdx, rank, ...] for one
 *  season. One map instead of the two (`y` + `m`) this replaced, which stored
 *  every year key twice and carried a finalRank that is min() of these ranks —
 *  derivable, so no longer stored. Measured on the 11,934-rider classics index:
 *  703 KB -> 547 KB gzipped, and 6.3ms FASTER end to end, because parsing
 *  156 KB less JSON saves more than the min() costs. */
type RawFlatYear = number[];
type RawRiderIndex = {
  teams: string[];
  /** Constituent-race name table; absent for the three Grand Tours. */
  races?: string[];
  riders: Record<string, {
    n: string; fn?: string; ln?: string; c: string | null; yw?: number[];
    /** Grand Tours. */
    y?: Record<string, RawYearTuple>;
    /** Aggregate races (classics, gravel) — replaces both `y` and `m`. */
    ym?: Record<string, RawFlatYear>;
  }>;
};

/** Attach `constituents` as a memoizing getter rather than building it up front.
 *
 *  The classics index carries a per-race breakdown for 11,934 riders, and
 *  turning all of them into objects cost ~380ms of the ~510ms that index took
 *  to load — for data only the career chart reads, one rider at a time.
 *
 *  The getter is NON-ENUMERABLE on purpose: mergedRidersForSelectedRaces()
 *  clones entries with a spread, and an enumerable getter would fire for every
 *  rider there and hand back exactly the eager cost this avoids. That merge
 *  copies this property's descriptor instead, so a cloned entry stays lazy and
 *  shares this memo rather than losing the property.
 */
function defineLazyConstituents(
  entry: RiderEntry,
  raw: Record<string, RawFlatYear>,
  raceTable: string[],
  years: RiderEntry["years"],
): void {
  let built: Map<number, ConstituentResult[]> | undefined;
  Object.defineProperty(entry, "constituents", {
    enumerable: false,
    configurable: true,
    get(): Map<number, ConstituentResult[]> {
      if (built) return built;
      built = new Map();
      for (const [yearStr, flat] of Object.entries(raw)) {
        const year = parseInt(yearStr);
        // The season's team, already resolved from flat[0] at load.
        const team = years.get(year)?.team ?? null;
        const out: ConstituentResult[] = [];
        // flat[0] is the team index; the rest are raceIdx/rank pairs.
        for (let i = 1; i < flat.length; i += 2) {
          out.push({ race: raceTable[flat[i]] ?? "—", rank: flat[i + 1] || 9999, team });
        }
        built.set(year, out);
      }
      return built;
    },
  });
}

export const riderIndexBuilt = emptyPerRace<boolean>(() => false);

// `riderIndexBuilt` only flips once the fetch AND the build have finished, so
// it cannot deduplicate concurrent callers — a second caller arriving while
// the first was still awaiting passed the guard and started its own download.
// drawRidersPage and drawRiderDetail both call this for every race, so opening
// a rider straight from a link did exactly that: two 2.8 MB classics fetches
// and two ~500ms rebuilds racing to populate the same Map. Sharing the
// in-flight promise collapses them into one; clearing it on settle means a
// failed load can still be retried.
const inFlightRiderIndex = emptyPerRace<Promise<void> | null>(() => null);

export function ensureRiderIndexFor(race: RaceId): Promise<void> {
  if (riderIndexBuilt[race]) return Promise.resolve();
  const pending = inFlightRiderIndex[race];
  if (pending) return pending;
  const load = buildRiderIndexFor(race).finally(() => { inFlightRiderIndex[race] = null; });
  inFlightRiderIndex[race] = load;
  return load;
}

async function buildRiderIndexFor(race: RaceId): Promise<void> {
  const raw = await fetchJson<RawRiderIndex>(RIDERS_INDEX_URL[race]);
  const teamTable = raw.teams;
  const raceTable = raw.races ?? [];
  const index = riderIndexByRace[race];
  for (const [slug, rec] of Object.entries(raw.riders)) {
    const id = `rider/${slug}`;
    const years = new Map<number, { finalRank: number; sprintRank: number; komRank: number; team: string | null }>();
    const teams = new Set<string>();
    // Two shapes: the Grand Tours' `y` tuples, and the aggregate races' flat
    // `ym` arrays, whose finalRank is derived rather than stored.
    for (const [yearStr, flat] of Object.entries(rec.ym ?? {})) {
      const team = flat[0] >= 0 ? teamTable[flat[0]] : null;
      let best = 9999;
      for (let i = 2; i < flat.length; i += 2) {
        const rank = flat[i] || 9999;
        if (rank < best) best = rank;
      }
      years.set(parseInt(yearStr), {
        finalRank: best, sprintRank: 9999, komRank: 9999, team,
      });
      if (team) teams.add(team);
    }
    for (const [yearStr, [finalRank, teamIdx, sprintRank, komRank]] of Object.entries(rec.y ?? {})) {
      const team = teamIdx >= 0 ? teamTable[teamIdx] : null;
      years.set(parseInt(yearStr), {
        finalRank,
        sprintRank: sprintRank || 9999,
        komRank: komRank || 9999,
        team,
      });
      if (team) teams.add(team);
    }

    const entry: RiderEntry = { id, name: rec.n, firstName: rec.fn, lastName: rec.ln, nationality: rec.c ?? null, youthWinYears: rec.yw ?? [], years, teams };
    if (rec.ym) defineLazyConstituents(entry, rec.ym, raceTable, years);
    index.set(id, entry);
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
