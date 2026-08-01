// Pure fetch + cache for per-year GC datasets. Does NOT trigger any redraws
// or touch view state — that orchestration (recomputing rankings, redrawing
// the active view) lives in main.ts's loadDataset(), which calls getDataset()
// from here.
import type { GcDataset } from "./types";
import { URLS_BY_RACE } from "./raceRegistry";
import { state } from "./state";

// Bounded LRU of parsed per-year datasets, so a long session that hops between
// many years never grows memory without limit. Re-visiting an evicted year
// re-fetches from the browser's HTTP cache (no network), only re-parsing.
const DATASET_CACHE = new Map<string, GcDataset>();
const DATASET_CACHE_MAX = 6;

export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export async function getDataset(year: string): Promise<GcDataset> {
  const cacheKey = `${state.currentRace}:${year}`;
  const cached = DATASET_CACHE.get(cacheKey);
  if (cached) {
    DATASET_CACHE.delete(cacheKey);
    DATASET_CACHE.set(cacheKey, cached);
    return cached;
  }
  const url = URLS_BY_RACE[state.currentRace][year];
  const ds = await fetchJson<GcDataset>(url);
  DATASET_CACHE.set(cacheKey, ds);
  if (DATASET_CACHE.size > DATASET_CACHE_MAX) {
    const oldest = DATASET_CACHE.keys().next().value;
    if (oldest !== undefined) DATASET_CACHE.delete(oldest);
  }
  return ds;
}
