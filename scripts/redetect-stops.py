#!/usr/bin/env python3
"""Re-run halt detection over saved tracks and persist the result.

Why this exists: `kind` (stationary/stopped) is DERIVED from a stop's duration, so a
threshold change needs no migration. But a change to the *detection* rule does — this
is how the long stops recovered on 2026-10-17 (S455) reached the tracks that were
already saved. Notes and tags on existing stops are carried over by start time, and
`updated_at` is left alone so the track list keeps its order.

Usage:
    ./venv/bin/python scripts/redetect-stops.py            # dry run, prints a summary
    ./venv/bin/python scripts/redetect-stops.py --apply    # writes (BACK UP THE DB FIRST)
    ./venv/bin/python scripts/redetect-stops.py --apply --only 77,78

A track whose stop list would not change is not written at all.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402

MERGE_MATCH_S = 120  # an old stop within this many seconds of a new one is "the same stop"


def merge_notes(old: list[dict], new: list[dict]) -> tuple[list[dict], int]:
    """Carry note/tag from the old stop list onto matching new stops. Returns (stops, carried)."""
    carried = 0
    for s in new:
        best, best_d = None, None
        for o in old:
            if not (o.get("tag") or o.get("note")):
                continue
            if s.get("start_ts") is None or o.get("start_ts") is None:
                continue
            d = abs(int(s["start_ts"]) - int(o["start_ts"]))
            if best_d is None or d < best_d:
                best, best_d = o, d
        if best is not None and best_d is not None and best_d <= MERGE_MATCH_S:
            s["tag"] = best.get("tag") or ""
            s["note"] = best.get("note") or ""
            carried += 1
    return new, carried


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the new stop lists")
    ap.add_argument("--only", default="", help="comma-separated track ids")
    args = ap.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip()}
    db_path = str(Path(os.environ.get("MAP_APP_DB", app.DB_PATH)))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro" if not args.apply else db_path, uri=not args.apply)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT id, name, points_json, stops_json FROM tracks ORDER BY id").fetchall()
    changed = 0
    total_before = total_after = 0
    for r in rows:
        if only and r["id"] not in only:
            continue
        try:
            points = json.loads(r["points_json"] or "[]")
        except ValueError:
            print(f"track {r['id']}: unreadable points_json — skipped")
            continue
        old = json.loads(r["stops_json"] or "[]") if r["stops_json"] else []
        new = app._detect_stops(points)
        new, carried = merge_notes(old, new)
        total_before += len(old)
        total_after += len(new)
        if not new and not old:
            continue
        same = (len(new) == len(old)
                and all(a.get("start_ts") == b.get("start_ts") and a.get("kind") == b.get("kind")
                        for a, b in zip(new, old)))
        if same:
            continue
        changed += 1
        kinds = ", ".join(f"{s['duration_s']}s/{s['kind']}" for s in new) or "none"
        print(f"track {r['id']:>3} {str(r['name'])[:38]:38} {len(old)} -> {len(new)} stops"
              f" (notes carried: {carried})  [{kinds}]")
        if args.apply:
            conn.execute("UPDATE tracks SET stops_json=? WHERE id=?",
                         (json.dumps(new, separators=(",", ":")), r["id"]))
    if args.apply:
        conn.commit()
    print(f"\n{'applied' if args.apply else 'dry run'}: {changed} track(s) changed, "
          f"stops {total_before} -> {total_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
