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
  "og-vuelta|#vuelta/2025/stage/gc|Vuelta a España|Stage-by-stage GC, sprint and KOM · 1935–2025|2025 general classification"
  "og-classics|#classics/2026/stage/gc|One-Day Classics|Monuments and classics · 11 races · 1892–2026|2026 season"
  "og-gravel|#gravel/2025/stage/gc|Gravel|Unbound · Leadville · Chequamegon · Sea Otter · 1994–2026|2025 season"
)

urlenc() { python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }

for card in "${CARDS[@]}"; do
  IFS='|' read -r name hash title sub note <<< "$card"
  url="$BASE/og-image.html?hash=$(urlenc "$hash")&title=$(urlenc "$title")&sub=$(urlenc "$sub")&note=$(urlenc "$note")"
  # --virtual-time-budget lets the SPA fetch its data and finish the D3
  # transition before the shutter; without it the card captures a blank chart.
  "$CHROME" --headless --disable-gpu --no-sandbox --hide-scrollbars \
    --window-size=1200,630 --virtual-time-budget=22000 \
    --screenshot="$OUT/$name.png" "$url" >/dev/null 2>&1
  printf '%-16s %s\n' "$name.png" "$(du -h "$OUT/$name.png" | cut -f1)"
done

echo "Wrote 5 cards to public/. Commit them — they are served as static assets."
