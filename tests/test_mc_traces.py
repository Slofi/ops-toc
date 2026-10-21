#!/usr/bin/env python3
"""MeshCore traces must stay an ANIMATION, not a static picture (S463).

The layer was first ported as static polylines. OM's own "Traces (MC)" plays each
newly-heard packet as a moving dot with a fading tail, hop by hop at 420 ms, and
a direct arrival as an expanding ring. These guards are behavioural: pacing,
in-flight mutation, fade, direct pulse, new-packets-only, and stop-on-off.

Run: python3 tests/test_mc_traces.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JS = (ROOT / "static" / "js" / "app.js").read_text()


def _function_body(name: str) -> str:
    """Whole `function name(...) { ... }` text, brace-matched."""
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


def test_pacing_matches_om() -> None:
    for const in (
        "const MC_TRACE_HOP_MS = 420;",
        "const MC_TRACE_FADE_MS = 900;",
        "const MC_TRACE_TAIL_LEN = 0.35;",
        "const MC_TRACE_DIRECT_MS = 1400;",
        "const MC_TRACE_DIRECT_R = 26;",
        "const MC_TRACE_SEED_CNT = 8;",
        "const MC_TRACE_REFRESH_MS = 6000;",
    ):
        assert const in JS, f"pacing constant missing or changed: {const}"


def test_no_static_path_drawing_left() -> None:
    assert "_mcTraceDraw" not in JS, "the old static trace draw is still present"
    refresh = _function_body("_mcTraceRefresh")
    assert "_mcTraceLaunch(" in refresh, "new rows are not launched as animations"
    assert "L.polyline(pts" not in JS, "a static full-path polyline is still drawn"


def test_dot_and_tail_move() -> None:
    launch = _function_body("_mcTraceLaunch")
    assert "L.polyline([]" in launch, "the tail must start empty and grow"
    assert "L.circleMarker(res.points[0]" in launch, "the moving head dot is missing"
    step = _function_body("_mcTraceStep")
    assert "a.dot.setLatLng(pt)" in step, "the dot never moves"
    assert "a.tail.setLatLngs(_mcTraceSlice(a.geom, from, head))" in step, "the tail never grows"
    assert "requestAnimationFrame" in JS, "no animation loop"


def test_arrival_fades() -> None:
    step = _function_body("_mcTraceStep")
    assert "const fade = (elapsed - a.duration) / MC_TRACE_FADE_MS;" in step
    assert "a.tail.setStyle({ opacity: 0.9 * o })" in step
    assert "a.dot.setStyle({ fillOpacity: o, opacity: o })" in step


def test_direct_arrival_pulses() -> None:
    direct = _function_body("_mcTraceLaunchDirect")
    assert "heard <b>direct</b>, no relay hops" in direct, "direct arrivals lost their tooltip"
    step = _function_body("_mcTraceStep")
    assert "a.ring.setRadius(3 + t * MC_TRACE_DIRECT_R)" in step, "the direct ring does not expand"
    assert "a.ring.setStyle({ opacity: 1 - t })" in step, "the direct ring does not fade"


def test_only_new_packets_animate() -> None:
    refresh = _function_body("_mcTraceRefresh")
    assert "_mcTraceSeen.has(_mcTraceKey(r))" in refresh, "already-seen packets are replayed"
    assert "MC_TRACE_SEED_CNT" in refresh and "MC_TRACE_SEED_MS" in refresh, "no seed replay on enable"
    assert "play = (seed ? fresh.slice(0, MC_TRACE_SEED_CNT) : fresh).reverse()" in refresh


def test_cold_start_retries_without_contacts() -> None:
    refresh = _function_body("_mcTraceRefresh")
    assert "if (!contacts.length && rows.length) return;" in refresh, (
        "a cold contact list would mark every row as seen and never animate it")
    assert "state.omLastData?.mc_contacts || []" in refresh
    # The guard must run BEFORE rows are marked seen.
    guard = refresh.index("if (!contacts.length && rows.length) return;")
    mark = refresh.index("rows.forEach((r) => _mcTraceSeen.add(_mcTraceKey(r)));")
    assert guard < mark, "rows are marked seen before the contacts guard"


def test_poll_stops_when_off() -> None:
    setter = _function_body("setMcTraces")
    assert "_mcTracesStop()" in setter
    stop = _function_body("_mcTracesStop")
    assert "clearInterval(_mcTraceTimer)" in stop
    assert "cancelAnimationFrame(_mcTraceRaf)" in _function_body("_mcTraceClear")
    om_toggle = _function_body("setOverlayEnabled")
    assert 'if (source === "om") _mcTracesStop();' in om_toggle, "turning OM off leaves the trace poll running"
    net_toggle = _function_body("setOmNet")
    assert "else _mcTracesStop();" in net_toggle, "turning MeshCore off leaves the trace poll running"


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
