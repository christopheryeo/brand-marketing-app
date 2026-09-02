#!/usr/bin/env python3
"""Local server for the People Directory with an editable "To Enhance" checkbox.

Serves Apps/people-directory.html and lets the checkbox persist the ToEnhance
flag back to the canonical Person record. Python stdlib only.

Endpoints:
  GET  /                       -> people-directory.html
  GET  /to-enhance-state?id=.. -> {"value": true|false|null}  (live from the note)
  POST /set-to-enhance         -> body {"id": "person-..", "value": true|false|null}

Run:  python3 directory_server.py     (or double-click "People Directory.command")
Set IB_VAULT_ROOT to point at a different vault (used for testing).
"""

import json
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)                                   # .../scripts
VAULT = Path(os.environ.get("IB_VAULT_ROOT") or os.path.dirname(SCRIPTS))  # .../influential-brands
HTML_PATH = VAULT / "Apps" / "people-directory.html"
PORT = int(os.environ.get("IB_DIRECTORY_PORT", "8766"))

sys.path.insert(0, SCRIPTS)
from mark_to_enhance import read_to_enhance, set_to_enhance  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        route = urlparse(self.path).path
        if route in ("/", "/index.html", "/people-directory.html"):
            try:
                self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "people-directory.html not found — run build_people_directory.py first.", "text/plain")
        elif route == "/to-enhance-state":
            pid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            try:
                self._send(200, json.dumps({"status": "ok", "id": pid, "value": read_to_enhance(pid, root=VAULT)}))
            except Exception as error:
                self._send(404, json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}))
        else:
            self._send(404, "Not found", "text/plain")

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/rebuild":
            try:
                build = os.path.join(HERE, "build_people_directory.py")
                r = subprocess.run([sys.executable, build], capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    raise RuntimeError((r.stderr or r.stdout or "build failed").strip()[:500])
                self._send(200, json.dumps({"status": "ok"}))
            except Exception as error:
                self._send(500, json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}))
            return
        if route != "/set-to-enhance":
            self._send(404, "Not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            value = payload.get("value")
            if value not in (True, False, None):
                raise ValueError("value must be true, false or null")
            result = set_to_enhance(payload.get("id"), value, root=VAULT)
            self._send(200, json.dumps({"status": "ok", **result}))
        except Exception as error:
            self._send(400, json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}))


def main():
    url = f"http://localhost:{PORT}/people-directory.html"
    if not HTML_PATH.exists():
        print(f"⚠  {HTML_PATH} not found — run build_people_directory.py first.")
    print(f"People Directory (editable) → {url}")
    print("Tick 'To Enhance' on a person to flag them for enhancement; changes save to the vault.")
    print("Close this window to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
