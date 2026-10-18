import { describe, expect, it } from "vitest";
import {
  RACES, RACE_IDS, RACE_ABBR, RACE_SHORT_LABEL, URLS_BY_RACE,
  emptyPerRace, getYearsForRace, isRaceId,
} from "../raceRegistry";

describe("race registry", () => {
  it("has a label for every registered race", () => {
    for (const id of RACE_IDS) {
      expect(RACE_ABBR[id], id).toBeTruthy();
      expect(RACE_SHORT_LABEL[id], id).toBeTruthy();
    }
  });

  it("isRaceId accepts registered slugs only", () => {
    for (const id of RACE_IDS) expect(isRaceId(id)).toBe(true);
    expect(isRaceId(undefined)).toBe(false);
    expect(isRaceId("")).toBe(false);
    expect(isRaceId("paris-roubaix")).toBe(false);
    // `in` would say yes to inherited keys; the guard must not.
    expect(isRaceId("toString")).toBe(false);
  });

  it("emptyPerRace gives every race its own fresh value", () => {
    const m = emptyPerRace<string[]>(() => []);
    expect(Object.keys(m).sort()).toEqual([...RACE_IDS].sort());
    m.tour.push("x");
    expect(m.giro).toEqual([]);
  });

  it("keeps the capability flags consistent with each race's shape", () => {
    for (const [id, r] of Object.entries(RACES)) {
      // An aggregate season has no running total, so these travel together.
      if (r.stagesAreRaces) {
        expect(r.hasCumulativeGc, id).toBe(false);
        expect(r.hasSprintKom, id).toBe(false);
        expect(r.hasAllYears, id).toBe(false);
        expect(r.hasRaceHistory, id).toBe(true);
      } else {
        expect(r.hasCumulativeGc, id).toBe(true);
        expect(r.hasAllYears, id).toBe(true);
        expect(r.hasSeasonPoints, id).toBe(false);
      }
    }
  });

  it("war bands are ordered, non-overlapping half-year ranges", () => {
    for (const [id, r] of Object.entries(RACES)) {
      let prevEnd = -Infinity;
      for (const b of r.warBands) {
        expect(b.end, id).toBeGreaterThan(b.start);
        expect(b.start, id).toBeGreaterThan(prevEnd);
        expect(b.start % 1, id).toBe(0.5);
        prevEnd = b.end;
      }
    }
  });
});

describe("year discovery", () => {
  it("finds data files for every race and lists years newest first", () => {
    for (const id of RACE_IDS) {
      const years = getYearsForRace(id);
      expect(years.length, id).toBeGreaterThan(0);
      expect([...years].sort().reverse(), id).toEqual(years);
      for (const y of years) expect(URLS_BY_RACE[id][y], `${id} ${y}`).toBeTruthy();
    }
  });

  it("covers the editions the archive claims", () => {
    expect(getYearsForRace("tour")).toContain("1903");
    expect(getYearsForRace("tour")).toContain("2026");
    expect(getYearsForRace("classics")[0]).toBe("2026");
  });
});
