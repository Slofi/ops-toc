"""
GPS module for CD apps (Map App, Sonde App).

Two modes:
  - OM proxy (primary):  polls OverMesh /api/settings/gps — avoids serial conflicts
                         when OM is running on the same machine.
  - Direct serial (fallback): reads NMEA from a local serial port, used when
                         OM is not reachable or proxy is disabled.

If om_proxy=true AND a port is also configured, the watchdog automatically
falls back to direct serial when OM becomes unreachable.

Settings stored in gps_config.json next to the app.
"""
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

gps_state = {
    "lat": None, "lon": None, "alt": None,
    "sats": 0, "sats_view": 0, "fix": False,
}
gps_lock      = threading.Lock()
_stop_event   = threading.Event()
_gps_thread   = None
_gps_runtime  = {"port": "", "running": False, "port_present": False, "error": "", "source": ""}
_config_path: Path | None = None

_PROXY_FAIL_LIMIT = 5   # consecutive failures before falling back to serial


# ── Config ────────────────────────────────────────────────────────────────────

def init(config_dir):
    global _config_path
    _config_path = Path(config_dir) / "gps_config.json"
    cfg = load_config()
    if cfg.get("enabled"):
        _start_from_config(cfg)
    threading.Thread(target=_watchdog_loop, daemon=True).start()


def load_config() -> dict:
    if _config_path and _config_path.exists():
        try:
            return json.loads(_config_path.read_text())
        except Exception:
            pass
    return {"enabled": False, "port": "", "om_proxy": True, "om_url": "http://localhost:8082"}


def save_config(cfg: dict):
    if _config_path:
        _config_path.write_text(json.dumps(cfg, indent=2))


def list_ports() -> list:
    try:
        import serial.tools.list_ports
        return sorted(p.device for p in serial.tools.list_ports.comports())
    except Exception:
        return []


def port_present(port: str) -> bool:
    port = str(port or "").strip()
    if not port:
        return False
    try:
        import serial.tools.list_ports
        return any(p.device == port for p in serial.tools.list_ports.comports())
    except Exception:
        return False


def _om_reachable(om_url: str) -> bool:
    try:
        url = om_url.rstrip("/") + "/api/settings/gps"
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# ── NMEA parsing ──────────────────────────────────────────────────────────────

def _nmea_coord(val, hemi):
    if not val:
        return None
    try:
        raw = float(val)
        d = int(raw / 100)
        m = raw - d * 100
        dec = d + m / 60.0
        return -dec if hemi in ("S", "W") else dec
    except (ValueError, TypeError):
        return None


def _parse_gga(line):
    try:
        if "*" in line:
            line = line[:line.index("*")]
        p = line.split(",")
        if len(p) < 10:
            return
        fix_q = int(p[6]) if p[6] else 0
        lat   = _nmea_coord(p[2], p[3])
        lon   = _nmea_coord(p[4], p[5])
        sats  = int(p[7]) if p[7] else 0
        alt   = float(p[9]) if p[9] else None
        with gps_lock:
            gps_state["sats"] = sats
            gps_state["fix"]  = fix_q > 0
            if fix_q > 0 and lat is not None and lon is not None:
                gps_state["lat"] = lat
                gps_state["lon"] = lon
                gps_state["alt"] = int(alt) if alt is not None else None
    except Exception as e:
        log.debug(f"GPS GGA: {e}")


def _parse_gsv(line):
    try:
        if "*" in line:
            line = line[:line.index("*")]
        p = line.split(",")
        if len(p) >= 4 and p[3]:
            with gps_lock:
                gps_state["sats_view"] = int(p[3])
    except Exception as e:
        log.debug(f"GPS GSV: {e}")


# ── UBX helpers ───────────────────────────────────────────────────────────────

def _ubx(cls, id_, payload=b''):
    msg = bytes([0xB5, 0x62, cls, id_, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF]) + payload
    a, b = 0, 0
    for byte in msg[2:]:
        a = (a + byte) & 0xFF
        b = (b + a) & 0xFF
    return msg + bytes([a, b])


def _init_device(ser):
    for nmea_id in (0x00, 0x04, 0x03):
        ser.write(_ubx(0x06, 0x01, bytes([0xF0, nmea_id, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])))
        time.sleep(0.05)
    ser.write(_ubx(0x06, 0x01, bytes([0x01, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])))
    time.sleep(0.05)
    ser.reset_input_buffer()


# ── Direct serial reader ──────────────────────────────────────────────────────

def _reader(port, stop_event):
    import serial as _serial
    log.info(f"GPS: opening {port}")
    with gps_lock:
        _gps_runtime.update({"port": port, "running": False, "port_present": port_present(port),
                              "error": "", "source": "direct"})
    try:
        ser = _serial.Serial()
        ser.port     = port
        ser.baudrate = 9600
        ser.timeout  = 1
        ser.dtr      = False
        ser.open()
    except Exception as e:
        log.error(f"GPS: cannot open {port}: {e}")
        with gps_lock:
            _gps_runtime.update({"running": False, "port_present": port_present(port), "error": str(e)})
        return

    try:
        _init_device(ser)
    except Exception as e:
        log.warning(f"GPS: init failed (continuing): {e}")

    with gps_lock:
        _gps_runtime.update({"running": True, "port_present": True, "error": ""})

    while not stop_event.is_set():
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()
            if line.startswith(("$GPGGA", "$GNGGA")):
                _parse_gga(line)
            elif line.startswith(("$GPGSV", "$GNGSV")):
                _parse_gsv(line)
        except Exception as e:
            log.warning(f"GPS read: {e}")
            time.sleep(1)

    try:
        ser.close()
    except Exception:
        pass
    with gps_lock:
        _gps_runtime.update({"running": False, "port_present": port_present(port)})
    log.info("GPS: direct reader stopped")


# ── OM proxy reader ───────────────────────────────────────────────────────────

def _proxy_reader(om_url, fallback_port, stop_event):
    url = om_url.rstrip("/") + "/api/settings/gps"
    log.info(f"GPS: proxy mode → {url}")
    with gps_lock:
        _gps_runtime.update({"port": f"OM ({om_url})", "running": True,
                              "port_present": True, "error": "", "source": "proxy"})
    fails = 0
    while not stop_event.is_set():
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                d = json.loads(resp.read())
            with gps_lock:
                gps_state["fix"]       = d.get("fix", False)
                gps_state["lat"]       = d.get("lat")
                gps_state["lon"]       = d.get("lon")
                gps_state["alt"]       = d.get("alt")
                gps_state["sats"]      = d.get("sats", 0)
                gps_state["sats_view"] = d.get("sats_view", 0)
                _gps_runtime["error"]  = ""
            fails = 0
        except Exception as e:
            fails += 1
            with gps_lock:
                _gps_runtime["error"] = f"OM unreachable ({fails}x): {e}"
            if fails >= _PROXY_FAIL_LIMIT and fallback_port and port_present(fallback_port):
                log.warning(f"GPS: OM unreachable after {fails} tries — falling back to {fallback_port}")
                break   # watchdog will restart as serial reader
        time.sleep(2)

    with gps_lock:
        _gps_runtime.update({"running": False})
    log.info("GPS: proxy reader stopped")


# ── Public API ────────────────────────────────────────────────────────────────

def _stop_current():
    _stop_event.set()
    time.sleep(0.25)


def gps_start(port):
    global _gps_thread, _stop_event
    port = str(port or "").strip()
    if not port:
        return
    if not port_present(port):
        with gps_lock:
            _gps_runtime.update({"port": port, "running": False, "port_present": False,
                                  "error": "Port not connected.", "source": "direct"})
        return
    _stop_current()
    _stop_event = threading.Event()
    _gps_thread = threading.Thread(target=_reader, args=(port, _stop_event), daemon=True)
    _gps_thread.start()


def _start_proxy(om_url, fallback_port=""):
    global _gps_thread, _stop_event
    _stop_current()
    _stop_event = threading.Event()
    _gps_thread = threading.Thread(target=_proxy_reader,
                                   args=(om_url, fallback_port, _stop_event), daemon=True)
    _gps_thread.start()


def gps_stop():
    global _gps_thread
    _stop_event.set()
    with gps_lock:
        gps_state.update({"lat": None, "lon": None, "alt": None, "sats": 0, "sats_view": 0, "fix": False})
        _gps_runtime.update({"port": "", "running": False, "port_present": False, "error": "", "source": ""})
    _gps_thread = None


def _start_from_config(cfg):
    if cfg.get("om_proxy") and cfg.get("om_url"):
        _start_proxy(cfg["om_url"], fallback_port=cfg.get("port", ""))
    elif cfg.get("port"):
        gps_start(cfg["port"])


def _watchdog_loop():
    global _gps_thread
    while True:
        time.sleep(5)
        cfg = load_config()
        if not cfg.get("enabled"):
            continue
        if _gps_thread and _gps_thread.is_alive():
            continue
        # Thread died — decide what to restart
        with gps_lock:
            source = _gps_runtime.get("source", "")
        om_proxy = cfg.get("om_proxy", False)
        om_url   = cfg.get("om_url", "")
        port     = cfg.get("port", "")
        if om_proxy and om_url:
            if _om_reachable(om_url):
                _start_proxy(om_url, fallback_port=port)
            elif port and port_present(port):
                log.info("GPS watchdog: OM down, starting serial fallback")
                gps_start(port)
        elif port and port_present(port):
            gps_start(port)
