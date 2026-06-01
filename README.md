# Map App

Standalone Leaflet map app for CD, Hand-Deck, and later OverMesh integration.

## Goals

- Keep the map as its own app, not an OM tab.
- Store downloaded/offline maps in one shared location.
- Store custom markers in the Map app, with add/edit/delete controls here.
- Let OM consume markers/tiles later without owning the marker controls.
- Record GPS traces from OM proxy or direct serial GPS and export them as GPX/GeoJSON.
- Let TOC-app reference and log Map App tracks without merging the codebases.
- Keep radio/mesh sharing as a later OM-backed action.

## Run

```bash
python3 app.py
```

Default URL:

```text
http://localhost:8090
```

Default data paths:

```text
/home/slofi/maps/map_app.db
/home/slofi/maps/mbtiles/*.mbtiles
```

## GPS And Tracks

Map App has GPS support in two modes:

- OM proxy: polls OM's GPS endpoint so only OM owns the serial GPS device.
- Direct serial: opens a local GPS dongle/serial port when running standalone.

The toolbar `GPS` button jumps to the current fix. The toolbar `Track` button
records a live dashed gold trace while GPS has a fix. Stopping the recording
saves it as a first-class track in Map App's SQLite DB.

Saved tracks appear in the left side panel under `Tracks`, below markers and
drawings. Track actions:

- view/zoom on map
- edit name/description
- export GPX
- export GeoJSON
- convert to a drawing
- delete

Track API:

- `GET /api/tracks`
- `POST /api/tracks`
- `PUT /api/tracks/<id>`
- `DELETE /api/tracks/<id>`
- `GET /api/tracks/<id>/gpx`
- `GET /api/tracks/<id>/geojson`
- `POST /api/tracks/<id>/drawing`

## API Surface For Future OM Use

- `GET /api/markers` - read custom markers for OM overlay.
- `GET /api/tracks` - read saved GPS tracks for TOC/OM integrations.
- `GET /api/tile-layers` - list local MBTiles and online layers.
- `GET /tiles/<layer>/<z>/<x>/<y>.png` - Map App's built-in local tile endpoint.
- `GET /api/export/geojson` - export markers and drawings.
- `POST /api/om/share-marker/<id>` - placeholder for later OM waypoint sharing.

## TOC-app Integration

TOC-app stays a separate app and reads Map App over HTTP instead of merging
repositories. TOC-app's Map tab can:

- check Map App status at `http://localhost:8090`
- list saved Map App tracks
- open per-track GPX/GeoJSON exports
- write a selected Map App track into the shared OM/TOC `toc_log` table as a
  `POSITION` entry

Shared CD tiles are served for other apps by `mbtileserver` on port `8092`, reading
the same `/home/slofi/maps/mbtiles/` directory Map App writes to. OM consumes that
shared server only when its `Use shared local tile DB` setting is enabled.
Marker creation, editing, deletion, drawing, measurement, and export controls stay
in Map App.

## Online Layers

Map App mirrors the OM online layer catalog, including CARTO, Esri, Stadia/Stamen,
Thunderforest, and MapTiler layers. Thunderforest and MapTiler layers need API
keys; use the `Keys` button in the toolbar. Keys are saved in browser
localStorage with the same names OM uses:

```text
thunderforestApiKey
mapTilerApiKey
```

## Appearance

Use the `Accent` button in the toolbar to set the UI accent colour. The selected
colour is saved in browser localStorage as:

```text
mapAppAccentColor
```

Map App derives readable accent and dim active-state colours the same way OM does.

## Place Search

The toolbar search box calls Map App's backend `/api/search` route. The backend
queries OpenStreetMap Nominatim with a Map App User-Agent and returns app-native
results; choosing a result pans/zooms the map and drops a temporary search marker.
