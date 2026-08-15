// Generates static per-race landing pages (tour/index.html, giro/index.html,
// vuelta/index.html) from the root index.html template, so each Grand Tour
// gets its own crawlable, distinctly-titled URL instead of everyone sharing
// one generic page behind hash routing. Runs as an npm "prebuild" step (see
// package.json) so these never drift out of sync with index.html by hand.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { RACES } from "./race-page-meta.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SITE = "https://eshiflet.github.io/tdf-analytics";

const template = readFileSync(join(__dirname, "index.html"), "utf8");

for (const [race, meta] of Object.entries(RACES)) {
  const url = `${SITE}/${race}/`;
  let html = template;

  html = html.replace(/<title>[^<]*<\/title>/, `<title>${meta.title}</title>`);
  html = html.replace(
    /<meta name="description" content="[^"]*" \/>/,
    `<meta name="description" content="${meta.description}" />`,
  );
  html = html.replace(/<meta property="og:title" content="[^"]*" \/>/, `<meta property="og:title" content="${meta.title}" />`);
  html = html.replace(/<meta property="og:description" content="[^"]*" \/>/, `<meta property="og:description" content="${meta.description}" />`);
  html = html.replace(/<meta property="og:url" content="[^"]*" \/>/, `<meta property="og:url" content="${url}" />`);
  html = html.replace(/<meta name="twitter:title" content="[^"]*" \/>/, `<meta name="twitter:title" content="${meta.title}" />`);
  html = html.replace(/<meta name="twitter:description" content="[^"]*" \/>/, `<meta name="twitter:description" content="${meta.description}" />`);
  html = html.replace(/<link rel="canonical" href="[^"]*" \/>/, `<link rel="canonical" href="${url}" />`);
  html = html.replace(
    /"name": "Cycling Analytics",\s*\n\s*"url": "[^"]*",\s*\n\s*"description": "[^"]*"/,
    `"name": "${meta.title}",\n        "url": "${url}",\n        "description": "${meta.description}"`,
  );
  html = html.replace(
    /(<p class="subtitle" id="subtitle-stage">)[^]*?(<\/p>)/,
    `$1\n          ${meta.subtitle}\n        $2`,
  );

  const dir = join(__dirname, race);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "index.html"), html);
  console.log(`generated ${race}/index.html`);
}
