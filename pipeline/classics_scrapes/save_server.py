#!/usr/bin/env python3
"""Save server for the one-day classics scrape.

Unlike the Grand Tour save servers (which accept already-parsed stage JSON
extracted by browser-side JS), this one accepts the page's RAW HTML and
writes it verbatim to <race-slug>/<year>.html. Parsing then happens in
Python via scrape_vuelta.py's find_results_table/parse_rows/parse_info, so
every already-validated PCS quirk — the "5:25:585:25:58" duplicated-time
cell, the <span class="hide"> authoritative ditto value, the adjacent-row
name-swap fields — is handled by the same code that handles it for the
Giro and Vuelta, rather than being reimplemented in JS and re-learned the
hard way. See ai-context.md's 2026-08-01 historical-audit note, which
recommends exactly this.

Listens on localhost:8765 (same port as the other save servers — only run
one at a time).
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json, os

DIR = os.path.dirname(os.path.abspath(__file__))

# Served at /relay. Receives {race, year, html} via postMessage from the PCS
# tab and re-posts it same-origin to this server, then acks back to the
# opener so the scraping loop knows the page is safely on disk.
RELAY_HTML = """<!doctype html>
<meta charset="utf-8">
<title>classics relay</title>
<body style="font:14px system-ui;padding:1rem">
<h3>classics scrape relay</h3>
<div id="log">waiting for messages…</div>
<script>
const log = document.getElementById('log');
let n = 0;
window.addEventListener('message', async (e) => {
  const d = e.data;
  if (!d || d.kind !== 'classics-save') return;
  try {
    const r = await fetch('/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({race: d.race, year: d.year, html: d.html}),
    });
    const text = await r.text();
    n++;
    log.textContent = n + ' saved — last: ' + text;
    e.source.postMessage({kind:'classics-ack', race:d.race, year:d.year, ok:r.ok, text}, '*');
  } catch (err) {
    e.source.postMessage({kind:'classics-ack', race:d.race, year:d.year, ok:false, text:String(err)}, '*');
  }
});
if (window.opener) window.opener.postMessage({kind:'classics-relay-ready'}, '*');
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Health check, plus the /relay page.

        /relay exists because a page on https://www.procyclingstats.com cannot
        POST to 127.0.0.1 at all in current Chrome: it is mixed content in the
        in-app browser, and Chrome proper blocks it under Private Network
        Access even with the opt-in preflight header. postMessage between
        windows is subject to neither policy, so the PCS page opens /relay and
        posts each page's HTML across; the relay is itself on this origin, so
        its POST back here is a plain same-origin request.
        """
        if self.path.startswith('/relay'):
            body = RELAY_HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b'classics save server ok\n'
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        # Chrome's Private Network Access gate: a page on a public origin
        # (https://www.procyclingstats.com) reaching a private address
        # (127.0.0.1) must be explicitly opted in by the private server, or
        # the request hangs with no error the page can see. This is why the
        # old "Chrome allows localhost POSTs from HTTPS pages" note in
        # ai-context.md no longer holds on its own.
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '86400')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data = json.loads(self.rfile.read(length))
        race, year, html = data['race'], str(data['year']), data['html']
        out_dir = os.path.join(DIR, race)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f'{year}.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        msg = f'{race}/{year}.html ({len(html)} bytes)'
        body = f'Saved {msg}'.encode()
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'text/plain')
        # Explicit length: without it the client waits on connection close,
        # which is what left Chrome's sockets in CLOSE_WAIT and made a POST
        # look like a hang.
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f'  OK {msg}', flush=True)

    def log_message(self, fmt, *args):
        pass


print('Save server listening on http://localhost:8765', flush=True)
print(f'Writing to {DIR}/<race>/<year>.html', flush=True)
# Threaded: a browser that opens a connection and never completes the request
# (a blocked mixed-content POST, a preflight that goes nowhere) would
# otherwise wedge the single-threaded server for every later request.
ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
