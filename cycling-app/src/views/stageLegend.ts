// By Stage sidebar legend: one row per rider, sorted by final rank, with
// swatch toggle, hover highlight and link to the rider page.
import { state, dataset, colorScale } from "../state";
import { legendEl } from "../dom";
import { displayName, nationalityFlagEl } from "../riderDisplay";
import { effectiveFinalRank } from "./stageRankings";
import { updateLineClasses, setHighlight } from "./stageHighlight";

export function buildLegend() {
  if (!state.dataset) return; // initial fetch in flight; loadDataset() rebuilds
  legendEl.innerHTML = "";
  // Sort legend by effective final rank for the current metric
  const sorted = [...dataset().riders].sort((a, b) => effectiveFinalRank(a) - effectiveFinalRank(b));
  for (const rider of sorted) {
    const row = document.createElement("div");
    row.className = "legend-item";
    row.dataset.id = rider.id;

    const rank = document.createElement("span");
    rank.className = "legend-rank";
    const r = effectiveFinalRank(rider);
    rank.textContent = r < 9999 ? String(r) : "–";

    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";

    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = displayName(rider);
    name.title = `${displayName(rider)} — ${rider.team ?? ""}`;

    // A result annulled after the fact. Drawn struck through, the way PCS
    // draws it — the rider stays in the list, keeps his rank and his line on
    // the chart, and the fact that the placing was taken away is visible
    // rather than silently applied.
    if (rider.dq) {
      name.classList.add("is-dq");
      rank.classList.add("is-dq");
      name.title = `${displayName(rider)} — ${rider.team ?? ""} · result later annulled`;
    }

    row.appendChild(rank);
    row.appendChild(swatch);
    row.appendChild(name);

    // An awarded time is NOT an annulment and must not look like one. Nothing
    // was taken away from this rider — he was credited with a time he did not
    // race and keeps the place he finished in — so striking him through, the
    // way a disqualification is drawn, would say the opposite of what happened.
    //
    // The glyph is PCS's own asterisk on purpose. PCS does not publish what
    // each mark is for, so reproducing its annotation claims exactly as much
    // as we know and no more; inventing a symbol would imply a reading of it.
    if (rider.adj?.length) {
      const mark = document.createElement("span");
      mark.className = "legend-adj-mark";
      mark.textContent = "*";
      const where = rider.adj.length === 1
        ? `stage ${rider.adj[0]}`
        : `stages ${rider.adj.join(", ")}`;
      // The glyph alone says nothing to a screen reader, which is why the DQ
      // marker beside it carries a title too.
      mark.title = `PCS marks his time on ${where} as awarded rather than `
        + "raced — credited with a group's time, usually after a crash inside "
        + "the final kilometres, while keeping the place he finished in";
      mark.setAttribute("aria-label", mark.title);
      row.appendChild(mark);
    }

    const flag = nationalityFlagEl(rider.nationality);
    if (flag) row.appendChild(flag);

    swatch.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.selected.has(rider.id)) {
        state.selected.delete(rider.id);
      } else {
        state.selected.add(rider.id);
      }
      refreshLegendState();
      updateLineClasses();
    });

    name.addEventListener("click", (e) => {
      e.stopPropagation();
      const slug = rider.id.replace(/^rider\//, "");
      window.location.hash = `#riders/${slug}`;
    });

    row.addEventListener("mouseenter", () => {
      setHighlight(rider.id);
    });
    row.addEventListener("mouseleave", () => {
      setHighlight(null);
    });

    legendEl.appendChild(row);
  }
  refreshLegendState();
}

export function refreshLegendState() {
  legendEl.querySelectorAll<HTMLDivElement>(".legend-item").forEach((row) => {
    const id = row.dataset.id!;
    const isSelected = state.selected.has(id);
    row.classList.toggle("active", isSelected);
    const swatch = row.querySelector<HTMLSpanElement>(".legend-swatch")!;
    swatch.style.background = isSelected ? colorScale()(id) : "var(--line-dim)";
  });
}
