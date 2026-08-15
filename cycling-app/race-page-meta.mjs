// Per-race SEO copy for the static landing pages.
//
// A DATA-ONLY module on purpose. generate-race-pages.mjs writes files when it
// runs, and vite.config.ts imports this list to build its multi-page `input`
// map — importing the generator itself would execute those writes every time
// the Vite config loads. Splitting the data out lets both read one source
// without either inheriting the other's side effects.

export const RACES = {
  tour: {
    title: "Tour de France Cycling Analytics — GC, Sprint & KOM Stats (1903–2026)",
    description: "Stage-by-stage GC, sprint, and KOM standings for every Tour de France since 1903 — every rider, every stage, every year.",
    subtitle: "Stage-by-stage GC, sprint, and KOM rankings for every Tour de France, 1903–2026.",
  },
  giro: {
    title: "Giro d'Italia Cycling Analytics — GC, Sprint & KOM Stats (1909–2026)",
    description: "Stage-by-stage GC, sprint, and KOM standings for every Giro d'Italia since 1909 — every rider, every stage, every year.",
    subtitle: "Stage-by-stage GC, sprint, and KOM rankings for every Giro d'Italia, 1909–2026.",
  },
  vuelta: {
    title: "Vuelta a España Cycling Analytics — GC, Sprint & KOM Stats (1935–2025)",
    description: "Stage-by-stage GC, sprint, and KOM standings for every Vuelta a España since 1935 — every rider, every stage, every year.",
    subtitle: "Stage-by-stage GC, sprint, and KOM rankings for every Vuelta a España, 1935–2025.",
  },
  // No sprint/KOM wording here: the classics contest neither, and the metric
  // is a finishing position rather than a GC standing.
  classics: {
    title: "One-Day Classics Cycling Analytics — Monument & Classic Results (1892–2026)",
    description: "Race-by-race results for the cycling monuments and classics — Milan–San Remo, Tour of Flanders, Paris–Roubaix, Liège–Bastogne–Liège, Il Lombardia and more, 1892–2026.",
    subtitle: "Race-by-race results across a full classics season, 1892–2026.",
  },
};
