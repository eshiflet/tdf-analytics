// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { createLatestGuard, escapeHtml } from "../utils";

describe("escapeHtml", () => {
  it("escapes the five characters that matter in an HTML template", () => {
    expect(escapeHtml(`<b>"A" & 'B'</b>`)).toBe("&lt;b&gt;&quot;A&quot; &amp; &#39;B&#39;&lt;/b&gt;");
  });

  it("escapes & first-class, so an entity-like name is shown literally", () => {
    expect(escapeHtml("AT&amp;T")).toBe("AT&amp;amp;T");
  });

  it("leaves ordinary names alone, accents included", () => {
    expect(escapeHtml("Pogačar Tadej")).toBe("Pogačar Tadej");
  });

  it("stringifies non-strings, so an Error can be passed straight in", () => {
    expect(escapeHtml(new Error("<x>"))).toBe("Error: &lt;x&gt;");
    expect(escapeHtml(0)).toBe("0");
  });

  it("neutralises a script payload when set as innerHTML", () => {
    const el = document.createElement("div");
    el.innerHTML = `<i>${escapeHtml("<img src=x onerror=alert(1)>")}</i>`;
    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toBe("<img src=x onerror=alert(1)>");
  });
});

describe("createLatestGuard", () => {
  it("only the most recent begin() is current", () => {
    const g = createLatestGuard();
    const a = g.begin();
    expect(g.isCurrent(a)).toBe(true);
    const b = g.begin();
    expect(g.isCurrent(a)).toBe(false);
    expect(g.isCurrent(b)).toBe(true);
  });

  // The bug this exists for: year A is requested, then year B; B's response
  // arrives first and A's arrives last. Unguarded, A (the OLD request) wins.
  it("keeps the newer result when responses arrive out of order", async () => {
    const g = createLatestGuard();
    let shown = "";
    const load = async (name: string, delayMs: number) => {
      const token = g.begin();
      await new Promise((r) => setTimeout(r, delayMs));
      if (!g.isCurrent(token)) return;
      shown = name;
    };
    await Promise.all([load("older (slow)", 20), load("newer (fast)", 1)]);
    expect(shown).toBe("newer (fast)");
  });

  it("without the guard the slow, older response wins (the original defect)", async () => {
    let shown = "";
    const load = async (name: string, delayMs: number) => {
      await new Promise((r) => setTimeout(r, delayMs));
      shown = name;
    };
    await Promise.all([load("older (slow)", 20), load("newer (fast)", 1)]);
    expect(shown).toBe("older (slow)");
  });
});
