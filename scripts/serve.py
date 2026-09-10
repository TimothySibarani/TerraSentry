"""Local web panel for RIMBA.

    python -m scripts.serve
    then open http://localhost:8765

Standard library only -- no Flask, no extra install. One less thing to break on a
borrowed laptop five minutes before a demo.

Endpoints:
    GET  /                          the panel
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
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rimba import pipeline  # noqa: E402

WEB = ROOT / "web"
DEFAULT_PORT = 8765
DEFAULT_PACE_MS = 550


class Handler(BaseHTTPRequestHandler):
    server_version = "RIMBA/0.1"

    # -- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def log_message(self, fmt: str, *args: object) -> None:
        # Quieter console: the panel is the interface, not the log.
        if "/api/" in self.path:
            sys.stderr.write(f"  {self.path}\n")

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path

        if route in ("/", "/index.html"):
            html = (WEB / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
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
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"RIMBA panel  ->  {url}")
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
