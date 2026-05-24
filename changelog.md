# Map App - Changelog

## 2026-05-24

**[Codex]** - Added pointer precision and native interaction polish: marker/ruler/line/area placement now shows a circular Leaflet magnifier following the pointer, synchronized to the current base layer at a higher zoom. Replaced browser-native `alert`, `confirm`, and `prompt` flows with an app-native dialog. Added toolbar place search backed by `/api/search`, which proxies OpenStreetMap Nominatim and returns app-native selectable results that pan/zoom the map.

**[Codex]** - Added Map App appearance/tooling refinements from live review: toolbar `Accent` dialog with OM-style accent/dim colour derivation and browser-local `mapAppAccentColor` storage; `Undo Last` button for in-progress ruler/line/area tools; Backspace/Delete undo shortcut for the latest in-progress point; and crosshair cursor while placing ruler/line/area points.

**[Codex]** - Mirrored OM's online map layer catalog into Map App: CARTO Voyager variants, Positron, Dark Matter, Esri Dark Gray/Satellite/Streets/Topo/Hillshade, Stadia/Stamen Toner Lite/Toner Dark/Terrain, Stadia Outdoors, Thunderforest Landscape/Outdoors/Pioneer/Atlas, and MapTiler Satellite Hybrid/Topo/Streets/Winter. Added a toolbar `Keys` dialog for Thunderforest and MapTiler API keys, stored under the same browser localStorage keys as OM (`thunderforestApiKey`, `mapTilerApiKey`).

**[Codex]** - Created initial standalone Map App scaffold from the Hand-Deck launcher map concept. Added Flask backend, SQLite storage, MBTiles tile serving, marker CRUD API, drawing API, multi-point distance measurement, GeoJSON export, local/online layer catalog, Leaflet UI, service file, README, and shared project status notes. Runtime smoke test passed with temporary data on port `18090`: health, tile layers, marker creation, drawing creation, and GeoJSON export.
