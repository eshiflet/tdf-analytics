// Payload budget — fails when the built site gets meaningfully bigger.
//
// WHY THIS EXISTS. Every payload win in this repo was measured once, by hand,
// and then had nothing holding it in place: the compact JSON separators (-10%),
// the riders_index re-encode (-22% gzipped), the cross-race bitmask that
// stopped the rider detail page loading all five indexes. Any of them could be
// undone by an exporter change and the only symptom would be a slower site —
// no test fails, no validator complains, and the diff on a 2 MB minified JSON
// file tells you nothing.
//
// So the sizes are committed. payload-baseline.json holds the GZIPPED byte
// count of everything worth watching, and this compares the current build
// against it.
//
// WHAT IT WATCHES, and why it is not simply "every file":
//
//   entry     main.js / main.css — the code. Note main.js also carries the
//             three all_races_summary.json files, which raceRegistry.ts
//             imports as data rather than by URL, so they are bundled into it
//             and never appear as their own asset. A regression in one of them
//             shows up here.
//   index     each riders_index.json — one fixed file per race, the biggest
//             single downloads and the ones that get re-encoded
//   bucket    the TOTAL of each race's per-year files, not each file. There
//             are 400+ of them, they are fetched one at a time, and pinning
//             each would be 400 lines of noise for a per-file signal nobody
//             acts on. The sum still catches an encoding regression.
//   total     everything in build/assets, so a new category cannot slip in
//             below the radar
//
// GROWTH IS EXPECTED. Adding a year makes the archive bigger and that is not a
// regression, which is why this compares against a committed baseline with a
// tolerance rather than a hardcoded ceiling. When growth is real, re-baseline
// deliberately:
//
//     node check-payload.mjs --update
//
// and the diff on payload-baseline.json shows exactly what grew, in the commit
// that grew it. That record is the actual product here — the failure is just
// what makes you look.
//
// Usage:
//   node check-payload.mjs              # compare against the baseline
//   node check-payload.mjs --update     # rewrite the baseline from this build
//   node check-payload.mjs --tolerance 5   # percent, default 2
import fs from "fs";
import path from "path";
import zlib from "zlib";

const BUILD_DIR = new URL("./build/assets/", import.meta.url);
const BASELINE = new URL("./payload-baseline.json", import.meta.url);

const args = process.argv.slice(2);
const update = args.includes("--update");
const tolIdx = args.indexOf("--tolerance");
// Two percent is below the noise floor of anything that isn't a real change:
// re-running the exporters byte-for-byte moves nothing, and the smallest
// encoding change measured here (nationality-as-index) was 1.0% and was
// rejected as not worth doing. A regression worth catching is bigger than both.
const TOLERANCE = tolIdx >= 0 ? Number(args[tolIdx + 1]) : 2;

const gzipSize = (file) =>
  zlib.gzipSync(fs.readFileSync(file), { level: 9 }).length;

/** Vite fingerprints every asset (`riders_index-B_ltjzQ1.json`). The hash
 *  changes on every content change by design, so it cannot be part of the key
 *  or the baseline would match nothing after the first edit. */
const unhash = (name) => name.replace(/-[A-Za-z0-9_-]{8}(\.[^.]+)$/, "$1");

/** Which race a data file belongs to, keyed on `basename:rawBytes`.
 *
 *  The build flattens every race's data into one assets/ directory, so the
 *  race is no longer in the path — `gc_by_stage_1987.json` could be the Tour's
 *  or the Giro's, and all five races have a `riders_index.json`. Vite copies
 *  these assets verbatim, so the raw byte count is carried through the build
 *  unchanged and disambiguates them without hashing 131 MB of source. Two
 *  races sharing a basename AND an exact byte count is possible in principle;
 *  that case is split evenly below rather than guessed at.
 *
 *  Reading the mapping out of src/data/ rather than hardcoding it also means a
 *  new race set shows up in the report as its own line, instead of silently
 *  joining another race's bucket. */
function raceOfEachDataFile() {
  const dataRoot = new URL("./src/data/", import.meta.url);
  const owner = new Map();
  for (const race of fs.readdirSync(dataRoot)) {
    // .DS_Store lives here on macOS; statting it as a directory throws.
    if (!fs.statSync(new URL(race, dataRoot)).isDirectory()) continue;
    const dir = new URL(`${race}/`, dataRoot);
    for (const file of fs.readdirSync(dir)) {
      const key = `${file}:${fs.statSync(new URL(file, dir)).size}`;
      if (!owner.has(key)) owner.set(key, []);
      owner.get(key).push(race);
    }
  }
  return owner;
}

function measure() {
  const owner = raceOfEachDataFile();
  const entries = new Map();
  const buckets = new Map();
  let total = 0;

  for (const name of fs.readdirSync(BUILD_DIR)) {
    const file = new URL(name, BUILD_DIR);
    const stat = fs.statSync(file);
    if (!stat.isFile()) continue;
    const size = gzipSize(file);
    total += size;
    const plain = unhash(name);
    const races = owner.get(`${plain}:${stat.size}`) ?? [];

    if (/^main\.(js|css)$/.test(plain)) {
      entries.set(`entry:${plain}`, size);
    } else if (races.length === 1 &&
               (plain === "riders_index.json" || plain === "all_races_summary.json")) {
      // One fixed file per race, and the two biggest things the app downloads.
      // These get their own line rather than a bucket: they are exactly what a
      // re-encode changes, and a 20% regression in one of them would vanish
      // inside a race's total.
      entries.set(`${plain.replace(".json", "")}:${races[0]}`, size);
    } else if (races.length) {
      // A per-year data file. An ambiguous one (same basename, same byte count,
      // two races) is split evenly rather than dropped: the per-race bucket is
      // then approximate, but the TOTAL stays exact — and the total is what
      // catches an across-the-board encoding regression.
      const share = size / races.length;
      for (const race of races) {
        buckets.set(`years:${race}`, (buckets.get(`years:${race}`) ?? 0) + share);
      }
    } else {
      // Chunks, fonts, images, the og: PNGs — and anything a future change
      // adds. Bucketed rather than ignored so nothing lands outside the report.
      buckets.set("other", (buckets.get("other") ?? 0) + size);
    }
  }

  const sizes = {};
  for (const [k, v] of [...entries, ...buckets]) sizes[k] = Math.round(v);
  sizes["total:assets"] = total;
  return Object.fromEntries(Object.entries(sizes).sort(([a], [b]) => a.localeCompare(b)));
}

const kb = (n) => `${(n / 1024).toFixed(1)} KB`;

if (!fs.existsSync(BUILD_DIR)) {
  console.error("No build/assets — run `npm run build` first.");
  process.exit(1);
}

const current = measure();

if (update) {
  fs.writeFileSync(BASELINE, JSON.stringify(current, null, 2) + "\n");
  console.log(`payload-baseline.json updated (${Object.keys(current).length} entries, ` +
              `${kb(current["total:assets"])} total gzipped)`);
  process.exit(0);
}

if (!fs.existsSync(BASELINE)) {
  console.error("No payload-baseline.json — create it with: node check-payload.mjs --update");
  process.exit(1);
}
const baseline = JSON.parse(fs.readFileSync(BASELINE, "utf-8"));

const regressions = [];
const added = [];
const removed = [];
for (const [key, size] of Object.entries(current)) {
  if (!(key in baseline)) { added.push([key, size]); continue; }
  const was = baseline[key];
  const growth = was === 0 ? 0 : (100 * (size - was)) / was;
  if (growth > TOLERANCE) regressions.push([key, was, size, growth]);
}
for (const key of Object.keys(baseline)) {
  if (!(key in current)) removed.push(key);
}

for (const [key, was, size, growth] of regressions) {
  console.log(`  REGRESSED ${key}  ${kb(was)} -> ${kb(size)}  +${growth.toFixed(1)}%`);
}
// An asset appearing or disappearing is reported but does not fail: adding a
// race set is normal work, and failing it would only teach people to pass
// --update reflexively, which is the one habit that makes this useless.
for (const [key, size] of added) console.log(`  new       ${key}  ${kb(size)} (not in baseline)`);
for (const key of removed) console.log(`  gone      ${key} (was ${kb(baseline[key])})`);

if (regressions.length) {
  console.log(
    `\nFAIL: ${regressions.length} payload(s) grew more than ${TOLERANCE}% gzipped.\n` +
    "If the growth is real — a new year, a new race — re-baseline deliberately:\n" +
    "  node check-payload.mjs --update\n" +
    "and commit payload-baseline.json alongside the change that caused it.");
  process.exit(1);
}

const drift = current["total:assets"] - baseline["total:assets"];
console.log(`PASS  ${Object.keys(current).length} payloads within ${TOLERANCE}% ` +
            `(total ${kb(current["total:assets"])} gzipped, ` +
            `${drift >= 0 ? "+" : ""}${kb(drift)} vs baseline)`);
