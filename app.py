from __future__ import annotations

import calendar
import gzip
import io
import json
import math
import os
import re
import shutil
import subprocess
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request
import urllib.error
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context


APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MAP_APP_DATA_DIR", "/home/slofi/maps"))
DB_PATH = Path(os.environ.get("MAP_APP_DB", DATA_DIR / "map_app.db"))
MBTILES_DIR = Path(os.environ.get("MAP_APP_MBTILES_DIR", DATA_DIR / "mbtiles"))
DEFAULT_MBTILES = os.environ.get("MAP_APP_DEFAULT_MBTILES", "")
PORT = int(os.environ.get("MAP_APP_PORT", "8090"))
DOWNLOAD_JOB_RETENTION_DAYS = int(os.environ.get("MAP_APP_DOWNLOAD_JOB_RETENTION_DAYS", "7"))
TILE_DOWNLOAD_RETRIES = int(os.environ.get("MAP_APP_TILE_DOWNLOAD_RETRIES", "2"))
TILE_FETCH_WORKERS = int(os.environ.get("OPS_TOC_TILE_WORKERS", "16"))
TILE_FETCH_BATCH = 64
DEFAULT_TILE_ESTIMATE_BYTES = int(os.environ.get("MAP_APP_TILE_ESTIMATE_BYTES", "12000"))

# Read-only live-map providers. OPS-TOC presents their data but the specialist
# apps remain the owners of decoding, radio state, and transmissions.
OVERLAY_URLS = {
    "om": os.environ.get("OPS_TOC_OM_URL", "http://localhost:8082").rstrip("/"),
    "adsb": os.environ.get("OPS_TOC_ADSB_URL", "http://localhost:5400").rstrip("/"),
    "ais": os.environ.get("OPS_TOC_AIS_URL", "http://localhost:5410").rstrip("/"),
    "sonde": os.environ.get("OPS_TOC_SONDE_URL", "http://localhost:5100").rstrip("/"),
    "autorx": os.environ.get("OPS_TOC_AUTORX_URL", "http://localhost:5000").rstrip("/"),
}
OVERLAY_TIMEOUT = float(os.environ.get("OPS_TOC_OVERLAY_TIMEOUT", "1.5"))

# TOC log — shared with OM via overmesh_prefs.db
OM_PREFS_DB = os.environ.get("TOC_LOG_DB", os.path.expanduser("~/overmesh/overmesh_prefs.db"))
_MISSION_RE = re.compile(r'\*\*(?:Mission|Mission\s*/\s*Folder):\*\*\s*(.+)', re.I)
_POS_RE     = re.compile(r'\*\*GPS:\*\*\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', re.I)
_TRACK_RE   = re.compile(r'\*\*Track:\*\*.*?#(\d+)', re.I)
_LOG_CATS   = {'NOTE', 'PLAN', 'SITREP', 'ALERT', 'ACTION', 'COMMS', 'CONTACT', 'POSITION', 'INTEL', 'WEATHER', 'TRACK'}

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # no static-file caching during active development
download_jobs: dict[str, dict[str, Any]] = {}
download_lock = threading.Lock()
download_condition = threading.Condition(download_lock)
download_queue: list[str] = []
download_worker_started = False
_cancelled_jobs: set[str] = set()
_paused_jobs: set[str] = set()
_active_jobs: set[str] = set()


@app.after_request
def add_cors_headers(resp):
    # OM on the same machine reads OPS-TOC's tile catalog from localhost:8090.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return resp


def now_ts() -> int:
    return int(time.time())


def _overlay_request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None,
                          timeout: float | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or OVERLAY_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = detail.get("error") or detail.get("message") or f"HTTP {exc.code}"
        except Exception:
            message = f"HTTP {exc.code}"
        raise RuntimeError(message) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(str(getattr(exc, "reason", exc))) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Provider returned invalid JSON") from exc


def _overlay_probe(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            resp.read(64)
        return True
    except Exception:
        return False


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MBTILES_DIR.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_dirs()
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS markers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lat         REAL NOT NULL,
                lon         REAL NOT NULL,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                emoji       TEXT DEFAULT 'pin',
                category    TEXT DEFAULT 'note',
                source      TEXT DEFAULT 'map-app',
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drawings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                kind        TEXT NOT NULL,
                color       TEXT DEFAULT '#f59e0b',
                data_json   TEXT NOT NULL,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                color       TEXT DEFAULT '#e8b04f',
                folder      TEXT DEFAULT '',
                points_json TEXT NOT NULL,
                distance_m  REAL DEFAULT 0,
                source      TEXT DEFAULT 'gps',
                started_at  INTEGER,
                ended_at    INTEGER,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS download_jobs (
                id           TEXT PRIMARY KEY,
                kind         TEXT NOT NULL,
                status       TEXT NOT NULL,
                name         TEXT NOT NULL,
                layer_name   TEXT DEFAULT '',
                path         TEXT NOT NULL,
                total        INTEGER DEFAULT 0,
                done         INTEGER DEFAULT 0,
                saved        INTEGER DEFAULT 0,
                failed       INTEGER DEFAULT 0,
                created_at   INTEGER NOT NULL,
                queued_at    INTEGER,
                started_at   INTEGER,
                finished_at  INTEGER,
                error        TEXT DEFAULT '',
                payload_json TEXT NOT NULL
            )
            """
        )
        for _tcol in (
            "folder TEXT DEFAULT ''",
            "report_json TEXT DEFAULT ''",
            "stops_json TEXT DEFAULT ''",
        ):
            try:
                conn.execute(f"ALTER TABLE tracks ADD COLUMN {_tcol}")
            except Exception:
                pass
        # Markers gained folders 2026-08-11 (S404). a3c38dc had shipped the
        # frontend grouping for this in June but never the column or the input,
        # which also broke Add/Edit Marker outright — see that changelog entry.
        try:
            conn.execute("ALTER TABLE markers ADD COLUMN folder TEXT DEFAULT ''")
        except Exception:
            pass


def _clean_text(value: Any, max_len: int, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text[:max_len]


def _float(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    if math.isnan(out) or math.isinf(out):
        raise ValueError(f"Invalid {field}")
    return out


def _coord(value: Any, field: str) -> float:
    """_float plus an on-Earth range check. Added 2026-08-11 (S404 sweep):
    nothing validated latitude/longitude anywhere, so a malformed GPX import or
    a client bug could store lat=999 — which then breaks fitBounds and puts a
    marker somewhere impossible. NaN/Inf were already rejected by _float."""
    out = _float(value, field)
    limit = 90.0 if field.startswith("lat") else 180.0
    if not -limit <= out <= limit:
        raise ValueError(f"Invalid {field}")
    return out


def _int(value: Any, field: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    return out


def _safe_slug(value: str, default: str = "map") -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    slug = "-".join(part for part in raw.split("-") if part)
    return (slug or default)[:80]


def _marker_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "lat": row["lat"],
        "lon": row["lon"],
        "name": row["name"],
        "description": row["description"] or "",
        "emoji": row["emoji"] or "pin",
        "category": row["category"] or "note",
        "folder": (row["folder"] if "folder" in row.keys() else "") or "",
        "source": row["source"] or "map-app",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _drawing_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        data = json.loads(row["data_json"])
    except (TypeError, ValueError):
        data = None
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "color": row["color"] or "#f59e0b",
        "data": data,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _track_row(row: sqlite3.Row, include_points: bool = True) -> dict[str, Any]:
    """With include_points=False, omit the point array but still report
    `point_count`. The list endpoint uses that: points were 99.85% of a 21.5 MB
    /api/tracks response (167k points across 63 tracks) and the list only ever
    needed the count — see the 2026-08-11 changelog entry."""
    keys = row.keys()
    # Summary mode must NOT parse points_json. Omitting the array from the
    # response but still json.loads()-ing it to count made /api/tracks take
    # 0.46 s for 32 KB while a single 753 KB track took 0.066 s — the cost was
    # never the transfer, it was parsing 167k points on every list request.
    # The caller supplies point_count via SQL json_array_length() instead.
    if include_points:
        try:
            points = json.loads(row["points_json"])
        except (TypeError, ValueError):
            points = []
        n_points = len(points)
    else:
        points = []
        n_points = int(row["point_count"]) if "point_count" in keys and row["point_count"] is not None else 0
    report: dict[str, Any] = {}
    if "report_json" in keys and row["report_json"]:
        try:
            report = json.loads(row["report_json"]) or {}
        except (TypeError, ValueError):
            report = {}
    stops: list[Any] = []
    if "stops_json" in keys and row["stops_json"]:
        try:
            stops = json.loads(row["stops_json"]) or []
        except (TypeError, ValueError):
            stops = []
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "color": row["color"] or "#e8b04f",
        "folder": row["folder"] or "",
        **({"points": points if isinstance(points, list) else []} if include_points else {}),
        "point_count": n_points,
        "distance_m": row["distance_m"] or 0,
        "source": row["source"] or "gps",
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "report": report if isinstance(report, dict) else {},
        "stops": stops if isinstance(stops, list) else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_mbtiles() -> list[dict[str, Any]]:
    files: list[Path] = []
    if DEFAULT_MBTILES:
        p = Path(DEFAULT_MBTILES).expanduser()
        if p.exists():
            files.append(p)
    files.extend(sorted(MBTILES_DIR.glob("*.mbtiles")))

    seen = set()
    layers = []
    for idx, path in enumerate(files):
        real = str(path.resolve())
        if real in seen:
            continue
        seen.add(real)
        layer_id = path.stem.replace(" ", "-").lower() or f"layer-{idx}"
        name = path.stem.replace("_", " ").replace("-", " ").title()
        meta = {}
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                rows = conn.execute("SELECT name,value FROM metadata").fetchall()
                meta = {r[0]: r[1] for r in rows}
                tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
        except sqlite3.Error:
            meta = {}
            tile_count = 0
        layers.append(
            {
                "id": layer_id,
                "name": meta.get("name") or name,
                "path": real,
                "format": (meta.get("format") or "png").lower(),
                "minzoom": int(meta.get("minzoom") or 0),
                "maxzoom": int(meta.get("maxzoom") or 18),
                "bounds": meta.get("bounds") or "",
                "size": path.stat().st_size if path.exists() else 0,
                "tile_count": tile_count,
                "description": meta.get("description") or "",
                "attribution": meta.get("attribution") or "",
                "source_url": meta.get("source_url") or "",
                "source_layer_name": meta.get("source_layer_name") or "",
                "source_min_zoom": meta.get("source_min_zoom") or meta.get("minzoom") or "",
                "source_max_zoom": meta.get("source_max_zoom") or meta.get("maxzoom") or "",
                "mtime": path.stat().st_mtime if path.exists() else 0,
                "map_app_tile_url": f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
            }
        )
    return layers


def find_mbtiles(layer_id: str) -> dict[str, Any] | None:
    for layer in list_mbtiles():
        if layer["id"] == layer_id:
            return layer
    return None


def detect_mimetype(data: bytes, fmt: str) -> str:
    if fmt in {"jpg", "jpeg"} or data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if fmt == "webp" or data[:4] == b"RIFF":
        return "image/webp"
    if fmt == "pbf" or fmt == "mvt":
        return "application/vnd.mapbox-vector-tile"
    return "image/png"


def tile_range_for_bounds(bounds: dict[str, float], zoom: int) -> list[tuple[int, int, int]]:
    min_lat = max(min(bounds["south"], bounds["north"]), -85.05112878)
    max_lat = min(max(bounds["south"], bounds["north"]), 85.05112878)
    min_lon = max(min(bounds["west"], bounds["east"]), -180)
    max_lon = min(max(bounds["west"], bounds["east"]), 180)
    n = 2**zoom

    def lon_to_x(lon: float) -> int:
        return int((lon + 180.0) / 360.0 * n)

    def lat_to_y(lat: float) -> int:
        lat_rad = math.radians(lat)
        return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    x1 = max(0, min(n - 1, lon_to_x(min_lon)))
    x2 = max(0, min(n - 1, lon_to_x(max_lon)))
    y1 = max(0, min(n - 1, lat_to_y(max_lat)))
    y2 = max(0, min(n - 1, lat_to_y(min_lat)))
    tiles = []
    for x in range(min(x1, x2), max(x1, x2) + 1):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            tiles.append((zoom, x, y))
    return tiles


def tile_count_for_bounds(bounds: dict[str, float], zoom: int) -> int:
    min_lat = max(min(bounds["south"], bounds["north"]), -85.05112878)
    max_lat = min(max(bounds["south"], bounds["north"]), 85.05112878)
    min_lon = max(min(bounds["west"], bounds["east"]), -180)
    max_lon = min(max(bounds["west"], bounds["east"]), 180)
    n = 2**zoom

    def lon_to_x(lon: float) -> int:
        return int((lon + 180.0) / 360.0 * n)

    def lat_to_y(lat: float) -> int:
        lat_rad = math.radians(lat)
        return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    x1 = max(0, min(n - 1, lon_to_x(min_lon)))
    x2 = max(0, min(n - 1, lon_to_x(max_lon)))
    y1 = max(0, min(n - 1, lat_to_y(max_lat)))
    y2 = max(0, min(n - 1, lat_to_y(min_lat)))
    return (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1)


def tiles_for_bounds(bounds: dict[str, float], min_zoom: int, max_zoom: int) -> list[tuple[int, int, int]]:
    tiles = []
    for z in range(min_zoom, max_zoom + 1):
        tiles.extend(tile_range_for_bounds(bounds, z))
    return tiles


def tile_count_for_zoom_range(bounds: dict[str, float], min_zoom: int, max_zoom: int) -> int:
    return sum(tile_count_for_bounds(bounds, z) for z in range(min_zoom, max_zoom + 1))


def substitute_tile_url(template: str, z: int, x: int, y: int) -> str:
    subdomain = "abc"[abs(x + y) % 3]
    return (
        template.replace("{s}", subdomain)
        .replace("{z}", str(z))
        .replace("{x}", str(x))
        .replace("{y}", str(y))
        .replace("{r}", "")
    )


def init_mbtiles(conn: sqlite3.Connection, metadata: dict[str, str]) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row)")
    conn.execute("DELETE FROM metadata")
    conn.executemany("INSERT INTO metadata (name,value) VALUES (?,?)", sorted(metadata.items()))


def update_mbtiles_metadata(conn: sqlite3.Connection, metadata: dict[str, str]) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)")
    conn.execute("DELETE FROM metadata")
    conn.executemany("INSERT INTO metadata (name,value) VALUES (?,?)", sorted(metadata.items()))


def patch_mbtiles_metadata(path: Path, updates: dict[str, str]) -> dict[str, str]:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)")
        rows = conn.execute("SELECT name,value FROM metadata").fetchall()
        metadata = {str(row[0]): str(row[1]) for row in rows}
        metadata.update({k: str(v) for k, v in updates.items()})
        update_mbtiles_metadata(conn, metadata)
        conn.commit()
    return metadata


def service_action_soon(action: str) -> None:
    time.sleep(1)
    subprocess.run(["systemctl", "--user", action, "ops-toc.service"], cwd=APP_ROOT, check=False)


def run_git(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    key = Path.home() / ".ssh" / "id_ed25519"
    if key.exists():
        env["GIT_SSH_COMMAND"] = f"ssh -i {key} -o BatchMode=yes -o StrictHostKeyChecking=no"
    return subprocess.run(
        ["git", *args],
        cwd=APP_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def git_version_payload(check_remote: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True, "is_git": (APP_ROOT / ".git").exists()}
    current = run_git(["rev-parse", "--short", "HEAD"])
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    remote = run_git(["config", "--get", "remote.origin.url"])
    payload.update(
        {
            "current": current.stdout.strip() if current.returncode == 0 else "",
            "branch": branch.stdout.strip() if branch.returncode == 0 else "",
            "remote": remote.stdout.strip() if remote.returncode == 0 else "",
        }
    )
    if not payload["is_git"] or current.returncode != 0:
        payload["ok"] = False
        payload["error"] = "OPS-TOC directory is not a usable git checkout."
        return payload
    if check_remote:
        ref = payload["branch"] if payload["branch"] and payload["branch"] != "HEAD" else "master"
        latest = run_git(["ls-remote", "origin", ref], timeout=20)
        if latest.returncode == 0 and latest.stdout.strip():
            full = latest.stdout.split()[0]
            payload["latest"] = full[:7]
            payload["up_to_date"] = full.startswith(payload["current"])
        else:
            payload["remote_error"] = latest.stdout.strip() or "Unable to check remote version."
    return payload


def update_job(job_id: str, **updates: Any) -> None:
    with download_lock:
        if job_id in download_jobs:
            download_jobs[job_id].update(updates)
            persist_download_job(download_jobs[job_id])
        download_condition.notify_all()


def _job_payload_json(job: dict[str, Any]) -> str:
    if job.get("status") in {"done", "error", "cancelled"}:
        return "{}"
    return json.dumps(job.get("payload") or {}, separators=(",", ":"))


def persist_download_job(job: dict[str, Any]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO download_jobs (
                id, kind, status, name, layer_name, path, total, done, saved, failed,
                created_at, queued_at, started_at, finished_at, error, payload_json
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                kind=excluded.kind,
                status=excluded.status,
                name=excluded.name,
                layer_name=excluded.layer_name,
                path=excluded.path,
                total=excluded.total,
                done=excluded.done,
                saved=excluded.saved,
                failed=excluded.failed,
                created_at=excluded.created_at,
                queued_at=excluded.queued_at,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                error=excluded.error,
                payload_json=excluded.payload_json
            """,
            (
                job["id"],
                job.get("kind") or "download",
                job.get("status") or "queued",
                job.get("name") or "Offline map",
                job.get("layer_name") or "",
                job.get("path") or "",
                int(job.get("total") or 0),
                int(job.get("done") or 0),
                int(job.get("saved") or 0),
                int(job.get("failed") or 0),
                int(job.get("created_at") or now_ts()),
                job.get("queued_at"),
                job.get("started_at"),
                job.get("finished_at"),
                job.get("error") or "",
                _job_payload_json(job),
            ),
        )


def start_download_worker_locked() -> None:
    global download_worker_started
    if not download_worker_started:
        threading.Thread(target=download_worker, daemon=True).start()
        download_worker_started = True


def _download_job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    status = row["status"]
    if status in {"done", "error", "cancelled"}:
        payload = {}
    else:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": status,
        "name": row["name"],
        "layer_name": row["layer_name"] or "",
        "path": row["path"],
        "total": row["total"] or 0,
        "done": row["done"] or 0,
        "saved": row["saved"] or 0,
        "failed": row["failed"] or 0,
        "created_at": row["created_at"],
        "queued_at": row["queued_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"] or "",
        "payload": payload,
    }


def load_download_jobs() -> None:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM download_jobs ORDER BY created_at").fetchall()
    with download_condition:
        download_jobs.clear()
        download_queue.clear()
        _paused_jobs.clear()
        _active_jobs.clear()
        for row in rows:
            job = _download_job_from_row(row)
            status = job.get("status")
            if status == "running":
                job.update({"status": "queued", "done": 0, "saved": 0, "failed": 0, "started_at": None, "error": ""})
                persist_download_job(job)
                status = "queued"
            download_jobs[job["id"]] = job
            if status == "queued":
                download_queue.append(job["id"])
            elif status == "paused":
                _paused_jobs.add(job["id"])
        if download_queue:
            start_download_worker_locked()
        download_condition.notify_all()


def cleanup_download_job_history() -> None:
    cutoff = now_ts() - DOWNLOAD_JOB_RETENTION_DAYS * 86400
    with get_db() as conn:
        conn.execute(
            """
            DELETE FROM download_jobs
            WHERE status IN ('done', 'error', 'cancelled')
              AND finished_at IS NOT NULL
              AND finished_at < ?
            """,
            (cutoff,),
        )


def enqueue_download_job(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    job = dict(job)
    job["status"] = "queued"
    job["queued_at"] = now_ts()
    job["payload"] = payload
    with download_condition:
        download_jobs[job["id"]] = job
        download_queue.append(job["id"])
        persist_download_job(job)
        start_download_worker_locked()
        download_condition.notify_all()
    return {k: v for k, v in job.items() if k != "payload"}


def download_worker() -> None:
    while True:
        with download_condition:
            while not download_queue:
                download_condition.wait()
            job_id = download_queue.pop(0)
            job = download_jobs.get(job_id)
            if not job or job.get("status") == "cancelled":
                continue
            _active_jobs.add(job_id)
            while job_id in _paused_jobs and job.get("status") != "cancelled":
                job["status"] = "paused"
                persist_download_job(job)
                download_condition.wait()
            if job_id in _cancelled_jobs or job.get("status") == "cancelled":
                job["status"] = "cancelled"
                job["finished_at"] = now_ts()
                _cancelled_jobs.discard(job_id)
                _active_jobs.discard(job_id)
                persist_download_job(job)
                continue
            job["status"] = "running"
            job["started_at"] = now_ts()
            persist_download_job(job)
            payload = dict(job.get("payload") or {})
        try:
            run_download_job(job_id, payload)
        finally:
            with download_condition:
                _active_jobs.discard(job_id)
                download_condition.notify_all()


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in job.items() if k != "payload"}
    elapsed = 0
    if out.get("started_at"):
        end = out.get("finished_at") or now_ts()
        elapsed = max(0, int(end) - int(out["started_at"]))
    done = int(out.get("done") or 0)
    total = int(out.get("total") or 0)
    rate = (done / elapsed) if elapsed > 0 and done > 0 else 0
    remaining = max(0, total - done)
    out["elapsed_s"] = elapsed
    out["tiles_per_s"] = round(rate, 2) if rate else 0
    out["eta_s"] = int(remaining / rate) if rate > 0 and remaining else 0
    if out.get("estimated_bytes") is None:
        out["estimated_bytes"] = int(total * DEFAULT_TILE_ESTIMATE_BYTES)
    return out


def estimate_tile_bytes(tile_count: int, layer: dict[str, Any] | None = None) -> int:
    avg = DEFAULT_TILE_ESTIMATE_BYTES
    if layer:
        try:
            layer_tiles = int(layer.get("tile_count") or 0)
            layer_size = int(layer.get("size") or 0)
            if layer_tiles > 0 and layer_size > 0:
                avg = max(1, int(layer_size / layer_tiles))
        except (TypeError, ValueError):
            avg = DEFAULT_TILE_ESTIMATE_BYTES
    return int(max(0, tile_count) * avg)


def clear_finished_download_jobs() -> int:
    statuses = {"done", "error", "cancelled"}
    with download_condition:
        remove_ids = [job_id for job_id, job in download_jobs.items() if job.get("status") in statuses]
        for job_id in remove_ids:
            download_jobs.pop(job_id, None)
            _cancelled_jobs.discard(job_id)
            _paused_jobs.discard(job_id)
            _active_jobs.discard(job_id)
        with get_db() as conn:
            conn.execute(
                "DELETE FROM download_jobs WHERE status IN ('done','error','cancelled')"
            )
        download_condition.notify_all()
    return len(remove_ids)


def missing_tiles_for_mbtiles(path: Path, tiles: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    if not path.exists():
        return tiles
    if not tiles:
        return []
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            zooms = sorted({z for z, _x, _y in tiles})
            existing: set[tuple[int, int, int]] = set()
            for z in zooms:
                rows = conn.execute(
                    "SELECT tile_column,tile_row FROM tiles WHERE zoom_level=?",
                    (z,),
                ).fetchall()
                existing.update((z, int(x), int(y)) for x, y in rows)
            missing = []
            for z, x, y in tiles:
                y_tms = (2**z - 1) - y
                if (z, x, y_tms) not in existing:
                    missing.append((z, x, y))
    except sqlite3.Error:
        return tiles
    return missing


def is_readable_mbtiles(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def fetch_tile_data(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(TILE_DOWNLOAD_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Slofi OPS-TOC/0.1"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.read()
        except Exception as exc:
            last_error = exc
            if attempt < TILE_DOWNLOAD_RETRIES:
                time.sleep(min(2.0, 0.35 * (attempt + 1)))
    if last_error:
        raise last_error
    return b""


def _fetch_tile_task(args: tuple) -> tuple:
    url_tpl, z, x, y = args
    url = substitute_tile_url(url_tpl, z, x, y)
    try:
        data = fetch_tile_data(url)
        return (z, x, y, data if data else None)
    except Exception:
        return (z, x, y, None)


def run_download_job(job_id: str, payload: dict[str, Any]) -> None:
    tiles = payload["tiles"]
    path = Path(payload["path"])
    tmp_path = path.with_suffix(path.suffix + ".part")
    saved = 0
    failed = 0
    try:
        ensure_dirs()
        if tmp_path.exists() and not is_readable_mbtiles(tmp_path):
            tmp_path.unlink(missing_ok=True)
        resume_partial = tmp_path.exists()
        if not resume_partial and payload.get("repair_existing") and path.exists():
            shutil.copy2(path, tmp_path)
            resume_partial = True
        with sqlite3.connect(tmp_path) as conn:
            init_mbtiles(conn, payload["metadata"])
            tiles_to_fetch = missing_tiles_for_mbtiles(tmp_path, tiles)
            saved = len(tiles) - len(tiles_to_fetch)
            update_job(job_id, done=saved, saved=saved, failed=failed)
            idx = saved
            with ThreadPoolExecutor(max_workers=TILE_FETCH_WORKERS) as executor:
                for batch_start in range(0, len(tiles_to_fetch), TILE_FETCH_BATCH):
                    with download_condition:
                        while job_id in _paused_jobs and job_id not in _cancelled_jobs:
                            if job_id in download_jobs:
                                download_jobs[job_id]["status"] = "paused"
                                persist_download_job(download_jobs[job_id])
                            download_condition.wait(timeout=1)
                        if job_id in download_jobs and download_jobs[job_id].get("status") == "paused":
                            download_jobs[job_id]["status"] = "running"
                            persist_download_job(download_jobs[job_id])
                    if job_id in _cancelled_jobs:
                        conn.commit()
                        tmp_path.unlink(missing_ok=True)
                        _cancelled_jobs.discard(job_id)
                        update_job(job_id, status="cancelled", finished_at=now_ts())
                        return
                    batch = tiles_to_fetch[batch_start:batch_start + TILE_FETCH_BATCH]
                    fetch_args = [(payload["url"], z, x, y) for z, x, y in batch]
                    for z, x, y, data in executor.map(_fetch_tile_task, fetch_args):
                        idx += 1
                        if data:
                            y_tms = (2**z - 1) - y
                            conn.execute(
                                "INSERT OR REPLACE INTO tiles (zoom_level,tile_column,tile_row,tile_data) VALUES (?,?,?,?)",
                                (z, x, y_tms, sqlite3.Binary(data)),
                            )
                            saved += 1
                        else:
                            failed += 1
                    conn.commit()
                    update_job(job_id, done=idx, saved=saved, failed=failed)
            conn.commit()
        tmp_path.replace(path)
        update_job(job_id, status="done", done=len(tiles), saved=saved, failed=failed, path=str(path), finished_at=now_ts())
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        update_job(job_id, status="error", error=str(exc), finished_at=now_ts())


def job_from_download_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, tuple[str, int] | None]:
    try:
        bounds = {
            "south": _float(payload.get("south"), "south"),
            "west": _float(payload.get("west"), "west"),
            "north": _float(payload.get("north"), "north"),
            "east": _float(payload.get("east"), "east"),
        }
        min_zoom = max(0, min(22, _int(payload.get("min_zoom"), "min_zoom")))
        max_zoom = max(0, min(22, _int(payload.get("max_zoom"), "max_zoom")))
    except ValueError as exc:
        return {}, None, (str(exc), 400)
    if min_zoom > max_zoom:
        min_zoom, max_zoom = max_zoom, min_zoom
    url = _clean_text(payload.get("url"), 500)
    if not url or "{z}" not in url or "{x}" not in url or "{y}" not in url:
        return {}, None, ("Tile URL template required", 400)
    tiles = tiles_for_bounds(bounds, min_zoom, max_zoom)
    if not tiles:
        return {}, None, ("No tiles in selected area", 400)

    name = _clean_text(payload.get("name"), 90, "Offline map") or "Offline map"
    layer_name = _clean_text(payload.get("layer_name"), 90, "Map layer") or "Map layer"
    fmt = _clean_text(payload.get("format"), 12, "png") or "png"
    slug = _safe_slug(f"{name}-{layer_name}-z{min_zoom}-{max_zoom}")
    path = MBTILES_DIR / f"{slug}.mbtiles"
    suffix = 2
    while path.exists() or path.with_suffix(path.suffix + ".part").exists():
        path = MBTILES_DIR / f"{slug}-{suffix}.mbtiles"
        suffix += 1
    metadata = {
        "name": name,
        "type": "baselayer",
        "version": "1",
        "description": f"{layer_name} offline tiles from OPS-TOC",
        "format": "jpg" if fmt in {"jpg", "jpeg"} else "png",
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
        "bounds": f"{bounds['west']},{bounds['south']},{bounds['east']},{bounds['north']}",
        "attribution": _clean_text(payload.get("attribution"), 260),
        "source_url": url,
        "source_min_zoom": str(min_zoom),
        "source_max_zoom": str(max_zoom),
        "source_layer_name": layer_name,
    }
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": "download",
        "status": "queued",
        "name": name,
        "layer_name": layer_name,
        "path": str(path),
        "total": len(tiles),
        "estimated_bytes": estimate_tile_bytes(len(tiles)),
        "done": 0,
        "saved": 0,
        "failed": 0,
        "created_at": now_ts(),
    }
    job_payload = {"tiles": tiles, "path": str(path), "url": url, "metadata": metadata}
    return job, job_payload, None


def job_from_layer(layer: dict[str, Any], mode: str) -> tuple[dict[str, Any], dict[str, Any] | None, tuple[str, int] | None]:
    path = Path(layer["path"])
    if MBTILES_DIR not in path.parents:
        return {}, None, (f"Cannot {mode} this tileset", 403)
    url = layer.get("source_url", "")
    if not url or "{z}" not in url:
        return {}, None, ("No source URL stored for this tileset", 400)
    bounds_str = layer.get("bounds", "")
    try:
        west, south, east, north = [float(v) for v in bounds_str.split(",")]
    except Exception:
        return {}, None, ("No bounds stored for this tileset", 400)
    min_zoom = int(layer.get("minzoom", 0))
    max_zoom = int(layer.get("maxzoom", 14))
    tiles = tiles_for_bounds({"south": south, "west": west, "north": north, "east": east}, min_zoom, max_zoom)
    if mode == "repair":
        tiles = missing_tiles_for_mbtiles(path, tiles)
    if not tiles:
        return {}, None, ("No missing tiles found" if mode == "repair" else "No tiles in area", 400)
    name = layer.get("name", "Offline map")
    layer_name = layer.get("source_layer_name", "Map layer")
    fmt = layer.get("format", "png")
    metadata = {
        "name": name, "type": "baselayer", "version": "1",
        "description": f"{layer_name} offline tiles from OPS-TOC",
        "format": fmt, "minzoom": str(min_zoom), "maxzoom": str(max_zoom),
        "bounds": bounds_str, "source_url": url,
        "source_min_zoom": str(min_zoom), "source_max_zoom": str(max_zoom),
        "source_layer_name": layer_name,
    }
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "kind": mode, "status": "queued", "name": name, "layer_name": layer_name,
        "path": str(path), "total": len(tiles), "estimated_bytes": estimate_tile_bytes(len(tiles), layer),
        "done": 0, "saved": 0, "failed": 0, "created_at": now_ts(),
    }
    payload = {
        "tiles": tiles, "path": str(path), "url": url, "metadata": metadata,
        "repair_existing": mode == "repair",
    }
    return job, payload, None


def haversine_m(a: dict[str, float], b: dict[str, float]) -> float:
    radius = 6371008.8
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def line_distance_m(points: list[dict[str, float]]) -> float:
    return sum(haversine_m(points[i - 1], points[i]) for i in range(1, len(points)))


# --- Track stops / debrief -------------------------------------------------
# A "stop" = a contiguous at-rest run (<STOP_KMH) lasting at least MIN_STOP_S.
# STOP_KMH is 1 (not 0) because a parked GPS blips <1 km/h of Doppler noise;
# MIN_STOP_S filters out momentary halts (traffic lights). Mirrors the moving/
# stopped logic in app.js trackStats so counts agree.
STOP_KMH = 1.0
MIN_STOP_S = 60.0
REPORT_FIELDS = ("purpose", "summary", "outcome", "followup", "activity")


def _seg_speed_kmh(a: dict[str, Any], b: dict[str, Any]) -> float:
    sa, sb = a.get("speed"), b.get("speed")
    if isinstance(sa, (int, float)) and isinstance(sb, (int, float)):
        return (sa + sb) / 2
    if isinstance(sb, (int, float)):
        return float(sb)
    dt = max((b.get("ts") or 0) - (a.get("ts") or 0), 1)
    return haversine_m(a, b) / dt * 3.6


def _mk_stop(points: list[dict[str, Any]], s: int, e: int, run: float, seq: int) -> dict[str, Any]:
    p = points[s]
    return {
        "seq": seq,
        "start_ts": points[s].get("ts"),
        "end_ts": points[e].get("ts"),
        "duration_s": int(round(run)),
        "lat": p.get("lat"),
        "lon": p.get("lon"),
        "note": "",
        "tag": "",
    }


def _detect_stops(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize discrete stops from a point list (auto-run at save time)."""
    stops: list[dict[str, Any]] = []
    n = len(points) if points else 0
    if n < 2:
        return stops
    start_idx: int | None = None
    run = 0.0
    seq = 1
    for k in range(1, n):
        a, b = points[k - 1], points[k]
        dt = max((b.get("ts") or 0) - (a.get("ts") or 0), 0)
        if _seg_speed_kmh(a, b) < STOP_KMH:
            if start_idx is None:
                start_idx = k - 1
            run += dt
        else:
            if start_idx is not None and run >= MIN_STOP_S:
                stops.append(_mk_stop(points, start_idx, k - 1, run, seq)); seq += 1
            start_idx = None
            run = 0.0
    if start_idx is not None and run >= MIN_STOP_S:
        stops.append(_mk_stop(points, start_idx, n - 1, run, seq)); seq += 1
    return stops


def _clean_report(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for f in REPORT_FIELDS:
        v = raw.get(f)
        if v is None:
            continue
        text = _clean_text(v, 40 if f == "activity" else 2000)
        if text:
            out[f] = text
    return out


def _clean_stops(raw: Any) -> list[dict[str, Any]]:
    """Sanitize a client-edited stops array — geometry/time kept, note+tag clamped."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            continue
        try:
            out.append({
                "seq": _int(s.get("seq", i + 1), "seq"),
                "start_ts": _int(s["start_ts"], "start_ts") if s.get("start_ts") is not None else None,
                "end_ts": _int(s["end_ts"], "end_ts") if s.get("end_ts") is not None else None,
                "duration_s": _int(s.get("duration_s", 0), "duration_s"),
                "lat": _coord(s["lat"], "lat") if s.get("lat") is not None else None,
                "lon": _coord(s["lon"], "lon") if s.get("lon") is not None else None,
                "note": _clean_text(s.get("note"), 500),
                "tag": _clean_text(s.get("tag"), 40),
            })
        except (ValueError, TypeError):
            continue
    return out


def marker_feature(marker: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {k: v for k, v in marker.items() if k not in {"lat", "lon"}},
        "geometry": {"type": "Point", "coordinates": [marker["lon"], marker["lat"]]},
    }


def drawing_feature(drawing: dict[str, Any]) -> dict[str, Any] | None:
    data = drawing.get("data") or {}
    points = data.get("points") or []
    if not points:
        return None
    coords = [[p["lon"], p["lat"]] for p in points]
    if drawing["kind"] == "polygon":
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        geometry = {"type": "Polygon", "coordinates": [coords]}
    else:
        geometry = {"type": "LineString", "coordinates": coords}
    return {
        "type": "Feature",
        "properties": {
            "id": drawing["id"],
            "name": drawing["name"],
            "kind": drawing["kind"],
            "color": drawing["color"],
            "created_at": drawing["created_at"],
            "updated_at": drawing["updated_at"],
        },
        "geometry": geometry,
    }


def track_feature(track: dict[str, Any]) -> dict[str, Any] | None:
    points = track.get("points") or []
    if len(points) < 2:
        return None
    coords = []
    for point in points:
        coord = [point["lon"], point["lat"]]
        if point.get("alt") is not None:
            coord.append(point["alt"])
        coords.append(coord)
    return {
        "type": "Feature",
        "properties": {
            "id": track["id"],
            "name": track["name"],
            "description": track.get("description") or "",
            "color": track["color"],
            "distance_m": track["distance_m"],
            "source": track["source"],
            "started_at": track["started_at"],
            "ended_at": track["ended_at"],
            "created_at": track["created_at"],
            "updated_at": track["updated_at"],
            "source_app": "map-app",
            "source_type": "gps-track",
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def export_markings_feature_collection() -> dict[str, Any]:
    features = []
    with get_db() as conn:
        marker_rows = conn.execute("SELECT * FROM markers ORDER BY id").fetchall()
        drawing_rows = conn.execute("SELECT * FROM drawings ORDER BY id").fetchall()
        track_rows = conn.execute("SELECT * FROM tracks ORDER BY id").fetchall()
    features.extend(marker_feature(_marker_row(r)) for r in marker_rows)
    for row in drawing_rows:
        feature = drawing_feature(_drawing_row(row))
        if feature:
            features.append(feature)
    for row in track_rows:
        feature = track_feature(_track_row(row))
        if feature:
            features.append(feature)
    for feature in features:
        props = feature.setdefault("properties", {})
        props.setdefault("source_app", "map-app")
    return {"type": "FeatureCollection", "features": features}


def _feature_props(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def _feature_name(feature: dict[str, Any], fallback: str) -> str:
    props = _feature_props(feature)
    return _clean_text(props.get("name") or props.get("title") or fallback, 80, fallback) or fallback


def _feature_points(coords: list[Any]) -> list[dict[str, float]]:
    points = []
    for coord in coords:
        if not isinstance(coord, list) or len(coord) < 2:
            continue
        try:
            lon = _coord(coord[0], "lon")
            lat = _coord(coord[1], "lat")
        except ValueError:
            continue
        points.append({"lat": lat, "lon": lon})
    return points


def import_markings_feature_collection(geojson: dict[str, Any]) -> dict[str, int]:
    if geojson.get("type") == "FeatureCollection":
        features = [f for f in (geojson.get("features") or []) if isinstance(f, dict)]
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        features = [{"type": "Feature", "properties": {}, "geometry": geojson}]
    markers_added = 0
    drawings_added = 0
    ts = now_ts()
    with get_db() as conn:
        for feature in features:
            geom = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
            gtype = geom.get("type")
            props = _feature_props(feature)
            name = _feature_name(feature, "Imported mark" if gtype == "Point" else "Imported drawing")
            color = _clean_text(props.get("color"), 16, "#f59e0b") or "#f59e0b"
            if gtype == "Point":
                coords = geom.get("coordinates") or []
                if len(coords) < 2:
                    continue
                try:
                    lon = _coord(coords[0], "lon")
                    lat = _coord(coords[1], "lat")
                except ValueError:
                    continue
                conn.execute(
                    """
                    INSERT INTO markers (lat,lon,name,description,emoji,category,source,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        lat,
                        lon,
                        name,
                        _clean_text(props.get("description") or props.get("desc"), 400),
                        _clean_text(props.get("marker_emoji") or props.get("emoji"), 24, "pin") or "pin",
                        _clean_text(props.get("source_type") or props.get("category"), 40, "exchange") or "exchange",
                        "om-exchange" if props.get("source_app") == "overmesh" else "geojson-import",
                        ts,
                        ts,
                    ),
                )
                markers_added += 1
            elif gtype == "LineString":
                points = _feature_points(geom.get("coordinates") or [])
                if len(points) < 2:
                    continue
                data = {"points": points, "distance_m": line_distance_m(points)}
                conn.execute(
                    "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                    (name, "line", color, json.dumps(data, separators=(",", ":")), ts, ts),
                )
                drawings_added += 1
            elif gtype == "MultiLineString":
                for idx, coords in enumerate(geom.get("coordinates") or [], start=1):
                    points = _feature_points(coords)
                    if len(points) < 2:
                        continue
                    data = {"points": points, "distance_m": line_distance_m(points)}
                    conn.execute(
                        "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                        (name if idx == 1 else f"{name} {idx}", "line", color, json.dumps(data, separators=(",", ":")), ts, ts),
                    )
                    drawings_added += 1
            elif gtype == "Polygon":
                rings = geom.get("coordinates") or []
                points = _feature_points(rings[0] if rings else [])
                if len(points) > 2 and points[0] == points[-1]:
                    points = points[:-1]
                if len(points) < 3:
                    continue
                data = {"points": points, "distance_m": line_distance_m(points + [points[0]])}
                conn.execute(
                    "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                    (name, "polygon", color, json.dumps(data, separators=(",", ":")), ts, ts),
                )
                drawings_added += 1
            elif gtype == "MultiPolygon":
                for idx, polygon in enumerate(geom.get("coordinates") or [], start=1):
                    points = _feature_points(polygon[0] if polygon else [])
                    if len(points) > 2 and points[0] == points[-1]:
                        points = points[:-1]
                    if len(points) < 3:
                        continue
                    data = {"points": points, "distance_m": line_distance_m(points + [points[0]])}
                    conn.execute(
                        "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                        (name if idx == 1 else f"{name} {idx}", "polygon", color, json.dumps(data, separators=(",", ":")), ts, ts),
                    )
                    drawings_added += 1
    return {"markers": markers_added, "drawings": drawings_added}


def _om_base_url(raw: str) -> str:
    url = _clean_text(raw, 240, "http://localhost:8082").rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OM URL must start with http:// or https://")
    return url


def _json_request(url: str, payload: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OM returned invalid JSON") from exc


def gpx_text(markers: list[dict[str, Any]], drawings: list[dict[str, Any]]) -> bytes:
    ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
    gpx = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "Slofi OPS-TOC",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    meta = ET.SubElement(gpx, "metadata")
    ET.SubElement(meta, "name").text = "OPS-TOC export"
    for marker in markers:
        wpt = ET.SubElement(gpx, "wpt", {"lat": str(marker["lat"]), "lon": str(marker["lon"])})
        ET.SubElement(wpt, "name").text = marker["name"]
        if marker.get("description"):
            ET.SubElement(wpt, "desc").text = marker["description"]
        ET.SubElement(wpt, "type").text = marker.get("category") or "marker"
        ET.SubElement(wpt, "sym").text = marker.get("emoji") or "pin"
    for drawing in drawings:
        if drawing.get("points"):
            points = drawing.get("points") or []
            kind = "gps-track"
        else:
            points = (drawing.get("data") or {}).get("points") or []
            kind = drawing["kind"]
        if len(points) < 2:
            continue
        trk = ET.SubElement(gpx, "trk")
        ET.SubElement(trk, "name").text = drawing["name"]
        if drawing.get("description"):
            ET.SubElement(trk, "desc").text = drawing["description"]
        ET.SubElement(trk, "type").text = kind
        seg = ET.SubElement(trk, "trkseg")
        for point in points:
            trkpt = ET.SubElement(seg, "trkpt", {"lat": str(point["lat"]), "lon": str(point["lon"])})
            if point.get("alt") is not None:
                ET.SubElement(trkpt, "ele").text = str(point["alt"])
            if point.get("time"):
                ET.SubElement(trkpt, "time").text = str(point["time"])
    ET.indent(gpx, space="  ")
    return ET.tostring(gpx, encoding="utf-8", xml_declaration=True)


def _xml_children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node if child.tag.rsplit("}", 1)[-1] == name]


def _xml_text(node: ET.Element, name: str, default: str = "") -> str:
    for child in _xml_children(node, name):
        return child.text or default
    return default


def _xml_points(nodes: list[ET.Element]) -> list[dict[str, float]]:
    points = []
    for node in nodes:
        try:
            point = {"lat": _coord(node.attrib.get("lat"), "lat"), "lon": _coord(node.attrib.get("lon"), "lon")}
            ele = _xml_text(node, "ele")
            if ele:
                point["alt"] = _float(ele, "alt")
            time_text = _xml_text(node, "time")
            if time_text:
                point["time"] = time_text
            points.append(point)
        except ValueError:
            continue
    return points


def _clean_track_points(points: list[Any]) -> list[dict[str, Any]]:
    clean = []
    for point in points:
        if not isinstance(point, dict):
            continue
        out: dict[str, Any] = {"lat": _coord(point.get("lat"), "lat"), "lon": _coord(point.get("lon"), "lon")}
        if point.get("alt") is not None:
            out["alt"] = _float(point.get("alt"), "alt")
        if point.get("time") is not None:
            out["time"] = _clean_text(point.get("time"), 60)
        if point.get("ts") is not None:
            out["ts"] = _int(point.get("ts"), "ts")
        if point.get("sats") is not None:
            out["sats"] = _int(point.get("sats"), "sats")
        if point.get("speed") is not None:
            try:
                out["speed"] = _float(point.get("speed"), "speed")
            except ValueError:
                pass
        clean.append(out)
    return clean


def _track_gpx_text(track: dict[str, Any]) -> bytes:
    ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
    gpx = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "Slofi OPS-TOC",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = track["name"]
    if track.get("description"):
        ET.SubElement(trk, "desc").text = track["description"]
    ET.SubElement(trk, "type").text = "gps-track"
    seg = ET.SubElement(trk, "trkseg")
    for point in track.get("points") or []:
        trkpt = ET.SubElement(seg, "trkpt", {"lat": str(point["lat"]), "lon": str(point["lon"])})
        if point.get("alt") is not None:
            ET.SubElement(trkpt, "ele").text = str(point["alt"])
        if point.get("time"):
            ET.SubElement(trkpt, "time").text = str(point["time"])
    ET.indent(gpx, space="  ")
    return ET.tostring(gpx, encoding="utf-8", xml_declaration=True)


def import_gpx_bytes(raw: bytes) -> dict[str, int]:
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("GPX file is too large")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Invalid GPX file") from exc
    ts = now_ts()
    markers_added = 0
    drawings_added = 0
    tracks_added = 0
    with get_db() as conn:
        for wpt in _xml_children(root, "wpt"):
            try:
                lat = _coord(wpt.attrib.get("lat"), "lat")
                lon = _coord(wpt.attrib.get("lon"), "lon")
            except ValueError:
                continue
            name = _clean_text(_xml_text(wpt, "name", "Waypoint"), 80, "Waypoint") or "Waypoint"
            desc = _clean_text(_xml_text(wpt, "desc"), 400)
            category = _clean_text(_xml_text(wpt, "type", "gpx"), 40, "gpx") or "gpx"
            emoji = _clean_text(_xml_text(wpt, "sym", "pin"), 24, "pin") or "pin"
            conn.execute(
                """
                INSERT INTO markers (lat,lon,name,description,emoji,category,source,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (lat, lon, name, desc, emoji, category, "gpx-import", ts, ts),
            )
            markers_added += 1
        for rte in _xml_children(root, "rte"):
            points = _xml_points(_xml_children(rte, "rtept"))
            if len(points) < 2:
                continue
            name = _clean_text(_xml_text(rte, "name", "GPX route"), 80, "GPX route") or "GPX route"
            conn.execute(
                "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (name, "line", "#f59e0b", json.dumps({"points": points, "distance_m": line_distance_m(points)}, separators=(",", ":")), ts, ts),
            )
            drawings_added += 1
        for trk in _xml_children(root, "trk"):
            name = _clean_text(_xml_text(trk, "name", "GPX track"), 80, "GPX track") or "GPX track"
            desc = _clean_text(_xml_text(trk, "desc"), 600)
            for idx, seg in enumerate(_xml_children(trk, "trkseg"), start=1):
                points = _xml_points(_xml_children(seg, "trkpt"))
                if len(points) < 2:
                    continue
                seg_name = name if idx == 1 else f"{name} {idx}"
                started_at = points[0].get("ts")
                ended_at = points[-1].get("ts")
                conn.execute(
                    """
                    INSERT INTO tracks (name,description,color,points_json,distance_m,source,started_at,ended_at,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        seg_name,
                        desc,
                        "#e8b04f",
                        json.dumps(points, separators=(",", ":")),
                        line_distance_m(points),
                        "gpx-import",
                        started_at,
                        ended_at,
                        ts,
                        ts,
                    ),
                )
                tracks_added += 1
    return {"markers": markers_added, "drawings": drawings_added, "tracks": tracks_added}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/lite")
def lite():
    # OPS-TOC Lite — same template/backend, compact HD 5" (1024x600) frontend
    return render_template("index.html", hd_lite=True)


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "ops-toc", "port": PORT, "data_dir": str(DATA_DIR)})


@app.route("/api/version")
def api_version():
    check_remote = request.args.get("check") in {"1", "true", "yes"}
    return jsonify(git_version_payload(check_remote))


@app.route("/api/update", methods=["POST"])
def api_update_app():
    logs: list[str] = []
    try:
        status = run_git(["status", "--short", "--branch"], timeout=20)
        if status.stdout.strip():
            logs.append("$ git status --short --branch\n" + status.stdout.strip())
        result = run_git(["pull", "--rebase", "--autostash"], timeout=90)
        logs.append("$ git pull --rebase --autostash\n" + result.stdout.strip())
    except Exception as exc:
        logs.append(str(exc))
        return jsonify({"ok": False, "error": str(exc), "log": "\n\n".join(logs)[-6000:]}), 500
    ok = result.returncode == 0
    if ok:
        threading.Thread(target=service_action_soon, args=("restart",), daemon=True).start()
    return jsonify({"ok": ok, "log": "\n\n".join(logs)[-6000:], "restart": ok}), (200 if ok else 500)


@app.route("/api/service/restart", methods=["POST"])
def api_restart_service():
    threading.Thread(target=service_action_soon, args=("restart",), daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting OPS-TOC service."})


@app.route("/api/service/stop", methods=["POST"])
def api_stop_service():
    threading.Thread(target=service_action_soon, args=("stop",), daemon=True).start()
    return jsonify({"ok": True, "message": "Stopping OPS-TOC service."})


@app.route("/api/tile-layers")
def api_tile_layers():
    local = list_mbtiles()
    online = [
        {
            "id": "osm",
            "name": "OpenStreetMap",
            "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "OpenStreetMap contributors",
            "maxzoom": 19,
        },
        {
            "id": "voyager",
            "name": "Voyager",
            "url": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
            "attribution": "OpenStreetMap, CARTO",
            "maxzoom": 19,
        },
        {
            "id": "voyager_nolabels",
            "name": "Voyager No Labels",
            "url": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png",
            "attribution": "OpenStreetMap, CARTO",
            "maxzoom": 19,
        },
        {
            "id": "positron",
            "name": "Positron",
            "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
            "attribution": "OpenStreetMap, CARTO",
            "maxzoom": 19,
        },
        {
            "id": "dark_matter",
            "name": "Dark Matter",
            "url": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            "attribution": "OpenStreetMap, CARTO",
            "maxzoom": 19,
        },
        {
            "id": "dark_nolabels",
            "name": "Dark No Labels",
            "url": "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
            "attribution": "OpenStreetMap, CARTO",
            "maxzoom": 19,
        },
        {
            "id": "esri_gray_dark",
            "name": "Esri Dark Gray",
            "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
            "attribution": "Esri, HERE, Garmin, OpenStreetMap, GIS User Community",
            "maxzoom": 16,
        },
        {
            "id": "stamen_toner_lite",
            "name": "Toner Lite",
            "url": "https://tiles.stadiamaps.com/tiles/stamen_toner_lite/{z}/{x}/{y}{r}.png",
            "attribution": "Stadia Maps, Stamen Design, OpenMapTiles, OpenStreetMap",
            "maxzoom": 20,
        },
        {
            "id": "stamen_toner_dark",
            "name": "Toner Dark",
            "url": "https://tiles.stadiamaps.com/tiles/stamen_toner_dark/{z}/{x}/{y}{r}.png",
            "attribution": "Stadia Maps, Stamen Design, OpenMapTiles, OpenStreetMap",
            "maxzoom": 20,
        },
        {
            "id": "stamen_terrain",
            "name": "Stamen Terrain",
            "url": "https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}{r}.png",
            "attribution": "Stadia Maps, Stamen Design, OpenMapTiles, OpenStreetMap",
            "maxzoom": 20,
        },
        {
            "id": "esri_sat",
            "name": "Esri Satellite",
            "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "attribution": "Esri",
            "maxzoom": 18,
        },
        {
            "id": "esri_streets",
            "name": "Esri Streets",
            "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
            "attribution": "Esri, DeLorme, NAVTEQ, USGS, Intermap, NRCAN",
            "maxzoom": 19,
        },
        {
            "id": "esri_topo",
            "name": "Esri Topo",
            "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
            "attribution": "Esri",
            "maxzoom": 18,
        },
        {
            "id": "topo",
            "name": "OpenTopoMap",
            "url": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
            "attribution": "OpenStreetMap contributors, OpenTopoMap",
            "maxzoom": 17,
        },
        {
            "id": "stadia_outdoors",
            "name": "Stadia Outdoors",
            "url": "https://tiles.stadiamaps.com/tiles/outdoors/{z}/{x}/{y}{r}.png",
            "attribution": "Stadia Maps, OpenMapTiles, OpenStreetMap",
            "maxzoom": 20,
        },
        {
            "id": "esri_hillshade",
            "name": "Esri Hillshade",
            "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
            "attribution": "Esri, Airbus DS, USGS, NGA, NASA, CGIAR",
            "maxzoom": 16,
        },
        {
            "id": "tf_landscape",
            "name": "TF Landscape ★",
            "url": "https://tile.thunderforest.com/landscape/{z}/{x}/{y}.png?apikey={apikey}",
            "attribution": "Thunderforest, OpenStreetMap contributors",
            "maxzoom": 22,
            "key_provider": "thunderforest",
        },
        {
            "id": "tf_outdoors",
            "name": "TF Outdoors ★",
            "url": "https://tile.thunderforest.com/outdoors/{z}/{x}/{y}.png?apikey={apikey}",
            "attribution": "Thunderforest, OpenStreetMap contributors",
            "maxzoom": 22,
            "key_provider": "thunderforest",
        },
        {
            "id": "tf_pioneer",
            "name": "TF Pioneer ★",
            "url": "https://tile.thunderforest.com/pioneer/{z}/{x}/{y}.png?apikey={apikey}",
            "attribution": "Thunderforest, OpenStreetMap contributors",
            "maxzoom": 22,
            "key_provider": "thunderforest",
        },
        {
            "id": "tf_atlas",
            "name": "TF Atlas ★",
            "url": "https://tile.thunderforest.com/atlas/{z}/{x}/{y}.png?apikey={apikey}",
            "attribution": "Thunderforest, OpenStreetMap contributors",
            "maxzoom": 22,
            "key_provider": "thunderforest",
        },
        {
            "id": "mt_hybrid",
            "name": "MT Satellite Hybrid ★",
            "url": "https://api.maptiler.com/maps/hybrid-v4-dark/{z}/{x}/{y}.jpg?key={mtapikey}",
            "attribution": "MapTiler, OpenStreetMap contributors",
            "maxzoom": 20,
            "key_provider": "maptiler",
        },
        {
            "id": "mt_topo",
            "name": "MT Topo ★",
            "url": "https://api.maptiler.com/maps/topo-v2/{z}/{x}/{y}.png?key={mtapikey}",
            "attribution": "MapTiler, OpenStreetMap contributors",
            "maxzoom": 20,
            "key_provider": "maptiler",
        },
        {
            "id": "mt_streets",
            "name": "MT Streets ★",
            "url": "https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key={mtapikey}",
            "attribution": "MapTiler, OpenStreetMap contributors",
            "maxzoom": 20,
            "key_provider": "maptiler",
        },
        {
            "id": "mt_winter",
            "name": "MT Winter ★",
            "url": "https://api.maptiler.com/maps/winter-v2/{z}/{x}/{y}.png?key={mtapikey}",
            "attribution": "MapTiler, OpenStreetMap contributors",
            "maxzoom": 20,
            "key_provider": "maptiler",
        },
    ]
    return jsonify({"local": local, "online": online})


@app.route("/api/search")
def api_search():
    query = _clean_text(request.args.get("q"), 120)
    if not query:
        return jsonify([])
    params = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "q": query,
            "limit": 8,
            "addressdetails": 1,
        }
    )
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Slofi OPS-TOC/0.1 (local cyberdeck map search)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, TimeoutError, ValueError) as exc:
        return jsonify({"error": f"Search failed: {exc}"}), 502

    results = []
    for item in data:
        try:
            lat = _coord(item.get("lat"), "lat")
            lon = _coord(item.get("lon"), "lon")
        except ValueError:
            continue
        results.append(
            {
                "name": _clean_text(item.get("display_name"), 260),
                "lat": lat,
                "lon": lon,
                "type": _clean_text(item.get("type"), 40),
                "category": _clean_text(item.get("category"), 40),
                "importance": item.get("importance"),
                "bbox": item.get("boundingbox") or [],
            }
        )
    return jsonify(results)


@app.route("/api/download-estimate", methods=["POST"])
def api_download_estimate():
    payload = request.get_json(silent=True) or {}
    try:
        bounds = {
            "south": _float(payload.get("south"), "south"),
            "west": _float(payload.get("west"), "west"),
            "north": _float(payload.get("north"), "north"),
            "east": _float(payload.get("east"), "east"),
        }
        min_zoom = max(0, min(22, _int(payload.get("min_zoom"), "min_zoom")))
        max_zoom = max(0, min(22, _int(payload.get("max_zoom"), "max_zoom")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if min_zoom > max_zoom:
        min_zoom, max_zoom = max_zoom, min_zoom
    count = tile_count_for_zoom_range(bounds, min_zoom, max_zoom)
    return jsonify({"tiles": count, "estimated_bytes": estimate_tile_bytes(count), "ok": True})


@app.route("/api/downloads", methods=["POST"])
def api_create_download():
    job, job_payload, error = job_from_download_payload(request.get_json(silent=True) or {})
    if error:
        message, status = error
        return jsonify({"error": message}), status
    return jsonify(enqueue_download_job(job, job_payload))


@app.route("/api/downloads", methods=["GET"])
def api_list_downloads():
    with download_lock:
        jobs = [public_job(job) for job in download_jobs.values()]
    jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return jsonify({"jobs": jobs})


@app.route("/api/downloads/clear-finished", methods=["POST"])
def api_clear_finished_downloads():
    cleared = clear_finished_download_jobs()
    return jsonify({"ok": True, "cleared": cleared})


@app.route("/api/downloads/<job_id>")
def api_get_download(job_id: str):
    with download_lock:
        job = download_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Download job not found"}), 404
        return jsonify(public_job(job))


@app.route("/tiles/<layer_id>/<int:z>/<int:x>/<int:y>.png")
def serve_tile(layer_id: str, z: int, x: int, y: int):
    layer = find_mbtiles(layer_id)
    if not layer:
        return Response(status=204)
    y_tms = (2**z - 1) - y
    try:
        with sqlite3.connect(f"file:{layer['path']}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, y_tms),
            ).fetchone()
        if not row:
            return Response(status=204)
        data = row[0]
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return send_file(io.BytesIO(data), mimetype=detect_mimetype(data, layer["format"]))
    except sqlite3.Error:
        return Response(status=500)


@app.route("/api/markers", methods=["GET"])
def api_get_markers():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM markers ORDER BY updated_at DESC, id DESC").fetchall()
    return jsonify([_marker_row(r) for r in rows])


@app.route("/api/markers", methods=["POST"])
def api_create_marker():
    payload = request.get_json(silent=True) or {}
    try:
        lat = _coord(payload.get("lat"), "lat")
        lon = _coord(payload.get("lon"), "lon")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    name = _clean_text(payload.get("name"), 80)
    if not name:
        return jsonify({"error": "Name required"}), 400
    ts = now_ts()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO markers (lat,lon,name,description,emoji,category,folder,source,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lat,
                lon,
                name,
                _clean_text(payload.get("description"), 400),
                _clean_text(payload.get("emoji"), 24, "pin") or "pin",
                _clean_text(payload.get("category"), 40, "note") or "note",
                _clean_text(payload.get("folder"), 80),
                _clean_text(payload.get("source"), 40, "map-app") or "map-app",
                ts,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM markers WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "marker": _marker_row(row)})


@app.route("/api/markers/<int:marker_id>", methods=["PUT"])
def api_update_marker(marker_id: int):
    payload = request.get_json(silent=True) or {}
    name = _clean_text(payload.get("name"), 80)
    if not name:
        return jsonify({"error": "Name required"}), 400
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM markers WHERE id=?", (marker_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Marker not found"}), 404
        lat = existing["lat"]
        lon = existing["lon"]
        if "lat" in payload:
            try:
                lat = _coord(payload.get("lat"), "lat")
                lon = _coord(payload.get("lon"), "lon")
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        conn.execute(
            """
            UPDATE markers
            SET lat=?,lon=?,name=?,description=?,emoji=?,category=?,folder=?,updated_at=?
            WHERE id=?
            """,
            (
                lat,
                lon,
                name,
                _clean_text(payload.get("description"), 400),
                _clean_text(payload.get("emoji"), 24, "pin") or "pin",
                _clean_text(payload.get("category"), 40, "note") or "note",
                _clean_text(payload.get("folder"), 80),
                now_ts(),
                marker_id,
            ),
        )
        row = conn.execute("SELECT * FROM markers WHERE id=?", (marker_id,)).fetchone()
    return jsonify({"ok": True, "marker": _marker_row(row)})


@app.route("/api/markers/<int:marker_id>", methods=["DELETE"])
def api_delete_marker(marker_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM markers WHERE id=?", (marker_id,))
    return jsonify({"ok": cur.rowcount > 0})


@app.route("/api/drawings", methods=["GET"])
def api_get_drawings():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM drawings ORDER BY updated_at DESC, id DESC").fetchall()
    return jsonify([_drawing_row(r) for r in rows])


@app.route("/api/drawings", methods=["POST"])
def api_create_drawing():
    payload = request.get_json(silent=True) or {}
    kind = _clean_text(payload.get("kind"), 20, "line")
    if kind not in {"line", "polygon", "measure"}:
        return jsonify({"error": "Unsupported drawing kind"}), 400
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    points = data.get("points") if isinstance(data.get("points"), list) else []
    if len(points) < 2:
        return jsonify({"error": "At least two points required"}), 400
    clean_points = []
    try:
        for p in points:
            clean_points.append({"lat": _coord(p.get("lat"), "lat"), "lon": _coord(p.get("lon"), "lon")})
    except (AttributeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    data["points"] = clean_points
    data["distance_m"] = line_distance_m(clean_points)
    ts = now_ts()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (
                _clean_text(payload.get("name"), 80, kind.title()) or kind.title(),
                kind,
                _clean_text(payload.get("color"), 16, "#f59e0b") or "#f59e0b",
                json.dumps(data, separators=(",", ":")),
                ts,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM drawings WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "drawing": _drawing_row(row)})


@app.route("/api/drawings/<int:drawing_id>", methods=["DELETE"])
def api_delete_drawing(drawing_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM drawings WHERE id=?", (drawing_id,))
    return jsonify({"ok": cur.rowcount > 0})


@app.route("/api/tracks", methods=["GET"])
def api_get_tracks():
    """Summary list by default — NO point arrays. Pass ?points=1 for the full
    payload (export/backup paths). Callers that need one track's points should
    use GET /api/tracks/<id> rather than pulling the whole list."""
    want_points = request.args.get("points") in ("1", "true", "yes")
    sql = "SELECT * FROM tracks ORDER BY updated_at DESC, id DESC"
    if not want_points:
        # json_array_length() counts in SQLite (~0.08 s for all tracks) instead
        # of parsing every point array in Python (~0.4 s and growing).
        # Every column EXCEPT points_json — otherwise ~20 MB of JSON text is
        # read into Python only to be discarded. json_array_length() does the
        # counting inside SQLite.
        sql = (
            "SELECT id, name, description, color, distance_m, source, started_at, "
            "ended_at, created_at, updated_at, folder, report_json, stops_json, "
            "json_array_length(points_json) AS point_count "
            "FROM tracks ORDER BY updated_at DESC, id DESC"
        )
    with get_db() as conn:
        rows = conn.execute(sql).fetchall()
    return jsonify([_track_row(r, include_points=want_points) for r in rows])


@app.route("/api/tracks/<int:track_id>", methods=["GET"])
def api_get_track(track_id: int):
    """Single track WITH points. Added 2026-08-11 — this route did not exist
    (it 405'd), which is why the frontend was fetching the entire list just to
    read one track."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    if not row:
        return jsonify({"error": "Track not found"}), 404
    return jsonify(_track_row(row))


def _insert_track(
    *,
    points: list[dict[str, Any]],
    name: Any = None,
    description: Any = None,
    color: Any = None,
    folder: Any = None,
    source: Any = None,
    started_at: int | None = None,
    ended_at: int | None = None,
    report: dict[str, str] | None = None,
) -> sqlite3.Row:
    """Persist a cleaned point list as a track. Shared by the manual POST /api/tracks
    path and the server-side recorder, so both get identical stop detection,
    distance and defaults."""
    ts = now_ts()
    stops = _detect_stops(points)
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO tracks (name,description,color,folder,points_json,distance_m,source,started_at,ended_at,report_json,stops_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _clean_text(name, 80, "GPS track") or "GPS track",
                _clean_text(description, 600),
                _clean_text(color, 16, "#e8b04f") or "#e8b04f",
                _clean_text(folder, 80),
                json.dumps(points, separators=(",", ":")),
                line_distance_m(points),
                _clean_text(source, 40, "gps") or "gps",
                started_at,
                ended_at,
                json.dumps(report or {}, separators=(",", ":")),
                json.dumps(stops, separators=(",", ":")),
                ts,
                ts,
            ),
        )
        return conn.execute("SELECT * FROM tracks WHERE id=?", (cur.lastrowid,)).fetchone()


@app.route("/api/tracks", methods=["POST"])
def api_create_track():
    payload = request.get_json(silent=True) or {}
    points = payload.get("points") if isinstance(payload.get("points"), list) else []
    try:
        clean_points = _clean_track_points(points)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    if len(clean_points) < 2:
        return jsonify({"error": "At least two GPS points required"}), 400
    started_at = payload.get("started_at")
    ended_at = payload.get("ended_at")
    try:
        started_at = _int(started_at, "started_at") if started_at is not None else clean_points[0].get("ts")
        ended_at = _int(ended_at, "ended_at") if ended_at is not None else clean_points[-1].get("ts")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    row = _insert_track(
        points=clean_points,
        name=payload.get("name"),
        description=payload.get("description"),
        color=payload.get("color"),
        folder=payload.get("folder"),
        source=payload.get("source"),
        started_at=started_at,
        ended_at=ended_at,
        report=_clean_report(payload.get("report")),
    )
    return jsonify({"ok": True, "track": _track_row(row)})


@app.route("/api/tracks/<int:track_id>", methods=["PUT"])
def api_update_track(track_id: int):
    payload = request.get_json(silent=True) or {}
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Track not found"}), 404
        current = _track_row(existing)
        points = current["points"]
        if "points" in payload:
            raw_points = payload.get("points") if isinstance(payload.get("points"), list) else []
            try:
                points = _clean_track_points(raw_points)
            except (ValueError, TypeError) as exc:
                return jsonify({"error": str(exc)}), 400
            if len(points) < 2:
                return jsonify({"error": "At least two GPS points required"}), 400
        name = _clean_text(payload.get("name", current["name"]), 80, current["name"]) or current["name"]
        description = _clean_text(payload.get("description", current["description"]), 600)
        color = _clean_text(payload.get("color", current["color"]), 16, current["color"]) or current["color"]
        folder = _clean_text(payload.get("folder", current["folder"]), 80)
        report = _clean_report(payload["report"]) if "report" in payload else current.get("report", {})
        if "stops" in payload:
            stops = _clean_stops(payload["stops"])
        elif "points" in payload:
            stops = _detect_stops(points)  # points changed, no notes to preserve
        else:
            stops = current.get("stops", [])
        conn.execute(
            """
            UPDATE tracks
            SET name=?,description=?,color=?,folder=?,points_json=?,distance_m=?,report_json=?,stops_json=?,updated_at=?
            WHERE id=?
            """,
            (name, description, color, folder, json.dumps(points, separators=(",", ":")), line_distance_m(points),
             json.dumps(report, separators=(",", ":")), json.dumps(stops, separators=(",", ":")), now_ts(), track_id),
        )
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    return jsonify({"ok": True, "track": _track_row(row)})


@app.route("/api/tracks/<int:track_id>", methods=["DELETE"])
def api_delete_track(track_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM tracks WHERE id=?", (track_id,))
    return jsonify({"ok": cur.rowcount > 0})


@app.route("/api/tracks/<int:track_id>/detect-stops", methods=["POST"])
def api_detect_track_stops(track_id: int):
    """Re-scan a track's stored points for stops WITHOUT persisting (preview)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    if not row:
        return jsonify({"error": "Track not found"}), 404
    track = _track_row(row)
    return jsonify({"ok": True, "stops": _detect_stops(track["points"])})


@app.route("/api/tracks/<int:track_id>/geojson")
def api_export_track_geojson(track_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    if not row:
        return jsonify({"error": "Track not found"}), 404
    track = _track_row(row)
    feature = track_feature(track)
    if not feature:
        return jsonify({"error": "Track has no exportable points"}), 400
    return jsonify({"type": "FeatureCollection", "features": [feature]})


@app.route("/api/tracks/<int:track_id>/gpx")
def api_export_track_gpx(track_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    if not row:
        return jsonify({"error": "Track not found"}), 404
    track = _track_row(row)
    filename = f"{_safe_slug(track['name'], 'gps-track')}.gpx"
    return Response(
        _track_gpx_text(track),
        mimetype="application/gpx+xml",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/tracks/<int:track_id>/drawing", methods=["POST"])
def api_track_to_drawing(track_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        if not row:
            return jsonify({"error": "Track not found"}), 404
        track = _track_row(row)
        points = [{"lat": p["lat"], "lon": p["lon"]} for p in track["points"]]
        if len(points) < 2:
            return jsonify({"error": "At least two points required"}), 400
        ts = now_ts()
        data = {"points": points, "distance_m": line_distance_m(points)}
        cur = conn.execute(
            "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (track["name"], "line", track["color"], json.dumps(data, separators=(",", ":")), ts, ts),
        )
        drawing = conn.execute("SELECT * FROM drawings WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "drawing": _drawing_row(drawing)})


@app.route("/api/measure", methods=["POST"])
def api_measure():
    payload = request.get_json(silent=True) or {}
    points = payload.get("points") if isinstance(payload.get("points"), list) else []
    try:
        clean = [{"lat": _coord(p.get("lat"), "lat"), "lon": _coord(p.get("lon"), "lon")} for p in points]
    except (AttributeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    if len(clean) < 2:
        return jsonify({"distance_m": 0, "segments": []})
    segments = []
    total = 0.0
    for i in range(1, len(clean)):
        dist = haversine_m(clean[i - 1], clean[i])
        total += dist
        segments.append({"from": i - 1, "to": i, "distance_m": dist})
    return jsonify({"distance_m": total, "segments": segments})


@app.route("/api/export/geojson")
def api_export_geojson():
    return jsonify(export_markings_feature_collection())


@app.route("/api/exchange/markings")
def api_exchange_markings():
    return jsonify({"ok": True, "data": export_markings_feature_collection()})


@app.route("/api/exchange/import", methods=["POST"])
def api_exchange_import():
    payload = request.get_json(silent=True) or {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return jsonify({"error": "GeoJSON data required"}), 400
    result = import_markings_feature_collection(data)
    return jsonify({"ok": True, **result})


@app.route("/api/om/sync/push", methods=["POST"])
def api_om_sync_push():
    payload = request.get_json(silent=True) or {}
    try:
        base = _om_base_url(payload.get("url") or "http://localhost:8082")
        data = export_markings_feature_collection()
        result = _json_request(f"{base}/api/map_exchange/import", {"data": data})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    if result.get("error"):
        return jsonify(result), 502
    return jsonify({"ok": True, "om": result})


@app.route("/api/om/sync/pull", methods=["POST"])
def api_om_sync_pull():
    payload = request.get_json(silent=True) or {}
    try:
        base = _om_base_url(payload.get("url") or "http://localhost:8082")
        result = _json_request(f"{base}/api/map_exchange/export")
        data = result.get("data")
        if not isinstance(data, dict):
            return jsonify({"error": "OM response missing GeoJSON data"}), 502
        imported = import_markings_feature_collection(data)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"ok": True, **imported, "om": result.get("counts") or {}})


@app.route("/api/export/gpx")
def api_export_gpx():
    with get_db() as conn:
        marker_rows = conn.execute("SELECT * FROM markers ORDER BY id").fetchall()
        drawing_rows = conn.execute("SELECT * FROM drawings ORDER BY id").fetchall()
        track_rows = conn.execute("SELECT * FROM tracks ORDER BY id").fetchall()
    markers = [_marker_row(r) for r in marker_rows]
    drawings = [_drawing_row(r) for r in drawing_rows]
    drawings.extend(_track_row(r) for r in track_rows)
    return Response(
        gpx_text(markers, drawings),
        mimetype="application/gpx+xml",
        headers={"Content-Disposition": "attachment; filename=ops-toc-export.gpx"},
    )


@app.route("/api/import/gpx", methods=["POST"])
def api_import_gpx():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "GPX file required"}), 400
    try:
        result = import_gpx_bytes(file.read())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@app.route("/api/om/share-marker/<int:marker_id>", methods=["POST"])
def api_om_share_marker(marker_id: int):
    # Placeholder by design: Map owns marker controls; OM remains the future radio backend.
    # Later this can call OM /api/waypoints/send when OM is running and the user chooses
    # channel/radio/recipient from the Map UI.
    with get_db() as conn:
        row = conn.execute("SELECT * FROM markers WHERE id=?", (marker_id,)).fetchone()
    if not row:
        return jsonify({"error": "Marker not found"}), 404
    return jsonify(
        {
            "ok": False,
            "pending": True,
            "message": "OM sharing is reserved for the later integration step.",
            "marker": _marker_row(row),
        }
    ), 501


init_db()
cleanup_download_job_history()
load_download_jobs()


# ── TOC log helpers ────────────────────────────────────────────────────

def get_toc_db() -> sqlite3.Connection:
    conn = sqlite3.connect(OM_PREFS_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _init_toc_db() -> None:
    with get_toc_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS toc_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT 'NOTE',
            body     TEXT NOT NULL
        )""")
        # Add uuid column if missing (migration for existing installs)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(toc_log)")}
        if "uuid" not in cols:
            conn.execute("ALTER TABLE toc_log ADD COLUMN uuid TEXT")
        # Backfill any rows that lack a uuid
        rows = conn.execute("SELECT id FROM toc_log WHERE uuid IS NULL").fetchall()
        for r in rows:
            conn.execute("UPDATE toc_log SET uuid=? WHERE id=?", (str(uuid.uuid4()), r[0]))


def _norm_log_cat(v: Any) -> str:
    c = (v or "NOTE").strip().upper()
    return c if c in _LOG_CATS else "NOTE"


def _norm_log_ts(v: Any) -> int:
    if v in (None, ""):
        return int(time.time())
    try:
        ts = int(float(v))
    except (TypeError, ValueError):
        return int(time.time())
    if ts > 10_000_000_000:
        ts = ts // 1000
    return max(0, ts)


def _toc_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "uuid": r["uuid"], "ts": r["ts"], "category": r["category"], "body": r["body"]}


def _toc_annotate(e: dict) -> dict:
    m = _MISSION_RE.search(e["body"] or "")
    e["mission"] = m.group(1).strip() if m else None
    p = _POS_RE.search(e["body"] or "")
    if p:
        e["lat"] = float(p.group(1))
        e["lon"] = float(p.group(2))
    t = _TRACK_RE.search(e["body"] or "")
    if t:
        e["track_id"] = int(t.group(1))
    return e


_init_toc_db()


# ── TOC log routes ─────────────────────────────────────────────────────

@app.route("/api/log/entries")
def api_log_entries():
    cat    = request.args.get("category", "").upper()
    miss   = request.args.get("mission", "")
    search = request.args.get("search", "")
    try:
        limit = min(int(request.args.get("limit", 500)), 10000)
    except (ValueError, TypeError):
        limit = 500
    where = []
    params: list[Any] = []
    if cat and cat != "ALL":
        where.append("category = ?")
        params.append(cat)
    if miss:
        where.append("(LOWER(body) LIKE ? OR LOWER(body) LIKE ?)")
        params.append(f"%mission%folder:%{miss.lower()}%")
        params.append(f"%mission:%{miss.lower()}%")
    if search:
        where.append("LOWER(body) LIKE ?")
        params.append(f"%{search.lower()}%")
    sql = "SELECT id,uuid,ts,category,body FROM toc_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with get_toc_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    entries = [_toc_annotate(_toc_row(r)) for r in rows]
    if miss:
        entries = [e for e in entries if (e.get("mission") or "").lower() == miss.lower()]
    if search:
        s = search.lower()
        entries = [e for e in entries if s in e["body"].lower()]
    return jsonify(entries)


@app.route("/api/log/entries", methods=["POST"])
def api_log_entries_add():
    d    = request.get_json(silent=True) or {}
    body = (d.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Body required"}), 400
    cat = _norm_log_cat(d.get("category"))
    ts  = _norm_log_ts(d.get("ts"))
    uid = str(uuid.uuid4())
    with get_toc_db() as conn:
        cur = conn.execute("INSERT INTO toc_log (ts,category,body,uuid) VALUES (?,?,?,?)", (ts, cat, body, uid))
        eid = cur.lastrowid
    return jsonify({"ok": True, **_toc_annotate({"id": eid, "uuid": uid, "ts": ts, "category": cat, "body": body})})


@app.route("/api/log/entries/<int:eid>", methods=["PUT", "PATCH"])
def api_log_entries_update(eid):
    d    = request.get_json(silent=True) or {}
    body = (d.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Body required"}), 400
    cat = _norm_log_cat(d.get("category"))
    ts  = _norm_log_ts(d.get("ts"))
    with get_toc_db() as conn:
        cur = conn.execute("UPDATE toc_log SET ts=?,category=?,body=? WHERE id=?", (ts, cat, body, eid))
        if cur.rowcount == 0:
            return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True, **_toc_annotate({"id": eid, "ts": ts, "category": cat, "body": body})})


@app.route("/api/log/entries/<int:eid>", methods=["DELETE"])
def api_log_entries_delete(eid):
    with get_toc_db() as conn:
        cur = conn.execute("DELETE FROM toc_log WHERE id=?", (eid,))
        if cur.rowcount == 0:
            return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/log/missions")
def api_log_missions():
    with get_toc_db() as conn:
        rows = conn.execute("SELECT ts,category,body FROM toc_log").fetchall()
    missions: dict = {}
    for r in rows:
        m = _MISSION_RE.search(r["body"] or "")
        if m:
            name = m.group(1).strip()
            key  = name.lower()
            cur  = missions.setdefault(key, {"name": name, "count": 0, "last_ts": 0, "categories": {}})
            cur["count"] += 1
            cur["last_ts"] = max(cur["last_ts"], int(r["ts"] or 0))
            cat  = r["category"] or "NOTE"
            cur["categories"][cat] = cur["categories"].get(cat, 0) + 1
    return jsonify(sorted(missions.values(), key=lambda x: (-x["last_ts"], x["name"].lower())))


@app.route("/api/log/missions/rename", methods=["PUT"])
def api_log_missions_rename():
    d   = request.get_json(silent=True) or {}
    old = (d.get("old_name") or "").strip()
    new = (d.get("new_name") or "").strip()
    if not old or not new:
        return jsonify({"error": "old_name and new_name required"}), 400
    with get_toc_db() as conn:
        rows = conn.execute("SELECT id,body FROM toc_log").fetchall()
        updated = 0
        for r in rows:
            body = r["body"] or ""
            m = _MISSION_RE.search(body)
            if m and m.group(1).strip().lower() == old.lower():
                new_body = _MISSION_RE.sub(lambda _: f"**Mission / Folder:** {new}", body, count=1)
                conn.execute("UPDATE toc_log SET body=? WHERE id=?", (new_body, r["id"]))
                updated += 1
    return jsonify({"ok": True, "updated": updated})


@app.route("/api/log/missions/delete", methods=["POST"])
def api_log_missions_delete():
    d    = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_toc_db() as conn:
        rows = conn.execute("SELECT id,body FROM toc_log").fetchall()
        updated = 0
        for r in rows:
            body = r["body"] or ""
            m = _MISSION_RE.search(body)
            if m and m.group(1).strip().lower() == name.lower():
                new_body = _MISSION_RE.sub("", body).lstrip("\n")
                conn.execute("UPDATE toc_log SET body=? WHERE id=?", (new_body, r["id"]))
                updated += 1
    return jsonify({"ok": True, "updated": updated})


@app.route("/api/log/stats")
def api_log_stats():
    with get_toc_db() as conn:
        rows = conn.execute(
            "SELECT category,COUNT(*) as n FROM toc_log GROUP BY category ORDER BY n DESC"
        ).fetchall()
    return jsonify([{"category": r["category"], "count": r["n"]} for r in rows])


@app.route("/api/log/export")
def api_log_export():
    fmt = request.args.get("fmt", "txt")
    with get_toc_db() as conn:
        rows = conn.execute("SELECT id,ts,category,body FROM toc_log ORDER BY ts ASC").fetchall()
    entries = [_toc_row(r) for r in rows]
    if fmt == "json":
        return Response(
            json.dumps(entries, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="field_log.json"'},
        )
    lines = []
    for e in entries:
        dt = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(e["ts"]))
        lines.append(f"[{dt}] [{e['category']}]\n{e['body']}\n")
    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": 'attachment; filename="field_log.txt"'},
    )


@app.route("/api/log/import", methods=["POST"])
def api_log_import():
    if request.files:
        upload = request.files.get("file")
        raw = upload.read().decode("utf-8", errors="replace") if upload else ""
    else:
        d   = request.get_json(silent=True) or {}
        raw = d.get("data", "")
    entries = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and item.get("body"):
                    entries.append({
                        "ts": _norm_log_ts(item.get("ts")),
                        "category": _norm_log_cat(item.get("category")),
                        "body": str(item.get("body", "")).strip(),
                    })
    except (json.JSONDecodeError, TypeError):
        _TXT_RE = re.compile(
            r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?Z?)\] \[([A-Z]+)\]\n(.*?)(?=\n\n\[|\Z)',
            re.S | re.M,
        )
        for m in _TXT_RE.finditer(raw):
            try:
                dt_raw = m.group(1)
                struct = time.strptime(dt_raw.rstrip("Z")[:19], "%Y-%m-%d %H:%M:%S")
                ts = calendar.timegm(struct) if dt_raw.endswith("Z") else int(time.mktime(struct))
            except Exception:
                ts = int(time.time())
            entries.append({
                "ts": ts,
                "category": _norm_log_cat(m.group(2)),
                "body": m.group(3).strip(),
            })
    if not entries:
        return jsonify({"error": "No importable entries found"}), 400
    with get_toc_db() as conn:
        for e in entries:
            uid = str(uuid.uuid4())
            conn.execute("INSERT INTO toc_log (ts,category,body,uuid) VALUES (?,?,?,?)",
                         (e["ts"], e["category"], e["body"], uid))
    return jsonify({"ok": True, "imported": len(entries)})


@app.route("/api/log/sync", methods=["POST"])
def api_log_sync():
    """Bidirectional append-only sync. One round-trip:
    Caller sends: known_uuids (list) + entries (list of dicts with uuid/ts/category/body).
    We import any entries we don't have, return any entries the caller is missing."""
    d = request.get_json(silent=True) or {}
    their_uuids = set(d.get("known_uuids") or [])
    their_entries = d.get("entries") or []

    imported = 0
    with get_toc_db() as conn:
        our_uuids = {r[0] for r in conn.execute("SELECT uuid FROM toc_log WHERE uuid IS NOT NULL")}
        for e in their_entries:
            uid = (e.get("uuid") or "").strip()
            if not uid or uid in our_uuids:
                continue
            ts  = _norm_log_ts(e.get("ts"))
            cat = _norm_log_cat(e.get("category"))
            body = (e.get("body") or "").strip()
            if not body:
                continue
            conn.execute("INSERT INTO toc_log (ts,category,body,uuid) VALUES (?,?,?,?)", (ts, cat, body, uid))
            our_uuids.add(uid)
            imported += 1

        missing_uuids = our_uuids - their_uuids
        send_rows = conn.execute(
            f"SELECT id,uuid,ts,category,body FROM toc_log WHERE uuid IN ({','.join('?'*len(missing_uuids))})",
            list(missing_uuids)
        ).fetchall() if missing_uuids else []

    return jsonify({
        "ok": True,
        "imported": imported,
        "entries": [_toc_row(r) for r in send_rows],
    })


@app.route("/api/downloads/<job_id>/cancel", methods=["POST"])
def api_cancel_download(job_id):
    with download_condition:
        job = download_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") in {"done", "error", "cancelled"}:
            return jsonify({"error": "Job already finished"}), 400
        if job_id in download_queue:
            download_queue.remove(job_id)
            job["status"] = "cancelled"
            job["finished_at"] = now_ts()
            persist_download_job(job)
            return jsonify({"ok": True, "job": public_job(job)})
    _cancelled_jobs.add(job_id)
    _paused_jobs.discard(job_id)
    with download_condition:
        download_condition.notify_all()
    return jsonify({"ok": True})


@app.route("/api/downloads/<job_id>/pause", methods=["POST"])
def api_pause_download(job_id):
    with download_condition:
        job = download_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in {"running", "queued"}:
            return jsonify({"error": "Job cannot be paused"}), 400
        _paused_jobs.add(job_id)
        job["status"] = "paused"
        persist_download_job(job)
        download_condition.notify_all()
        return jsonify({"ok": True, "job": public_job(job)})


@app.route("/api/downloads/<job_id>/resume", methods=["POST"])
def api_resume_download(job_id):
    with download_condition:
        job = download_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in {"paused", "running"}:
            return jsonify({"error": "Job cannot be resumed"}), 400
        _paused_jobs.discard(job_id)
        if job.get("status") == "paused":
            if job_id in _active_jobs:
                job["status"] = "running"
            else:
                job["status"] = "queued"
                if job_id not in download_queue:
                    download_queue.append(job_id)
                start_download_worker_locked()
            persist_download_job(job)
        download_condition.notify_all()
        return jsonify({"ok": True, "job": public_job(job)})

@app.route("/api/tile-layers/<layer_id>", methods=["DELETE"])
def api_delete_tile_layer(layer_id):
    layer = find_mbtiles(layer_id)
    if not layer:
        return jsonify({"error": "Tileset not found"}), 404
    path = Path(layer["path"])
    if MBTILES_DIR not in path.parents:
        return jsonify({"error": "Cannot delete this tileset"}), 403
    with download_lock:
        for job in download_jobs.values():
            if job.get("status") in {"queued", "running", "paused"} and job.get("path") == str(path):
                return jsonify({"error": "Tileset has a running download or refresh job"}), 409
    path.unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.route("/api/tile-layers/<layer_id>", methods=["PUT"])
def api_update_tile_layer(layer_id):
    layer = find_mbtiles(layer_id)
    if not layer:
        return jsonify({"error": "Tileset not found"}), 404
    path = Path(layer["path"])
    if MBTILES_DIR not in path.parents:
        return jsonify({"error": "Cannot rename this tileset"}), 403
    body = request.get_json(silent=True) or {}
    name = _clean_text(body.get("name"), 90)
    if not name:
        return jsonify({"error": "Name is required"}), 400
    try:
        patch_mbtiles_metadata(path, {"name": name})
    except sqlite3.Error as exc:
        return jsonify({"error": f"Rename failed: {exc}"}), 500
    updated = find_mbtiles(layer_id) or layer
    return jsonify({"ok": True, "layer": updated})


@app.route("/api/tile-layers/<layer_id>/refresh", methods=["POST"])
def api_refresh_tile_layer(layer_id):
    layer = find_mbtiles(layer_id)
    if not layer:
        return jsonify({"error": "Tileset not found"}), 404
    job, payload, error = job_from_layer(layer, "refresh")
    if error:
        message, status = error
        return jsonify({"error": message}), status
    return jsonify(enqueue_download_job(job, payload))


@app.route("/api/tile-layers/<layer_id>/repair", methods=["POST"])
def api_repair_tile_layer(layer_id):
    layer = find_mbtiles(layer_id)
    if not layer:
        return jsonify({"error": "Tileset not found"}), 404
    job, payload, error = job_from_layer(layer, "repair")
    if error:
        message, status = error
        return jsonify({"error": message}), status
    return jsonify(enqueue_download_job(job, payload))


def extension_tiles_for_layer(layer: dict[str, Any], new_min: int, new_max: int) -> tuple[list[tuple[int, int, int]], int, int, tuple[str, int] | None]:
    path = Path(layer["path"])
    if MBTILES_DIR not in path.parents:
        return [], new_min, new_max, ("Cannot extend this tileset", 403)
    bounds_str = layer.get("bounds", "")
    try:
        west, south, east, north = [float(v) for v in bounds_str.split(",")]
    except Exception:
        return [], new_min, new_max, ("No bounds stored for this tileset", 400)
    existing_min = int(layer.get("minzoom", new_min))
    existing_max = int(layer.get("maxzoom", new_max))
    zooms_to_fetch = [
        z for z in range(new_min, new_max + 1)
        if z < existing_min or z > existing_max
    ]
    tiles: list[tuple[int, int, int]] = []
    selected_bounds = {"south": south, "west": west, "north": north, "east": east}
    for z in zooms_to_fetch:
        tiles.extend(tile_range_for_bounds(selected_bounds, z))
    return missing_tiles_for_mbtiles(path, tiles), min(existing_min, new_min), max(existing_max, new_max), None


def extension_tile_count_for_layer(layer: dict[str, Any], new_min: int, new_max: int) -> tuple[int, int, int, tuple[str, int] | None]:
    path = Path(layer["path"])
    if MBTILES_DIR not in path.parents:
        return 0, new_min, new_max, ("Cannot extend this tileset", 403)
    bounds_str = layer.get("bounds", "")
    try:
        west, south, east, north = [float(v) for v in bounds_str.split(",")]
    except Exception:
        return 0, new_min, new_max, ("No bounds stored for this tileset", 400)
    existing_min = int(layer.get("minzoom", new_min))
    existing_max = int(layer.get("maxzoom", new_max))
    selected_bounds = {"south": south, "west": west, "north": north, "east": east}
    count = 0
    for z in range(new_min, new_max + 1):
        if z < existing_min or z > existing_max:
            count += tile_count_for_bounds(selected_bounds, z)
    return count, min(existing_min, new_min), max(existing_max, new_max), None


@app.route("/api/tile-layers/<layer_id>/extend-estimate", methods=["POST"])
def api_extend_tile_layer_estimate(layer_id):
    layer = find_mbtiles(layer_id)
    if not layer:
        return jsonify({"error": "Tileset not found"}), 404
    body = request.get_json(silent=True) or {}
    try:
        new_min = max(0, min(22, _int(body.get("min_zoom"), "min_zoom")))
        new_max = max(0, min(22, _int(body.get("max_zoom"), "max_zoom")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if new_min > new_max:
        new_min, new_max = new_max, new_min
    tile_count, merged_min, merged_max, error = extension_tile_count_for_layer(layer, new_min, new_max)
    if error:
        message, status = error
        return jsonify({"error": message}), status
    return jsonify({
        "ok": True,
        "tiles": tile_count,
        "estimated_bytes": estimate_tile_bytes(tile_count, layer),
        "minzoom": merged_min,
        "maxzoom": merged_max,
    })


@app.route("/api/tile-layers/<layer_id>/extend", methods=["POST"])
def api_extend_tile_layer(layer_id):
    """Download additional zoom levels into an existing tileset."""
    layer = find_mbtiles(layer_id)
    if not layer:
        return jsonify({"error": "Tileset not found"}), 404
    body = request.get_json(silent=True) or {}
    try:
        new_min = max(0, min(22, _int(body.get("min_zoom"), "min_zoom")))
        new_max = max(0, min(22, _int(body.get("max_zoom"), "max_zoom")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if new_min > new_max:
        new_min, new_max = new_max, new_min
    url = layer.get("source_url", "")
    if not url or "{z}" not in url:
        return jsonify({"error": "No source URL stored for this tileset"}), 400
    path = Path(layer["path"])
    bounds_str = layer.get("bounds", "")
    tiles, merged_min, merged_max, error = extension_tiles_for_layer(layer, new_min, new_max)
    if error:
        message, status = error
        return jsonify({"error": message}), status
    if not tiles:
        return jsonify({"error": "No new or missing tiles in selected zoom range"}), 400
    name = layer.get("name", "Offline map")
    layer_name = layer.get("source_layer_name", "Map layer")
    fmt = layer.get("format", "png")
    metadata = {
        "name": name, "type": "baselayer", "version": "1",
        "description": f"{layer_name} offline tiles from OPS-TOC",
        "format": fmt, "minzoom": str(merged_min), "maxzoom": str(merged_max),
        "bounds": bounds_str, "source_url": url,
        "source_min_zoom": str(merged_min), "source_max_zoom": str(merged_max),
        "source_layer_name": layer_name,
    }
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "kind": "extend", "status": "queued", "name": name, "layer_name": layer_name,
        "path": str(path), "total": len(tiles), "estimated_bytes": estimate_tile_bytes(len(tiles), layer),
        "done": 0, "saved": 0, "failed": 0, "created_at": now_ts(),
    }
    payload = {"tiles": tiles, "path": str(path), "url": url, "metadata": metadata, "repair_existing": True}
    return jsonify(enqueue_download_job(job, payload))


@app.route("/api/tile-layers/update-all", methods=["POST"])
def api_update_all_tile_layers():
    jobs = []
    errors = []
    for layer in list_mbtiles():
        if not layer.get("source_url"):
            continue
        job, payload, error = job_from_layer(layer, "refresh")
        if error:
            errors.append({"id": layer["id"], "error": error[0]})
            continue
        jobs.append(enqueue_download_job(job, payload))
    return jsonify({"ok": True, "jobs": jobs, "errors": errors})


@app.route("/api/tile-layers/repair-all", methods=["POST"])
def api_repair_all_tile_layers():
    jobs = []
    errors = []
    for layer in list_mbtiles():
        if not layer.get("source_url"):
            continue
        job, payload, error = job_from_layer(layer, "repair")
        if error:
            errors.append({"id": layer["id"], "error": error[0]})
            continue
        jobs.append(enqueue_download_job(job, payload))
    return jsonify({"ok": True, "jobs": jobs, "errors": errors})


# ── Live operational overlays ────────────────────────────────────────────────

@app.route("/api/overlays/status")
def api_overlay_status():
    status: dict[str, Any] = {}

    try:
        data = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/mc/status')
        status["om"] = {
            "online": True,
            "detail": "online",
            "radios": len(data.get("mc_nodes", [])) if isinstance(data, dict) else 0,
        }
    except RuntimeError as exc:
        status["om"] = {"online": False, "detail": "app offline", "error": str(exc)}

    try:
        data = _overlay_request_json(f'{OVERLAY_URLS["adsb"]}/api/aircraft')
        active = data.get("active", []) if isinstance(data, dict) else []
        running = bool(data.get("dump1090_running")) if isinstance(data, dict) else False
        status["adsb"] = {
            "online": True, "receiver_online": running, "count": len(active),
            "detail": f'{len(active)} live' if running else "decoder stopped",
        }
    except RuntimeError as exc:
        status["adsb"] = {"online": False, "detail": "app offline", "error": str(exc)}

    try:
        data = _overlay_request_json(f'{OVERLAY_URLS["ais"]}/api/vessels')
        active = data.get("active", []) if isinstance(data, dict) else []
        running = bool(data.get("ais_running")) if isinstance(data, dict) else False
        status["ais"] = {
            "online": True, "receiver_online": running, "count": len(active),
            "detail": f'{len(active)} live' if running else "decoder stopped",
        }
    except RuntimeError as exc:
        status["ais"] = {"online": False, "detail": "app offline", "error": str(exc)}

    sonde_online = _overlay_probe(f'{OVERLAY_URLS["sonde"]}/api/version')
    autorx_online = sonde_online and _overlay_probe(
        f'{OVERLAY_URLS["autorx"]}/socket.io/?EIO=4&transport=polling'
    )
    status["sonde"] = {
        "online": sonde_online,
        "receiver_online": autorx_online,
        "detail": "stream online" if autorx_online else ("auto_rx offline" if sonde_online else "app offline"),
        "stream_url": OVERLAY_URLS["autorx"] if sonde_online else None,
    }
    return jsonify({"sources": status, "timestamp": time.time()})


@app.route("/api/overlays/<source>")
def api_overlay_data(source: str):
    try:
        if source == "adsb":
            return jsonify(_overlay_request_json(f'{OVERLAY_URLS["adsb"]}/api/aircraft'))
        if source == "ais":
            return jsonify(_overlay_request_json(f'{OVERLAY_URLS["ais"]}/api/vessels'))
        if source == "om":
            mt_nodes = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/nodes')
            mc_status = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/mc/status')
            radios = [radio for radio in mc_status.get("mc_nodes", []) if radio.get("id")]

            def fetch_radio_contacts(radio: dict[str, Any]) -> list[dict[str, Any]]:
                radio_id = str(radio.get("id") or "")
                try:
                    payload = _overlay_request_json(
                        f'{OVERLAY_URLS["om"]}/api/mc/{urllib.parse.quote(radio_id, safe="")}/contacts'
                    )
                except RuntimeError:
                    return []
                items = []
                for contact in payload.get("contacts", []):
                    item = dict(contact)
                    item["radio_id"] = radio_id
                    item["radio_name"] = radio.get("name") or radio_id
                    item["radio_status"] = radio.get("status")
                    items.append(item)
                return items

            fetched: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=max(1, min(4, len(radios)))) as pool:
                for items in pool.map(fetch_radio_contacts, radios):
                    fetched.extend(items)

            # A contact learned by several MC radios is one map object. Prefer a
            # live copy, then the newest advert, while retaining its hearing radio.
            by_contact: dict[str, dict[str, Any]] = {}
            for item in fetched:
                key = str(item.get("full_key") or item.get("id") or "")
                if not key:
                    continue
                old = by_contact.get(key)
                rank = (not bool(item.get("archived_only")), int(item.get("last_seen_ts") or 0))
                old_rank = (not bool(old.get("archived_only")), int(old.get("last_seen_ts") or 0)) if old else (False, 0)
                if old is None or rank > old_rank:
                    by_contact[key] = item
            mc_contacts = list(by_contact.values())
            return jsonify({"mt_nodes": mt_nodes, "mc_contacts": mc_contacts, "mc_radios": mc_status.get("mc_nodes", [])})
        return jsonify({"error": "Unknown overlay source"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "source": source, "offline": True}), 503


@app.route("/api/overlays/om/action", methods=["POST"])
def api_overlay_om_action():
    data = request.get_json(silent=True) or {}
    network = str(data.get("network") or "").lower()
    action = str(data.get("action") or "").lower()
    radio_id = str(data.get("radio_id") or "")
    target = str(data.get("target") or "")
    if network not in {"mt", "mc"} or action not in {"dm", "refresh"}:
        return jsonify({"error": "Unsupported OM action"}), 400
    if not target:
        return jsonify({"error": "Target is required"}), 400

    if network == "mt" and action == "dm":
        path = f'/api/node/{urllib.parse.quote(target, safe="")}/dm'
        payload = {"message": str(data.get("text") or ""), "radio_id": radio_id or None}
    elif network == "mt":
        path = f'/api/node/{urllib.parse.quote(target, safe="")}/position'
        payload = {"radio_id": radio_id or None}
    elif action == "dm":
        if not radio_id:
            return jsonify({"error": "MC radio is required"}), 400
        path = f'/api/mc/{urllib.parse.quote(radio_id, safe="")}/send_dm'
        payload = {"text": str(data.get("text") or ""), "target": target}
    else:
        if not radio_id:
            return jsonify({"error": "MC radio is required"}), 400
        path = f'/api/mc/{urllib.parse.quote(radio_id, safe="")}/statusreq/{urllib.parse.quote(target, safe="")}'
        payload = {}
    try:
        result = _overlay_request_json(f'{OVERLAY_URLS["om"]}{path}', method="POST", payload=payload, timeout=35)
        return jsonify(result)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502


# ── Comms (read-only mesh messages: MT + MC channels & DMs) ────────────────────
# OPS-TOC displays OverMesh's messages; OM stays the owner of the radios and of
# Silent Running. Read-only — no send here. NOTE: MC's /channels endpoint queries
# the device live (~30s), so it is deliberately NOT called on this poll path; MC
# channel threads are derived from each message's channel index instead.

def _comms_norm(m, network, radio_id, radio_name, channel_names=None):
    is_dm = bool(m.get("is_dm")) if network == "mt" else (m.get("subtype") == "dm")
    sent = bool(m.get("sent"))
    ch = int(m.get("channel") or 0)
    if is_dm:
        peer_id, peer_name = (m.get("to_id"), m.get("to_name")) if sent else (m.get("from_id"), m.get("from_name"))
    else:
        peer_id = peer_name = None
    ch_name = (channel_names or {}).get(ch)
    if not ch_name:
        ch_name = "Primary" if (network == "mt" and ch == 0) else f"CH{ch}"
    # Order by arrival, not the message's own ts: relayed/received MT messages can
    # carry a much older embedded ts that would bury them out of order. The id is
    # assigned on arrival ("<epoch>-<seq>" for MT), so its epoch prefix is the true
    # local order. MC ids aren't time-based → fall back to ts.
    order = int(m.get("ts") or 0)
    head = str(m.get("id") or "").split("-", 1)[0]
    if network == "mt" and head.isdigit():
        order = int(head)
    return {
        "network": network, "radio_id": radio_id or m.get("radio_id"), "radio_name": radio_name,
        "is_dm": is_dm, "channel": ch, "channel_name": ch_name,
        "from_id": m.get("from_id"), "from_name": m.get("from_name"),
        "to_id": m.get("to_id"), "to_name": m.get("to_name"),
        "peer_id": peer_id, "peer_name": peer_name,
        "text": m.get("text") or "", "ts": int(m.get("ts") or 0), "order": order,
        "sent": sent, "status": m.get("status"),
    }


# MC channel names require a live device query (~seconds, up to ~30s) — so fetch
# them lazily in a background thread and cache, never on the hot poll path. First
# view of an MC radio shows CHn; names fill in within a poll cycle once cached.
_mc_chan_cache: dict[str, dict[str, Any]] = {}   # radio_id -> {"names": {idx: name}, "ts": epoch}
_mc_chan_inflight: set[str] = set()
_mc_chan_lock = threading.Lock()
_MC_CHAN_TTL = 1800  # channels rarely change — refresh at most every 30 min


def _mc_channel_names_fetch(radio_id: str) -> None:
    try:
        data = _overlay_request_json(
            f'{OVERLAY_URLS["om"]}/api/mc/{urllib.parse.quote(radio_id, safe="")}/channels', timeout=35
        )
        names = {ch.get("idx"): ch.get("name") for ch in (data.get("channels") or [])
                 if ch.get("idx") is not None and ch.get("name")}
    except Exception:
        names = {}
    with _mc_chan_lock:
        _mc_chan_cache[radio_id] = {"names": names, "ts": time.time()}
        _mc_chan_inflight.discard(radio_id)


def _mc_channel_names(radio_id: str) -> dict:
    with _mc_chan_lock:
        entry = _mc_chan_cache.get(radio_id)
        if entry and (time.time() - entry["ts"] < _MC_CHAN_TTL):
            return entry["names"]
        stale = entry["names"] if entry else {}
        if radio_id in _mc_chan_inflight:
            return stale
        _mc_chan_inflight.add(radio_id)
    threading.Thread(target=_mc_channel_names_fetch, args=(radio_id,), daemon=True).start()
    return stale


@app.route("/api/comms/messages")
def api_comms_messages():
    messages: list[dict[str, Any]] = []
    mt_channels: list[dict[str, Any]] = []
    radios: list[dict[str, Any]] = []
    online = False

    # Meshtastic — one call returns channel messages + DMs
    try:
        mt = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/chat/messages?limit=300')
        online = True
        try:
            chans = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/chat/channels')
        except RuntimeError:
            chans = []
        ch_names = {c.get("index"): c.get("name") for c in chans if isinstance(c, dict)}
        mt_channels = [{"index": c.get("index"), "name": c.get("name")} for c in chans if isinstance(c, dict)]
        for m in (mt.get("messages") or []):
            messages.append(_comms_norm(m, "mt", m.get("radio_id"), None, ch_names))
    except RuntimeError:
        pass

    # MeshCore — per connected radio (concurrent), messages only
    try:
        mc_status = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/mc/status')
        online = True
        mc_radios = [r for r in mc_status.get("mc_nodes", []) if r.get("id")]
        radios = [{"id": r.get("id"), "name": r.get("name") or r.get("id"), "status": r.get("status")} for r in mc_radios]
        connected = [r for r in mc_radios if r.get("status") == "connected"]

        def fetch_mc(radio):
            rid = str(radio.get("id"))
            rname = radio.get("name") or rid
            try:
                data = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/mc/{urllib.parse.quote(rid, safe="")}/messages?limit=300')
            except RuntimeError:
                return []
            names = _mc_channel_names(rid)
            return [_comms_norm(m, "mc", rid, rname, names) for m in (data.get("messages") or [])]

        if connected:
            with ThreadPoolExecutor(max_workers=max(1, min(4, len(connected)))) as pool:
                for items in pool.map(fetch_mc, connected):
                    messages.extend(items)
    except RuntimeError:
        pass

    silent = False
    try:
        s = _overlay_request_json(f'{OVERLAY_URLS["om"]}/api/silent_mode')
        silent = bool(s.get("silent_mode")) if isinstance(s, dict) else False
    except RuntimeError:
        pass

    messages.sort(key=lambda m: m.get("order") or 0)
    return jsonify({"online": online, "silent": silent, "messages": messages, "mt_channels": mt_channels, "radios": radios, "generated": time.time()})


@app.route("/api/comms/send", methods=["POST"])
def api_comms_send():
    # The read-only presenter turns writer here: proxy a message send to OM, which
    # stays the owner of the radios and of Silent Running (OM returns 409 if active).
    data = request.get_json(silent=True) or {}
    network = str(data.get("network") or "").lower()
    kind = str(data.get("kind") or "").lower()      # "channel" | "dm"
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Message is empty"}), 400
    radio_id = str(data.get("radio_id") or "")
    peer_id = str(data.get("peer_id") or "")
    try:
        channel = int(data.get("channel") or 0)
    except (TypeError, ValueError):
        channel = 0

    if network == "mt":
        payload = {"text": text, "channel": channel}
        if kind == "dm":
            if not peer_id:
                return jsonify({"error": "DM target required"}), 400
            payload["dest_id"] = peer_id
        path = "/api/chat/send"
    elif network == "mc":
        if not radio_id:
            return jsonify({"error": "MC radio required"}), 400
        if kind == "dm":
            if not peer_id:
                return jsonify({"error": "DM target required"}), 400
            path = f'/api/mc/{urllib.parse.quote(radio_id, safe="")}/send_dm'
            payload = {"text": text, "target": peer_id}
        else:
            path = f'/api/mc/{urllib.parse.quote(radio_id, safe="")}/send_chan'
            payload = {"text": text, "channel": channel}
    else:
        return jsonify({"error": "Unknown network"}), 400

    try:
        result = _overlay_request_json(f'{OVERLAY_URLS["om"]}{path}', method="POST", payload=payload, timeout=20)
        return jsonify({"ok": True, "result": result})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/comms/stream")
def api_comms_stream():
    # SSE proxy: relay OM's /api/chat/stream (MT messages + push_to_sse'd MC
    # messages + status events) to the OPS-TOC browser same-origin — OM sets no
    # CORS, so a direct EventSource can't reach it. Read-only. The frontend uses
    # this only as a "something changed" trigger to re-poll /api/comms/messages
    # instantly; the 4 s poll stays the reliable baseline if this drops.
    def relay():
        try:
            req = urllib.request.Request(
                f'{OVERLAY_URLS["om"]}/api/chat/stream', headers={"Accept": "text/event-stream"}
            )
            with urllib.request.urlopen(req, timeout=None) as up:
                for chunk in up:
                    yield chunk
        except Exception:
            yield b": upstream unavailable\n\n"
    resp = Response(stream_with_context(relay()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ── GPS ───────────────────────────────────────────────────────────────────────

import gps as _gps

_gps.init(APP_ROOT)


def _gps_payload():
    with _gps.gps_lock:
        pos = dict(_gps.gps_state)
        rt  = dict(_gps._gps_runtime)
    cfg = _gps.load_config()
    return {**cfg, **pos, **rt}


@app.route("/api/gps")
def api_gps_get():
    return jsonify(_gps_payload())


@app.route("/api/settings/gps")
def api_settings_gps_get():
    return jsonify(_gps_payload())


@app.route("/api/gps", methods=["POST"])
def api_gps_set():
    data     = request.get_json(silent=True) or {}
    cfg = _gps.load_config()
    enabled  = bool(data.get("enabled", cfg.get("enabled", True)))
    port     = str(data.get("port", "")).strip()
    om_proxy = bool(data.get("om_proxy", False))
    om_url   = str(data.get("om_url", "http://localhost:8082")).strip()
    manual   = bool(data.get("manual", False))
    cfg["enabled"]  = enabled
    cfg["port"]     = port
    cfg["om_proxy"] = om_proxy
    cfg["om_url"]   = om_url
    cfg["manual"]   = manual
    if manual:
        try:
            cfg["manual_lat"] = float(data.get("lat", 0))
            cfg["manual_lon"] = float(data.get("lon", 0))
        except (ValueError, TypeError):
            pass
    _gps.save_config(cfg)
    if enabled:
        if manual:
            _gps.gps_stop()
            lat = cfg.get("manual_lat")
            lon = cfg.get("manual_lon")
            if lat is not None and lon is not None:
                _gps.gps_set_manual(float(lat), float(lon))
        elif om_proxy and om_url:
            _gps._start_proxy(om_url, fallback_port=port)
        elif port:
            _gps.gps_start(port)
        else:
            _gps.gps_stop()
    else:
        _gps.gps_stop()
    return jsonify({"ok": True})


@app.route("/api/gps/ports")
def api_gps_ports():
    return jsonify({"ports": _gps.list_ports()})


# ── Track recorder (server-side) ──────────────────────────────────────────────
# Recording lives HERE, not in the browser. The page is a viewer: it starts and
# stops the recorder and polls it for the live polyline. A closed tab, a blanked
# screen, a killed browser or a reloaded page no longer costs a track — only
# ops-toc.service going down does, and the buffer is flushed to disk so even a
# service restart resumes mid-track.
#
# Why this matters: the old browser recorder failed silently. gps.py kept
# serving /api/gps, so OM Lite still showed a moving marker while nothing was
# being recorded (27 km lost that way on 2026-07-07).
#
# The capture filters below were MOVED from app.js captureGpsPoint(), not
# copied — the JS version is deleted. One implementation, one place to fix.

REC_STATE_PATH       = DATA_DIR / "active_track.json"
REC_MIN_SATS         = 4      # below this the fix is not trustworthy
REC_NEAR_M           = 3.0    # "hasn't really moved" radius
REC_MULTIPATH_KMH    = 5.0    # receiver says crawling ...
REC_MULTIPATH_M      = 50.0   # ... but the position jumped -> multipath glitch
REC_MAX_SPEED_MS     = 100.0  # 360 km/h absolute sanity cap
REC_STATIONARY_KMH   = 3.0
REC_STATIONARY_M     = 5.0
REC_FLUSH_S          = 5.0    # at most one state write per this many seconds
# ...but a PARKED recorder adds no points and only advances the tail timestamp,
# yet _rec_save_state() rewrites the WHOLE buffer. That write grows with the
# track (~133 B/point: 4000 points = 518 KB per flush = 364 MB/hour), so a long
# halt burns hundreds of MB rewriting a number. Total bytes are O(n^2) in points.
# Parked flushes are therefore rate-limited separately; losing up to this many
# seconds of PARKED time on a crash costs no distance and a few seconds of halt
# duration. (CD keeps ~/maps on NVMe, so this is waste and I/O, not SD wear.)
REC_FLUSH_IDLE_S     = 60.0
REC_DEFAULT_INTERVAL = 10
REC_TICK_S           = 1.0

# RLock, not Lock: the request handlers build a summary while already holding it.
_rec_lock = threading.RLock()
_rec: dict[str, Any] = {
    "active": False,
    "points": [],
    "started_at": None,
    "ended_at": None,
    "min_interval": REC_DEFAULT_INTERVAL,
    # None | "start" | "end" — which at-rest marker the tail currently is, so a
    # halt is bracketed by a PAIR of at-rest points (see _rec_consider).
    "rest_phase": None,
}
_rec_dirty = False        # something changed
_rec_points_dirty = False # a point was ADDED (not just the tail ts advanced)
_rec_last_flush = 0.0


def _rec_iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".000Z"


def _rec_consider(pos: dict[str, Any]) -> None:
    """Filter one GPS sample into the active buffer. Caller holds _rec_lock."""
    global _rec_dirty, _rec_points_dirty
    if not _rec["active"]:
        return
    if not pos.get("fix") or pos.get("lat") is None or pos.get("lon") is None:
        return
    if (pos.get("sats") or 0) < REC_MIN_SATS:
        return
    raw_spd = pos.get("speed")
    spd = float(raw_spd) if isinstance(raw_spd, (int, float)) and raw_spd >= 0 else None
    ts = int(time.time())
    point = {
        "lat": float(pos["lat"]),
        "lon": float(pos["lon"]),
        "alt": pos.get("alt"),
        "sats": pos.get("sats") or 0,
        "speed": spd,
        "ts": ts,
        "time": _rec_iso(ts),
    }
    pts = _rec["points"]
    if pts:
        last = pts[-1]
        dist = haversine_m(last, point)
        dt = ts - (last.get("ts") or 0)

        # Interval throttle: don't oversample while barely moving.
        if dist < REC_NEAR_M and dt < _rec["min_interval"]:
            return

        # Multipath rejection: receiver reports stopped/crawling but the
        # position jumped far -> GPS glitch, not movement.
        if spd is not None and spd < REC_MULTIPATH_KMH and dist > REC_MULTIPATH_M:
            return

        # Absolute sanity cap regardless of dt.
        if dt > 0 and dist / dt > REC_MAX_SPEED_MS:
            return

        # Minimum-movement gate: a parked vehicle must not accumulate GPS-jitter
        # distance. A halt is recorded as TWO at-rest markers bracketing it —
        # halt-start and halt-end — both pinned to the arrival coordinates and
        # both carrying the real (near-zero) speed.
        #
        # WHY TWO, not one refreshed point (fixed 2026-08-11, S404): _detect_stops
        # walks consecutive PAIRS and asks _seg_speed_kmh(a, b) < STOP_KMH. That
        # helper prefers the points' stored `speed` over distance/time. The old
        # code refreshed the arrival point's timestamp but left its speed at
        # whatever it was when captured — 50 km/h, recorded while still moving —
        # so an 80 s halt read as (50+0)/2 = 25 km/h and NEVER tripped the 1 km/h
        # threshold. A single point can't express "at rest from t1 to t2"; it takes
        # a pair. Measured before the fix: dt=84 s, dist=13.9 m -> 25.00 km/h with
        # the stored speed, 0.59 km/h without it.
        #
        # Both markers sit at `last`'s exact coordinates, so they add ZERO
        # distance — the original no-fake-metres guarantee is preserved.
        stationary = spd < REC_STATIONARY_KMH if spd is not None else dist < REC_NEAR_M
        if stationary and dist < REC_STATIONARY_M:
            rest = {
                **point,
                "lat": last["lat"],
                "lon": last["lon"],
                "speed": 0.0 if spd is None else spd,
            }
            phase = _rec.get("rest_phase")
            if phase is None:
                pts.append(rest)          # halt START — its ts is when we stopped
                _rec_points_dirty = True
                _rec["rest_phase"] = "start"
            elif phase == "start":
                pts.append(rest)          # halt END — from here we only advance it
                _rec_points_dirty = True
                _rec["rest_phase"] = "end"
            else:
                last["ts"] = ts           # still parked: advance the end marker
                last["time"] = rest["time"]
                last["speed"] = rest["speed"]
            _rec["ended_at"] = ts
            _rec_dirty = True
            return

    pts.append(point)
    _rec_points_dirty = True
    _rec["rest_phase"] = None  # moving again — the next halt starts a fresh pair
    _rec["ended_at"] = ts
    _rec_dirty = True


def _rec_save_state() -> None:
    """Atomically persist the buffer so a restart resumes mid-track.
    Caller holds _rec_lock."""
    try:
        if not _rec["points"] and not _rec["active"]:
            REC_STATE_PATH.unlink(missing_ok=True)
            return
        REC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = REC_STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_rec, separators=(",", ":")))
        tmp.replace(REC_STATE_PATH)
    except OSError:
        pass


def _rec_load_state() -> None:
    """Restore a buffer left behind by a previous run (crash, restart, reboot)."""
    try:
        raw = json.loads(REC_STATE_PATH.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict) or not isinstance(raw.get("points"), list):
        return
    try:
        points = _clean_track_points(raw["points"])
    except (ValueError, TypeError):
        points = []
    with _rec_lock:
        _rec["active"] = bool(raw.get("active"))
        _rec["points"] = points
        _rec["started_at"] = raw.get("started_at")
        _rec["ended_at"] = raw.get("ended_at")
        try:
            _rec["min_interval"] = max(1, int(raw.get("min_interval") or REC_DEFAULT_INTERVAL))
        except (TypeError, ValueError):
            _rec["min_interval"] = REC_DEFAULT_INTERVAL
        # Restored so a restart mid-halt continues the existing at-rest pair
        # instead of opening a second one.
        rp = raw.get("rest_phase")
        _rec["rest_phase"] = rp if rp in ("start", "end") else None


def _rec_summary(since: int | None = None) -> dict[str, Any]:
    """Recorder status. With `since`, also return points from that index on —
    always including the last known point, because the stationary gate mutates
    it in place and the client's copy would otherwise go stale."""
    with _rec_lock:
        pts = _rec["points"]
        out: dict[str, Any] = {
            "active": _rec["active"],
            "count": len(pts),
            "distance_m": line_distance_m(pts) if len(pts) > 1 else 0.0,
            "started_at": _rec["started_at"],
            "ended_at": _rec["ended_at"],
            "min_interval": _rec["min_interval"],
            "buffered": bool(pts),
        }
        if since is not None:
            start = 0 if not pts else max(0, min(since - 1, len(pts) - 1))
            out["from"] = start
            out["points"] = [dict(p) for p in pts[start:]]
        return out


def _rec_clear() -> None:
    """Caller holds _rec_lock."""
    # rest_phase reset explicitly: today the `if pts:` guard means an empty
    # buffer always takes the append path (which clears it), so a stale value is
    # harmless — but that is implicit. If the guard or the append ever moves, a
    # leftover "end" would make the next track's FIRST halt collapse into one
    # point again: exactly the bug this state machine exists to fix.
    _rec.update({"active": False, "points": [], "started_at": None,
                 "ended_at": None, "rest_phase": None})
    _rec_save_state()


def _rec_loop() -> None:
    global _rec_dirty, _rec_points_dirty, _rec_last_flush
    while True:
        try:
            with _gps.gps_lock:
                pos = dict(_gps.gps_state)
            with _rec_lock:
                _rec_consider(pos)
                # A parked recorder only moves the tail timestamp — rewriting
                # the whole buffer every 5 s for that is pure waste.
                due = REC_FLUSH_S if _rec_points_dirty else REC_FLUSH_IDLE_S
                if _rec_dirty and time.monotonic() - _rec_last_flush >= due:
                    _rec_save_state()
                    _rec_dirty = False
                    _rec_points_dirty = False
                    _rec_last_flush = time.monotonic()
        except Exception:
            pass  # a recorder tick must never kill the thread
        time.sleep(REC_TICK_S)


@app.route("/api/recording")
def api_recording_get():
    raw = request.args.get("since")
    since: int | None
    try:
        since = int(raw) if raw is not None else None
    except ValueError:
        since = None
    return jsonify(_rec_summary(since))


@app.route("/api/recording/start", methods=["POST"])
def api_recording_start():
    payload = request.get_json(silent=True) or {}
    try:
        interval = int(payload.get("min_interval", REC_DEFAULT_INTERVAL))
    except (TypeError, ValueError):
        interval = REC_DEFAULT_INTERVAL
    interval = max(1, min(interval, 3600))
    with _gps.gps_lock:
        pos = dict(_gps.gps_state)
    if not pos.get("fix") or pos.get("lat") is None:
        return jsonify({"error": "Waiting for a GPS fix before recording."}), 409
    with _rec_lock:
        if _rec["active"]:
            return jsonify({"error": "Already recording"}), 409
        if _rec["points"]:
            return jsonify({"error": "An unsaved track is still buffered — save or discard it first."}), 409
        ts = int(time.time())
        _rec.update({"active": True, "points": [], "started_at": ts, "ended_at": ts,
                     "min_interval": interval, "rest_phase": None})
        _rec_consider(pos)  # seed the first point immediately
        _rec_save_state()
        return jsonify({"ok": True, **_rec_summary(0)})


@app.route("/api/recording/stop", methods=["POST"])
def api_recording_stop():
    """Halt capture but KEEP the buffer — the save dialog runs afterwards and
    the points stay server-side until explicitly saved or discarded."""
    with _rec_lock:
        _rec["active"] = False
        _rec_save_state()
        return jsonify({"ok": True, **_rec_summary(0)})


@app.route("/api/recording/save", methods=["POST"])
def api_recording_save():
    payload = request.get_json(silent=True) or {}
    with _rec_lock:
        _rec["active"] = False  # no appends while we commit
        points = [dict(p) for p in _rec["points"]]
        started_at, ended_at = _rec["started_at"], _rec["ended_at"]
    if len(points) < 2:
        return jsonify({"error": "At least two GPS points required"}), 400
    try:
        clean_points = _clean_track_points(points)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    row = _insert_track(
        points=clean_points,
        name=payload.get("name"),
        description=payload.get("description"),
        color=payload.get("color"),
        folder=payload.get("folder"),
        source="gps",
        started_at=started_at if started_at is not None else clean_points[0].get("ts"),
        ended_at=ended_at if ended_at is not None else clean_points[-1].get("ts"),
        report=_clean_report(payload.get("report")),
    )
    with _rec_lock:
        _rec_clear()
    return jsonify({"ok": True, "track": _track_row(row)})


@app.route("/api/recording/discard", methods=["POST"])
def api_recording_discard():
    with _rec_lock:
        _rec_clear()
    return jsonify({"ok": True})


_rec_load_state()
threading.Thread(target=_rec_loop, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
