#!/usr/bin/env python3
"""Input guards for tile addresses and oversized ids (S455 re-sweep).

Both were HTTP 500s on nonsense input:
  * GET /api/tracks/<huge int> — sqlite cannot bind a >64-bit integer (OverflowError);
  * GET /tiles/<layer>/99/0/0.png — the TMS arithmetic built an unbindable integer.

Run: python3 tests/test_input_guards.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


def _fresh():
    tmp = Path(tempfile.mkdtemp())
    app.DB_PATH = tmp / "map_app.db"
    app.MBTILES_DIR = tmp / "mbtiles"
    app.MBTILES_DIR.mkdir(parents=True, exist_ok=True)
    app.init_db()
    return tmp


def _make_pack(tmp: Path) -> None:
    """A tiny real pack with ONE tile at z=1 (0,0) — also the positive control."""
    pack = tmp / "mbtiles" / "testpack.mbtiles"
    with sqlite3.connect(pack) as conn:
        app.init_mbtiles(conn, {"name": "test pack", "format": "png", "minzoom": "1", "maxzoom": "1"})
        conn.execute("INSERT INTO tiles (zoom_level,tile_column,tile_row,tile_data) VALUES (?,?,?,?)",
                     (1, 0, 1, b"\x89PNG\r\n\x1a\nfaketile"))  # TMS y = (2**z-1) - y
        conn.commit()


def test_huge_id_is_404_not_500() -> None:
    _fresh()
    client = app.app.test_client()
    for path in ("/api/tracks/999999999999999999999999",
                 "/api/tracks/999999999999999999999999/geojson"):
        st = client.get(path)
        assert st.status_code == 404, (path, st.status_code)


def test_tile_out_of_range_is_204() -> None:
    tmp = _fresh()
    _make_pack(tmp)
    client = app.app.test_client()
    # negative zoom is rejected by Flask's <int:> converter (404 JSON), the rest are 204
    for path, allowed in (
        ("/tiles/testpack/99/0/0.png", {204}),
        ("/tiles/testpack/-1/0/0.png", {204, 404}),
        ("/tiles/testpack/1/5/0.png", {204}),
        ("/tiles/testpack/1/0/5.png", {204}),
        ("/tiles/testpack/30/0/0.png", {204}),
    ):
        st = client.get(path)
        assert st.status_code in allowed, (path, st.status_code)


def test_real_tile_is_still_served() -> None:
    """Positive control: the 204s above must not be hiding a broken tile path."""
    tmp = _fresh()
    _make_pack(tmp)
    client = app.app.test_client()
    st = client.get("/tiles/testpack/1/0/0.png")
    assert st.status_code == 200, st.status_code
    assert st.data.endswith(b"faketile"), st.data[:20]


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
