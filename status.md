type:: project
status:: active
tags:: #ops-toc #map-app #leaflet #offline-maps #field-log #cyberdeck
updated:: 2026-06-09

# OPS-TOC

> OPS-TOC is the Cyberdeck's main map-management and field-operations app. It owns markers, drawings, GPS tracks, offline tile downloads, LOG, MISSIONS, and SOP. Shared tile DB feeds Sonde App, OM, and future apps.

## State

| **Status**    | Active — started via Dashboard tile, not enabled at boot |
| **Port**      | 8090 |
| **Host**      | Cyberdeck (rock-5b, 100.97.104.107) |
| **Service**   | ops-toc.service (user systemd, NOT enabled) |
| **Data dir**  | ~/maps/ (DB + MBTiles shared with all CD apps) |
| **Repo**      | github.com/Slofi/ops-toc |
| **Git location** | `~/Projects/ops-toc/` (direct — no longer via map-app/) |
| **Latest pushed app commit** | `GPS recording: outlier rejection + min satellite filter` |

## Access

| Resource | Value |
|----------|-------|
| App URL  | http://localhost:8090 (on CD) |
| App path | ~/Projects/ops-toc/ |
| Service  | systemctl --user start/stop/restart ops-toc |

## Quick Commands

**Start/stop:**
```bash
systemctl --user start ops-toc
systemctl --user stop ops-toc
systemctl --user restart ops-toc
```

**Logs:**
```bash
journalctl --user -u ops-toc -f
```

## Key Paths

| Item | Path |
|------|------|
| App | ~/Projects/ops-toc/app.py |
| Template | ~/Projects/ops-toc/templates/index.html |
| JS | ~/Projects/ops-toc/static/js/app.js |
| CSS | ~/Projects/ops-toc/static/css/app.css |
| Venv | ~/Projects/ops-toc/venv/ |
| Service | ~/.config/systemd/user/ops-toc.service |
| DB | ~/maps/map_app.db |
| MBTiles | ~/maps/mbtiles/ |
| Shared log DB | ~/overmesh/overmesh_prefs.db (`toc_log`) |

## Current Integration

- OPS-TOC owns all map-specific controls: markers, drawings, GPS tracks, offline downloads, and downloaded-map management.
- OPS-TOC owns the standalone field workflow: LOG, MISSIONS, and SOP tabs.
- LOG/MISSIONS read and write OM's shared `toc_log` table directly in `~/overmesh/overmesh_prefs.db`.
- OM and OPS-TOC now share the same TOC category set, including `WEATHER`.
- `log-app.service` / standalone TOC-app is retired, stopped, and disabled.
- `ops-toc.service` is the manual/Dashboard-controlled OPS-TOC service and is not enabled at boot.
- Map data remains intentionally split: markers/drawings/tracks stay in `~/maps/map_app.db`; OM may consume map data read-only later but should not co-own map edit controls.
- CD GPS receiver is the u-blox GNSS USB device on `/dev/ttyACM0`. OPS-TOC currently owns it directly (`gps_config.json`: enabled true, port `/dev/ttyACM0`, `om_proxy=false`).
- 2026-06-09 field boot issue: `gpsd` auto-claimed `/dev/ttyACM0`, making OPS-TOC show "Device or resource busy". Persistent fix applied: `gpsd.service` and `gpsd.socket` are now masked to `/dev/null` on the CD.
- GPS port selection now uses the stable `/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00` symlink, so the GPS works on either USB-A socket without reconfiguration.

## Pending

- **HD responsive UI** — CSS media query adaptation for small screens (≤600px). Compact toolbar, touch-optimized LOG composer, map-first layout with LOG/SOP as slide-up panels. One codebase, adapts automatically. Implement once HD screen arrives and real hardware can be tested.
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

**2026-06-09** — GPS detection now socket-independent: `list_ports()` returns both raw `/dev/tty*` devices and their stable `/dev/serial/by-id/*` symlinks, with by-id entries listed first and labeled "(stable, recommended)". `port_present()` resolves symlinks before comparing against detected ports. `gps_config.json` switched to the u-blox by-id path so the GPS works on either CD USB-A socket without reconfiguration. Persistent fix for `gpsd` reclaiming the port applied via `sudo systemctl mask --now gpsd.service gpsd.socket`. Verified live: direct source, by-id port, fix true, 12 sats used / 13 in view.

**2026-06-09** — CD field boot fix: OPS-TOC was showing GPS port busy on `/dev/ttyACM0`. Root cause was system `gpsd` auto-start/udev ownership of the u-blox receiver (`SYSTEMD_WANTS=gpsdctl@ttyACM0.service` and `gpsd.service` running). Stopped `gpsd.service` + `gpsd.socket`, disabled `gpsd.socket`, restarted `ops-toc.service`, and verified OPS-TOC direct GPS live on `/dev/ttyACM0` with fix true, 12 sats used / 14 in view. (Persistent mask applied later same day — see entry above.)

**2026-06-09** — Fixed lower-left empty trace-review popup: `#track-chart-panel` starts with the `hidden` attribute in HTML, but its CSS set `display:flex`, overriding browser hidden behavior and leaving an empty chart panel visible on the map before any track popup was opened. Added `#track-chart-panel[hidden] { display: none !important; }` and clear chart title/body in `hideTrackChart()` so stale trace-review content cannot flash. Also kept transparent `errorTileUrl` fallback for local/online Leaflet tile failures as defensive cleanup. JS syntax check passed with `node --check static/js/app.js`; OPS-TOC restarted.

**2026-06-06** — GPS recording: added speed-based outlier rejection (drops points implying >100 m/s = 360 km/h, catching GPS jumps) and minimum 4-satellite requirement. Prevents erratic jumps in recorded tracks caused by brief signal loss/re-acquisition.

**2026-06-05** — Track UX overhaul: removed Discard toolbar button (now only accessible via Save dialog); replaced sequential appPrompt stop flow with a single Save Track dialog (name + folder + colour swatches + custom colour input, Discard option when stopping). Track list now groups tracks by folder with collapsible headers. Track Edit dialog includes name, folder, and colour. Markers and Add Marker buttons consolidated into a Markers ▾ dropdown. App-dialog buttons made larger for touch.

**2026-06-04** — Fixed track naming on mobile: `onclose` (backdrop-tap path) was returning null instead of `input.value`, silently discarding the typed name. `b8c4499`.
**2026-06-04** — Fixed track stop dialog: name input now hidden during confirm step (CSS `hidden` attribute override by `label{display:block}` — switched to `style.display`). Track end markers changed from plain squares to SVG teardrop location-pin shape. GPS port scan now shows device names (`ttyACM1 — u-blox GNSS receiver`) via sysfs. GPS port-row visibility fixed same way as dialog. pyserial added to requirements.txt. GPS configured on ttyACM1 (was wrongly set to ttyACM2 — mapping shifted). Added Restart confirmation dialog. `9e221b7`, `3f30627`, `fd5e8c5`.
**2026-06-03** — Fixed track save dialog never resolving on mobile (backdrop tap fires only `onclose`, not `oncancel`, leaving the promise hung). Added `settled` guard + `onclose` now always resolves promise. Auto-save with default name when dialog is dismissed; banner notifies user. Added **Discard** button (red, toolbar, visible only during recording) with confirm before discarding live recording. Committed `c45e38e`, pushed to GitHub.
**2026-06-03** — Git repo consolidated: `~/Projects/ops-toc/` is now the real git checkout (was `~/Projects/map-app/`). In-app update (git pull + service restart) now works. `map-app/` is stale/unused. All future commits go directly from `ops-toc/`.
**2026-06-02** — Final Codex bug sweep pushed to GitHub (`ce5fa38`): downloaded-map Repair endpoint now returns/enqueues repair jobs; LOG/MISSIONS rendering escapes mission names/categories from shared OM `toc_log`; OPS-TOC and Dashboard health verified.
**2026-06-02** — Local rename completed: checkout moved to `~/Projects/ops-toc`, user service renamed to `ops-toc.service`, Dashboard tile now launches OPS-TOC on port 8090, and stale `map-app.service` was retired. Shared DB names remain `~/maps/map_app.db` and `MAP_APP_*` for compatibility with other map consumers.
**2026-06-02** — GitHub repository renamed from `Slofi/map-app` to `Slofi/ops-toc`; local `origin` updated to `git@github.com:Slofi/ops-toc.git`.
**2026-06-02** — Codex compatibility/service pass: OPS-TOC log filtering now applies category/mission/search before the 500-row display limit, so older matching entries are found. Mission rename/remove is case-insensitive. OM was updated to support the shared `WEATHER` category. `log-app.service` was stopped/disabled; former `map-app.service` was active but disabled at boot. Pushed to GitHub (`127e5d5` in `Slofi/ops-toc`, `aee724b` in `Slofi/overmesh`).
**2026-06-02** — Added SOP tab: 8 interactive checklist sections (Activation, Pre-Departure, En Route, Arrival, Open Station, Close Station, Comms Degraded, RC Run) + 2 reference sections (Log Discipline, Category Reference). Progress bars, collapse/expand, per-section and global reset, state persisted in localStorage. Pushed to GitHub (d0b9ea0).
**2026-06-02** — Renamed to OPS-TOC. UI polish: font 15px, toolbar 56px, burger+GPS pinned right, UI zoom slider (80–130%) in Appearance. Custom split clipboard+pin SVG brand icon. Pushed to GitHub (26217d5).
**2026-06-02** — Bug sweep 2: offline settings crash from LOG/MISSIONS tab fixed (prepareOfflineSection, updateOfflineEstimate, currentBoundsPayload, startOfflineDownload all guarded against null state.map). renderBody leading blank line on mission-tagged entries fixed. Deployed to CD (b2d799f).
**2026-06-02** — Bug sweep 1: LOG/MISSIONS tabs were 300px wide (grid layout fix), GPS marker crashed every 3s when map not yet opened, edit entry reset timestamp to now. Deployed to CD (0be590e).
**2026-06-02** — Deployed to CD (d2df5fd). log-app service disabled + retired, TOC-app launcher tile removed. Map App now owns all LOG + MISSIONS functionality on CD.
**2026-06-02** — Merged TOC-app into Map App. Added LOG tab (entry composer, all 10 categories, mission/GPS attach, filter bar, timeline) and MISSIONS tab (mission manager). Backend adds /api/log/* routes sharing overmesh_prefs.db toc_log table with OM. Toolbar restructured: main tabs always visible, map tools hidden on LOG/MISSIONS. GPS status badge always visible. Map init deferred to first MAP tab open. Log export/import added to hamburger.
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
OPS-TOC / Map App (port 8090)
  Flask backend           → serves HTML, markers, drawings, tile proxy
  Offline downloader      → downloads tiles from online sources
  Tile manager            → manages ~/maps/mbtiles/ (delete, refresh)
  LOG/MISSIONS/SOP        → shares OM toc_log in ~/overmesh/overmesh_prefs.db
  Marker/drawing owner    → SQLite DB at ~/maps/map_app.db
        ↓ writes MBTiles to ~/maps/mbtiles/
mbtileserver (port 8092)  → serves all apps: Sonde App, OM (opt-in), future apps
```

**Design rule:** OPS-TOC owns all map-specific controls (markers, drawings, tracks, downloads). OM may consume map data read-only later but must not own add/edit/delete controls.

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
