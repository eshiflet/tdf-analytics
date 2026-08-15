// Per-race SEO copy for the static landing pages.
//
// A DATA-ONLY module on purpose. generate-race-pages.mjs writes files when it
// runs, and vite.config.ts imports this list to build its multi-page `input`
// map — importing the generator itself would execute those writes every time
// the Vite config loads. Splitting the data out lets both read one source
// without either inheriting the other's side effects.

// The host the site actually SERVES from. eshiflet.github.io/tdf-analytics/
// and ericshiflet.com/tdf-analytics/ both 301 here, so this is the one URL
// that returns 200 and the only one worth putting in a canonical tag or a
// sitemap. A sitemap is also restricted to URLs on its own host: listing
// eshiflet.github.io entries in a sitemap served from www.ericshiflet.com
// meant search engines ignored the whole file.
export const SITE = "https://www.ericshiflet.com/tdf-analytics";

export const RACES = {
  tour: {
    title: "Tour de France Cycling Analytics — GC, Sprint & KOM Stats (1903–2026)",
    description: "Stage-by-stage GC, sprint, and KOM standings for every Tour de France since 1903 — every rider, every stage, every year.",
  },
  giro: {
    title: "Giro d'Italia Cycling Analytics — GC, Sprint & KOM Stats (1909–2026)",
    description: "Stage-by-stage GC, sprint, and KOM standings for every Giro d'Italia since 1909 — every rider, every stage, every year.",
  },
  vuelta: {
    title: "Vuelta a España Cycling Analytics — GC, Sprint & KOM Stats (1935–2025)",
    description: "Stage-by-stage GC, sprint, and KOM standings for every Vuelta a España since 1935 — every rider, every stage, every year.",
  },
  // No sprint/KOM wording here: the classics contest neither, and the metric
  // is a finishing position rather than a GC standing.
  classics: {
    title: "One-Day Classics Cycling Analytics — Monument & Classic Results (1892–2026)",
    description: "Race-by-race results for the cycling monuments and classics — Milan–San Remo, Tour of Flanders, Paris–Roubaix, Liège–Bastogne–Liège, Il Lombardia and more, 1892–2026.",
  },
};
