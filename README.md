# Map App

Standalone Leaflet map app for CD, Hand-Deck, and later OverMesh integration.

## Goals

- Keep the map as its own app, not an OM tab.
- Store downloaded/offline maps in one shared location.
- Store custom markers in the Map app, with add/edit/delete controls here.
- Let OM consume markers/tiles later without owning the marker controls.
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

## API Surface For Future OM Use

- `GET /api/markers` - read custom markers for OM overlay.
- `GET /api/tile-layers` - list local MBTiles and online layers.
- `GET /tiles/<layer>/<z>/<x>/<y>.png` - shared local tile endpoint.
- `GET /api/export/geojson` - export markers and drawings.
- `POST /api/om/share-marker/<id>` - placeholder for later OM waypoint sharing.

OM should initially consume markers and tiles read-only. Marker creation, editing,
deletion, drawing, measurement, and export controls stay in Map App.

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
