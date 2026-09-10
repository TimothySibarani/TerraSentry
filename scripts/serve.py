"""Local web panel for TerraSentry.

    python -m scripts.serve
    then open http://localhost:8765

Standard library only -- no Flask, no extra install. One less thing to break on a
borrowed laptop five minutes before a demo.

Endpoints:
    GET  /                          the panel (built Astro app if present, else web/index.html)
    GET  /api/portfolio             whole supply base screened, aggregated
    GET  /api/suppliers             demo suppliers
    GET  /api/screen?supplier=ID    full dossier as JSON (no streaming)
    GET  /api/stream?supplier=ID    Server-Sent Events, one event per real pipeline step

On pacing: the pipeline finishes in well under a second, which is too fast to read. The
stream endpoint accepts ``pace`` (milliseconds between steps, default 550) purely for
legibility. The steps and their payloads are real and unmodified; each carries its true
``elapsed_ms``, which the panel displays. Do not describe the pacing as processing time.

Run from the repo root -- the data paths are relative to it.
"""

from __future__ import annotations

import json
import math
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from terrasentry import pipeline, portfolio  # noqa: E402

WEB = ROOT / "web"
DIST = ROOT / "frontend" / "dist"
DATA_DIR = ROOT / "data"
DEFAULT_PORT = 8765

# Only these are servable from data/. Everything else in there is either input the panel
# does not need or, in a real deployment, supplier data that has no business on a URL.
SERVABLE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".geojson", ".json"}
CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".geojson": "application/geo+json",
    ".json": "application/json", ".js": "text/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".map": "application/json",
    ".svg": "image/svg+xml", ".woff2": "font/woff2", ".ico": "image/x-icon",
}
DEFAULT_PACE_MS = 550


def dumps(payload: object) -> str:
    """JSON that a browser will actually parse.

    Python emits NaN and Infinity as bare tokens and accepts them again on the way in,
    so a round-trip through Python hides the problem completely -- but JSON.parse in
    every browser rejects them, and the client dies on a payload the server thinks is
    fine. Coerce non-finite floats to null so one odd number cannot take down the panel.
    """
    def clean(obj):
        if isinstance(obj, float):
            return obj if math.isfinite(obj) else None
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [clean(v) for v in obj]
        return obj

    return json.dumps(clean(payload), ensure_ascii=False, allow_nan=False)


class Server(ThreadingHTTPServer):
    """Refuses to start if the port is already taken.

    Python enables SO_REUSEADDR by default, and on Windows that lets a second process
    bind a port another process is already listening on. Both then answer, whichever the
    OS picks first -- so a stale server from an earlier run silently shadows the new one
    and you debug phantom 404s against code you already fixed. Fail loudly instead.
    """

    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    server_version = "TerraSentry/0.1"

    # -- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, code: int = 200) -> None:
        self._send(code, dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def log_message(self, fmt: str, *args: object) -> None:
        # Quieter console: the panel is the interface, not the log.
        if "/api/" in self.path:
            sys.stderr.write(f"  {self.path}\n")

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path

        if self._serve_frontend(route):
            return

        if route == "/map.js":
            self._send(200, (WEB / "map.js").read_bytes(), CONTENT_TYPES[".js"])
            return

        if route.startswith("/data/"):
            self._serve_data(route)
            return

        if route == "/api/portfolio":
            try:
                self._json(portfolio.screen_all())
            except Exception as exc:
                self._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
            return

        if route == "/api/suppliers":
            self._json(pipeline.list_suppliers())
            return

        if route == "/api/screen":
            supplier = (self._query().get("supplier") or [""])[0]
            try:
                self._json(pipeline.run(supplier))
            except KeyError as exc:
                self._json({"error": str(exc)}, code=404)
            except Exception as exc:  # surface real errors rather than a blank page
                self._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
            return

        if route == "/api/stream":
            self._stream()
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")

    # -- frontend -----------------------------------------------------------

    def _serve_frontend(self, route: str) -> bool:
        """Serve the built Astro panel, falling back to the original vanilla one.

        Keeping both working matters during the migration: if a build is broken or Node
        is unavailable on someone's machine, `web/index.html` still runs. Returns True
        when the request was handled.
        """
        if route.startswith(("/api/", "/data/")):
            return False

        if DIST.is_dir():
            rel = "index.html" if route == "/" else route.lstrip("/")
            if rel.endswith("/"):
                rel += "index.html"
            target = (DIST / rel).resolve()
            try:
                target.relative_to(DIST.resolve())
            except ValueError:
                self._send(403, b"outside dist", "text/plain; charset=utf-8")
                return True
            if target.is_dir():
                target = target / "index.html"
            if target.is_file():
                self._send(200, target.read_bytes(),
                           CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream"))
                return True
            # An unknown path under a static build is a 404, not a silent fallthrough.
            if route not in ("/", "/index.html", "/map.js"):
                return False

        if route in ("/", "/index.html"):
            self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            return True
        return False

    # -- static data --------------------------------------------------------

    def _serve_data(self, route: str) -> None:
        """Serve cached imagery and geometry, and nothing else.

        Resolves the path and confirms it is still inside data/ before reading. Without
        that check a request for /data/../../.env walks straight out of the tree -- the
        oldest bug in static file serving, and worth the four lines.
        """
        rel = unquote(route[len("/data/"):])
        target = (DATA_DIR / rel).resolve()
        try:
            target.relative_to(DATA_DIR.resolve())
        except ValueError:
            self._send(403, b"outside data directory", "text/plain; charset=utf-8")
            return
        if target.suffix.lower() not in SERVABLE_SUFFIXES or not target.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream"))

    # -- SSE --------------------------------------------------------------

    def _stream(self) -> None:
        query = self._query()
        supplier = (query.get("supplier") or [""])[0]
        try:
            pace_ms = max(0, int((query.get("pace") or [DEFAULT_PACE_MS])[0]))
        except ValueError:
            pace_ms = DEFAULT_PACE_MS

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        # One screening per connection. Without this the socket lingers after the final
        # event and holds a worker thread until the client gives up.
        self.close_connection = True

        def emit(event: str, payload: object) -> None:
            block = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            self.wfile.write(block.encode("utf-8"))
            self.wfile.flush()

        def on_step(step: pipeline.Step) -> None:
            emit("step", step.to_dict())
            if pace_ms:
                time.sleep(pace_ms / 1000.0)

        try:
            result = pipeline.run(supplier, on_step=on_step)
            emit("result", result)
            emit("done", {"ok": True})
        except KeyError as exc:
            emit("error", {"message": str(exc)})
        except BrokenPipeError:
            pass  # browser navigated away mid-stream
        except Exception as exc:
            emit("error", {"message": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}")
            raise SystemExit(2)

    url = f"http://localhost:{port}"
    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError as exc:
        print(f"Cannot bind port {port}: {exc}")
        print("Another TerraSentry server is probably still running. Stop it, or pass a different port:")
        print(f"    python -m scripts.serve {port + 1}")
        raise SystemExit(1)
    print(f"TerraSentry panel  ->  {url}")
    print("Ctrl+C to stop.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        server.server_close()


if __name__ == "__main__":
    main()
