// Which riders the Riders grid shows: the selected race sets, merged per rider,
// then narrowed by search, year, team, nation, jersey and annulment filters.
// Split out of riders.ts so the filtering has no DOM in it.
import type { RaceId } from "../raceRegistry";
import { RACE_IDS } from "../raceRegistry";
import { state } from "../state";
import { compareNames, displayName, foldForSearch, searchHaystack } from "../riderDisplay";
import type { RiderEntry } from "../riderIndexData";
import { riderIndexByRace, riderIndexBuilt } from "../riderIndexData";
import type { JerseyCategory } from "../jerseyIcons";
import { jerseyYearsWon } from "../jerseyIcons";

export function selectedRacesForRiders(): RaceId[] {
  return state.ridersFilterRaces.size === 0 ? [...RACE_IDS] : RACE_IDS.filter((r) => state.ridersFilterRaces.has(r));
}

// Merging clones every rider entry (new Map/Set per rider) across all selected
// races, which is wasted work when only the search text or a non-race filter
// changed. Cache the merge, keyed on the selected race set.
//
// INCREMENTAL, because the page no longer waits for every index before drawing.
// The cache remembers which races have been FOLDED IN, not just which were
// selected: drawRidersPage draws as soon as the current race's index is ready
// and folds the rest in when they land, and a cache keyed on the selection
// alone cannot tell those two moments apart — it would hand the second render
// the first render's riders and the late races would never appear.
//
// Folding late arrivals into the existing clones rather than rebuilding from
// scratch is what makes drawing early cheap. Re-merging all 17,736 riders a
// second time cost more than the early draw saved (measured: full grid ready
// 1,571 ms -> 2,511 ms); folding in only the races not yet merged costs the
// late races and nothing else.
let mergedRidersCache: {
  racesKey: string;
  /** Races already merged into `byId`. A selected race whose index was still
   *  loading is simply absent, and gets folded in on a later call. */
  folded: Set<RaceId>;
  byId: Map<string, RiderEntry>;
  entries: RiderEntry[];
} | null = null;

export function mergedRidersForSelectedRaces(): RiderEntry[] {
  const races = selectedRacesForRiders();
  const racesKey = races.join(",");
  if (!mergedRidersCache || mergedRidersCache.racesKey !== racesKey) {
    mergedRidersCache = { racesKey, folded: new Set(), byId: new Map(), entries: [] };
  }
  const cache = mergedRidersCache;
  // A race that has not finished building contributes nothing yet — and must
  // not be marked folded, or it would never be merged at all.
  const toFold = races.filter((r) => riderIndexBuilt[r] && !cache.folded.has(r));
  if (toFold.length === 0) return cache.entries;

  for (const race of toFold) {
    for (const [id, entry] of riderIndexByRace[race]) {
      const existing = cache.byId.get(id);
      if (existing) {
        for (const [year, yearData] of entry.years) {
          if (!existing.years.has(year)) existing.years.set(year, yearData);
        }
        for (const team of entry.teams) existing.teams.add(team);
      } else {
        const clone: RiderEntry = { ...entry, years: new Map(entry.years), teams: new Set(entry.teams) };
        // `constituents` is a non-enumerable lazy getter, so the spread above
        // skips it (which is the point — spreading 11,934 classics riders must
        // not build them all). Carry the descriptor across so the clone keeps
        // the property, still lazy and sharing the original's memo.
        const lazyConstituents = Object.getOwnPropertyDescriptor(entry, "constituents");
        if (lazyConstituents) Object.defineProperty(clone, "constituents", lazyConstituents);
        cache.byId.set(id, clone);
      }
    }
    cache.folded.add(race);
  }
  cache.entries = [...cache.byId.values()];
  return cache.entries;
}

/** Does a rider satisfy every active jersey toggle?
 *
 *  With no year selected the question is career-wide: won each selected
 *  classification at least once, ever. Selecting years makes it a question
 *  about those years specifically — the rider must have won ALL the selected
 *  jerseys within a SINGLE one of the selected years. So "yellow + 2021, 2023"
 *  is the two riders who actually wore yellow in one of those years, and
 *  "yellow + green" is one rider who took both in the same season rather than
 *  one in each of two years a decade apart. Applied across races, that same
 *  rule asks for a Giro/Tour double in one season. */
function matchesJerseyFilter(entry: RiderEntry, selectedRaces: RaceId[]): boolean {
  // Toggles belonging to a race the user has since deselected are ignored.
  const active = [...state.ridersFilterJerseys]
    .map((key) => key.split(":") as [RaceId, JerseyCategory])
    .filter(([raceId]) => selectedRaces.includes(raceId));
  if (active.length === 0) return true;
  const yearsWonPerToggle = active.map(([raceId, category]) => {
    const raceEntry = riderIndexByRace[raceId].get(entry.id);
    return raceEntry ? jerseyYearsWon(raceEntry)[category] : [];
  });
  if (state.ridersFilterYears.size === 0) {
    return yearsWonPerToggle.every((years) => years.length > 0);
  }
  return [...state.ridersFilterYears]
    .some((year) => yearsWonPerToggle.every((years) => years.includes(year)));
}

// Both name forms, accent-folded, in one haystack. Folding is ~14,000 string
// normalizations per keystroke otherwise; the names never change once loaded,
// so each entry pays for it once.
const searchKeyCache = new WeakMap<RiderEntry, string>();
function riderSearchKey(entry: RiderEntry): string {
  let key = searchKeyCache.get(entry);
  if (key === undefined) {
    key = searchHaystack(`${entry.name}\n${displayName(entry)}`);
    searchKeyCache.set(entry, key);
  }
  return key;
}

export function filteredRiders(): RiderEntry[] {
  const q = foldForSearch(state.ridersSearchQuery);
  const years = state.ridersFilterYears;
  const selectedRaces = selectedRacesForRiders();
  return mergedRidersForSelectedRaces()
    .filter((e) => {
      if (q && !riderSearchKey(e).includes(q)) return false;
      // Years are OR'd: "2021, 2023" means either year, not both.
      if (years.size > 0 && ![...years].some((y) => e.years.has(y))) return false;
      if (state.ridersFilterTeam && !e.teams.has(state.ridersFilterTeam)) return false;
      if (state.ridersFilterNationality && e.nationality !== state.ridersFilterNationality) return false;
      // ANDs with every other filter, so "United States" + this answers
      // "American riders who have been disqualified" directly.
      if (state.ridersFilterDq && e.dqYears.length === 0) return false;
      if (!matchesJerseyFilter(e, selectedRaces)) return false;
      return true;
    })
    .sort((a, b) => compareNames(a.lastName ?? a.name, b.lastName ?? b.name));
}
