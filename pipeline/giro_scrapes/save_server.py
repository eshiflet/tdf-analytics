#!/usr/bin/env python3
"""Tiny HTTP server that accepts POSTed stage JSON and saves to disk."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, sys

DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data = json.loads(self.rfile.read(length))
        stage_num = data['n']
        path = os.path.join(DIR, f'stage_{stage_num}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(f'Saved stage {stage_num} ({len(data.get("rows",[]))} rows)'.encode())
        print(f'  ✓ stage_{stage_num}.json ({len(data.get("rows",[]))} rows)')

    def log_message(self, fmt, *args):
        pass  # suppress request logs

print(f'Save server listening on http://localhost:8765')
print(f'Writing to {DIR}/')
HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
