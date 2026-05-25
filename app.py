from __future__ import annotations

import gzip
import io
import json
import math
import os
import shutil
import subprocess
import sqlite3
import threading
import time
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
    # OM on the same machine reads Map App's tile catalog from localhost:8090.
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


def tiles_for_bounds(bounds: dict[str, float], min_zoom: int, max_zoom: int) -> list[tuple[int, int, int]]:
    tiles = []
    for z in range(min_zoom, max_zoom + 1):
        tiles.extend(tile_range_for_bounds(bounds, z))
    return tiles


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


def service_action_soon(action: str) -> None:
    time.sleep(1)
    subprocess.run(["systemctl", "--user", action, "map-app.service"], cwd=APP_ROOT, check=False)


def run_git(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=APP_ROOT,
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
        payload["error"] = "Map App directory is not a usable git checkout."
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
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
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
    return out


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
    missing = []
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            for z, x, y in tiles:
                y_tms = (2**z - 1) - y
                row = conn.execute(
                    "SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                    (z, x, y_tms),
                ).fetchone()
                if not row:
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
            req = urllib.request.Request(url, headers={"User-Agent": "Slofi Map App/0.1"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.read()
        except Exception as exc:
            last_error = exc
            if attempt < TILE_DOWNLOAD_RETRIES:
                time.sleep(min(2.0, 0.35 * (attempt + 1)))
    if last_error:
        raise last_error
    return b""


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
            for idx, (z, x, y) in enumerate(tiles_to_fetch, start=saved + 1):
                with download_condition:
                    while job_id in _paused_jobs and job_id not in _cancelled_jobs:
                        if job_id in download_jobs:
                            download_jobs[job_id]["status"] = "paused"
                            persist_download_job(download_jobs[job_id])
                        download_condition.wait(timeout=1)
                    if job_id in download_jobs and download_jobs[job_id].get("status") == "paused":
                        download_jobs[job_id]["status"] = "running"
                        persist_download_job(download_jobs[job_id])
                url = substitute_tile_url(payload["url"], z, x, y)
                try:
                    data = fetch_tile_data(url)
                    if not data:
                        failed += 1
                    else:
                        y_tms = (2**z - 1) - y
                        conn.execute(
                            "INSERT OR REPLACE INTO tiles (zoom_level,tile_column,tile_row,tile_data) VALUES (?,?,?,?)",
                            (z, x, y_tms, sqlite3.Binary(data)),
                        )
                        saved += 1
                except Exception:
                    failed += 1
                if idx % 25 == 0:
                    conn.commit()
                update_job(job_id, done=idx, saved=saved, failed=failed)
                if job_id in _cancelled_jobs:
                    conn.commit()
                    tmp_path.unlink(missing_ok=True)
                    _cancelled_jobs.discard(job_id)
                    update_job(job_id, status="cancelled", finished_at=now_ts())
                    return
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
        "description": f"{layer_name} offline tiles from Map App",
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
        "description": f"{layer_name} offline tiles from Map App",
        "format": fmt, "minzoom": str(min_zoom), "maxzoom": str(max_zoom),
        "bounds": bounds_str, "source_url": url,
        "source_min_zoom": str(min_zoom), "source_max_zoom": str(max_zoom),
        "source_layer_name": layer_name,
    }
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "kind": mode, "status": "queued", "name": name, "layer_name": layer_name,
        "path": str(path), "total": len(tiles), "done": 0, "saved": 0, "failed": 0, "created_at": now_ts(),
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


def export_markings_feature_collection() -> dict[str, Any]:
    features = []
    with get_db() as conn:
        marker_rows = conn.execute("SELECT * FROM markers ORDER BY id").fetchall()
        drawing_rows = conn.execute("SELECT * FROM drawings ORDER BY id").fetchall()
    features.extend(marker_feature(_marker_row(r)) for r in marker_rows)
    for row in drawing_rows:
        feature = drawing_feature(_drawing_row(row))
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
            "creator": "Slofi Map App",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    meta = ET.SubElement(gpx, "metadata")
    ET.SubElement(meta, "name").text = "Map App export"
    for marker in markers:
        wpt = ET.SubElement(gpx, "wpt", {"lat": str(marker["lat"]), "lon": str(marker["lon"])})
        ET.SubElement(wpt, "name").text = marker["name"]
        if marker.get("description"):
            ET.SubElement(wpt, "desc").text = marker["description"]
        ET.SubElement(wpt, "type").text = marker.get("category") or "marker"
        ET.SubElement(wpt, "sym").text = marker.get("emoji") or "pin"
    for drawing in drawings:
        points = (drawing.get("data") or {}).get("points") or []
        if len(points) < 2:
            continue
        trk = ET.SubElement(gpx, "trk")
        ET.SubElement(trk, "name").text = drawing["name"]
        ET.SubElement(trk, "type").text = drawing["kind"]
        seg = ET.SubElement(trk, "trkseg")
        for point in points:
            ET.SubElement(seg, "trkpt", {"lat": str(point["lat"]), "lon": str(point["lon"])})
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
            points.append({"lat": _float(node.attrib.get("lat"), "lat"), "lon": _float(node.attrib.get("lon"), "lon")})
        except ValueError:
            continue
    return points


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
            for idx, seg in enumerate(_xml_children(trk, "trkseg"), start=1):
                points = _xml_points(_xml_children(seg, "trkpt"))
                if len(points) < 2:
                    continue
                seg_name = name if idx == 1 else f"{name} {idx}"
                conn.execute(
                    "INSERT INTO drawings (name,kind,color,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                    (seg_name, "line", "#f59e0b", json.dumps({"points": points, "distance_m": line_distance_m(points)}, separators=(",", ":")), ts, ts),
                )
                drawings_added += 1
    return {"markers": markers_added, "drawings": drawings_added}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "map-app", "port": PORT, "data_dir": str(DATA_DIR)})


@app.route("/api/version")
def api_version():
    check_remote = request.args.get("check") in {"1", "true", "yes"}
    return jsonify(git_version_payload(check_remote))


@app.route("/api/update", methods=["POST"])
def api_update_app():
    try:
        result = run_git(["pull", "--ff-only"], timeout=60)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    ok = result.returncode == 0
    if ok:
        threading.Thread(target=service_action_soon, args=("restart",), daemon=True).start()
    return jsonify({"ok": ok, "log": result.stdout[-6000:], "restart": ok}), (200 if ok else 500)


@app.route("/api/service/restart", methods=["POST"])
def api_restart_service():
    threading.Thread(target=service_action_soon, args=("restart",), daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting Map App service."})


@app.route("/api/service/stop", methods=["POST"])
def api_stop_service():
    threading.Thread(target=service_action_soon, args=("stop",), daemon=True).start()
    return jsonify({"ok": True, "message": "Stopping Map App service."})


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
            "User-Agent": "Slofi Map App/0.1 (local cyberdeck map search)",
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
    count = len(tiles_for_bounds(bounds, min_zoom, max_zoom))
    return jsonify({"tiles": count, "ok": True})


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
    markers = [_marker_row(r) for r in marker_rows]
    drawings = [_drawing_row(r) for r in drawing_rows]
    return Response(
        gpx_text(markers, drawings),
        mimetype="application/gpx+xml",
        headers={"Content-Disposition": "attachment; filename=map-app-export.gpx"},
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
