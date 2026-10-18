import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The module keeps its caches at module scope, so every test gets a fresh copy.
async function load() {
  vi.resetModules();
  return await import("../riderIndexData");
}

// Invented riders only: a real name here would expire when the data changes.
const GT_INDEX = {
  teams: ["Team Alpha", "Team Beta"],
  xr: ["classics", "someFutureRace"],
  riders: {
    "ann-example": {
      fn: "Ann", ln: "Example", c: "France", yw: [1999], dq: ["2001"],
      // [gcRank, teamIdx] and [gcRank, teamIdx, sprint, kom]; 0 = absent rank.
      y: { "2000": [3, 0], "2001": [1, 1, 0, 5], "2002": [9999, -1] },
      x: 0b11,
    },
    "bob-sample": { n: "Odd Ordering", c: null, y: { "2000": [10, 1] } },
  },
};

const CLASSICS_INDEX = {
  teams: ["Team Alpha"],
  races: ["Race One", "Race Two"],
  riders: {
    // ym: [teamIdx, raceIdx, rank, raceIdx, rank, ...]; rank 0 = no finish.
    "cy-test": { fn: "Cy", ln: "Test", c: "Italy", ym: { "2010": [0, 0, 7, 1, 2], "2011": [-1, 1, 0] } },
  },
};

function serve(byRace: Record<string, unknown>) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    const body = byRace[Object.keys(byRace).find((k) => url.includes(k)) ?? ""];
    if (body === undefined) return { ok: false, status: 404, text: async () => "" };
    return { ok: true, status: 200, text: async () => JSON.stringify(body) };
  }));
  return calls;
}

beforeEach(() => { vi.unstubAllGlobals(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("rider index build", () => {
  it("derives per-year ranks, teams and sentinels from Grand Tour tuples", async () => {
    const m = await load();
    const urls = m.RIDERS_INDEX_URL;
    serve({ [urls.tour]: GT_INDEX });
    await m.ensureRiderIndexFor("tour");

    const ann = m.riderIndexByRace.tour.get("rider/ann-example")!;
    expect(ann.name).toBe("Example Ann");               // rebuilt as ln + " " + fn
    expect(ann.years.get(2000)).toEqual({ finalRank: 3, sprintRank: 9999, komRank: 9999, team: "Team Alpha" });
    expect(ann.years.get(2001)).toEqual({ finalRank: 1, sprintRank: 9999, komRank: 5, team: "Team Beta" });
    expect(ann.years.get(2002)!.team).toBeNull();        // -1 means no team
    expect([...ann.teams].sort()).toEqual(["Team Alpha", "Team Beta"]);
    expect(ann.youthWinYears).toEqual([1999]);
    expect(ann.dqYears).toEqual([2001]);                 // coerced to numbers

    const bob = m.riderIndexByRace.tour.get("rider/bob-sample")!;
    expect(bob.name).toBe("Odd Ordering");               // explicit `n` wins
    expect(bob.nationality).toBeNull();
  });

  it("builds sorted team and nationality lists", async () => {
    const m = await load();
    serve({ [m.RIDERS_INDEX_URL.tour]: GT_INDEX });
    await m.ensureRiderIndexFor("tour");
    expect(m.allTeamsSortedByRace.tour).toEqual(["Team Alpha", "Team Beta"]);
    expect(m.allNationalitiesSortedByRace.tour).toEqual(["France"]);
    expect(m.riderIndexBuilt.tour).toBe(true);
    expect(m.riderIndexBuilt.giro).toBe(false);
  });

  it("decodes the cross-race bitmask and ignores unknown slugs", async () => {
    const m = await load();
    serve({ [m.RIDERS_INDEX_URL.tour]: GT_INDEX });
    await m.ensureRiderIndexFor("tour");
    // bit 0 = classics, bit 1 = a slug this build has never heard of.
    expect(m.riderIndexByRace.tour.get("rider/ann-example")!.alsoIn).toEqual(["classics"]);
    expect(m.riderIndexByRace.tour.get("rider/bob-sample")!.alsoIn).toEqual([]);
  });

  it("takes an aggregate season's finalRank as the best finish and ignores DNFs", async () => {
    const m = await load();
    serve({ [m.RIDERS_INDEX_URL.classics]: CLASSICS_INDEX });
    await m.ensureRiderIndexFor("classics");
    const cy = m.riderIndexByRace.classics.get("rider/cy-test")!;
    expect(cy.years.get(2010)!.finalRank).toBe(2);
    expect(cy.years.get(2010)!.team).toBe("Team Alpha");
    expect(cy.years.get(2011)!.finalRank).toBe(9999);    // only a non-finish
    expect(cy.years.get(2011)!.team).toBeNull();
  });

  it("builds constituents lazily, keeps them off enumeration, and memoizes", async () => {
    const m = await load();
    serve({ [m.RIDERS_INDEX_URL.classics]: CLASSICS_INDEX });
    await m.ensureRiderIndexFor("classics");
    const cy = m.riderIndexByRace.classics.get("rider/cy-test")!;

    // A spread must not fire the getter: that is the whole point of laziness.
    expect(Object.keys({ ...cy })).not.toContain("constituents");

    const c = cy.constituents!;
    expect(c.get(2010)).toEqual([
      { race: "Race One", rank: 7, team: "Team Alpha" },
      { race: "Race Two", rank: 2, team: "Team Alpha" },
    ]);
    expect(c.get(2011)![0].rank).toBe(9999);
    expect(cy.constituents).toBe(c);
  });

  it("omits constituents for Grand Tours", async () => {
    const m = await load();
    serve({ [m.RIDERS_INDEX_URL.tour]: GT_INDEX });
    await m.ensureRiderIndexFor("tour");
    expect(m.riderIndexByRace.tour.get("rider/ann-example")!.constituents).toBeUndefined();
  });
});

describe("loading", () => {
  it("shares one download between concurrent callers", async () => {
    const m = await load();
    const calls = serve({ [m.RIDERS_INDEX_URL.tour]: GT_INDEX });
    await Promise.all([m.ensureRiderIndexFor("tour"), m.ensureRiderIndexFor("tour")]);
    expect(calls).toHaveLength(1);
    await m.ensureRiderIndexFor("tour");                 // already built
    expect(calls).toHaveLength(1);
  });

  it("rejects on a failed fetch and can be retried", async () => {
    const m = await load();
    serve({});
    await expect(m.ensureRiderIndexFor("tour")).rejects.toThrow(/HTTP 404/);
    expect(m.riderIndexBuilt.tour).toBe(false);
    serve({ [m.RIDERS_INDEX_URL.tour]: GT_INDEX });
    await m.ensureRiderIndexFor("tour");
    expect(m.riderIndexBuilt.tour).toBe(true);
  });

  it("builds queued indexes smallest first", async () => {
    const m = await load();
    const order: string[] = [];
    const big = { ...GT_INDEX, riders: { ...GT_INDEX.riders, ...Object.fromEntries(
      Array.from({ length: 200 }, (_, i) => [`pad-${i}`, { fn: "P", ln: `${i}`, c: "X", y: { "2000": [1, 0] } }])) } };
    serve({ [m.RIDERS_INDEX_URL.tour]: big, [m.RIDERS_INDEX_URL.giro]: GT_INDEX });
    await Promise.all([
      m.ensureRiderIndexFor("tour").then(() => order.push("tour")),
      m.ensureRiderIndexFor("giro").then(() => order.push("giro")),
    ]);
    expect(order).toEqual(["giro", "tour"]);
  });
});

describe("crossRaceFor", () => {
  it("returns null until some index mentioning the rider is built", async () => {
    const m = await load();
    expect(m.crossRaceFor("rider/ann-example")).toBeNull();
    serve({ [m.RIDERS_INDEX_URL.tour]: GT_INDEX });
    await m.ensureRiderIndexFor("tour");
    expect(m.crossRaceFor("rider/ann-example")).toEqual(["tour", "classics"]);
    expect(m.crossRaceFor("rider/bob-sample")).toEqual(["tour"]);
    expect(m.crossRaceFor("rider/nobody")).toBeNull();
  });
});
