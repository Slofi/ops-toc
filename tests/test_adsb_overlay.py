#!/usr/bin/env python3
"""ADS-B overlay contract (S463, extended for the traces toggle).

Five behaviours that were each broken in the live app, so they get a guard:

1. `/api/overlays/adsb?slim=1` returns only what the map draws (no history,
   no per-aircraft track points) — the payload that makes a 1 s poll cheap.
   The full payload must stay unchanged for every other consumer.
2. The ADS-B popup shows Airline and Country (both already in the feed).
3. `_syncOverlayMarkers` moves a marker BEFORE the open-popup guard, so a plane
   keeps moving under its popup; the guard still protects the popup DOM.

The JS checks read the source, because these are ordering/field invariants of a
single browser bundle with no JS test runner. They are deliberately about
behaviour, not cosmetics: the popup fields, the move-before-guard order, and the
per-source poll floor.

Run: python3 tests/test_adsb_overlay.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

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


def test_slim_payload() -> None:
    original = app._overlay_request_json

    def fake(url, method="GET", payload=None, timeout=None):
        assert url.endswith("/api/aircraft"), url
        return {
            "active": [
                {"hex": "abc123", "lat": 46.0, "lon": 15.0, "speed": 400,
                 "airline": "Test Air", "country": "Slovenia",
                 "track_points": [[46.0, 15.0, 30000]]},
                "not-a-dict",  # a malformed row must not 500 the overlay
            ],
            "history": [{"hex": "dead01"}],
            "timestamp": 123.0,
            "stats": {"active_count": 1},
        }

    app._overlay_request_json = fake
    try:
        client = app.app.test_client()

        slim = client.get("/api/overlays/adsb?slim=1")
        assert slim.status_code == 200, slim.status_code
        data = slim.get_json()
        assert set(data) == {"active", "slim", "timestamp"}, set(data)
        assert data["slim"] is True
        assert len(data["active"]) == 1, data["active"]
        row = data["active"][0]
        assert "track_points" not in row, row
        assert row["airline"] == "Test Air" and row["country"] == "Slovenia"
        assert "history" not in data

        with_tracks = client.get("/api/overlays/adsb?slim=1&traces=1").get_json()
        assert with_tracks["active"][0].get("track_points"), "traces=1 lost the track points"
        assert "history" not in with_tracks

        full = client.get("/api/overlays/adsb")
        assert full.status_code == 200, full.status_code
        body = full.get_json()
        assert body["history"] == [{"hex": "dead01"}]
        assert body["active"][0]["track_points"], "full payload lost its track points"
    finally:
        app._overlay_request_json = original


def test_popup_has_airline_and_country() -> None:
    body = _function_body("renderAdsbOverlay")
    assert '["Airline", ac.airline]' in body, "ADS-B popup lost the Airline row"
    assert '["Country", ac.country]' in body, "ADS-B popup lost the Country row"


def _find(body: str, needle: str) -> int:
    try:
        return body.index(needle)
    except ValueError:
        raise AssertionError(f"missing {needle!r}") from None


def test_open_popup_marker_still_moves() -> None:
    body = _function_body("_syncOverlayMarkers")
    move = _find(body, "marker.setLatLng([it.lat, it.lon])")
    guard = _find(body, "if (marker === open)")
    assert move < guard, (
        "the open-popup guard runs before setLatLng; a plane will freeze under its popup")
    # The guard must still exist: moving the marker is wanted, rebuilding the
    # popup DOM under the operator is not.
    assert "marker._popupHtml !== it.popup" in body, "open popups are no longer protected from rebuilds"


def test_open_popup_age_stays_honest() -> None:
    body = _function_body("_syncOverlayMarkers")
    assert "_refreshPopupAge(marker, it.updatedTs)" in body, (
        "the open popup's Updated row is never refreshed; its age freezes")
    assert "_ageCell(ac.last_seen)" in _function_body("renderAdsbOverlay"), (
        "the ADS-B Updated row lost its refreshable timestamp")


def test_traces_toggle_wired() -> None:
    controls = _function_body("renderOverlayControls")
    assert 'type="checkbox" data-adsb-trace' in controls, "no ADS-B traces toggle under the ADS-B row"
    assert "setAdsbTraces(input.checked)" in controls, "the traces toggle is not wired"
    setter = _function_body("setAdsbTraces")
    assert '"ops_toc_adsb_traces"' in setter, "the traces toggle is not persisted"
    assert "_adsbTraceClear()" in setter, "turning traces off does not clear the lines"


def test_traces_style_matches_the_adsb_app() -> None:
    # The ADS-B app: weight 1.8, opacity 0.65, gone -> #445 + dashed 4 6.
    assert "ADSB_TRACE_STYLE = { weight: 1.8, opacity: 0.65 }" in JS
    draw = _function_body("_adsbTraceDraw")
    assert 'color: ac.gone ? "#445" : _adsbColor(ac)' in draw
    assert 'dashArray: ac.gone ? "4 6" : null' in draw
    assert "setLatLngs(latlngs)" in draw, "traces are rebuilt instead of updated in place"


def test_traces_follow_the_adsb_overlay() -> None:
    source_clear = _function_body("_clearOverlaySource")
    assert 'if (source === "adsb") _adsbTraceClear()' in source_clear, (
        "turning the ADS-B overlay off leaves its traces on the map")
    assert 'const adsbUrl = `/api/overlays/adsb?slim=1${_adsbTracesOn ? "&traces=1" : ""}`;' in JS, (
        "the feed never asks for track points when traces are on")
    render = _function_body("renderAdsbOverlay")
    assert "if (_adsbTracesOn) _adsbTraceDraw(data)" in render, (
        "the traces layer is not refreshed with the aircraft feed")


def test_poll_cadence_constant() -> None:
    assert "OVERLAY_POLL_MS = { adsb: 1000, ais: 2000, om: 15000 }" in JS
    assert "setInterval(pollEnabledOverlays, OVERLAY_TICK_MS)" in JS
    assert "OVERLAY_TICK_MS = 1000" in JS


def test_legend_single_source_and_dismissable() -> None:
    # The legend must come from the same data as the marker colours.
    assert "const ADSB_ALT_BANDS = [" in JS
    for band in ('"Ground / below 0 ft"', '"0 – 5,000 ft"', '"5,000 – 18,000 ft"',
                 '"18,000 – 30,000 ft"', '"30,000 ft +"'):
        assert band in JS, f"legend band label missing: {band}"
    color = _function_body("_adsbColor")
    assert "for (const band of ADSB_ALT_BANDS)" in color, "marker colours no longer come from the band table"
    rows = _function_body("_adsbLegendRows")
    assert "...ADSB_ALT_BANDS.map((band) => [band.label, band.color])" in rows, (
        "the legend is hard-coded instead of using the band table")
    assert "ADSB_MILITARY_COLOR" in rows and "ADSB_EMERGENCY_COLOR" in rows and "ADSB_NO_ALT_COLOR" in rows

    show = _function_body("_adsbLegendShow")
    assert 'div.querySelector(".adsb-legend-close").onclick = () => { div.style.display = "none"; }' in show, (
        "the X does not dismiss the legend")
    assert 'node.style.display = "";' in show, "re-enabling would not bring a dismissed legend back"
    assert 'title="Hide legend"' in show

    toggle = _function_body("setOverlayEnabled")
    assert 'if (source === "adsb") _adsbLegendShow();' in toggle, "enabling ADS-B does not show the legend"
    assert 'if (source === "adsb") _adsbLegendHide();' in toggle, "disabling ADS-B leaves the legend on the map"
    init = _function_body("initLiveOverlays")
    assert 'if (state.overlayEnabled.has("adsb")) _adsbLegendShow();' in init, (
        "a page load with ADS-B already enabled shows no legend")


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
