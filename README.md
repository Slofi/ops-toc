# OPS-TOC

OPS-TOC is the Cyberdeck's main map-management and field-operations app. It is the former standalone Map App after the TOC-app merge.

## Goals

- Keep the map as its own app, not an OM tab.
- Store downloaded/offline maps in one shared location.
- Store custom markers, drawings, GPS tracks, and downloaded-map controls in OPS-TOC.
- Let OM consume markers/tiles later without owning the marker controls.
- Record GPS traces from OM proxy or direct serial GPS and export them as GPX/GeoJSON.
- Host the field LOG, MISSIONS, and SOP workflows in the same app.
- Share LOG/MISSIONS with OM through the same `~/overmesh/overmesh_prefs.db` `toc_log` table.
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
/home/slofi/overmesh/overmesh_prefs.db  # shared toc_log with OM
```

## GPS And Tracks

OPS-TOC has GPS support in two modes:

- OM proxy: polls OM's GPS endpoint so only OM owns the serial GPS device.
- Direct serial: opens a local GPS dongle/serial port when running standalone.

On the Cyberdeck, direct serial includes the internal Beitian BN-220/BN-280-style
GPS on Rock 5B UART3 at `/dev/ttyS3`. In Settings -> GPS/Position, choose
`Direct serial port` and then `Internal BN-220 / BN-280 GPS - Rock 5B UART3
(/dev/ttyS3)`. USB GPS dongles remain available through `Auto-detect USB GPS`
and any stable `/dev/serial/by-id/*` entries.

OPS-TOC also exposes its current GPS state at `GET /api/settings/gps`, using the
same shape as OM's GPS proxy endpoint. Other CD apps can point their GPS proxy
base URL at `http://localhost:8090` to consume OPS-TOC's internal GPS fix.

The toolbar `GPS` button jumps to the current fix. The toolbar `Track` button
records a live dashed gold trace while GPS has a fix. Stopping the recording
saves it as a first-class track in OPS-TOC's SQLite DB.

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
- `GET /api/gps` - read OPS-TOC's live GPS state and config.
- `POST /api/gps` - update GPS source/config.
- `GET /api/gps/ports` - list USB GPS and internal UART GPS choices.
- `GET /api/settings/gps` - OM-compatible GPS proxy endpoint for other apps.
- `GET /api/tracks` - read saved GPS tracks for TOC/OM integrations.
- `GET /api/tile-layers` - list local MBTiles and online layers.
- `GET /tiles/<layer>/<z>/<x>/<y>.png` - OPS-TOC's built-in local tile endpoint.
- `GET /api/export/geojson` - export markers and drawings.
- `POST /api/om/share-marker/<id>` - placeholder for later OM waypoint sharing.

## LOG / MISSIONS / SOP Integration

TOC-app (Field Log) has been merged into OPS-TOC. The old standalone `log-app.service`
is retired, stopped, and disabled. OPS-TOC now owns LOG, MISSIONS, and SOP.

- OPS-TOC owns all map controls (markers, drawings, tracks, downloads)
- LOG/MISSIONS are wired directly to the shared `overmesh_prefs.db` (`toc_log` table) that OM also reads/writes
- DB split: log entries from `~/overmesh/overmesh_prefs.db`, markers/drawings/tracks from `~/maps/map_app.db`
- Category compatibility with OM includes NOTE, PLAN, SITREP, ALERT, ACTION, COMMS, CONTACT, POSITION, INTEL, and WEATHER
- SOP is app-local UI state stored in browser localStorage

Shared CD tiles are served for other apps by `mbtileserver` on port `8092`, reading
the same `/home/slofi/maps/mbtiles/` directory OPS-TOC writes to. OM consumes that
shared server only when its `Use shared local tile DB` setting is enabled.

## Online Layers

OPS-TOC mirrors the OM online layer catalog, including CARTO, Esri, Stadia/Stamen,
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

OPS-TOC derives readable accent and dim active-state colours the same way OM does.

## Place Search

The toolbar search box calls OPS-TOC's backend `/api/search` route. The backend
queries OpenStreetMap Nominatim with an OPS-TOC User-Agent and returns app-native
results; choosing a result pans/zooms the map and drops a temporary search marker.
