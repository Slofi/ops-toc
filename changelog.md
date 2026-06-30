# OPS-TOC / Map App - Changelog

## 2026-06-30

**[Claude]** - HD 5-inch touch display optimisation (`@media (max-width: 1024px)` block in `app.css`): topo background texture via `html` background-image (copy `~/overmesh/static/background-topo.png` to `~/Projects/ops-toc/static/` on CD to activate); frosted glass toolbar with amber bottom border; amber 2px indicator bar at top of active main tab; enlarged touch targets for main tabs (40px height), hamburger button (52×48px), dropdown menu items (52px), list rows (44px min), composer select/text inputs (36px), SOP items (44px) with 20×20px checkbox, checklist card headers; body textarea reduced to 72px height to leave more room for log entries; body padding/gap tightened (5px/3px) to recover vertical space on 600px screen. CSS degrades gracefully if background PNG is missing.

**[Codex]** - Corrected the internal Cyberdeck GPS diagnosis. The BN-280 on Rock 5B UART3 (`/dev/ttyS3`) is confirmed working after balcony testing: OPS-TOC reported `fix=true`, `lat=46.039179`, `lon=14.497671`, `alt=302`, `sats=8`, and `sats_view=13`. Earlier "likely dead" notes are superseded. The key operational caveat is that OPS-TOC must use explicit `/dev/ttyS3`; `port: "auto"` only follows USB GPS dongles and will not select the internal receiver. A restart/re-init after setting `/dev/ttyS3` produced the fix.

## 2026-06-18

**[Codex]** - Added the editable OPS-TOC CHECKLIST tab after SOP. Checklists are pure frontend localStorage state under `ops_toc_checklists`, with folders/types, multiple collapsible cards, rename/delete/reset, progress counts/bars, item add/edit/delete/toggle/reorder, text export, JSON export, and import from JSON/TXT/MD including Markdown task boxes like `- [ ]`, `- []`, and `- [x]`. Removed the temporary field-template loader and cleaned out the backend `/api/checklists/seed` route because Import now covers saved/template files. Copied the Desktop checklist test files into repo `TEST/` without removing the Desktop originals. Added the header clock (`HH:MM:SS`, `DD.MM.YY`), enlarged Settings/App Control touch targets, and changed in-app UI Zoom so visible `100%` now includes a 1.15x base scale matching the user's previous `115%` setting, with a one-time migration from saved `115%` to `100%`.

## 2026-06-12

**[Codex]** - Improved OPS-TOC as the central offline map hub and pushed GitHub commit `4d33754 Improve offline maps and controls`. Offline downloads and zoom-extension estimates now include estimated size, extension jobs estimate missing/new tiles before queueing, and zero-tile extensions are skipped. Downloaded MBTiles maps can now be renamed from the UI/API. Extension jobs copy/repair the existing MBTiles into the `.part` file before adding new zooms, preventing edit-zoom jobs from replacing an existing map with only the new zoom range. Missing-tile estimation was optimized, and terminal jobs no longer expose bulky payloads. Added click/press feedback animations across controls, tidied GPS settings with an iPhone-style receiver switch, and added black splash screens for Restart/Shutdown.

## 2026-06-03

**[Claude]** — Fixed track save dialog losing the track on mobile. Root cause: mobile Chromium backdrop tap fires only the `close` event on `<dialog>`, not `cancel`. The old `onclose` handler only called `cleanup()` without resolving the promise, so the async chain hung and the API save call never ran. Fix: added a `settled` guard and made `onclose` always resolve the promise (to null), regardless of close path. In `stopTrackRecording`, when the dialog resolves to null (dismissed/cancelled), the track now auto-saves with a default name and shows a 6-second banner: "Track auto-saved as '…' — rename from track list". Track is never silently lost. (`c45e38e`)

**[Claude]** — Added **Discard** button to the toolbar. Appears (red, danger style) only while a GPS recording is active. Asks for confirmation, then clears the recording without saving. Previously the only way to discard a recording was to stop it, name it, save it, then delete it from the track list. (`c45e38e`)

**[Claude]** — Consolidated git repo to `~/Projects/ops-toc/`. Previously: `.git` lived in `~/Projects/map-app/`; the workflow was edit in `ops-toc/`, copy files to `map-app/`, commit from there. This made the in-app git-pull update fail with 500 (run_git ran in `ops-toc/` which had no `.git`). Fix: pushed the outstanding commit from `map-app/`, then `git init` + remote + fetch + reset --hard in `ops-toc/`. All future commits go directly from `ops-toc/`. `map-app/` is now stale/unused.

## 2026-06-02

**[Codex]** - Bug sweep after local OPS-TOC rename: fixed the downloaded-map Repair endpoint so it returns/enqueues the repair job instead of falling through with no response. Hardened LOG/MISSIONS rendering so mission names and categories from the shared OM `toc_log` DB are escaped before use in HTML attributes, inline handlers, and CSS class names. Verified OPS-TOC service, dashboard status, log/missions APIs, tile layers API, and JS/Python syntax checks.

**[Codex]** - Completed the local rename after the GitHub repo rename: checkout moved to `~/Projects/ops-toc`, the user service is now `ops-toc.service`, stale `map-app.service` was retired, in-app restart/update controls target the new unit, and the Cyberdeck Dashboard tile now launches OPS-TOC on port 8090. Compatibility names for shared map data remain unchanged: `~/maps/map_app.db`, `MAP_APP_*`, and `map_app_tile_url`.

**[Codex]** - Renamed the running app to OPS-TOC after the TOC-app merge. OPS-TOC now owns the main map-management surface plus LOG, MISSIONS, and SOP. The map DB remains `~/maps/map_app.db`; the field log remains shared with OM through `~/overmesh/overmesh_prefs.db` table `toc_log`.

**[Codex]** - Fixed shared log compatibility and service state. OPS-TOC now filters category/mission/search in SQL before applying the display limit, so older matching log rows are not hidden. Mission rename/remove is case-insensitive. OM now accepts and edits `WEATHER` entries, matching OPS-TOC's category set. The standalone `log-app.service` is stopped/disabled. Pushed OPS-TOC commit `127e5d5` and OM commit `aee724b`.

**[Claude/Codex]** - Added SOP tab, LOG/MISSIONS tabs, OPS-TOC UI polish, deferred map initialization, fixed LOG/MISSIONS layout, GPS marker behavior before map initialization, edit timestamp preservation, offline settings guards when map is not initialized, and mission-tag rendering cleanup.

## 2026-05-25

**[CD/Codex]** - Pulled the CD-pushed offline download management work back to TestBox. Map App now has a real in-app download queue for new downloads, refreshes, repairs, and update-all jobs; pause/resume/cancel controls; a Download Queue settings panel; richer Downloaded Tilesets metadata and summary totals; per-tileset Use, Repair, Refresh, and Delete actions; safe `.part` writes for refresh/update so existing MBTiles are only replaced after success; and an app-package-style settings UI.

**[Codex]** - Updated `status.md` with the current queue behavior, API endpoints, and follow-up risks from the CD-pushed version.

**[Codex]** - Added SQLite-backed download job persistence locally on TestBox. The `download_jobs` table stores job state and payloads so queued jobs survive restart, paused jobs remain paused until resumed, and interrupted running jobs are restored as queued for retry.

**[Codex]** - Added true partial MBTiles resume locally on TestBox. Restarted jobs now reuse readable `.part` files, skip already-saved tiles, and fetch only missing entries; unreadable partials are discarded and rebuilt. Finished/error/cancelled job records are pruned after 7 days by default, and individual tile downloads retry with short backoff before being counted as failed.

**[Codex]** - Added Download Queue polish locally on TestBox: job API responses now include elapsed time, tile rate, and ETA; the queue panel shows active/finished/failed counts; and a Clear Finished button removes completed/cancelled/error job records without deleting downloaded MBTiles.

**[Codex]** - Added GPX import/export locally on TestBox. Export writes markers as waypoints and drawings as tracks; import reads waypoints into markers and tracks/routes into line drawings from Settings -> Import / Export.

**[Codex]** - Added local Map App <-> OverMesh marking exchange. Map App can pull OM Marks/Self Notes/Overlays into local markers/drawings, and push Map App markers/drawings into OM as Self Notes/Overlays. The exchange is HTTP/GeoJSON based and deliberately local-only: it does not broadcast marks over the mesh.

**[Codex]** - Added an app-native searchable manual to the hamburger menu, modeled after OM's in-app manual. It covers map basics, markers, drawings/ruler, offline maps, queue controls, import/export, OM sync, appearance, API keys, updates, restart, and shutdown.

## 2026-05-24

**[Codex]** - Added current-view offline map downloads. The toolbar `Offline` dialog estimates tile counts, downloads the selected online base layer into MBTiles under `/home/slofi/maps/mbtiles/`, tracks progress, refreshes the local layer list when complete, and exposes the catalog/tiles with CORS so local OM can consume the same tiles on the CD.

**[Codex]** - Fixed two live-review UI issues: closing the Markers side panel now toggles an explicit layout class and invalidates Leaflet size so no stale black map area remains; the magnifier no longer rebuilds/recenters its tile layer on every mousemove, uses same-zoom cached tiles with CSS optical scaling, and throttles center updates to avoid black/laggy behavior.

**[Codex]** - Added pointer precision and native interaction polish: marker/ruler/line/area placement now shows a circular Leaflet magnifier following the pointer, synchronized to the current base layer at a higher zoom. Replaced browser-native `alert`, `confirm`, and `prompt` flows with an app-native dialog. Added toolbar place search backed by `/api/search`, which proxies OpenStreetMap Nominatim and returns app-native selectable results that pan/zoom the map.

**[Codex]** - Added Map App appearance/tooling refinements from live review: toolbar `Accent` dialog with OM-style accent/dim colour derivation and browser-local `mapAppAccentColor` storage; `Undo Last` button for in-progress ruler/line/area tools; Backspace/Delete undo shortcut for the latest in-progress point; and crosshair cursor while placing ruler/line/area points.

**[Codex]** - Mirrored OM's online map layer catalog into Map App: CARTO Voyager variants, Positron, Dark Matter, Esri Dark Gray/Satellite/Streets/Topo/Hillshade, Stadia/Stamen Toner Lite/Toner Dark/Terrain, Stadia Outdoors, Thunderforest Landscape/Outdoors/Pioneer/Atlas, and MapTiler Satellite Hybrid/Topo/Streets/Winter. Added a toolbar `Keys` dialog for Thunderforest and MapTiler API keys, stored under the same browser localStorage keys as OM (`thunderforestApiKey`, `mapTilerApiKey`).

**[Codex]** - Created initial standalone Map App scaffold from the Hand-Deck launcher map concept. Added Flask backend, SQLite storage, MBTiles tile serving, marker CRUD API, drawing API, multi-point distance measurement, GeoJSON export, local/online layer catalog, Leaflet UI, service file, README, and shared project status notes. Runtime smoke test passed with temporary data on port `18090`: health, tile layers, marker creation, drawing creation, and GeoJSON export.
