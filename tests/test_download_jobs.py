#!/usr/bin/env python3
"""Regression tests for download-job bookkeeping (S455 re-sweep).

Two defects found in the second sweep, both introduced by the first sweep's fix:
  * path reservation renamed a REPAIR/EXTEND job's target pack (their path is the
    pack being repaired, so they must never be renamed);
  * resuming an ERRORED job while its id was still marked active set it to
    "running" with no worker behind it — a job that never moves again.

Run: python3 tests/test_download_jobs.py
"""
from __future__ import annotations

import os
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
    with app.download_condition:
        app.download_jobs.clear()
        app.download_queue.clear()
        app._active_jobs.clear()
        app._paused_jobs.clear()
        app._cancelled_jobs.clear()
    return tmp


def _job(job_id, kind, path, status="running"):
    return {"id": job_id, "kind": kind, "status": status, "name": job_id, "layer_name": "",
            "path": str(path), "total": 1, "done": 0, "saved": 0, "failed": 0,
            "created_at": 1}


def test_new_download_reserves_a_free_path() -> None:
    tmp = _fresh()
    path = tmp / "mbtiles" / "pack.mbtiles"
    with app.download_condition:
        app.download_jobs["a"] = _job("a", "download", path)
    payload = {"tiles": [(1, 1, 1)], "path": str(path), "url": "http://x/{z}/{x}/{y}", "metadata": {}}
    out = app.enqueue_download_job(_job("b", "download", path, status="queued"), payload)
    assert out["path"] != str(path), out["path"]
    assert out["path"].endswith("-2.mbtiles"), out["path"]
    assert payload["path"] == out["path"]


def test_repair_keeps_its_target_path() -> None:
    """A repair operates on an existing pack — its path must NEVER be renamed."""
    tmp = _fresh()
    path = tmp / "mbtiles" / "existing.mbtiles"
    with app.download_condition:
        app.download_jobs["other"] = _job("other", "download", path)
    payload = {"tiles": [(1, 1, 1)], "path": str(path), "url": "http://x/{z}/{x}/{y}",
               "metadata": {}, "repair_existing": True}
    out = app.enqueue_download_job(_job("r", "repair", path, status="queued"), payload)
    assert out["path"] == str(path), out["path"]
    assert payload["path"] == str(path)


def test_resume_error_job_enqueues_even_if_marked_active() -> None:
    tmp = _fresh()
    path = tmp / "mbtiles" / "p.mbtiles"
    with app.download_condition:
        job = _job("e", "download", path, status="error")
        job["payload"] = {"tiles": [(1, 1, 1)], "path": str(path)}
        app.download_jobs["e"] = job
        app._active_jobs.add("e")  # the window between update_job(error) and finally
    client = app.app.test_client()
    st = client.post("/api/downloads/e/resume")
    assert st.status_code == 200, st.status_code
    with app.download_condition:
        assert app.download_jobs["e"]["status"] == "queued", app.download_jobs["e"]["status"]
        assert "e" in app.download_queue


def test_resume_without_retained_tiles_is_refused() -> None:
    tmp = _fresh()
    with app.download_condition:
        job = _job("n", "download", tmp / "mbtiles" / "n.mbtiles", status="error")
        job["payload"] = {}
        app.download_jobs["n"] = job
    client = app.app.test_client()
    st = client.post("/api/downloads/n/resume")
    assert st.status_code == 400, st.status_code


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
