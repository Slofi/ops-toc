#!/usr/bin/env python3
"""Regression tests for the GitHub updater (S455 migration).

The updater is the part that touches a live checkout, so every guard is exercised
against REAL throwaway git repos: it must refuse to reset a tree that is ahead, must
stash local edits instead of losing them, must survive an unreachable origin, and must
land exactly on origin's commit when it is behind.

Run: python3 tests/test_updater.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

GIT_ID = ["-c", "user.name=sweep", "-c", "user.email=sweep@example.com"]


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stdout}{proc.stderr}")
    return (proc.stdout or "").strip()


def make_repos() -> tuple[Path, Path]:
    """A bare origin + a working clone of it, one commit deep."""
    base = Path(tempfile.mkdtemp())
    origin = base / "origin.git"
    git(base, "init", "--bare", "-q", str(origin))
    seed = base / "seed"
    git(base, "clone", "-q", str(origin), str(seed))
    (seed / "app.py").write_text("print('v1')\n")
    (seed / "requirements.txt").write_text("flask\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "v1")
    git(seed, "push", "-q", "origin", "HEAD:refs/heads/master")
    work = base / "work"
    git(base, "clone", "-q", str(origin), str(work))
    return base, work


def publish_commit(origin: Path, base: Path, text: str) -> str:
    seed = base / "seed"
    git(seed, "pull", "-q", "origin", "master")
    (seed / "app.py").write_text(text)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "v2")
    git(seed, "push", "-q", "origin", "HEAD:refs/heads/master")
    return git(origin, "rev-parse", "--short", "master")


def run_job(work: Path) -> dict:
    with app._update_lock:
        app._update_state.update({"running": False, "ok": None, "message": "", "log": []})
    app._update_run_job(target=work)
    return dict(app._update_state)


def test_not_a_checkout_is_refused() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = run_job(tmp)
    assert state["ok"] is False and "not a git checkout" in state["message"].lower(), state


def test_behind_updates_to_origin() -> None:
    base, work = make_repos()
    remote = publish_commit(base / "origin.git", base, "print('v2')\n")
    state = run_job(work)
    assert state["ok"] is True, state
    assert git(work, "rev-parse", "--short", "HEAD") == remote
    assert (work / "app.py").read_text() == "print('v2')\n"
    assert "Restart required" in state["message"], state["message"]


def test_already_up_to_date_does_not_reset() -> None:
    base, work = make_repos()
    before = git(work, "rev-parse", "HEAD")
    state = run_job(work)
    assert state["ok"] is True and "Already up to date" in state["message"], state
    assert git(work, "rev-parse", "HEAD") == before


def test_ahead_is_refused() -> None:
    base, work = make_repos()
    (work / "app.py").write_text("print('local')\n")
    git(work, "commit", "-q", "-am", "local work")
    head = git(work, "rev-parse", "HEAD")
    publish_commit(base / "origin.git", base, "print('v2')\n")
    state = run_job(work)
    assert state["ok"] is False and "ahead" in state["message"].lower(), state
    assert git(work, "rev-parse", "HEAD") == head, "an ahead tree must not be touched"


def test_dirty_edits_are_stashed_not_lost() -> None:
    base, work = make_repos()
    publish_commit(base / "origin.git", base, "print('v2')\n")
    (work / "app.py").write_text("print('my uncommitted edit')\n")
    state = run_job(work)
    assert state["ok"] is True, state
    assert (work / "app.py").read_text() == "print('v2')\n", "the update should win the tree"
    stashes = git(work, "stash", "list")
    assert "ops-toc-update-" in stashes, stashes
    assert "my uncommitted edit" in git(work, "stash", "show", "-p", "stash@{0}")


def test_unreachable_origin_changes_nothing() -> None:
    base, work = make_repos()
    head = git(work, "rev-parse", "HEAD")
    git(work, "remote", "set-url", "origin", str(base / "gone.git"))
    state = run_job(work)
    assert state["ok"] is False, state
    assert git(work, "rev-parse", "HEAD") == head
    assert any("Error" in line for line in state["log"]), state["log"]


def test_ahead_behind_counting() -> None:
    base, work = make_repos()
    publish_commit(base / "origin.git", base, "print('v2')\n")
    info = app._git_update_info(fetch=True, cwd=work)
    assert info["behind"] == 1 and info["ahead"] == 0, info
    assert info["remote_commit"], info
    assert info["fetch_ok"] is True


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {str(exc)[:400]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
