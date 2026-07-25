"""
app.py  -  the Digital Asset Assistant web app.

Runs on the Python standard library only (http.server) so you can start it
with just `python app.py` - no pip install required. Open the printed URL.

Endpoints
  GET  /                     -> the search UI
  GET  /api/search?q=...     -> ranked results (JSON)
  POST /api/mark_final       -> {family, id}  human-confirms the canonical version
  POST /api/correct_tag      -> {id, tag}     human adds/corrects a tag
  GET  /api/audit            -> recent audit-log lines (governance)
  POST /api/role             -> {role}        switch member/admin (permission demo)
  GET  /thumb/<file>         -> a thumbnail image
"""

import json
import os
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
