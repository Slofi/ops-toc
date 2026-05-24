# Map App - Status

Standalone Leaflet map app for Cyberdeck, Hand-Deck, and future OverMesh integration.

## Current State

Initial scaffold built. The app runs independently on Flask and stores its own data in a shared map directory by default:

- DB: `/home/slofi/maps/map_app.db`
- MBTiles folder: `/home/slofi/maps/mbtiles/`
- Port: `8090`

## Implemented

- Standalone Leaflet UI.
- Online layers: Voyager, OpenStreetMap, Esri satellite, Positron.
- Expanded online layer catalog copied from OM:
  - OSM, CARTO Voyager/No Labels, Positron, Dark Matter/No Labels
  - Esri Dark Gray, Satellite, Streets, Topo, Hillshade
  - Stadia/Stamen Toner Lite, Toner Dark, Terrain, Stadia Outdoors
  - Thunderforest Landscape/Outdoors/Pioneer/Atlas with API key support
  - MapTiler Satellite Hybrid/Topo/Streets/Winter with API key support
- API-key dialog in Map App stores keys in browser localStorage using the same keys as OM:
  - `thunderforestApiKey`
  - `mapTilerApiKey`
- Accent colour control:
  - toolbar `Accent` button opens a colour picker dialog
  - stored in browser localStorage as `mapAppAccentColor`
  - uses OM-style HSL normalization for readable `--accent` and dim active-state background
- Place search:
  - toolbar search calls `/api/search`
  - backend proxies OpenStreetMap Nominatim with a Map App User-Agent
  - results are app-native and selecting a result pans/zooms the map
- Local MBTiles catalog and tile endpoint: `/tiles/<layer>/<z>/<x>/<y>.png`.
- Custom markers owned by Map App:
  - add
  - edit
  - delete
  - list panel
  - `GET /api/markers` for future OM read-only overlay use
- Drawing tools:
  - line drawing
  - polygon/area drawing
  - adjustable multi-point ruler
  - `Undo Last` removes the most recent in-progress point
  - Backspace/Delete also remove the most recent in-progress point
  - ruler/line/area placement uses a crosshair cursor
  - marker/ruler/line/area placement shows a circular magnifier following the pointer
  - saved drawings in SQLite
- App-native dialogs replace browser `alert`, `confirm`, and `prompt` flows.
- Export:
  - `GET /api/export/geojson` exports markers and drawings.
- Future OM hook:
  - `POST /api/om/share-marker/<id>` exists as a placeholder and intentionally returns `501` until OM integration is designed.

## Pending

- Add real offline map download/import UI.
- Decide whether to use MBTiles only or also support PMTiles.
- Add GPX/KML import/export.
- Add marker categories, filters, and styling.
- Add route profile / segment list for ruler paths.
- Add optional GPS marker endpoint/client once CD/HD GPS source is decided.
- Later: make OM consume Map App markers and tiles read-only.
- Later: implement "Share via OM" by calling OM's waypoint API from Map App controls.

## Design Rule

Map App owns map-specific controls. OM may consume map data later, but should not own marker add/edit/delete controls.
