#!/usr/bin/env python3
"""Run every OPS-TOC test suite in one go; exit 0 only when all are green.

Usage: ./venv/bin/python tests/run_all.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = sorted(p for p in HERE.glob("test_*.py"))


def main() -> int:
    failed = []
    for suite in SUITES:
        proc = subprocess.run([sys.executable, str(suite)], capture_output=True, text=True, timeout=900)
        lines = (proc.stdout or "").strip().splitlines()
        tail = lines[-1] if lines else "(no output)"
        ok = proc.returncode == 0 and "passed" in tail
        print(f"{'ok  ' if ok else 'FAIL'} {suite.stem:24} {tail}")
        if not ok:
            failed.append(suite.stem)
            print((proc.stdout or "")[-1500:])
            print((proc.stderr or "")[-800:])
    print(f"\n{len(SUITES) - len(failed)}/{len(SUITES)} suites green")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
