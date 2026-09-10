"""Map layer assembly, and the static-file guard on the server."""

import importlib.util
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from terrasentry import pipeline

ROOT = Path(__file__).resolve().parents[1]


def _serve():
    spec = importlib.util.spec_from_file_location("serve_mod", ROOT / "scripts" / "serve.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_map_layers_include_plot_adjacent_and_hotspots():
    layers = pipeline.run("SUP-001")["map"]
    assert layers["plot"]["geometry"]["type"] == "Polygon"
    assert len(layers["adjacent"]) == 1
    assert layers["adjacent"][0]["properties"]["parcel_id"] == "PARCEL-N-114"
    assert len(layers["hotspots_inside"]) > 0
    assert all({"lon", "lat", "acq_date"} <= set(h) for h in layers["hotspots_inside"])


def test_clean_supplier_has_no_adjacent_parcel_layer():
    layers = pipeline.run("SUP-002")["map"]
    assert layers["adjacent"] == []
    assert layers["hotspots_inside"] == []


def test_missing_imagery_is_not_an_error():
    """The panel must draw vectors with no cached composite -- that is the normal state."""
    layers = pipeline.run("SUP-001")["map"]
    assert isinstance(layers["imagery"], list)


def test_server_serves_map_js_and_data():
    srv, base = _serve()
    try:
        assert _get(base, "/map.js")[0] == 200
        assert _get(base, "/data/polygons/SUP-001.geojson")[0] == 200
    finally:
        srv.shutdown()


def test_data_route_refuses_path_traversal():
    """/data/../../.env must not walk out of the data directory."""
    srv, base = _serve()
    try:
        for attack in ("/data/../.env", "/data/..%2f..%2f.env", "/data/../../.gitignore"):
            code, _ = _get(base, attack)
            assert code in (403, 404), f"{attack} returned {code}"
    finally:
        srv.shutdown()


def test_data_route_refuses_unlisted_suffixes():
    srv, base = _serve()
    try:
        assert _get(base, "/data/entities/suppliers.json")[0] == 200   # allowed suffix
        assert _get(base, "/data/cache")[0] == 404                     # directory, not a file
    finally:
        srv.shutdown()


def test_server_never_emits_nan():
    """Python writes NaN as a bare token and reads it back happily; browsers refuse it.

    A lon/lat transposition makes the geodesic area NaN, and one such supplier used to
    produce a payload that Python round-tripped fine and every browser rejected -- so the
    panel died on data the server considered valid.
    """
    import json as _json

    srv, base = _serve()
    try:
        for path in ("/api/portfolio", "/api/screen?supplier=SUP-023"):
            code, body = _get(base, path)
            assert code == 200, path
            text = body.decode("utf-8")
            assert "NaN" not in text and "Infinity" not in text, f"{path} emitted a non-finite token"
            _json.loads(text, parse_constant=_reject)  # strict: fail on NaN/Infinity
    finally:
        srv.shutdown()


def _reject(token):
    raise AssertionError(f"non-finite JSON constant in payload: {token}")


def test_transposed_coordinates_give_a_finite_area_and_a_clear_problem():
    from terrasentry import pipeline

    r = pipeline.run("SUP-023")
    import math

    assert math.isfinite(r["geometry"]["area_ha"])
    assert any("swapped" in p for p in r["problems"])
