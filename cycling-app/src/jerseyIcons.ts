// ─── Jersey Icons ────────────────────────────────────────────────────────────
// One icon per classification a rider has ever won at least once (GC winners
// across multiple years — e.g. Greg LeMond's 3 yellow jerseys — still get a
// single icon, since riderJerseysWon() only checks "won at least once").
// Hand-drawn generic jersey silhouette (not official ASO artwork) reused for
// all four, colored/patterned per classification.
import type { RaceId } from "./raceRegistry";
import { RACES, RACE_ABBR } from "./raceRegistry";
import { raceConfig } from "./state";
import { tooltipEl } from "./dom";
import { positionTooltip } from "./tooltip";
import type { RiderEntry } from "./riderIndexData";
import { riderIndexByRace } from "./riderIndexData";

const JERSEY_PATH = "M9,2 L4,2 L1,6 L5,9 L5,22 L19,22 L19,9 L23,6 L20,2 L15,2 Q12,5 9,2 Z";

export function jerseySvg(fill: string, stroke = "#00000055", letter?: string): string {
  const label = letter
    ? `<text x="12" y="16" text-anchor="middle" font-size="11" font-weight="700" font-family="Helvetica, Arial, sans-serif" style="fill:#000; user-select:none">${letter}</text>`
    : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="1.3em" height="1.3em"><path d="${JERSEY_PATH}" fill="${fill}" stroke="${stroke}" stroke-width="1" stroke-linejoin="round"/>${label}</svg>`;
}

let komJerseyClipCounter = 0;
/** White jersey + polka dots (red for TDF, blue for Vuelta), clipped to the jersey silhouette. */
export function komJerseySvg(dotColor = "#E4002B"): string {
  const clipId = `komclip${komJerseyClipCounter++}`;
  const dots = [6, 10, 14, 18]
    .flatMap((y, row) => {
      const offset = row % 2 ? 2 : 0;
      return [5 + offset, 10 + offset, 15 + offset, 20 + offset].map(
        (x) => `<circle cx="${x}" cy="${y}" r="1.3" fill="${dotColor}"/>`,
      );
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="1.3em" height="1.3em"><defs><clipPath id="${clipId}"><path d="${JERSEY_PATH}"/></clipPath></defs><path d="${JERSEY_PATH}" fill="#FFFFFF" stroke="#888888" stroke-width="1" stroke-linejoin="round"/><g clip-path="url(#${clipId})">${dots}</g></svg>`;
}

export const JERSEY_LABELS = { gc: "GC winner", sprint: "Sprint winner", kom: "KOM winner", youth: "Young rider winner" } as const;
export const JERSEY_SIMPLE_LABEL: Record<JerseyCategory, string> = { gc: "GC", sprint: "Sprint", kom: "KOM", youth: "Youth" };
export function jerseyTooltipLabel(category: JerseyCategory): string {
  return raceConfig().jerseyTooltips[category];
}

// Computed once per race, not per call: the riders grid asks for this once per
// rider PER RACE (14,260 x 4 per rebuild), and a fresh filtered array each time
// was the bulk of that loop's cost. The registry is static, so one array per
// race is safe to share — treat the result as read-only.
const jerseyCategoryCache = new Map<RaceId, readonly JerseyCategory[]>();

/** The classifications a race actually contests — the classics award no
 *  sprint/KOM jersey (and no youth one), so those icons are omitted entirely
 *  rather than rendered as jerseys nobody can win. */
export function jerseyCategoriesForRace(race: RaceId): readonly JerseyCategory[] {
  const cached = jerseyCategoryCache.get(race);
  if (cached) return cached;
  const config = RACES[race];
  const categories = (Object.keys(JERSEY_LABELS) as JerseyCategory[]).filter((category) => {
    if (category === "youth") return config.hasYouth;
    if (category === "sprint" || category === "kom") return config.hasSprintKom;
    return true;
  });
  jerseyCategoryCache.set(race, categories);
  return categories;
}

/** "<Race> - <Classification>" title for the riders-grid icons and the jersey
 *  filter buttons. A one-day race has no running general classification, so
 *  its lone jersey belongs to the winner on the day, not a "GC". */
export function jerseyIconTitle(category: JerseyCategory, race: RaceId): string {
  const label = category === "gc" && !RACES[race].hasCumulativeGc
    ? "Winner"
    : JERSEY_SIMPLE_LABEL[category];
  return `${RACE_ABBR[race]} - ${label}`;
}

// Riders who had a result taken away for doping. This drives the note beside
// the rider's name on the detail page; DOPING_GC_NOTES below adds which jersey
// for the GC years where the revoked result was the overall win.
//
// Membership is a documented revocation, not a suspension and not an
// inference: a rider belongs here only when a governing body actually removed
// a result. Duplicate ranks in the data are a hint that one happened, never
// evidence on their own — the same duplicates also come from PCS artefacts —
// so nothing is added here without the case behind it.
export const DOPING_REVOKED_NOTE = "Some race results revoked for doping";
export const RIDERS_WITH_REVOKED_RESULTS = new Set<string>([
  "rider/lance-armstrong",   // all seven Tour wins, 1999-2005
  "rider/floyd-landis",      // 2006 Tour
  "rider/alberto-contador",  // 2010 Tour and 2011 Giro
  "rider/bernhard-kohl",     // 2008 Tour KOM, re-awarded to Carlos Sastre
]);

// Doping notes shown next to GC jersey years on the rider detail page. Keys
// are a subset of RIDERS_WITH_REVOKED_RESULTS — a rider whose revoked result
// wasn't a GC win (Kohl's KOM) has no entry here.
export const DOPING_GC_NOTES: Record<string, string> = {
  "rider/lance-armstrong": "Stripped of yellow jersey due to doping",
  "rider/floyd-landis": "Stripped of yellow jersey due to doping",
  "rider/alberto-contador": "Stripped of 2010 yellow jersey due to doping",
};
export type JerseyCategory = keyof typeof JERSEY_LABELS;

// A rider's win years never change once the index is loaded, but the Riders
// grid asks for them once per rider PER RACE on every keystroke — 14,000
// riders x 4 races, each call allocating and sorting four arrays. Keyed on the
// entry object so it dies with the index it came from.
const jerseyYearsCache = new WeakMap<RiderEntry, Record<JerseyCategory, number[]>>();

/** Every year this rider won each classification (GC/sprint/KOM derived from
 *  per-year rank data; youth from the pipeline's classification_standings
 *  lookup, since that classification isn't in the per-year JSON at all). */
export function jerseyYearsWon(entry: RiderEntry): Record<JerseyCategory, number[]> {
  const cached = jerseyYearsCache.get(entry);
  if (cached) return cached;
  const computed = computeJerseyYearsWon(entry);
  jerseyYearsCache.set(entry, computed);
  return computed;
}

function computeJerseyYearsWon(entry: RiderEntry): Record<JerseyCategory, number[]> {
  const gc: number[] = [], sprint: number[] = [], kom: number[] = [];
  for (const [year, y] of entry.years) {
    if (y.finalRank === 1) gc.push(year);
    if (y.sprintRank === 1) sprint.push(year);
    if (y.komRank === 1) kom.push(year);
  }
  const sortAsc = (a: number, b: number) => a - b;
  return {
    gc: gc.sort(sortAsc),
    sprint: sprint.sort(sortAsc),
    kom: kom.sort(sortAsc),
    youth: [...entry.youthWinYears].sort(sortAsc),
  };
}

export function jerseyIconSvg(category: JerseyCategory): string {
  const jersey = raceConfig().jersey;
  if (category === "gc") return jerseySvg(jersey.gc);
  if (category === "sprint") return jerseySvg(jersey.sprint);
  if (category === "kom") {
    return "dots" in jersey.kom ? komJerseySvg(jersey.kom.dots) : jerseySvg(jersey.kom.solid);
  }
  return jerseySvg("#FFFFFF", "#888888");
}

export function jerseyIconSvgForRace(category: JerseyCategory, race: RaceId): string {
  const jersey = RACES[race].jersey;
  if (category === "gc") return jerseySvg(jersey.gc);
  if (category === "sprint") {
    // Tour and Vuelta both use green for the sprint jersey — letter them so
    // they're distinguishable when shown side by side (rider grid, filters).
    const letter = race === "tour" ? "T" : race === "vuelta" ? "V" : undefined;
    return jerseySvg(jersey.sprint, undefined, letter);
  }
  if (category === "kom") {
    return "dots" in jersey.kom ? komJerseySvg(jersey.kom.dots) : jerseySvg(jersey.kom.solid);
  }
  return jerseySvg("#FFFFFF", "#888888");
}

/** Small jersey <span> icons for every classification a rider has won. */
export function jerseyIconsEl(entry: RiderEntry): HTMLSpanElement[] {
  const years = jerseyYearsWon(entry);
  return (Object.keys(JERSEY_LABELS) as JerseyCategory[])
    .filter((category) => years[category].length > 0)
    .map((category) => {
      const el = document.createElement("span");
      el.className = "jersey-icon";
      el.title = JERSEY_LABELS[category];
      el.innerHTML = jerseyIconSvg(category);
      return el;
    });
}

/** Jersey icons for the riders grid, one per race that the rider won a
 *  classification in. Each jersey is colored for its specific race.
 *  `years`, when non-empty, restricts the icons to wins from those years, so
 *  the icons agree with the year filter instead of contradicting it — a 2019
 *  yellow-jersey winner shows no jersey while the grid is filtered to 2026. */
export function jerseyIconsElMultiRace(
  entry: RiderEntry,
  races: RaceId[],
  years: ReadonlySet<number> = new Set(),
): HTMLSpanElement[] {
  const out: HTMLSpanElement[] = [];
  for (const race of races) {
    const raceEntry = riderIndexByRace[race].get(entry.id);
    if (!raceEntry) continue;
    const won = jerseyYearsWon(raceEntry);
    for (const category of jerseyCategoriesForRace(race)) {
      if (won[category].length === 0) continue;
      if (years.size > 0 && !won[category].some((y) => years.has(y))) continue;
      const el = document.createElement("span");
      el.className = "jersey-icon";
      el.title = jerseyIconTitle(category, race);
      el.innerHTML = jerseyIconSvgForRace(category, race);
      out.push(el);
    }
  }
  return out;
}

/** Jersey icons + a "(year, year, ...)" label after each — rider detail page
 *  only; the Riders grid uses the plain icons from jerseyIconsEl(). */
export function jerseyIconsWithYearsEl(entry: RiderEntry): HTMLSpanElement[] {
  const years = jerseyYearsWon(entry);
  const out: HTMLSpanElement[] = [];
  for (const category of Object.keys(JERSEY_LABELS) as JerseyCategory[]) {
    if (years[category].length === 0) continue;
    const icon = document.createElement("span");
    icon.className = "jersey-icon";
    icon.innerHTML = jerseyIconSvg(category);
    icon.addEventListener("mouseenter", (e) => {
      tooltipEl.innerHTML = `<div class="t-name">${jerseyTooltipLabel(category)}</div>`;
      positionTooltip(e as MouseEvent);
    });
    icon.addEventListener("mouseleave", () => { tooltipEl.hidden = true; });
    out.push(icon);
    const yearsEl = document.createElement("span");
    yearsEl.className = "jersey-years";
    yearsEl.textContent = `(${years[category].join(", ")})`;
    out.push(yearsEl);
    if (category === "gc" && DOPING_GC_NOTES[entry.id]) {
      const noteEl = document.createElement("span");
      noteEl.className = "jersey-stripped-note";
      noteEl.textContent = DOPING_GC_NOTES[entry.id];
      out.push(noteEl);
    }
  }
  return out;
}
