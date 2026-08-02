#!/usr/bin/env python3
"""
Local sink for the browser-fetch re-scrape (2026-08-01 ditto-mark fix
rollout, see ai-context.md). The Browser pane's JS fetches PCS pages
directly (bypassing Cloudflare via its own solved challenge) and POSTs
parsed stage JSON here; this just writes it to disk in the exact schema
scrape_giro.py/scrape_vuelta.py already produce.

Usage: python3 browser_scrape_server.py [port]   (default 8934)

POST /save?race=giro&year=1920
  body: JSON array of stage objects [{n, info, profile_icon, rows,
        sprint_points, kom_points}, ...]
  Deletes existing stage_N.json for that year first, then writes fresh ones.

GET /status  -> {"ok": true}
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/save", "/save-partial"):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        qs = parse_qs(parsed.query)
        race = qs.get("race", [""])[0]
        year = qs.get("year", [""])[0]
        if race not in ("giro", "vuelta") or not year.isdigit():
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error": "bad race/year"}')
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            stages = json.loads(body)
        except Exception as e:
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        out_dir = os.path.join(HERE, f"{race}_scrapes", year)
        os.makedirs(out_dir, exist_ok=True)

        if parsed.path == "/save":
            for f in os.listdir(out_dir):
                if f.startswith("stage_") and f.endswith(".json"):
                    os.remove(os.path.join(out_dir, f))

        for stage in stages:
            out_path = os.path.join(out_dir, f"stage_{stage['n']}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(stage, f, ensure_ascii=False)

        verb = "wrote" if parsed.path == "/save" else "backfilled"
        print(f"{race} {year}: {verb} {len(stages)} stage files", flush=True)

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "count": len(stages)}).encode())

    def log_message(self, fmt, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8934
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Listening on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
