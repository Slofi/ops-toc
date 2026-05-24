from __future__ import annotations

import gzip
import io
import json
import math
import os
import subprocess
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file


APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MAP_APP_DATA_DIR", "/home/slofi/maps"))
DB_PATH = Path(os.environ.get("MAP_APP_DB", DATA_DIR / "map_app.db"))
MBTILES_DIR = Path(os.environ.get("MAP_APP_MBTILES_DIR", DATA_DIR / "mbtiles"))
DEFAULT_MBTILES = os.environ.get("MAP_APP_DEFAULT_MBTILES", "")
PORT = int(os.environ.get("MAP_APP_PORT", "8090"))

app = Flask(__name__)
download_jobs: dict[str, dict[str, Any]] = {}
download_lock = threading.Lock()


@app.after_request
def add_cors_headers(resp):
    # OM on the same machine reads Map App's tile catalog from localhost:8090.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
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
        except sqlite3.Error:
            meta = {}
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


def service_action_soon(action: str) -> None:
    time.sleep(1)
    subprocess.run(["systemctl", "--user", action, "map-app.service"], cwd=APP_ROOT, check=False)


def update_job(job_id: str, **updates: Any) -> None:
    with download_lock:
        if job_id in download_jobs:
            download_jobs[job_id].update(updates)


def run_download_job(job_id: str, payload: dict[str, Any]) -> None:
    tiles = payload["tiles"]
    path = Path(payload["path"])
    tmp_path = path.with_suffix(path.suffix + ".part")
    saved = 0
    failed = 0
    try:
        ensure_dirs()
        if tmp_path.exists():
            tmp_path.unlink()
        with sqlite3.connect(tmp_path) as conn:
            init_mbtiles(conn, payload["metadata"])
            for idx, (z, x, y) in enumerate(tiles, start=1):
                url = substitute_tile_url(payload["url"], z, x, y)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Slofi Map App/0.1"})
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        data = resp.read()
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
            conn.commit()
        tmp_path.replace(path)
        update_job(job_id, status="done", done=len(tiles), saved=saved, failed=failed, path=str(path), finished_at=now_ts())
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        update_job(job_id, status="error", error=str(exc), finished_at=now_ts())


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "map-app", "port": PORT, "data_dir": str(DATA_DIR)})


@app.route("/api/update", methods=["POST"])
def api_update_app():
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=APP_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
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
    url = _clean_text(payload.get("url"), 500)
    if not url or "{z}" not in url or "{x}" not in url or "{y}" not in url:
        return jsonify({"error": "Tile URL template required"}), 400
    tiles = tiles_for_bounds(bounds, min_zoom, max_zoom)
    if not tiles:
        return jsonify({"error": "No tiles in selected area"}), 400

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
    }
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "name": name,
        "layer_name": layer_name,
        "total": len(tiles),
        "done": 0,
        "saved": 0,
        "failed": 0,
        "created_at": now_ts(),
    }
    with download_lock:
        download_jobs[job_id] = job
    thread = threading.Thread(
        target=run_download_job,
        args=(
            job_id,
            {
                "tiles": tiles,
                "path": str(path),
                "url": url,
                "metadata": metadata,
            },
        ),
        daemon=True,
    )
    thread.start()
    return jsonify(job)


@app.route("/api/downloads/<job_id>")
def api_get_download(job_id: str):
    with download_lock:
        job = download_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Download job not found"}), 404
        return jsonify(dict(job))


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
    features = []
    with get_db() as conn:
        marker_rows = conn.execute("SELECT * FROM markers ORDER BY id").fetchall()
        drawing_rows = conn.execute("SELECT * FROM drawings ORDER BY id").fetchall()
    features.extend(marker_feature(_marker_row(r)) for r in marker_rows)
    for row in drawing_rows:
        feature = drawing_feature(_drawing_row(row))
        if feature:
            features.append(feature)
    return jsonify({"type": "FeatureCollection", "features": features})


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
