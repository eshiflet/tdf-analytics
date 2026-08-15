// Generates the static per-race landing pages (tour/, giro/, vuelta/,
// classics/) from the root index.html template, so each race gets its own
// crawlable, distinctly-titled URL instead of everyone sharing one generic
// page behind hash routing. Also generates sitemap.xml and robots.txt, so the
// race list and the site host each live in exactly one place
// (race-page-meta.mjs).
//
// Runs as an npm "prebuild"/"predev" step (see package.json) so none of this
// drifts out of sync with index.html by hand.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { RACES, SITE } from "./race-page-meta.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

const template = readFileSync(join(__dirname, "index.html"), "utf8");

/**
 * Replace, but FAIL if the pattern matched nothing.
 *
 * String.replace on a non-matching regex is a silent no-op, and that is how
 * this script quietly rotted: it rewrote a `<p class="subtitle">` that commit
 * 58ce75f had removed from index.html, so every landing page shipped with the
 * template's copy and nobody found out. Anything this script claims to
 * customize must actually be customized, or the page is stale and looks fine.
 */
function sub(html, pattern, replacement, label) {
  if (!pattern.test(html)) {
    throw new Error(
      `generate-race-pages: "${label}" matched nothing in index.html. ` +
        `The template changed; this page would have shipped stale metadata.`,
    );
  }
  return html.replace(pattern, replacement);
}

for (const [race, meta] of Object.entries(RACES)) {
  const url = `${SITE}/${race}/`;
  let html = template;

  html = sub(html, /<title>[^<]*<\/title>/, `<title>${meta.title}</title>`, "title");
  html = sub(html, /<meta name="description" content="[^"]*" \/>/,
    `<meta name="description" content="${meta.description}" />`, "description");
  html = sub(html, /<meta property="og:title" content="[^"]*" \/>/,
    `<meta property="og:title" content="${meta.title}" />`, "og:title");
  html = sub(html, /<meta property="og:description" content="[^"]*" \/>/,
    `<meta property="og:description" content="${meta.description}" />`, "og:description");
  html = sub(html, /<meta property="og:url" content="[^"]*" \/>/,
    `<meta property="og:url" content="${url}" />`, "og:url");
  html = sub(html, /<meta name="twitter:title" content="[^"]*" \/>/,
    `<meta name="twitter:title" content="${meta.title}" />`, "twitter:title");
  html = sub(html, /<meta name="twitter:description" content="[^"]*" \/>/,
    `<meta name="twitter:description" content="${meta.description}" />`, "twitter:description");
  html = sub(html, /<link rel="canonical" href="[^"]*" \/>/,
    `<link rel="canonical" href="${url}" />`, "canonical");
  html = sub(html,
    /"name": "[^"]*",\s*\n\s*"url": "[^"]*",\s*\n\s*"description": "[^"]*"/,
    `"name": "${meta.title}",\n        "url": "${url}",\n        "description": "${meta.description}"`,
    "schema.org WebSite");

  const dir = join(__dirname, race);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "index.html"), html);
  console.log(`generated ${race}/index.html`);
}

// sitemap.xml — generated rather than hand-kept, because a hand-kept copy is a
// THIRD place the race list lives (after this file and vite.config.ts's input
// map) and it drifted exactly like the others: classics was missing from it
// too, so the one new section of the site was never advertised to crawlers.
const urls = [
  { loc: `${SITE}/`, priority: "1.0" },
  ...Object.keys(RACES).map((race) => ({ loc: `${SITE}/${race}/`, priority: "0.9" })),
];
const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map(({ loc, priority }) => `  <url>
    <loc>${loc}</loc>
    <changefreq>weekly</changefreq>
    <priority>${priority}</priority>
  </url>`).join("\n")}
</urlset>
`;
writeFileSync(join(__dirname, "public", "sitemap.xml"), sitemap);
console.log(`generated public/sitemap.xml (${urls.length} URLs)`);

writeFileSync(join(__dirname, "public", "robots.txt"),
  `User-agent: *\nAllow: /\n\nSitemap: ${SITE}/sitemap.xml\n`);
console.log("generated public/robots.txt");
