#!/usr/bin/env python3
"""AIS and radiosonde trails (S463).

AIS: the overlay now offers an "AIS traces" sub-toggle that draws each vessel's
track_points in the AIS app's own trail style (weight 1.8, opacity 0.65; gone
0.35, dashed "4 6", marker colour). The slim payload drops track_points unless
`&traces=1` asks for them.

Sondes: the overlay used to keep only the latest position. The flight path is
the useful part of a sounding, so telemetry now accumulates a capped path
(~50 m / 100 m altitude gate) and a "Radiosonde traces" sub-toggle draws it.

Run: python3 tests/test_ais_sonde_overlay.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

JS = (ROOT / "static" / "js" / "app.js").read_text()


def _function_body(name: str) -> str:
    start = JS.index("function " + name)
    open_brace = JS.index("{", start)
    depth = 0
    for i in range(open_brace, len(JS)):
        if JS[i] == "{":
            depth += 1
        elif JS[i] == "}":
            depth -= 1
            if depth == 0:
                return JS[start:i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


VESSEL = {"mmsi": 278001, "name": "Test Boat", "lat": 45.5, "lon": 13.5,
          "track_points": [[45.4, 13.4, 5.0, 90], [45.5, 13.5, 6.0, 90]],
          "gone": False}


def test_ais_slim_payload() -> None:
    original = app._overlay_request_json

    def fake(url, method="GET", payload=None, timeout=None):
        assert url.endswith("/api/vessels"), url
        return {"active": [VESSEL, "not-a-dict"],
                "history": [{**VESSEL, "mmsi": 278002, "gone": True}],
                "stats": {"active_count": 1}}

    app._overlay_request_json = fake
    try:
        client = app.app.test_client()

        slim = client.get("/api/overlays/ais?slim=1")
        assert slim.status_code == 200, slim.status_code
        data = slim.get_json()
        assert data["slim"] is True
        assert len(data["active"]) == 2, data["active"]  # malformed row survives
        assert "track_points" not in data["active"][0]
        assert "track_points" not in data["history"][0]
        assert data["active"][0]["name"] == "Test Boat"
        assert data["stats"] == {"active_count": 1}

        with_tracks = client.get("/api/overlays/ais?slim=1&traces=1").get_json()
        assert with_tracks["slim"] is True
        assert with_tracks["active"][0]["track_points"] == VESSEL["track_points"]
        assert with_tracks["history"][0]["track_points"] == VESSEL["track_points"]

        full = client.get("/api/overlays/ais").get_json()
        assert "slim" not in full
        assert full["active"][0]["track_points"] == VESSEL["track_points"]
    finally:
        app._overlay_request_json = original


def test_ais_traces_wired_and_styled() -> None:
    assert '<span>AIS traces</span>' in JS
    assert 'data-ais-trace' in JS
    assert 'if (source === "ais" && checked)' in JS
    assert 'box.querySelectorAll("[data-ais-trace]").forEach' in JS
    setter = _function_body("setAisTraces")
    assert 'safeSetItem("ops_toc_ais_traces"' in setter
    assert "_aisTraceClear();" in setter
    assert 'loadOverlaySource("ais");' in setter
    assert 'const aisUrl = `/api/overlays/ais?slim=1${_aisTracesOn ? "&traces=1" : ""}`;' in JS
    draw = _function_body("_aisTraceDraw")
    assert "Array.isArray(v.track_points)" in draw
    assert "color: _aisColor(v)" in draw
    assert "opacity: v.gone ? 0.35 : 0.65" in draw
    assert 'dashArray: v.gone ? "4 6" : null' in draw
    assert "const AIS_TRACE_STYLE = { weight: 1.8 };" in JS
    assert "line.setLatLngs(pts)" in draw and "line.setStyle(style)" in draw
    assert "_aisTraceLines.delete(mmsi)" in draw, "gone vessels must lose their trail"
    clear = _function_body("_clearOverlaySource")
    assert 'if (source === "ais") _aisTraceClear();' in clear


def test_sonde_path_accumulation() -> None:
    render = _function_body("_renderSondeObject")
    assert "const path = Array.isArray(prev.path) ? prev.path.slice() : [];" in render
    assert "> 0.0005" in render, "the 50 m gate is gone (one point per telemetry frame)"
    assert "> 100" in render, "the 100 m altitude gate is gone"
    assert "path.push([data.lat, data.lon, data.alt ?? null])" in render
    assert "if (path.length > SONDE_TRACE_MAX) path.shift();" in render
    assert "const SONDE_TRACE_MAX = 1500;" in JS
    icon = _function_body("_sondeIcon")
    assert "_sondeColor(id)" in icon, "the trail colour must come from the icon colour"


def test_sonde_traces_wired() -> None:
    assert '<span>Radiosonde traces</span>' in JS
    assert 'data-sonde-trace' in JS
    assert 'if (source === "sonde" && checked)' in JS
    assert 'box.querySelectorAll("[data-sonde-trace]").forEach' in JS
    setter = _function_body("setSondeTraces")
    assert 'safeSetItem("ops_toc_sonde_traces"' in setter
    assert "_sondeTraceClear();" in setter
    assert "_sondeTraceDraw();" in setter
    render = _function_body("renderSondeOverlay")
    assert "if (_sondeTracesOn) _sondeTraceDraw();" in render
    draw = _function_body("_sondeTraceDraw")
    assert "const color = _sondeColor(id);" in draw
    assert "weight: 2, opacity: 0.75" in draw
    assert "line.setLatLngs(pts)" in draw
    clear = _function_body("_clearOverlaySource")
    assert 'if (source === "sonde") _sondeTraceClear();' in clear


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    total = len(tests)
    print(f"{total - failed}/{total} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
