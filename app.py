"""
app.py  -  the Digital Asset Assistant web app.

Runs on the Python standard library only (http.server) so you can start it
with just `python app.py` - no pip install required. Open the printed URL.

Endpoints
  GET  /                     -> the search UI
  GET  /api/search?q=...     -> ranked results (JSON)
  POST /api/mark_final       -> {family, id}  human-confirms the canonical version
  POST /api/correct_tag      -> {id, tag}     human adds/corrects a tag
  POST /api/open             -> {id}          reveal the asset's folder (local only)
  GET  /api/audit            -> recent audit-log lines (governance)
  POST /api/role             -> {role}        switch member/admin (permission demo)
  GET  /thumb/<file>         -> a thumbnail image
"""

import json
import os
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import guardrails
from search_engine import SearchEngine

HOST, PORT = "127.0.0.1", int(os.environ.get("DAA_PORT", 8080))
ENGINE = None  # lazy


def engine():
    global ENGINE
    if ENGINE is None:
        ENGINE = SearchEngine()
    return ENGINE


def open_asset(asset_id, reveal=False):
    """Open an internal asset, or reveal it in the OS file browser.

    reveal=False -> launch the file in its default app (e.g. PowerPoint).
    reveal=True  -> open the containing folder with the file selected.

    This only makes sense because the prototype runs locally on the user's own
    machine. Two guard rails apply: it never touches public links, and it
    refuses any path that resolves outside the configured asset library.
    """
    asset = next((a for a in engine().assets if a.get("id") == asset_id), None)
    if not asset:
        return False, "Asset not found in the index."
    if asset.get("kind") == "link":
        return False, "This is a public link, not a file — open the URL instead."

    base = os.path.normpath(config.ASSETS_DIR)
    full = os.path.normpath(os.path.join(base, asset.get("rel_path", "")))
    if full != base and not full.startswith(base + os.sep):
        return False, "Blocked: path is outside the asset library."
    if not os.path.exists(full):
        return False, f"Not on this machine: {full}"

    guardrails.audit("REVEAL_ASSET" if reveal else "OPEN_ASSET",
                     f"user={config.CURRENT_USER} id={asset_id} path={full}")
    try:
        if reveal:
            # Open the containing folder with the file selected.
            subprocess.Popen(["explorer", "/select,", full])
            return True, "Opening the folder…"
        os.startfile(full)  # launch in the default app (Windows)
        return True, "Opening the file…"
    except Exception as exc:  # never crash the server on an open failure
        return False, f"Could not open: {exc}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # keep the console clean

    # -- helpers -------------------------------------------------------------
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # -- GET -----------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            html_path = os.path.join(config.PROJECT_DIR, "templates", "index.html")
            with open(html_path, encoding="utf-8") as fh:
                self._send(200, fh.read(), "text/html; charset=utf-8")
            return

        if path == "/api/search":
            q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            if not config.ENABLED:
                self._send(200, {"disabled": True,
                                 "message": "The assistant is paused (kill-switch ON)."})
                return
            clean, ok, msg = guardrails.screen_query(q)
            if not ok:
                self._send(200, {"blocked": True, "message": msg, "query": q})
                return
            guardrails.audit("SEARCH", clean)
            self._send(200, engine().search(clean))
            return

        if path == "/api/audit":
            self._send(200, {"lines": guardrails.read_audit()})
            return

        if path == "/api/state":
            self._send(200, {"role": config.CURRENT_USER, "enabled": config.ENABLED,
                             "count": len(engine().assets)})
            return

        if path.startswith("/thumb/"):
            fn = os.path.basename(path)
            fp = os.path.join(config.THUMBS_DIR, fn)
            if os.path.exists(fp):
                with open(fp, "rb") as fh:
                    self._send(200, fh.read(), "image/jpeg")
            else:
                self._send(404, b"", "image/jpeg")
            return

        self._send(404, {"error": "not found"})

    # -- POST ----------------------------------------------------------------
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        data = self._read_json()

        if path == "/api/mark_final":
            guardrails.mark_final(data.get("family", ""), data.get("id", ""))
            self._send(200, {"ok": True})
            return

        if path == "/api/correct_tag":
            guardrails.correct_tag(data.get("id", ""), (data.get("tag", "") or "").strip())
            # rebuild vectors so the new tag is searchable immediately
            engine()._load()
            self._send(200, {"ok": True})
            return

        if path == "/api/open":
            ok, msg = open_asset(data.get("id", ""), bool(data.get("reveal")))
            self._send(200, {"ok": ok, "message": msg})
            return

        if path == "/api/role":
            role = data.get("role", "member")
            config.CURRENT_USER = "admin" if role == "admin" else "member"
            guardrails.audit("ROLE_SWITCH", config.CURRENT_USER)
            self._send(200, {"ok": True, "role": config.CURRENT_USER})
            return

        self._send(404, {"error": "not found"})


def main():
    # touch the index up front so errors show immediately
    eng = engine()
    print("=" * 64)
    print(" Codebasics Digital Asset Assistant  (prototype)")
    print("=" * 64)
    print(f" Indexed assets : {len(eng.assets)}")
    print(f" Duplicate sets : {len(eng.dup_families)}")
    print(f" Open your browser at:  http://{HOST}:{PORT}")
    print(" Press Ctrl+C to stop.")
    print("=" * 64)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
