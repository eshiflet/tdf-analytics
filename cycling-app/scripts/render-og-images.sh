#!/usr/bin/env bash
# Renders the social-card images in public/ from the app's REAL charts.
#
# Each card is og-image.html screenshotted by headless Chrome at exactly
# 1200x630 (the Open Graph size Slack/X/iMessage/Facebook crop to). og-image.html
# iframes the live SPA at a deep link and hides the chrome, so the picture is
# the same D3 render a visitor gets and cannot drift from the real thing.
#
# Run manually after a chart or palette change -- NOT part of `npm run build`,
# which must stay installable-free and headless-Chrome-free for CI.
#
#   npm run dev            # in another shell; must be serving on :5173
#   ./scripts/render-og-images.sh
set -euo pipefail

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
BASE="${BASE:-http://localhost:5173/tdf-analytics}"
HERE="$(cd "$(dirname "${BASE_SOURCE:-$0}")/.." && pwd)"
OUT="$HERE/public"

[ -x "$CHROME" ] || { echo "Chrome not found at $CHROME (override with CHROME=...)" >&2; exit 1; }
curl -sSf -o /dev/null "$BASE/" || { echo "No dev server at $BASE — run 'npm run dev' first." >&2; exit 1; }

# name | app hash | headline | subhead | corner note
CARDS=(
  "og-image|#allraces|Cycling Analytics|Tour · Giro · Vuelta · Classics · Gravel · 1892–2026|Every rider, every stage, every year"
  "og-tour|#2026/stage/gc|Tour de France|Stage-by-stage GC, sprint and KOM · 1903–2026|2026 general classification"
  "og-giro|#giro/2026/stage/gc|Giro d'Italia|Stage-by-stage GC, sprint and KOM · 1909–2026|2026 general classification"
  "og-vuelta|#vuelta/2026/stage/gc|Vuelta a España|Stage-by-stage GC, sprint and KOM · 1935–2026|2026 general classification"
  "og-classics|#classics/2026/stage/gc|One-Day Classics|Monuments and classics · 11 races · 1892–2026|2026 season"
  "og-gravel|#gravel/2025/stage/gc|Gravel|Unbound · Leadville · Chequamegon · Sea Otter · 1994–2026|2025 season"
)

urlenc() { python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }

# Optional filter: re-render ONE card instead of all six.
#
#   ./scripts/render-og-images.sh og-vuelta
#
# A card goes stale on its own schedule — the Vuelta's did when the 2026 edition
# landed and nothing else changed — and re-rendering the other five to fix one
# rewrites five committed binaries whose content did not change. Chrome's
# antialiasing and pngquant's palette search are not bit-reproducible, so those
# five would show up in the diff as noise with no way to tell them from a real
# design change.
ONLY="${1:-}"
matched=0

for card in "${CARDS[@]}"; do
  IFS='|' read -r name hash title sub note <<< "$card"
  if [ -n "$ONLY" ] && [ "$name" != "$ONLY" ]; then continue; fi
  matched=$((matched + 1))
  url="$BASE/og-image.html?hash=$(urlenc "$hash")&title=$(urlenc "$title")&sub=$(urlenc "$sub")&note=$(urlenc "$note")"
  # --virtual-time-budget lets the SPA fetch its data and finish the D3
  # transition before the shutter; without it the card captures a blank chart.
  "$CHROME" --headless --disable-gpu --no-sandbox --hide-scrollbars \
    --window-size=1200,630 --virtual-time-budget=22000 \
    --screenshot="$OUT/$name.png" "$url" >/dev/null 2>&1
  before=$(du -k "$OUT/$name.png" | cut -f1)

  # Chrome writes 24-bit PNG, which is 300-430 KB of mostly antialiasing on a
  # dark chart — 1.87 MB across the six, committed. pngquant takes them to a
  # 256-colour palette for about a third of that, and at 3x magnification the
  # dense line area shows no banding and no colour shift (checked 2026-09-11).
  # Lossless indexing is not an option: og-classics alone holds ~19,000
  # distinct colours.
  if command -v pngquant >/dev/null; then
    pngquant --quality=65-90 --speed 1 --force --output "$OUT/$name.png" \
             "$OUT/$name.png" 2>/dev/null \
      || echo "  (pngquant could not hold 65-90 on $name — left unquantised)"
  else
    echo "  (pngquant not installed — $name.png stays ~3x larger than it needs to be)"
  fi
  after=$(du -k "$OUT/$name.png" | cut -f1)
  printf '%-16s %4s KB -> %4s KB\n' "$name.png" "$before" "$after"
done

if [ -n "$ONLY" ] && [ "$matched" -eq 0 ]; then
  echo "No card named '$ONLY'. Known: $(printf '%s ' "${CARDS[@]%%|*}")" >&2
  exit 1
fi
echo "Wrote $matched card(s) to public/. Commit them — they are served as static assets."
