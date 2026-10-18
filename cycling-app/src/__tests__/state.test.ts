import { beforeEach, describe, expect, it, vi } from "vitest";

// state.ts is a module-level singleton, so each test gets a fresh copy.
async function load() {
  vi.resetModules();
  return await import("../state");
}

describe("state accessors", () => {
  let m: Awaited<ReturnType<typeof load>>;
  beforeEach(async () => { m = await load(); });

  it("start empty, and say which field was read too early", () => {
    expect(m.state.dataset).toBeUndefined();
    expect(() => m.dataset()).toThrow(/state\.dataset read before it was loaded/);
    expect(() => m.colorScale()).toThrow(/colorScale/);
    expect(() => m.xScale()).toThrow(/xScale/);
    expect(() => m.yScale()).toThrow(/yScale/);
  });

  it("return the value once it is set", () => {
    const ds = { riders: [], stages: [] } as never;
    m.state.dataset = ds;
    expect(m.dataset()).toBe(ds);
  });

  it("start on the newest tour year", async () => {
    const { getYearsForRace } = await import("../raceRegistry");
    expect(m.state.currentRace).toBe("tour");
    expect(m.state.currentYear).toBe(getYearsForRace("tour")[0]);
  });
});
