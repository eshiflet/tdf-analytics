# Pro Cycling Analytics — Web App

A lightweight, static web app for visualizing pro cycling race data. Built with
Vite + TypeScript + D3 — no backend, no framework overhead. Deploys anywhere
that can serve static files.

## What's here

This is the first chart: **GC position by stage** for the 2024 Tour de France.
Each line is a rider; the x-axis is stage number, the y-axis is their overall
(general classification) rank after that stage. Lines stop where a rider
finished, DNF'd, or didn't start.

- Search any rider by name
- Quick-select top 10 / top 20 / all / none
- Click a rider in the legend (or click their line) to toggle it on/off
- Hover a line for stage-by-stage rank and time gap

The data (`src/data/gc_by_stage.json`) is bundled directly into the app at
build time — exported from the `cycling.db` SQLite database. To refresh it
after re-scraping more races, regenerate that JSON and re-run the build.

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

**Note:** because the app uses ES modules, you can't just double-click
`build/index.html` and open it directly in a browser (browsers block ES
module scripts loaded over `file://`). Always serve it via `npm run dev`,
`npm run preview`, or a real static host.

## Project layout

```
index.html          entry HTML
src/main.ts          chart logic (D3)
src/types.ts         TypeScript types for the dataset
src/style.css        styling
src/data/            bundled race data (JSON, generated from cycling.db)
build/               production build output (already built; rebuild with npm run build)
```
