#!/usr/bin/env python3
"""ADS-B overlay contract (S463).

Three behaviours that were each broken in the live app, so they get a guard:

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


def test_open_popup_marker_still_moves() -> None:
    body = _function_body("_syncOverlayMarkers")
    move = body.index("marker.setLatLng([it.lat, it.lon])")
    guard = body.index("if (marker === open) continue")
    assert move < guard, (
        "the open-popup guard runs before setLatLng; a plane will freeze under its popup")
    # The guard must still exist: moving the marker is wanted, rebuilding the
    # popup DOM under the operator is not.
    assert "marker._popupHtml !== it.popup" in body, "open popups are no longer protected from rebuilds"


def test_poll_cadence_constant() -> None:
    assert "OVERLAY_POLL_MS = { adsb: 1000, ais: 2000, om: 15000 }" in JS
    assert "setInterval(pollEnabledOverlays, OVERLAY_TICK_MS)" in JS
    assert "OVERLAY_TICK_MS = 1000" in JS


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
