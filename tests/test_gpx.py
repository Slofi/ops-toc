#!/usr/bin/env python3
"""Regression tests for GPX import/export and point ordering (S455 sweep).

The bug: `<time>` was parsed into a string only, so every imported track had
`started_at = ended_at = None`, no duration, and no stops — an export/import round
trip lost all timing even though the GPX carried it.

Run: python3 tests/test_gpx.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>round trip</name><trkseg>
    <trkpt lat="46.0000" lon="14.0000"><ele>300</ele><time>2026-10-17T08:00:00Z</time></trkpt>
    <trkpt lat="46.0009" lon="14.0000"><ele>300</ele><time>2026-10-17T08:00:10Z</time></trkpt>
    <trkpt lat="46.0018" lon="14.0000"><ele>300</ele><time>2026-10-17T08:00:20Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""


def test_iso_to_ts() -> None:
    assert app._iso_to_ts("2026-10-17T08:00:00Z") == 1792224000
    assert app._iso_to_ts("2026-10-17T10:00:00+02:00") == 1792224000
    assert app._iso_to_ts("2026-10-17T08:00:00.500Z") == 1792224000
    assert app._iso_to_ts("not a date") is None
    assert app._iso_to_ts(None) is None


def test_xml_points_carry_ts() -> None:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(GPX)
    seg = root.find(".//{http://www.topografix.com/GPX/1/1}trkseg")
    pts = app._xml_points(list(seg))
    assert len(pts) == 3, pts
    assert all(isinstance(p.get("ts"), int) for p in pts), pts
    assert pts[0]["ts"] == 1792224000
    assert [p["ts"] for p in pts] == sorted(p["ts"] for p in pts)


def test_points_are_sorted_when_all_have_ts() -> None:
    given = [
        {"lat": 46.0, "lon": 14.0, "ts": 300},
        {"lat": 46.0, "lon": 14.0, "ts": 100},
        {"lat": 46.0, "lon": 14.0, "ts": 200},
    ]
    out = app._clean_track_points(given)
    assert [p["ts"] for p in out] == [100, 200, 300], out


def test_points_keep_order_when_ts_is_missing() -> None:
    given = [{"lat": 46.0, "lon": 14.0, "ts": 300}, {"lat": 46.0, "lon": 14.0}]
    out = app._clean_track_points(given)
    assert [p.get("ts") for p in out] == [300, None], out


def test_import_writes_duration_and_stops() -> None:
    """The import path must produce started_at/ended_at; a long halt must be detected."""
    # A 12-minute halt after two 10 s legs: this must import as one Stopped event.
    gpx = GPX.replace(
        '<trkpt lat="46.0018" lon="14.0000"><ele>300</ele><time>2026-10-17T08:00:20Z</time></trkpt>',
        '<trkpt lat="46.0009" lon="14.0000"><ele>300</ele><time>2026-10-17T08:12:20Z</time></trkpt>',
    )
    assert gpx != GPX, "test fixture replacement did not apply"
    import tempfile

    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "sweep.db"
    old = os.environ.get("MAP_APP_DB")
    os.environ["MAP_APP_DB"] = str(tmp)
    try:
        # reload the module-level DB paths for this test only
        app.DB_PATH = tmp
        app.init_db()
        result = app.import_gpx_bytes(gpx.encode())
        assert result["tracks"] == 1, result
        with app.get_db() as conn:
            row = conn.execute("select * from tracks order by id desc limit 1").fetchone()
        assert row["started_at"] and row["ended_at"], dict(row)
        assert row["ended_at"] - row["started_at"] == 740, row["ended_at"] - row["started_at"]
        stops = json.loads(row["stops_json"] or "[]")
        assert len(stops) == 1 and stops[0]["kind"] == "stopped", stops
    finally:
        if old is None:
            os.environ.pop("MAP_APP_DB", None)
        else:
            os.environ["MAP_APP_DB"] = old


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
