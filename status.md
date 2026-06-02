type:: project
status:: active
tags:: #map-app #leaflet #offline-maps #cyberdeck
updated:: 2026-06-02

# Map App

> Standalone Leaflet map app for the Cyberdeck. Owns markers, drawings, and offline tile downloads. Shared tile DB feeds Sonde App, OM, and future apps.

## State

| **Status**    | Active — started via Dashboard tile, not enabled at boot |
| **Port**      | 8090 |
| **Host**      | Cyberdeck (rock-5b, 100.97.104.107) |
| **Service**   | map-app.service (user systemd, NOT enabled) |
| **Data dir**  | ~/maps/ (DB + MBTiles shared with all CD apps) |
| **Repo**      | github.com/Slofi/map-app (Codex manages, Claude can push from CD) |

## Access

| Resource | Value |
|----------|-------|
| App URL  | http://localhost:8090 (on CD) |
| App path | ~/Projects/map-app/ |
| Service  | systemctl --user start/stop/restart map-app |

## Quick Commands

**Start/stop:**
```bash
systemctl --user start map-app
systemctl --user stop map-app
systemctl --user restart map-app
```

**Logs:**
```bash
journalctl --user -u map-app -f
```

## Key Paths

| Item | Path |
|------|------|
| App | ~/Projects/map-app/app.py |
| Template | ~/Projects/map-app/templates/index.html |
| JS | ~/Projects/map-app/static/js/app.js |
| CSS | ~/Projects/map-app/static/css/app.css |
| Venv | ~/Projects/map-app/venv/ |
| Service | ~/.config/systemd/user/map-app.service |
| DB | ~/maps/map_app.db |
| MBTiles | ~/maps/mbtiles/ |

## Pending

- **Merge TOC-app into Map-app** — add LOG + MISSIONS tabs; wire to shared `overmesh_prefs.db` (`toc_log` table); retire log-app service and launcher tile. TOC-app's map tab goes away, replaced by Map-app's full map.
- Deploy current Map-app to CD before starting the merge
- Decide whether to support PMTiles in addition to MBTiles
- Add KML import/export
- Add marker categories, filters, and styling
- Add route profile / segment list for ruler paths
- Add optional GPS marker endpoint once CD/HD GPS source is decided
- Add per-source throttling/concurrency settings and clearer retry/backoff behavior
- Add cleanup/repair tool for orphan `.part` files and corrupt MBTiles
- Later: OM consumes Map App markers read-only
- Later: optional "Share via OM" mesh broadcast action for selected markers, separate from local sync

## Changelog

**2026-05-25** — Pulled CD/GitHub download-management work to TestBox. Added richer downloaded map catalog, total map/tile/size summary, per-map Use/Repair/Refresh/Delete actions, queue panel, pause/resume/cancel controls, Repair Missing, Update All, safe `.part` replacement for refresh/update, and app-package-style settings UI. Current implementation uses an in-memory Flask queue with one worker thread. (Session continuation)
**2026-05-25** — Added local SQLite persistence for download jobs. Jobs are stored in `download_jobs` inside `~/maps/map_app.db`; queued jobs survive restart, paused jobs remain paused until resumed, and running jobs are restored as queued so the app can retry them after restart. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local partial MBTiles resume and per-tile retry/backoff. Restarted/interrupted jobs now keep readable `.part` files, validate them, skip already-saved tiles, and fetch only missing tiles. Finished/error/cancelled job history is retained for 7 days by default via `MAP_APP_DOWNLOAD_JOB_RETENTION_DAYS`; tile retries default to 2 via `MAP_APP_TILE_DOWNLOAD_RETRIES`. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local queue management polish. Download jobs now expose elapsed time, tile rate, and ETA; the Download Queue panel shows active/finished/failed counts and a Clear Finished button that removes completed/cancelled/error job records without touching MBTiles. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local GPX import/export. Export writes markers as GPX waypoints and drawings as GPX tracks. Import reads GPX waypoints into markers and GPX tracks/routes into line drawings through a Settings → Import / Export panel. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local Map App ↔ OM marking exchange. Map App now has Pull From OM / Push To OM controls in Import / Export, using OM's `/api/map_exchange/export` and `/api/map_exchange/import`. Pull imports OM Marks, Self Notes, and Overlays into Map App markers/drawings. Push sends Map App markers as OM Self Notes and drawings as OM Overlays. This is local-only and does not broadcast over mesh. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local in-app manual. Hamburger menu now includes Manual, opening a searchable app-native manual modeled after OM's section-card manual. It covers map basics, markers, drawings/ruler, offline maps, download queue, import/export/OM sync, appearance, keys, and app control. Not deployed to CD yet. (Session continuation)
**2026-05-24** — Offline download UX: layer dropdown, cancel button, tileset management (delete/refresh), zoom presets, backend cancel/delete/refresh endpoints. Pushed from CD. (Session 308)
**2026-05-24** — Added to CD Dashboard (tile + start/stop). mbtileserver start/stop added to Dashboard settings panel. (Session 308)
**2026-05-24** — Shared tile architecture implemented: Map App downloads to ~/maps/mbtiles/, mbtileserver serves on :8092 to all CD apps. (Session 308)

---
---
# ////// FULL REFERENCE //////

## Architecture

```
Map App (port 8090)
  Flask backend           → serves HTML, markers, drawings, tile proxy
  Offline downloader      → downloads tiles from online sources
  Tile manager            → manages ~/maps/mbtiles/ (delete, refresh)
  Marker/drawing owner    → SQLite DB at ~/maps/map_app.db
        ↓ writes MBTiles to ~/maps/mbtiles/
mbtileserver (port 8092)  → serves all apps: Sonde App, OM (opt-in), future apps
```

**Design rule:** Map App owns all map-specific controls (markers, drawings, downloads). OM may consume map data read-only later but must not own add/edit/delete controls.

## Shared Tile Workflow

How offline tiles flow across CD apps:

1. Open Map App → toolbar → **Offline**
2. Pan/zoom map to the area you want, or use a region preset
3. Select layer (OSM, Esri Satellite, etc.)
4. Set zoom range with preset buttons (Country z6–10 / Region z9–14 / Local z12–16 / Detail z14–17) or set manually
5. Hit **Download** — progress bar shows, Cancel available during download
6. When done, tileset appears in "Downloaded Tilesets" list (name · layer · zoom range · size · date)
7. **All CD apps immediately see the new tileset** — no restart needed
   - Sonde App: toolbar → Local → pick from list
   - OM: Settings → Offline Maps → enable "Use shared local tile DB"

**Tile freshness:** Refresh is always manual (data cap protection). Each tileset shows its download date. Use Refresh button to re-download same area + zoom levels.

**Key rule:** OM must stay fully standalone. Shared tile server is opt-in via toggle, default off.

## Download Management

Current behavior after the CD/GitHub update:

- New downloads, refreshes, repairs, and update-all requests are queued through Map App.
- The backend uses one worker thread, so jobs run one at a time instead of hammering tile providers.
- Jobs are persisted in SQLite in `download_jobs`, including the original tile payload needed to retry.
- After restart, queued jobs are queued again, paused jobs stay paused, and running jobs are restored as queued.
- Readable `.part` files are reused after restart; the downloader scans existing tiles and downloads only missing entries.
- Unreadable `.part` files are discarded and rebuilt from scratch.
- Individual tile requests retry with short backoff before counting as failed.
- Job API responses include elapsed seconds, tile rate, and ETA for queue display.
- Finished/cancelled/error job records can be cleared manually from the Download Queue panel.
- Running jobs can be paused, resumed, or cancelled from the Offline Download controls and the Download Queue panel.
- Refresh/update writes to `<tileset>.mbtiles.part` and replaces the existing MBTiles only after the job finishes.
- Cancelled or failed refresh/update jobs remove the `.part` file and leave the previous good MBTiles file in place.
- Repair copies the existing MBTiles into a `.part` file and downloads only missing tiles.
- Delete refuses to remove a tileset while a queued/running/paused job targets the same file.
- Downloaded Tilesets shows map count, total tile count, total size, source layer, zoom range, bounds, tile URL, and per-map actions.

Current caveats:

- Resume is tile-level, not byte-range HTTP resume. A partially downloaded individual tile is retried as a whole tile.
- Finished/error/cancelled job records are pruned on startup after 7 days by default.

## Zoom Level Guide

| Level | What you see |
|-------|-------------|
| z6  | Country overview |
| z9  | City / region |
| z12 | Streets |
| z14 | Detailed streets |
| z16 | Buildings / paths |

Range z11–14 is the practical sweet spot for field use (orientation + street navigation). z15–16 only for small high-detail areas.

## Online Layer Catalog

- OSM, CARTO Voyager/No Labels, Positron, Dark Matter/No Labels
- Esri Dark Gray, Satellite, Streets, Topo, Hillshade
- Stadia/Stamen Toner Lite, Toner Dark, Terrain, Stadia Outdoors
- Thunderforest Landscape/Outdoors/Pioneer/Atlas (API key)
- MapTiler Satellite Hybrid/Topo/Streets/Winter (API key)

API keys stored in browser localStorage: `thunderforestApiKey`, `mapTilerApiKey` (same keys as OM).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/markers` | GET | All markers (read-only for OM) |
| `/api/export/geojson` | GET | Export markers + drawings |
| `/api/export/gpx` | GET | Export markers as waypoints and drawings as tracks |
| `/api/import/gpx` | POST | Import GPX waypoints/tracks/routes |
| `/api/exchange/markings` | GET | Export markers/drawings for app-to-app exchange |
| `/api/exchange/import` | POST | Import app-to-app GeoJSON markings |
| `/api/om/sync/pull` | POST | Pull OM markings from configured OM URL |
| `/api/om/sync/push` | POST | Push Map App markings to configured OM URL |
| `/api/search` | GET | Place search (Nominatim proxy) |
| `/api/tile-layers` | GET | List downloaded tilesets (includes source_url, mtime) |
| `/tiles/<layer>/<z>/<x>/<y>.png` | GET | Serve local MBTile |
| `/api/downloads` | POST | Start offline download job |
| `/api/downloads` | GET | List current in-memory download jobs |
| `/api/downloads/clear-finished` | POST | Clear done/error/cancelled job records only |
| `/api/downloads/<id>` | GET | Poll job status |
| `/api/downloads/<id>/cancel` | POST | Cancel running download |
| `/api/downloads/<id>/pause` | POST | Pause queued/running download job |
| `/api/downloads/<id>/resume` | POST | Resume paused download job |
| `/api/tile-layers/<id>` | DELETE | Delete tileset file |
| `/api/tile-layers/<id>/refresh` | POST | Re-download tileset (same area + zoom) |
| `/api/tile-layers/<id>/repair` | POST | Download missing tiles for existing tileset |
| `/api/tile-layers/update-all` | POST | Queue refresh jobs for all refreshable tilesets |
| `/api/tile-layers/repair-all` | POST | Queue repair jobs for all refreshable tilesets |
| `/api/om/share-marker/<id>` | POST | Placeholder, returns 501 |
| `/api/download-estimate` | POST | Estimate tile count before download |
| `/api/tracks` | GET | List saved GPS tracks |
| `/api/tracks` | POST | Save a new GPS track |
| `/api/tracks/<id>` | PUT | Update track name/description/color |
| `/api/tracks/<id>` | DELETE | Delete track |
| `/api/tracks/<id>/gpx` | GET | Export track as GPX |
| `/api/tracks/<id>/geojson` | GET | Export track as GeoJSON |
| `/api/tracks/<id>/drawing` | POST | Convert track to a drawing |
