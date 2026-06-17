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
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file


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

# TOC log — shared with OM via overmesh_prefs.db
OM_PREFS_DB = os.environ.get("TOC_LOG_DB", os.path.expanduser("~/overmesh/overmesh_prefs.db"))
_MISSION_RE = re.compile(r'\*\*(?:Mission|Mission\s*/\s*Folder):\*\*\s*(.+)', re.I)
_POS_RE     = re.compile(r'\*\*GPS:\*\*\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', re.I)
_TRACK_RE   = re.compile(r'\*\*Track:\*\*.*?#(\d+)', re.I)
_LOG_CATS   = {'NOTE', 'PLAN', 'SITREP', 'ALERT', 'ACTION', 'COMMS', 'CONTACT', 'POSITION', 'INTEL', 'WEATHER', 'TRACK'}

app = Flask(__name__)
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
        try:
            conn.execute("ALTER TABLE tracks ADD COLUMN folder TEXT DEFAULT ''")
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


def _track_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        points = json.loads(row["points_json"])
    except (TypeError, ValueError):
        points = []
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "color": row["color"] or "#e8b04f",
        "folder": row["folder"] or "",
        "points": points if isinstance(points, list) else [],
        "distance_m": row["distance_m"] or 0,
        "source": row["source"] or "gps",
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
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
            lon = _float(coord[0], "lon")
            lat = _float(coord[1], "lat")
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
                    lon = _float(coords[0], "lon")
                    lat = _float(coords[1], "lat")
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
            point = {"lat": _float(node.attrib.get("lat"), "lat"), "lon": _float(node.attrib.get("lon"), "lon")}
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
        out: dict[str, Any] = {"lat": _float(point.get("lat"), "lat"), "lon": _float(point.get("lon"), "lon")}
        if point.get("alt") is not None:
            out["alt"] = _float(point.get("alt"), "alt")
        if point.get("time") is not None:
            out["time"] = _clean_text(point.get("time"), 60)
        if point.get("ts") is not None:
            out["ts"] = _int(point.get("ts"), "ts")
        if point.get("sats") is not None:
            out["sats"] = _int(point.get("sats"), "sats")
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
                lat = _float(wpt.attrib.get("lat"), "lat")
                lon = _float(wpt.attrib.get("lon"), "lon")
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
            lat = _float(item.get("lat"), "lat")
            lon = _float(item.get("lon"), "lon")
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
        lat = _float(payload.get("lat"), "lat")
        lon = _float(payload.get("lon"), "lon")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    name = _clean_text(payload.get("name"), 80)
    if not name:
        return jsonify({"error": "Name required"}), 400
    ts = now_ts()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO markers (lat,lon,name,description,emoji,category,source,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                lat,
                lon,
                name,
                _clean_text(payload.get("description"), 400),
                _clean_text(payload.get("emoji"), 24, "pin") or "pin",
                _clean_text(payload.get("category"), 40, "note") or "note",
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
                lat = _float(payload.get("lat"), "lat")
                lon = _float(payload.get("lon"), "lon")
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        conn.execute(
            """
            UPDATE markers
            SET lat=?,lon=?,name=?,description=?,emoji=?,category=?,updated_at=?
            WHERE id=?
            """,
            (
                lat,
                lon,
                name,
                _clean_text(payload.get("description"), 400),
                _clean_text(payload.get("emoji"), 24, "pin") or "pin",
                _clean_text(payload.get("category"), 40, "note") or "note",
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
            clean_points.append({"lat": _float(p.get("lat"), "lat"), "lon": _float(p.get("lon"), "lon")})
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
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tracks ORDER BY updated_at DESC, id DESC").fetchall()
    return jsonify([_track_row(r) for r in rows])


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
    ts = now_ts()
    started_at = payload.get("started_at")
    ended_at = payload.get("ended_at")
    try:
        started_at = _int(started_at, "started_at") if started_at is not None else clean_points[0].get("ts")
        ended_at = _int(ended_at, "ended_at") if ended_at is not None else clean_points[-1].get("ts")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO tracks (name,description,color,folder,points_json,distance_m,source,started_at,ended_at,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _clean_text(payload.get("name"), 80, "GPS track") or "GPS track",
                _clean_text(payload.get("description"), 600),
                _clean_text(payload.get("color"), 16, "#e8b04f") or "#e8b04f",
                _clean_text(payload.get("folder"), 80),
                json.dumps(clean_points, separators=(",", ":")),
                line_distance_m(clean_points),
                _clean_text(payload.get("source"), 40, "gps") or "gps",
                started_at,
                ended_at,
                ts,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (cur.lastrowid,)).fetchone()
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
        conn.execute(
            """
            UPDATE tracks
            SET name=?,description=?,color=?,folder=?,points_json=?,distance_m=?,updated_at=?
            WHERE id=?
            """,
            (name, description, color, folder, json.dumps(points, separators=(",", ":")), line_distance_m(points), now_ts(), track_id),
        )
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    return jsonify({"ok": True, "track": _track_row(row)})


@app.route("/api/tracks/<int:track_id>", methods=["DELETE"])
def api_delete_track(track_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM tracks WHERE id=?", (track_id,))
    return jsonify({"ok": cur.rowcount > 0})


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
        clean = [{"lat": _float(p.get("lat"), "lat"), "lon": _float(p.get("lon"), "lon")} for p in points]
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


# ── GPS ───────────────────────────────────────────────────────────────────────

import gps as _gps

_gps.init(APP_ROOT)


@app.route("/api/gps")
def api_gps_get():
    with _gps.gps_lock:
        pos = dict(_gps.gps_state)
        rt  = dict(_gps._gps_runtime)
    cfg = _gps.load_config()
    return jsonify({**cfg, **pos, **rt})


@app.route("/api/gps", methods=["POST"])
def api_gps_set():
    data     = request.get_json(silent=True) or {}
    enabled  = bool(data.get("enabled", False))
    port     = str(data.get("port", "")).strip()
    om_proxy = bool(data.get("om_proxy", False))
    om_url   = str(data.get("om_url", "http://localhost:8082")).strip()
    cfg = _gps.load_config()
    cfg["enabled"]  = enabled
    cfg["port"]     = port
    cfg["om_proxy"] = om_proxy
    cfg["om_url"]   = om_url
    _gps.save_config(cfg)
    if enabled:
        if om_proxy and om_url:
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


@app.route("/api/checklists/seed")
def api_checklists_seed():
    data = [
        {"name": "CD Hardware & Power", "items": [
            "Battery charged / power bank ready",
            "Rock 5B powers on cleanly",
            "Display connected + working",
            "M70 keyboard connected",
            "USB hub seated properly",
            "RTL-SDR dongle connected",
            "WiFi adapter (RTL8812AU) connected",
            "u-blox GPS dongle connected",
            "CC1101 module connected",
            "Argus (MC node) connected via USB",
            "Fan / cooling adequate",
            "All cables secured",
        ]},
        {"name": "CD Dashboard & Services", "items": [
            "Dashboard loads at :8080",
            "All tiles visible with correct status",
            "OPS-TOC tile — port 8090",
            "OM tile — port 8082",
            "ADS-B tile — port 5400",
            "Banshee tile — port 5200",
            "Casper tile — port 5300",
            "mbtileserver running — port 8092",
            "OPS-TOC — check for update",
            "OM — check for update",
            "ADS-B App — check for update",
        ]},
        {"name": "GPS", "items": [
            "u-blox detected (OPS-TOC auto port)",
            "GPS fix acquired",
            "Satellite count ≥ 8",
            "Position accurate (matches known location)",
            "OPS-TOC position marker on map",
            "ADS-B receiver position correct (Auto source)",
            "OM GPS disabled (OPS-TOC owns port — expected)",
        ]},
        {"name": "OPS-TOC", "items": [
            "App loads at :8090",
            "Map loads — online layer",
            "Offline map loads — Slovenia tiles",
            "Offline layer switch works",
            "Place search works (Nominatim)",
            "Add marker → saved",
            "Edit marker → saved",
            "Delete marker → confirmed",
            "Draw line / polygon",
            "GPS recording — start track",
            "Walk 100m+ with GPS active",
            "Stop track — save with name + colour",
            "Track shows on map correctly",
            "Export track as GPX",
            "LOG tab — add entry (category + text)",
            "LOG tab — filter by category",
            "MISSIONS tab — create mission",
            "MISSIONS tab — log entry to mission",
            "SOP tab — complete a section",
            "CHECKLIST tab — all checklists load",
            "Settings — GPS port shown correctly",
            "App restart from Settings works",
        ]},
        {"name": "OverMesh (OM)", "items": [
            "App loads at :8082",
            "MT nodes visible on dashboard",
            "MC nodes visible (Argus shown)",
            "MT ↔ MC bridge working",
            "Send mesh message from OM",
            "Receive mesh message in OM",
            "OM telemetry updating (battery, signal)",
            "Argus node status green",
            "Node positions updating",
        ]},
        {"name": "Meshtastic Nodes", "items": [
            "EDC1 on air — visible in OM",
            "EDC2 on air — visible in OM",
            "EDC3 on air — visible in OM",
            "Send DM between nodes",
            "Broadcast received by all nodes",
            "Telemetry visible (battery %, RSSI)",
            "GPS position updating (if node has GPS)",
            "Range test — record farthest distance",
            "Node-to-node message without CD relay",
        ]},
        {"name": "Argus (rc-collector)", "items": [
            "Argus powered on",
            "Visible as MC node in OM",
            "RPTR relay active (forwarding MC messages)",
            "rc-collector DMs appearing in OM",
            "Intel flow: mesh → DMs → OM visible",
            "Range test at distance from CD",
            "Standalone run (no laptop dependency)",
        ]},
        {"name": "ADS-B App", "items": [
            "RTL-SDR toggled ON in Settings",
            "dump1090 started from Settings panel",
            "dump1090 status dot green",
            "Aircraft appearing on map",
            "Aircraft DB loaded (registration + type visible)",
            "Airline name showing (operators.json)",
            "Country of registration showing",
            "Track trails visible",
            "Range rings on",
            "Closest / farthest shown in header",
            "Follow mode — tap aircraft → Follow",
            "History tab — aircraft gone >60s listed",
            "MBTiles offline map layer working",
        ]},
        {"name": "Intercept / SDR", "items": [
            "RTL8812AU in monitor mode",
            "WiFi networks detected (iw scan)",
            "Banshee loads at :5200",
            "Banshee — passive WiFi scan",
            "Banshee — handshake capture attempt",
            "acarsdec — ACARS on 131.725 MHz",
            "dumpvdl2 — VDL2 on 136.900 MHz",
            "AIS-catcher — AIS 161.975 / 162.025 MHz (if near water)",
            "Kismet running (if set up on CD)",
        ]},
        {"name": "Casper (CC1101)", "items": [
            "Casper loads at :5300",
            "CC1101 module detected",
            "Sub-GHz scan — 433 MHz band",
            "Signal captured (gate remote, weather sensor, etc.)",
            "Signal logged / saved",
            "Replay test (own device only)",
        ]},
    ]
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
