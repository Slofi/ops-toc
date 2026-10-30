#!/usr/bin/env python3
"""Regression tests for the GPS reader: one port, one reader, clean sentences.

Run: python3 tests/test_gps_single_reader.py

Covers the 2026-10-30 bug (S477). OPS-TOC was running with TWO `_reader` threads
and two open fds on /dev/ttyACM0. gps_start() had no lock, so a watchdog restart
racing an HTTP settings save could each start a reader; _stop_current() only ever
stopped the newest one, so the other kept the port open for the life of the
process. Two readers split the NMEA byte stream, each assembling lines out of the
other's halves, and the parsers trusted field positions without checking the
checksum — so a torn sentence became a "valid" fix hundreds of metres away, or a
speed of 18,150,846 km/h, for a second or two, then the next good sentence put it
back. That is the "position jumps far away and comes back" symptom.

`test_concurrent_starts_leave_one_reader` fails on the pre-fix gps.py (verified
against `git show HEAD:gps.py`), so these tests can actually fail.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
# GPS_UNDER_TEST lets this suite run against another copy — that is how the
# race test was proven to FAIL on the pre-fix gps.py.
GPS_PATH = os.environ.get("GPS_UNDER_TEST") or os.path.join(os.path.dirname(HERE), "gps.py")


# ── fake serial layer ─────────────────────────────────────────────────────────
class FakeSerial:
    """Stands in for pyserial. Records every open() so leaks are countable."""

    instances: list["FakeSerial"] = []
    lock = threading.Lock()

    def __init__(self):
        self.is_open = False
        self.closed_at = None
        self.timeout = None
        self.write_timeout = None
        self.port = None
        self.baudrate = None
        self.dtr = None

    def open(self):
        self.is_open = True
        with FakeSerial.lock:
            FakeSerial.instances.append(self)

    def close(self):
        self.is_open = False
        self.closed_at = time.monotonic()

    def reset_input_buffer(self):
        pass

    def write(self, _data):
        return len(_data)

    def readline(self):
        # Park like a real silent port would, so the reader stays in its loop.
        time.sleep(0.02)
        return b""

    @classmethod
    def open_count(cls) -> int:
        with cls.lock:
            return sum(1 for s in cls.instances if s.is_open)


def _load_gps():
    spec = importlib.util.spec_from_file_location("gps_under_test", GPS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # No hardware here: pretend the port exists and the device is silent.
    mod.port_present = lambda port: True                      # noqa: ARG005
    mod._baud_for_port = lambda port: 9600                    # noqa: ARG005
    mod._init_device = lambda ser: None                       # noqa: ARG005
    fake_serial = types.ModuleType("serial")
    fake_serial.Serial = FakeSerial
    sys.modules["serial"] = fake_serial
    mod._gps_runtime.update({"running": False})
    return mod


def _stop_all(mod, timeout=3.0):
    mod.gps_stop()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if FakeSerial.open_count() == 0:
            return
        time.sleep(0.02)


def _live_readers(mod) -> int:
    return sum(1 for t in threading.enumerate()
               if t.name.endswith("(_reader)") and t.is_alive())


# ── checksum ──────────────────────────────────────────────────────────────────
def test_checksum_accepts_published_sentences() -> None:
    """Positive control: sentences from the NMEA standard's own examples."""
    mod = _load_gps()
    good = [
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
        "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
        "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75",
    ]
    for line in good:
        assert mod._nmea_ok(line), f"rejected a valid sentence: {line}"


def test_checksum_rejects_torn_sentences() -> None:
    """The failure shape: a sentence split between two competing readers."""
    mod = _load_gps()
    line = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    torn = line[:20] + line[40:]              # bytes stolen in the middle
    bad = [
        torn,
        line.replace(",1,08,", ",08,"),        # dropped field, checksum not updated
        line[:-2],                             # checksum cut off
        line.replace("*47", ""),               # no checksum at all
        line.replace("*47", "*48"),            # wrong checksum
        line[1:],                              # missing '$'
        "",
    ]
    for item in bad:
        assert not mod._nmea_ok(item), f"accepted a torn sentence: {item!r}"


# ── the reader-start race ─────────────────────────────────────────────────────
def test_concurrent_starts_leave_one_reader() -> None:
    """N simultaneous gps_start() calls must leave exactly one open port.

    Pre-fix this produced one reader per caller (the watchdog plus an HTTP save
    was the real-world pair), which is what split the NMEA stream.
    """
    mod = _load_gps()
    FakeSerial.instances.clear()
    errors: list[BaseException] = []

    def start():
        try:
            mod.gps_start("/dev/ttyFAKE0")
        except BaseException as exc:          # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    time.sleep(0.4)                            # let losers notice the generation bump

    try:
        assert not errors, f"gps_start raised: {errors[0]!r}"
        assert FakeSerial.open_count() == 1, (
            f"{FakeSerial.open_count()} open serial ports, expected 1 "
            f"({FakeSerial.instances})")
        assert _live_readers(mod) == 1, f"{_live_readers(mod)} live _reader threads, expected 1"
    finally:
        _stop_all(mod)


def test_restart_releases_the_port() -> None:
    """A settings change must close the old fd before/while the new reader runs."""
    mod = _load_gps()
    FakeSerial.instances.clear()
    try:
        mod.gps_start("/dev/ttyFAKE0")
        time.sleep(0.3)
        mod.gps_start("/dev/ttyFAKE0")         # same save the UI makes
        time.sleep(0.3)
        assert FakeSerial.open_count() == 1, f"{FakeSerial.open_count()} ports left open"
        assert _live_readers(mod) == 1, f"{_live_readers(mod)} live _reader threads"
    finally:
        _stop_all(mod)
        assert FakeSerial.open_count() == 0, "gps_stop() left the port open"


def test_stop_then_start_does_not_orphan() -> None:
    """gps_stop() -> gps_start() is what the UI does for manual/no-port states."""
    mod = _load_gps()
    FakeSerial.instances.clear()
    try:
        for _ in range(3):
            mod.gps_start("/dev/ttyFAKE0")
            time.sleep(0.15)
            mod.gps_stop()
            time.sleep(0.15)
            assert FakeSerial.open_count() == 0, "a reader survived gps_stop()"
        mod.gps_start("/dev/ttyFAKE0")
        time.sleep(0.3)
        assert FakeSerial.open_count() == 1, f"{FakeSerial.open_count()} open ports"
    finally:
        _stop_all(mod)


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
        except Exception as exc:   # a missing helper still counts as a failure,
            failed += 1            # not as a crashed suite (old gps.py copies)
            print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
