#!/usr/bin/env python3
"""Regression tests for track halt detection and the two kinds of halt.

Run: python3 tests/test_stops.py

Covers the 2026-10-17 bug (S455): a long stop was in the recorded points as one pair
with ZERO metres moved and a huge dt, but the pair carried the speed from before the
halt and from after it (2.5 and 2.6 km/h), so a stored-speed-only rule read 2.55 km/h
and dropped the stop entirely. Case `test_long_gap_with_stale_speeds` fails on the old
implementation — that is deliberate, so these tests can actually fail.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (imports the Flask app; starting the recorder thread is harmless)


def _pt(ts: int, lat: float, lon: float, speed: float | None = None) -> dict:
    return {"ts": ts, "lat": lat, "lon": lon, "speed": speed, "alt": 500, "sats": 8}


def _halt_pair(t0: int, t1: int, lat: float, lon: float, sa: float, sb: float) -> list[dict]:
    """Two points at the SAME position `t1-t0` seconds apart (the recorder's at-rest pair)."""
    return [_pt(t0, lat, lon, sa), _pt(t1, lat, lon, sb)]


def _drive(t0: int, lat: float, lon: float, n: int, step_m: float = 60.0, spd: float = 50.0) -> list[dict]:
    """n points heading north at `spd`, `step_m` apart, one every 10 s."""
    out = []
    dlat = step_m / 111_320.0
    for i in range(n):
        out.append(_pt(t0 + i * 10, lat + i * dlat, lon, spd))
    return out


def test_long_gap_with_stale_speeds() -> None:
    """A 24-minute halt bridged by one pair, with the pre/post-halt speeds stored."""
    pts = _drive(0, 46.0, 14.0, 6)
    pts += _halt_pair(60, 60 + 1424, 46.0 + 6 * 60 / 111_320.0, 14.0, 2.5, 2.6)
    pts += _drive(60 + 1424, 46.0 + 6 * 60 / 111_320.0, 14.0, 6)

    # Positive control: the speed the OLD rule used is above STOP_KMH, which is why
    # this stop used to disappear. If this ever drops below 1, the test stops testing.
    pair_speed = app._seg_speed_kmh(pts[6], pts[7])
    assert pair_speed > app.STOP_KMH, pair_speed
    assert pts[6]["lat"] == pts[7]["lat"] and pts[6]["lon"] == pts[7]["lon"]

    stops = app._detect_stops(pts)
    assert len(stops) == 1, stops
    assert stops[0]["kind"] == "stopped", stops[0]
    assert abs(stops[0]["duration_s"] - 1424) <= 1, stops[0]


def test_short_halt_is_stationary() -> None:
    """A traffic-light halt (90 s) is part of the drive: 'stationary', not an event."""
    pts = _drive(0, 46.0, 14.0, 5)
    pts += _halt_pair(40, 130, 46.0 + 4 * 60 / 111_320.0, 14.0, 0.0, 0.0)
    pts += _drive(130, 46.0 + 4 * 60 / 111_320.0, 14.0, 5)
    stops = app._detect_stops(pts)
    assert len(stops) == 1, stops
    assert stops[0]["kind"] == "stationary", stops[0]


def test_driving_has_no_stops() -> None:
    stops = app._detect_stops(_drive(0, 46.0, 14.0, 40))
    assert stops == [], stops


def test_kind_boundary_is_ten_minutes() -> None:
    assert app.stop_kind(599) == "stationary"
    assert app.stop_kind(600) == "stopped"
    assert app.stop_kind(None) == "stationary"


def test_clean_stops_recomputes_kind() -> None:
    """A client cannot persist a label that disagrees with the duration."""
    out = app._clean_stops([
        {"seq": 1, "start_ts": 10, "end_ts": 40, "duration_s": 30, "kind": "stopped", "lat": 46.0, "lon": 14.0},
        {"seq": 2, "start_ts": 100, "end_ts": 1300, "duration_s": 1200, "kind": "stationary", "lat": 46.0, "lon": 14.0},
    ])
    assert [s["kind"] for s in out] == ["stationary", "stopped"], out


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
