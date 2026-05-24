# Map App - Changelog

## 2026-05-24

**[Codex]** - Added Map App appearance/tooling refinements from live review: toolbar `Accent` dialog with OM-style accent/dim colour derivation and browser-local `mapAppAccentColor` storage; `Undo Last` button for in-progress ruler/line/area tools; Backspace/Delete undo shortcut for the latest in-progress point; and crosshair cursor while placing ruler/line/area points.

**[Codex]** - Mirrored OM's online map layer catalog into Map App: CARTO Voyager variants, Positron, Dark Matter, Esri Dark Gray/Satellite/Streets/Topo/Hillshade, Stadia/Stamen Toner Lite/Toner Dark/Terrain, Stadia Outdoors, Thunderforest Landscape/Outdoors/Pioneer/Atlas, and MapTiler Satellite Hybrid/Topo/Streets/Winter. Added a toolbar `Keys` dialog for Thunderforest and MapTiler API keys, stored under the same browser localStorage keys as OM (`thunderforestApiKey`, `mapTilerApiKey`).

**[Codex]** - Created initial standalone Map App scaffold from the Hand-Deck launcher map concept. Added Flask backend, SQLite storage, MBTiles tile serving, marker CRUD API, drawing API, multi-point distance measurement, GeoJSON export, local/online layer catalog, Leaflet UI, service file, README, and shared project status notes. Runtime smoke test passed with temporary data on port `18090`: health, tile layers, marker creation, drawing creation, and GeoJSON export.
