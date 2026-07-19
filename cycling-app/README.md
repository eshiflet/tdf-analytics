# Pro Cycling Analytics — Web App

A static web app for visualizing pro cycling race data across three Grand
Tours — the Tour de France, Giro d'Italia, and Vuelta a España. Built with
Vite + TypeScript + D3 — no backend, no framework overhead. Deploys anywhere
that can serve static files.

## What's here

Pick a race and year from the dropdowns at top, then choose a view:

- **By Stage** — a bump chart of every rider's rank after each stage, for GC
  position, Sprint points, or KOM points. Search any rider by name, quick-select
  Top 10/20/All/None, or filter by team/nationality. Click a rider (in the
  legend or on their line) to toggle them on/off; hover a line for stage-by-stage
  detail.
- **Race Overview** — per-stage distance, elevation, and difficulty for the
  selected year, colored by route type.
- **All Races Overview** — four charts comparing every edition of the selected
  race across its full history (distance, elevation, GC winner time, speed).
- **Riders** — a searchable/filterable grid of every rider who's ridden the
  selected race, plus a per-rider detail page. The detail page is cross-race:
  it shows a rider's results in all three Grand Tours at once, with toggles to
  show/hide each race and each classification (GC/Sprint/KOM) independently.

Every view is deep-linkable via the URL hash (e.g. `#giro/2026/stage/gc`,
`#vuelta/allraces`, `#riders/eddy-merckx`) and race-aware — a bare hash with
no race segment means the Tour de France.

The data (`src/data/<race>/*.json`) is bundled directly into the app at build
time — exported from the `cycling.db` SQLite database by the Python scripts in
`../pipeline/`. To refresh it after re-scraping or re-ingesting, re-run the
relevant export script(s) (see `../ai-context.md` for the full pipeline) and
rebuild.

## Running it

Requires [Node.js](https://nodejs.org) (v18+).

```bash
npm install        # one-time, fetches dependencies
npm run dev        # starts a local dev server, prints a localhost URL
```

Open the printed URL in your browser.

## Building for deployment

```bash
npm run build       # outputs static files to build/
npm run preview     # sanity-check the production build locally
```

The `build/` folder is a complete static site — every file in it is plain
HTML/CSS/JS. You can:

- Drag the `build/` folder into [Netlify Drop](https://app.netlify.com/drop)
- Deploy it with `vercel`, `netlify deploy`, or GitHub Pages
- Serve it from any static file host (S3, nginx, etc.)

In this repo, deployment to GitHub Pages is automated via
`.github/workflows/` on every push to `main` — see that workflow file for the
exact build/validate/deploy steps.

**Note:** because the app uses ES modules, you can't just double-click
`build/index.html` and open it directly in a browser (browsers block ES
module scripts loaded over `file://`). Always serve it via `npm run dev`,
`npm run preview`, or a real static host.

## Verifying changes

Two smoke-test scripts run against the built bundle (used in CI, see the
GitHub Actions workflow):

```bash
npm run build
node verify.mjs         # sanity checks on the default stage-chart view
node verify-views.mjs   # deep-link regression checks across all four views
```

## Project layout

```
index.html           entry HTML
src/main.ts           app logic: chart drawing (D3), hash routing, all four views
src/types.ts          TypeScript types for the datasets
src/style.css         styling
src/data/<race>/      bundled per-race data (JSON, generated from cycling.db;
                       race is "tour", "giro", or "vuelta")
verify.mjs             smoke test: default stage-chart view
verify-views.mjs       smoke test: deep links across all views
build/                 production build output (rebuild with npm run build)
```

For the full data pipeline (scraping, ingesting, exporting) and detailed
architecture notes, see `../ai-context.md`.
