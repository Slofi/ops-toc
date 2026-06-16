const state = {
  map: null,
  baseLayer: null,
  markers: new Map(),
  markerLayers: new Map(),
  drawings: new Map(),
  drawingLayers: new Map(),
  tracks: new Map(),
  trackLayers: new Map(),
  trackVisible: new Map(),
  recording: null,
  recordingLayer: null,
  tool: null,
  toolPoints: [],
  toolMarkers: [],
  toolLine: null,
  activeLayerValue: "",
  magnifierMap: null,
  magnifierLayer: null,
  magnifierLatLng: null,
  magnifierRaf: 0,
  magnifierLastUpdate: 0,
  searchMarker: null,
  offlinePoll: 0,
  queuePoll: 0,
  offlineBounds: null,
  offlineJobId: null,
  collapsedFolders: new Set(),
};

const el = (id) => document.getElementById(id);
const DEFAULT_ACCENT = "#e8b04f";
const TRACK_COLOR = "#e8b04f";
const TRACK_COLORS = ["#e8b04f","#ef4444","#22c55e","#3b82f6","#a855f7","#f97316","#06b6d4","#ec4899"];
let _trackSaveSelectedColor = TRACK_COLOR;

function bindClick(id, handler) {
  const node = el(id);
  if (node) node.onclick = handler;
}

function bindEvent(id, eventName, handler) {
  const node = el(id);
  if (node) node.addEventListener(eventName, handler);
}

function installControlFeedback() {
  const selector = [
    ".btn",
    ".menu-item",
    ".main-tab",
    ".layer-opt",
    ".search-result",
    ".list-row",
    ".sop-section-head",
    ".track-folder-header",
    ".color-swatch",
    ".color-swatch-custom",
    ".switch-control",
  ].join(",");
  document.addEventListener("click", (event) => {
    const node = event.target.closest(selector);
    if (!node || node.disabled || node.getAttribute("aria-disabled") === "true") return;
    node.classList.remove("click-feedback");
    void node.offsetWidth;
    node.classList.add("click-feedback");
    window.setTimeout(() => node.classList.remove("click-feedback"), 260);
  }, true);
}

function showServiceSplash(message) {
  const splash = el("service-splash");
  const msg = el("service-splash-message");
  if (!splash || !msg) return;
  msg.textContent = message;
  splash.hidden = false;
}

function hideServiceSplash() {
  const splash = el("service-splash");
  if (splash) splash.hidden = true;
}

function hexToHsl(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    if (max === g) h = ((b - r) / d + 2) / 6;
    if (max === b) h = ((r - g) / d + 4) / 6;
  }
  return [Math.round(h * 360), Math.round(s * 100), Math.round(l * 100)];
}

function hslToHex(h, s, l) {
  s /= 100;
  l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const k = (n + h / 30) % 12;
    const c = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * c).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function applyAccentColor(hex) {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex || "")) return;
  const [h, s, l] = hexToHsl(hex);
  const accentHex = hslToHex(h, s, Math.max(l, 45));
  const dimHex = hslToHex(h, Math.min(s * 0.5, 35), Math.max(l * 0.25, 12));
  document.documentElement.style.setProperty("--accent", accentHex);
  document.documentElement.style.setProperty("--accent-dim", dimHex);
  document.documentElement.style.setProperty("--accent-faint", `hsla(${h}, ${s}%, ${Math.max(l, 45)}%, 0.10)`);
  document.documentElement.style.setProperty("--accent-mid", `hsla(${h}, ${s}%, ${Math.max(l, 45)}%, 0.32)`);
  const swatch = el("accent-swatch");
  if (swatch) swatch.style.background = accentHex;
}

function currentAccentColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || DEFAULT_ACCENT;
}

function applyUIZoom(pct) {
  const scale = Math.min(130, Math.max(80, Number(pct) || 100));
  document.documentElement.style.zoom = (scale / 100).toString();
}

function saveZoom() {
  const pct = Number(el("ui-zoom-input")?.value || 100);
  localStorage.setItem("mapAppUIZoom", pct);
  applyUIZoom(pct);
}

function resetZoom() {
  localStorage.removeItem("mapAppUIZoom");
  if (el("ui-zoom-input")) { el("ui-zoom-input").value = 100; el("ui-zoom-value").textContent = "100%"; }
  applyUIZoom(100);
}

function appDialog({ title = "Message", message = "", mode = "alert", value = "", placeholder = "" }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (val) => { if (!settled) { settled = true; resolve(val); } };

    const dialog = el("app-dialog");
    const form = el("app-dialog-form");
    const inputWrap = el("app-dialog-input-label");
    const input = el("app-dialog-input");
    const cancel = el("app-dialog-cancel");
    el("app-dialog-title").textContent = title;
    el("app-dialog-message").textContent = message;
    inputWrap.style.display = mode === "prompt" ? "" : "none";
    cancel.hidden = mode === "alert";
    input.value = value;
    input.placeholder = placeholder;

    const cleanup = () => {
      form.onsubmit = null;
      cancel.onclick = null;
      dialog.oncancel = null;
      dialog.onclose = null;
    };
    form.onsubmit = (event) => {
      event.preventDefault();
      cleanup();
      dialog.close();
      finish(mode === "prompt" ? input.value : true);
    };
    cancel.onclick = (event) => {
      event.preventDefault();
      cleanup();
      dialog.close();
      finish(mode === "confirm" || mode === "prompt" ? null : false);
    };
    dialog.oncancel = (event) => {
      event.preventDefault();
      cleanup();
      dialog.close();
      finish(mode === "confirm" || mode === "prompt" ? null : false);
    };
    // onclose fires for uncontrolled close paths (backdrop tap on mobile, layout-shift misses)
    // For prompt: return whatever is typed so a stray backdrop tap doesn't silently discard the name.
    // For confirm/alert: null/false as before.
    dialog.onclose = () => { cleanup(); finish(mode === "prompt" ? input.value : (mode === "confirm" ? null : false)); };
    dialog.showModal();
    if (mode === "prompt") setTimeout(() => {
      input.focus();
      input.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); form.requestSubmit(el("app-dialog-ok")); }
      };
    }, 60);
  });
}

function appAlert(message, title = "OPS-TOC") {
  return appDialog({ title, message, mode: "alert" });
}

function appConfirm(message, title = "Confirm") {
  return appDialog({ title, message, mode: "confirm" });
}

function appPrompt(message, value = "", title = "Name") {
  return appDialog({ title, message, value, mode: "prompt" });
}

function fmtDistance(meters) {
  if (!Number.isFinite(meters)) return "0 m";
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(meters < 10000 ? 2 : 1)} km`;
}

function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getFullYear()).slice(-2)}`;
}

function fmtDateTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const hh  = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${fmtDate(ts)} ${hh}:${min}`;
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function fmtBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function fmtTileEstimate(tiles, bytes = 0) {
  const count = Number(tiles || 0);
  const size = Number(bytes || 0);
  const parts = [`${count.toLocaleString()} tiles`];
  if (size > 0) parts.push(`~${fmtBytes(size)}`);
  return parts.join(" · ");
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const MAP_APP_MANUAL_SECTIONS = [
  {
    title: "Map Basics",
    tags: "map layers search markers drawings ruler toolbar side panel",
    body: [
      "OPS-TOC is the Cyberdeck map workspace. It owns local markers, drawings, measurements, offline tile downloads, and app-to-app marking exchange.",
      "The layer selector switches between online layers and local MBTiles. Local layers appear after a download completes or after the shared tile server sees MBTiles in the shared folder.",
      "The place search box uses the OPS-TOC backend to query Nominatim, then pans or zooms to the selected result."
    ],
    buttons: [
      ["Markers", "Open or close the left panel with saved markers and drawings."],
      ["Search", "Find places by name and jump the map to the selected result."],
      ["Layer menu", "Choose online or local MBTiles base layers."],
      ["GeoJSON", "Export all current markers and drawings as GeoJSON."]
    ]
  },
  {
    title: "Markers",
    tags: "markers pins notes add edit delete category emoji om sync",
    body: [
      "Markers are local OPS-TOC points. They have a name, optional description, icon text, and category.",
      "Use Add Marker, then click the map. Existing markers can be edited or deleted from the marker popup or the left panel.",
      "When pushed to OM through local sync, OPS-TOC markers become OM Self Notes. They are not broadcast as mesh waypoints."
    ],
    buttons: [
      ["Add Marker", "Start marker placement. Click the map to open the marker form."],
      ["Edit", "Change marker text, description, icon text, or category."],
      ["Delete", "Remove the marker from OPS-TOC only."],
      ["Push To OM", "Send markers to OM as local Self Notes."]
    ]
  },
  {
    title: "Drawings And Ruler",
    tags: "drawings ruler line polygon area measure undo finish delete",
    body: [
      "Draw Line, Draw Area, and Ruler all create multi-point map drawings. Ruler paths also store total distance.",
      "While placing points, the cursor becomes a crosshair and a magnifier bubble helps with precise placement.",
      "Undo Last removes the most recent in-progress point. Finish saves the shape; Cancel discards the in-progress shape."
    ],
    buttons: [
      ["Ruler", "Measure a multi-point path and optionally save it."],
      ["Draw Line", "Create a saved line drawing."],
      ["Draw Area", "Create a saved polygon drawing."],
      ["Undo Last", "Delete the latest point in the active drawing."],
      ["Finish", "Save the active drawing."],
      ["Cancel", "Discard the active drawing."]
    ]
  },
  {
    title: "GPS Tracks",
    tags: "gps track trace record dongle gpx geojson edit share",
    body: [
      "GPS can run through OM proxy or direct serial. Record stores fixed GPS positions as a saved track with distance, timestamps, and altitude when available.",
      "Saved tracks can be viewed on the map, logged into the shared field log, renamed, exported as GPX or GeoJSON, converted into a drawing, or deleted."
    ],
    buttons: [
      ["GPS", "Jump to the current GPS fix."],
      ["Record", "Start or stop a GPS trace."],
      ["Log", "Create a TRACK log entry from a saved GPS track."],
      ["Edit", "Rename a saved track."],
      ["GPX", "Download one track as a GPX file."],
      ["GeoJSON", "Open one track as GeoJSON for sharing."]
    ]
  },
  {
    title: "Offline Maps",
    tags: "offline maps mbtiles downloads zoom region tiles layers queue local tile server",
    body: [
      "Offline downloads write MBTiles into the shared Cyberdeck folder, normally ~/maps/mbtiles/. The CD tile server and other apps can use those files.",
      "Use Find region or Use Current View, choose an online source, set min/max zoom, then Download. Higher zoom levels grow very fast.",
      "Downloaded maps appear in Downloaded Tilesets with actions for Use, Repair, Refresh, and Delete."
    ],
    buttons: [
      ["Find region", "Search for a named region and use its bounds for the download."],
      ["Use Current View", "Use the visible map area as the download bounds."],
      ["Country / Region / Local / Detail", "Apply practical zoom presets."],
      ["Download", "Queue a new MBTiles download."],
      ["Repair", "Download missing tiles for an existing tileset."],
      ["Refresh", "Re-download the same bounds and zoom range."]
    ]
  },
  {
    title: "Download Queue",
    tags: "queue pause resume cancel eta speed retry partial resume update all repair all",
    body: [
      "Downloads are queued so OPS-TOC does not hammer tile providers. The queue shows progress, saved/failed tiles, speed, and ETA.",
      "Jobs are persisted in SQLite. Queued and paused jobs survive restart; interrupted jobs can resume from readable .part MBTiles files and skip already saved tiles.",
      "Finished, cancelled, and failed job records can be cleared without deleting downloaded maps."
    ],
    buttons: [
      ["Pause", "Pause a queued or running job."],
      ["Resume", "Continue a paused job."],
      ["Cancel", "Cancel a job and remove its partial file."],
      ["Repair Missing", "Queue repair jobs for downloaded maps."],
      ["Update All", "Queue refresh jobs for all refreshable maps."],
      ["Clear Finished", "Remove finished job records only."]
    ]
  },
  {
    title: "Import, Export, And OM Sync",
    tags: "gpx geojson import export overmesh om sync pull push markings overlays self notes",
    body: [
      "GPX import creates markers from waypoints and line drawings from tracks/routes. GPX export writes markers as waypoints and drawings as tracks.",
      "Pull From OM imports OM Marks, Self Notes, and Overlays into OPS-TOC markers and drawings.",
      "Push To OM sends OPS-TOC markers as OM Self Notes and drawings as OM Overlays. This is local-only and does not broadcast anything over the mesh."
    ],
    buttons: [
      ["Import GPX", "Read GPX waypoints, tracks, and routes into OPS-TOC."],
      ["Export GPX", "Download OPS-TOC markings as GPX."],
      ["Export GeoJSON", "Download OPS-TOC markings as GeoJSON."],
      ["Pull From OM", "Import OM local map markings from the configured OM URL."],
      ["Push To OM", "Send OPS-TOC markings to OM as local notes and overlays."]
    ]
  },
  {
    title: "Appearance, Keys, And App Control",
    tags: "settings accent keys thunderforest maptiler update restart shutdown version",
    body: [
      "Appearance controls the accent color. API keys are stored in this browser profile using the same localStorage key names as OM.",
      "Version check compares the local git checkout to GitHub. Update pulls from GitHub and restarts OPS-TOC when successful.",
      "Restart and Shutdown act on the user systemd service on the target device."
    ],
    buttons: [
      ["Save Keys", "Save Thunderforest and MapTiler API keys in the browser profile."],
      ["Save Accent", "Store the current accent color in the browser profile."],
      ["Check Version", "Compare the running checkout with GitHub."],
      ["Update", "Run git pull and restart the service after success."],
      ["Restart", "Restart ops-toc.service."],
      ["Shutdown", "Stop ops-toc.service."]
    ]
  }
];

function manualText(section) {
  const buttonText = (section.buttons || []).map(([label, desc]) => `${label} ${desc}`).join(" ");
  const splitText = (section.split || []).map((group) => [
    group.title,
    ...(group.body || []),
    ...(group.buttons || []).map(([label, desc]) => `${label} ${desc}`),
  ].flat().join(" ")).join(" ");
  return [section.title, section.tags, ...(section.body || []), buttonText, splitText].join(" ").toLowerCase();
}

function manualSearchParts(query = "") {
  const raw = String(query || "").trim().toLowerCase();
  return { raw, terms: raw.split(/\s+/).filter(Boolean) };
}

function manualEscapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function manualHighlight(text, parts) {
  let out = esc(text || "");
  const needles = [...new Set([parts?.raw, ...(parts?.terms || [])].filter((s) => s && s.length >= 2))]
    .sort((a, b) => b.length - a.length);
  if (!needles.length) return out;
  const re = new RegExp(`(${needles.map((needle) => manualEscapeRegExp(esc(needle))).join("|")})`, "ig");
  return out.replace(re, "<mark>$1</mark>");
}

function manualScore(section, parts) {
  if (!parts?.terms?.length) return { score: 1, matches: 0 };
  const title = String(section.title || "").toLowerCase();
  const tags = String(section.tags || "").toLowerCase();
  const body = (section.body || []).join(" ").toLowerCase();
  const buttons = (section.buttons || []).map(([label, desc]) => `${label} ${desc}`).join(" ").toLowerCase();
  const split = (section.split || []).map((group) => [
    group.title,
    ...(group.body || []),
    ...(group.buttons || []).map(([label, desc]) => `${label} ${desc}`),
  ].flat().join(" ")).join(" ").toLowerCase();
  const all = [title, tags, body, buttons, split].join(" ");
  let score = 0;
  let matches = 0;
  if (parts.raw && all.includes(parts.raw)) score += 12;
  parts.terms.forEach((term) => {
    if (!all.includes(term)) return;
    matches += 1;
    if (title.includes(term)) score += 12;
    if (tags.includes(term)) score += 8;
    if (buttons.includes(term)) score += 5;
    if (split.includes(term)) score += 4;
    if (body.includes(term)) score += 3;
  });
  if (matches === parts.terms.length) score += 10;
  return { score, matches };
}

function manualButtonHtml(item, parts = null) {
  const label = Array.isArray(item) ? item[0] : item?.label;
  const desc = Array.isArray(item) ? item[1] : item?.desc;
  return `<div class="manual-button-row">
    <span class="btn">${manualHighlight(label || "", parts)}</span>
    <span>${manualHighlight(desc || "", parts)}</span>
  </div>`;
}

function manualSplitHtml(groups, parts = null) {
  if (!groups?.length) return "";
  return `<div class="manual-split">${groups.map((group) => `
    <div class="manual-card">
      <div class="manual-card-title">${manualHighlight(group.title || "", parts)}</div>
      ${(group.body || []).map((line) => `<p>${manualHighlight(line, parts)}</p>`).join("")}
      ${(group.buttons || []).length ? `<div class="manual-buttons">${group.buttons.map((btn) => manualButtonHtml(btn, parts)).join("")}</div>` : ""}
    </div>`).join("")}</div>`;
}

function renderManual(query = "") {
  const box = el("manual-results");
  if (!box) return;
  const parts = manualSearchParts(query);
  const ranked = parts.terms.length
    ? MAP_APP_MANUAL_SECTIONS.map((section) => ({ section, ...manualScore(section, parts) }))
      .filter((r) => r.score > 0 && r.matches > 0)
      .sort((a, b) => b.score - a.score || a.section.title.localeCompare(b.section.title))
    : MAP_APP_MANUAL_SECTIONS.map((section) => ({ section, score: 1, matches: 0 }));
  const sections = ranked.map((r) => r.section);
  if (!sections.length) {
    box.innerHTML = '<div class="manual-empty">No manual sections match that search.</div>';
    return;
  }
  const summary = parts.terms.length
    ? `<div class="manual-summary">Showing ${sections.length} section${sections.length === 1 ? "" : "s"} ranked by relevance.</div>`
    : "";
  box.innerHTML = summary + sections.map((section) => `
    <div class="manual-section">
      <div class="manual-title">${manualHighlight(section.title, parts)}</div>
      ${(section.body || []).map((line) => `<p>${manualHighlight(line, parts)}</p>`).join("")}
      ${manualSplitHtml(section.split, parts)}
      ${(section.buttons || []).length ? `<div class="manual-buttons">${section.buttons.map((btn) => manualButtonHtml(btn, parts)).join("")}</div>` : ""}
    </div>`).join("");
}

function openManual() {
  setHamburgerOpen(false);
  const dialog = el("manual-dialog");
  const search = el("manual-search");
  if (search) search.value = "";
  renderManual("");
  dialog?.showModal();
  setTimeout(() => search?.focus(), 50);
}

function iconHtml(text) {
  const label = (text || "pin").slice(0, 3);
  return `<div class="marker-chip">${esc(label)}</div>`;
}

function markerIcon(marker) {
  return L.divIcon({
    html: iconHtml(marker.emoji),
    className: "",
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function popupForMarker(marker) {
  return `
    <div style="min-width:180px;max-width:260px">
      <div style="color:var(--accent);font-weight:700;margin-bottom:4px">${esc(marker.name)}</div>
      ${marker.description ? `<div style="margin-bottom:7px">${esc(marker.description)}</div>` : ""}
      <div style="color:var(--muted);font-size:11px;margin-bottom:8px">
        ${marker.lat.toFixed(5)}, ${marker.lon.toFixed(5)}
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn small" onclick="editMarker(${marker.id})">Edit</button>
        <button class="btn small" onclick="shareMarkerLater(${marker.id})">Share via OM</button>
        <button class="btn small danger" onclick="deleteMarker(${marker.id})">Delete</button>
      </div>
    </div>`;
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.message || `HTTP ${res.status}`);
    err.data = data;
    throw err;
  }
  return data;
}

function setBanner(text) {
  const b = el("banner");
  if (!text) {
    b.classList.remove("show");
    b.textContent = "";
    return;
  }
  b.textContent = text;
  b.classList.add("show");
}

function setToolButtons(active) {
  for (const id of ["add-marker-btn", "measure-btn", "draw-line-btn", "draw-poly-btn"]) {
    el(id)?.classList.toggle("active", active === id);
  }
  el("undo-point-btn").hidden = !state.tool || !state.toolPoints.length;
  el("finish-tool-btn").hidden = !state.tool || state.toolPoints.length < 2;
  el("cancel-tool-btn").hidden = !state.tool;
  el("measure-card").classList.toggle("show", state.tool === "measure");
}

function placementToolActive() {
  return ["marker", "measure", "line", "polygon"].includes(state.tool);
}

function invalidateMapSoon() {
  for (const delay of [0, 80, 220]) {
    setTimeout(() => {
      state.map?.invalidateSize({ animate: false });
      state.magnifierMap?.invalidateSize({ animate: false });
    }, delay);
  }
}

function setSidePanelClosed(closed) {
  el("side-panel").classList.toggle("closed", closed);
  el("tab-map").classList.toggle("panel-closed", closed);
  invalidateMapSoon();
}

function enableMagnifier() {
  if (!placementToolActive()) return;
  el("magnifier").classList.add("show");
  if (!state.magnifierMap) {
    state.magnifierMap = L.map("magnifier-map", {
      attributionControl: false,
      zoomControl: false,
      dragging: false,
      touchZoom: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tap: false,
      preferCanvas: true,
    }).setView(state.map.getCenter(), state.map.getZoom());
  }
  if (!state.magnifierLayer) syncMagnifierLayer();
  setTimeout(() => state.magnifierMap.invalidateSize(), 20);
}

function disableMagnifier() {
  el("magnifier").classList.remove("show");
  state.magnifierLatLng = null;
  if (state.magnifierRaf) {
    cancelAnimationFrame(state.magnifierRaf);
    state.magnifierRaf = 0;
  }
  state.map?.dragging.enable();
}

function positionMagnifier(originalEvent) {
  if (!placementToolActive() || !state.magnifierMap) return;
  const wrap = el("map-wrap").getBoundingClientRect();
  const mag = el("magnifier");
  const size = mag.offsetWidth || 172;
  const offset = 28;
  const clientX = originalEvent.clientX ?? originalEvent.touches?.[0]?.clientX;
  const clientY = originalEvent.clientY ?? originalEvent.touches?.[0]?.clientY;
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
  let left = clientX - wrap.left + offset;
  let top = clientY - wrap.top - size - offset;
  if (left + size > wrap.width - 8) left = clientX - wrap.left - size - offset;
  if (top < 8) top = clientY - wrap.top + offset;
  left = Math.max(8, Math.min(left, wrap.width - size - 8));
  top = Math.max(8, Math.min(top, wrap.height - size - 8));
  mag.style.left = `${left}px`;
  mag.style.top = `${top}px`;
}

function updateMagnifier(event) {
  if (!placementToolActive()) return;
  enableMagnifier();
  positionMagnifier(event.originalEvent || event);
  state.magnifierLatLng = event.latlng || state.map.mouseEventToLatLng(event.originalEvent || event);
  const now = performance.now();
  if (now - state.magnifierLastUpdate < 90) return;
  state.magnifierLastUpdate = now;
  if (state.magnifierRaf) cancelAnimationFrame(state.magnifierRaf);
  state.magnifierRaf = requestAnimationFrame(() => {
    state.magnifierRaf = 0;
    if (!state.magnifierMap || !state.magnifierLatLng || !placementToolActive()) return;
    state.magnifierMap.setView(state.magnifierLatLng, state.map.getZoom(), { animate: false });
  });
}

function clearTool() {
  state.toolMarkers.forEach((m) => state.map.removeLayer(m));
  state.toolMarkers = [];
  if (state.toolLine) state.map.removeLayer(state.toolLine);
  state.toolLine = null;
  state.toolPoints = [];
  state.tool = null;
  setBanner("");
  el("map").classList.remove("tool-crosshair");
  disableMagnifier();
  setToolButtons(null);
}

function startTool(tool) {
  clearTool();
  state.tool = tool;
  if (tool === "marker") setBanner("Tap map to place a marker");
  if (tool === "measure") setBanner("Tap points for the ruler. Drag points to adjust.");
  if (tool === "line") setBanner("Tap points for a line, then Finish.");
  if (tool === "polygon") setBanner("Tap area corners, then Finish.");
  el("map").classList.toggle("tool-crosshair", placementToolActive());
  enableMagnifier();
  const activeId = { marker: "add-marker-btn", measure: "measure-btn", line: "draw-line-btn", polygon: "draw-poly-btn" }[tool];
  setToolButtons(activeId);
}

function updateToolLine() {
  if (state.toolLine) state.map.removeLayer(state.toolLine);
  if (state.toolPoints.length < 2) {
    el("measure-total").textContent = "0 m";
    setToolButtons({ marker: "add-marker-btn", measure: "measure-btn", line: "draw-line-btn", polygon: "draw-poly-btn" }[state.tool]);
    return;
  }
  const latlngs = state.toolPoints.map((p) => [p.lat, p.lon]);
  if (state.tool === "polygon") {
    state.toolLine = L.polygon(latlngs, { color: "#f59e0b", weight: 2, fillOpacity: 0.16 }).addTo(state.map);
  } else {
    state.toolLine = L.polyline(latlngs, { color: state.tool === "measure" ? currentAccentColor() : "#f59e0b", weight: 3 }).addTo(state.map);
  }
  updateMeasureTotal();
  setToolButtons({ marker: "add-marker-btn", measure: "measure-btn", line: "draw-line-btn", polygon: "draw-poly-btn" }[state.tool]);
}

async function updateMeasureTotal() {
  if (state.toolPoints.length < 2) return;
  try {
    const data = await api("/api/measure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ points: state.toolPoints }),
    });
    el("measure-total").textContent = fmtDistance(data.distance_m);
  } catch {
    el("measure-total").textContent = "";
  }
}

function addToolPoint(latlng) {
  const idx = state.toolPoints.length;
  const point = { lat: latlng.lat, lon: latlng.lng };
  state.toolPoints.push(point);
  const color = state.tool === "measure" ? currentAccentColor() : "#f59e0b";
  const marker = L.marker(latlng, {
    draggable: true,
    icon: L.divIcon({
      html: `<div class="marker-chip" style="background:${color};border-color:#fff;color:#111">${idx + 1}</div>`,
      className: "",
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    }),
  }).addTo(state.map);
  marker.bindTooltip(String(idx + 1), { permanent: true, direction: "top", offset: [0, -8] });
  marker.on("drag", () => {
    const ll = marker.getLatLng();
    state.toolPoints[idx] = { lat: ll.lat, lon: ll.lng };
    updateToolLine();
  });
  state.toolMarkers.push(marker);
  updateToolLine();
}

function undoToolPoint() {
  if (!state.toolPoints.length) return;
  state.toolPoints.pop();
  const marker = state.toolMarkers.pop();
  if (marker) state.map.removeLayer(marker);
  updateToolLine();
}

async function finishTool() {
  if (!state.tool || state.toolPoints.length < 2) return;
  if (state.tool === "measure" || state.tool === "line" || state.tool === "polygon") {
    const kind = state.tool === "measure" ? "measure" : state.tool;
    const name = await appPrompt(
      "Name this drawing:",
      kind === "measure" ? "Ruler path" : kind === "polygon" ? "Area" : "Line",
      "Save Drawing",
    );
    if (name === null) return;
    try {
      await api("/api/drawings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim() || kind,
          kind,
          color: kind === "measure" ? currentAccentColor() : "#f59e0b",
          data: { points: state.toolPoints },
        }),
      });
      clearTool();
      await loadDrawings();
    } catch (err) {
      await appAlert(err.message, "Save Failed");
    }
  }
}

function openMarkerDialog(marker = null, latlng = null) {
  el("marker-title").textContent = marker ? "Edit Marker" : "Add Marker";
  el("marker-id").value = marker?.id || "";
  el("marker-lat").value = marker?.lat ?? latlng?.lat ?? "";
  el("marker-lon").value = marker?.lon ?? latlng?.lng ?? "";
  el("marker-name").value = marker?.name || "";
  el("marker-desc").value = marker?.description || "";
  el("marker-emoji").value = marker?.emoji || "pin";
  el("marker-category").value = marker?.category || "note";
  el("marker-status").textContent = "";
  el("marker-dialog").showModal();
  setTimeout(() => el("marker-name").focus(), 80);
}

async function saveMarker(event) {
  event.preventDefault();
  const id = el("marker-id").value;
  const payload = {
    lat: parseFloat(el("marker-lat").value),
    lon: parseFloat(el("marker-lon").value),
    name: el("marker-name").value.trim(),
    description: el("marker-desc").value.trim(),
    emoji: el("marker-emoji").value.trim() || "pin",
    category: el("marker-category").value.trim() || "note",
  };
  try {
    if (id) {
      await api(`/api/markers/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/markers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    el("marker-dialog").close();
    await loadMarkers();
  } catch (err) {
    el("marker-status").textContent = err.message;
  }
}

function renderMarker(marker) {
  const existing = state.markerLayers.get(marker.id);
  if (existing) state.map.removeLayer(existing);
  const layer = L.marker([marker.lat, marker.lon], { icon: markerIcon(marker) })
    .addTo(state.map)
    .bindPopup(popupForMarker(marker));
  state.markerLayers.set(marker.id, layer);
}

async function loadMarkers() {
  const markers = await api("/api/markers");
  const active = new Set(markers.map((m) => m.id));
  for (const [id, layer] of state.markerLayers.entries()) {
    if (!active.has(id)) {
      state.map.removeLayer(layer);
      state.markerLayers.delete(id);
      state.markers.delete(id);
    }
  }
  markers.forEach((m) => {
    state.markers.set(m.id, m);
    renderMarker(m);
  });
  renderMarkerList();
}

function renderMarkerList() {
  const list = el("marker-list");
  const markers = [...state.markers.values()].sort((a, b) => b.updated_at - a.updated_at);
  if (!markers.length) {
    list.innerHTML = '<div class="empty">No markers yet. Use Add Marker, then tap the map.</div>';
    return;
  }
  list.innerHTML = markers.map((m) => `
    <div class="list-row" onclick="flyToMarker(${m.id})">
      <div class="row-icon">${esc((m.emoji || "pin").slice(0, 3))}</div>
      <div class="row-main">
        <div class="row-title">${esc(m.name)}</div>
        <div class="row-sub">${esc(m.category || "note")} - ${m.lat.toFixed(4)}, ${m.lon.toFixed(4)}</div>
      </div>
      <div class="row-actions">
        <button class="btn small" onclick="event.stopPropagation();editMarker(${m.id})">Edit</button>
      </div>
    </div>`).join("");
}

function flyToMarker(id) {
  const m = state.markers.get(id);
  if (!m) return;
  state.map.setView([m.lat, m.lon], Math.max(state.map.getZoom(), 14));
  setTimeout(() => state.markerLayers.get(id)?.openPopup(), 180);
}

function editMarker(id) {
  const marker = state.markers.get(id);
  if (marker) openMarkerDialog(marker);
}

async function deleteMarker(id) {
  const marker = state.markers.get(id);
  if (!marker || !(await appConfirm(`Delete marker "${marker.name}"?`, "Delete Marker"))) return;
  await api(`/api/markers/${id}`, { method: "DELETE" });
  await loadMarkers();
}

async function shareMarkerLater(id) {
  try {
    await api(`/api/om/share-marker/${id}`, { method: "POST" });
  } catch (err) {
    await appAlert(`${err.message}\n\nThis is intentional for v0.1: Map owns markers, OM integration comes next.`, "OM Sharing");
  }
}

function renderDrawing(drawing) {
  const old = state.drawingLayers.get(drawing.id);
  if (old) state.map.removeLayer(old);
  const points = drawing.data?.points || [];
  if (points.length < 2) return;
  const latlngs = points.map((p) => [p.lat, p.lon]);
  const opts = { color: drawing.color || "#f59e0b", weight: 3, fillOpacity: 0.14 };
  const layer = drawing.kind === "polygon" ? L.polygon(latlngs, opts) : L.polyline(latlngs, opts);
  layer.addTo(state.map).bindPopup(`
    <div>
      <div style="color:var(--accent);font-weight:700">${esc(drawing.name)}</div>
      <div style="color:var(--muted);font-size:11px">${esc(drawing.kind)} - ${fmtDistance(drawing.data?.distance_m || 0)}</div>
      <button class="btn small danger" onclick="deleteDrawing(${drawing.id})">Delete</button>
    </div>`);
  state.drawingLayers.set(drawing.id, layer);
}

async function loadDrawings() {
  const drawings = await api("/api/drawings");
  const active = new Set(drawings.map((d) => d.id));
  for (const [id, layer] of state.drawingLayers.entries()) {
    if (!active.has(id)) {
      state.map.removeLayer(layer);
      state.drawingLayers.delete(id);
      state.drawings.delete(id);
    }
  }
  drawings.forEach((d) => {
    state.drawings.set(d.id, d);
    renderDrawing(d);
  });
  renderDrawingList();
}

function renderDrawingList() {
  const list = el("drawing-list");
  const drawings = [...state.drawings.values()].sort((a, b) => b.updated_at - a.updated_at);
  if (!drawings.length) {
    list.innerHTML = '<div class="empty">No drawings yet. Use Ruler, Draw Line, or Draw Area.</div>';
    return;
  }
  list.innerHTML = drawings.map((d) => `
    <div class="list-row" onclick="flyToDrawing(${d.id})">
      <div class="row-icon">${d.kind === "polygon" ? "area" : d.kind === "measure" ? "m" : "line"}</div>
      <div class="row-main">
        <div class="row-title">${esc(d.name)}</div>
        <div class="row-sub">${esc(d.kind)} - ${fmtDistance(d.data?.distance_m || 0)}</div>
      </div>
      <button class="btn small danger" onclick="event.stopPropagation();deleteDrawing(${d.id})">Del</button>
    </div>`).join("");
}

function flyToDrawing(id) {
  const layer = state.drawingLayers.get(id);
  if (!layer) return;
  state.map.fitBounds(layer.getBounds().pad(0.2), { maxZoom: 15 });
  setTimeout(() => layer.openPopup?.(), 160);
}

async function deleteDrawing(id) {
  const drawing = state.drawings.get(id);
  if (!drawing || !(await appConfirm(`Delete drawing "${drawing.name}"?`, "Delete Drawing"))) return;
  await api(`/api/drawings/${id}`, { method: "DELETE" });
  await loadDrawings();
}

function distanceBetween(a, b) {
  const radius = 6371008.8;
  const lat1 = a.lat * Math.PI / 180;
  const lat2 = b.lat * Math.PI / 180;
  const dlat = lat2 - lat1;
  const dlon = (b.lon - a.lon) * Math.PI / 180;
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(h));
}

const _trackCache = {};

function fmtDuration(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

function speedPercentile(arr, p) {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(Math.floor(s.length * p), s.length - 1)];
}

function trackStats(track) {
  const pts = track.points;
  if (!pts || pts.length < 2) return null;
  const duration = (pts.at(-1).ts || 0) - (pts[0].ts || 0);
  const dist = track.distance_m || trackDistance(pts);
  const avgKmh = duration > 0 ? dist / duration * 3.6 : 0;
  const rawSpeeds = [];
  for (let i = 1; i < pts.length; i++) {
    const d = distanceBetween(pts[i - 1], pts[i]);
    const dt = Math.max((pts[i].ts || 0) - (pts[i - 1].ts || 0), 1);
    rawSpeeds.push(d / dt * 3.6);
  }
  const maxKmh = speedPercentile(rawSpeeds, 0.95);
  const alts = pts.map(p => p.alt != null ? Number(p.alt) : null).filter(a => a !== null);
  let elevGain = 0, elevLoss = 0;
  for (let i = 1; i < alts.length; i++) {
    const diff = alts[i] - alts[i - 1];
    if (diff > 2) elevGain += diff;
    else if (diff < -2) elevLoss += Math.abs(diff);
  }
  const minAlt = alts.length ? Math.min(...alts) : null;
  const maxAlt = alts.length ? Math.max(...alts) : null;
  return { dist, duration, avgKmh, maxKmh, elevGain, elevLoss, hasAlt: alts.length > 0, minAlt, maxAlt, startTs: pts[0].ts || null, endTs: pts.at(-1).ts || null };
}

function trackSegmentColor(ratio) {
  const r = ratio < 0.5 ? Math.round(510 * ratio) : 255;
  const g = ratio < 0.5 ? 210 : Math.round(210 * (1 - (ratio - 0.5) * 2));
  return `rgb(${r},${g},0)`;
}

function showTrackColorLegend(mode, stats) {
  let legend = el("track-color-legend");
  if (!legend) {
    legend = document.createElement("div");
    legend.id = "track-color-legend";
    legend.style.cssText = "position:fixed;bottom:72px;right:16px;z-index:1500;pointer-events:none";
    document.body.appendChild(legend);
  }
  const label = mode === "speed" ? "Speed" : "Altitude";
  const lo = mode === "speed" ? "slow" : "low";
  const hi = mode === "speed" ? "fast" : "high";
  let extraHtml = "";
  if (stats) {
    if (mode === "speed") {
      extraHtml = `<div style="color:var(--text);margin-top:5px;font-size:11px;line-height:1.6">top: <b>${stats.maxKmh.toFixed(0)} km/h</b><br>avg: ${stats.avgKmh.toFixed(0)} km/h</div>`;
    } else if (stats.minAlt !== null && stats.maxAlt !== null) {
      extraHtml = `<div style="color:var(--text);margin-top:5px;font-size:11px;line-height:1.6">${Math.round(stats.minAlt)} m → <b>${Math.round(stats.maxAlt)} m</b></div>`;
    }
  }
  legend.innerHTML = `<div style="background:var(--surface1);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:11px">
    <div style="font-weight:600;margin-bottom:4px;color:var(--text)">${label}</div>
    <div style="width:90px;height:8px;background:linear-gradient(to right,rgb(0,210,0),rgb(255,210,0),rgb(255,0,0));border-radius:2px"></div>
    <div style="display:flex;justify-content:space-between;color:var(--muted);margin-top:2px"><span>${lo}</span><span>${hi}</span></div>
    ${extraHtml}
  </div>`;
  legend.hidden = false;
}

function hideTrackColorLegend() {
  const l = el("track-color-legend");
  if (l) l.hidden = true;
}

function renderTrackColored(trackId, mode) {
  const track = _trackCache[trackId];
  if (!track || !state.map) return;
  const pts = track.points;
  if (!pts || pts.length < 2) return;
  const old = state.trackLayers.get(track.id);
  if (old) state.map.removeLayer(old);

  let values = [];
  if (mode === "speed") {
    for (let i = 1; i < pts.length; i++) {
      const d = distanceBetween(pts[i - 1], pts[i]);
      const dt = Math.max((pts[i].ts || 0) - (pts[i - 1].ts || 0), 1);
      values.push(d / dt * 3.6);
    }
    const maxV = speedPercentile(values, 0.95) || 1;
    values = values.map(v => Math.min(v, maxV) / maxV);
  } else {
    const alts = pts.map(p => p.alt != null ? Number(p.alt) : null);
    const valid = alts.filter(a => a !== null);
    if (!valid.length) { renderTrack(track); return; }
    const minA = Math.min(...valid), maxA = Math.max(...valid);
    const range = maxA - minA || 1;
    for (let i = 1; i < pts.length; i++) {
      const a = ((alts[i - 1] ?? minA) + (alts[i] ?? minA)) / 2;
      values.push((a - minA) / range);
    }
  }

  const group = L.featureGroup();
  for (let i = 1; i < pts.length; i++) {
    L.polyline([[pts[i - 1].lat, pts[i - 1].lon], [pts[i].lat, pts[i].lon]], {
      color: trackSegmentColor(values[i - 1] || 0), weight: 5, opacity: 0.95,
    }).addTo(group);
  }
  L.marker([pts[0].lat, pts[0].lon], { icon: makeTrackEndIcon('S', '#27ae60'), zIndexOffset: 10 }).addTo(group);
  L.marker([pts.at(-1).lat, pts.at(-1).lon], { icon: makeTrackEndIcon('E', '#e74c3c'), zIndexOffset: 10 }).addTo(group);
  group.bindPopup(trackPopup(track));
  group.on('popupopen', () => showTrackChart(track));
  group.on('popupclose', hideTrackChart);
  group.addTo(state.map);
  state.trackLayers.set(track.id, group);
  state.trackVisible.set(track.id, true);
  renderTrackList();
  showTrackColorLegend(mode, trackStats(track));
}

function trackDistance(points) {
  return points.reduce((sum, point, idx) => idx ? sum + distanceBetween(points[idx - 1], point) : 0, 0);
}

function makeTrackEndIcon(label, bg) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="34" viewBox="0 0 24 34">
    <path d="M12 0C5.4 0 0 5.4 0 12c0 8.4 12 22 12 22s12-13.6 12-22C24 5.4 18.6 0 12 0z" fill="${bg}" stroke="rgba(0,0,0,0.28)" stroke-width="1"/>
    <circle cx="12" cy="12" r="6" fill="white" opacity="0.88"/>
    <text x="12" y="16" font-size="8" font-family="sans-serif" font-weight="bold" fill="${bg}" text-anchor="middle">${label}</text>
  </svg>`;
  return L.divIcon({
    className: '',
    html: svg,
    iconSize: [24, 34],
    iconAnchor: [12, 34],
  });
}

// Chart layout constants (viewBox space)
const _CCW = 316, _CCH = 95; // viewBox width/height
const _CPL = 34, _CPR = 4, _CPT = 5, _CPB = 8; // padding: left (y-axis labels), right, top, bottom

let _chartInteractInit = false;
function _initTrackChartInteractions() {
  if (_chartInteractInit) return;
  _chartInteractInit = true;
  const panel = el('track-chart-panel');
  const head  = panel && panel.querySelector('.chart-panel-head');
  const grip  = panel && panel.querySelector('.chart-resize-grip');
  if (!panel || !head) return;

  // Drag to move via header
  head.addEventListener('pointerdown', e => {
    if (e.target.closest('button')) return;
    e.preventDefault();
    head.setPointerCapture(e.pointerId);
    const wrap  = el('map-wrap');
    const wRect = wrap.getBoundingClientRect();
    const pRect = panel.getBoundingClientRect();
    panel.style.bottom = 'auto';
    panel.style.top    = (pRect.top  - wRect.top)  + 'px';
    panel.style.left   = (pRect.left - wRect.left) + 'px';
    const startX = e.clientX, startY = e.clientY;
    const startL = pRect.left - wRect.left;
    const startT = pRect.top  - wRect.top;
    head.onpointermove = e => {
      const maxL = wRect.width  - panel.offsetWidth;
      const maxT = wRect.height - panel.offsetHeight;
      panel.style.left = Math.max(0, Math.min(maxL, startL + e.clientX - startX)) + 'px';
      panel.style.top  = Math.max(0, Math.min(maxT, startT + e.clientY - startY)) + 'px';
    };
    head.onpointerup = head.onpointercancel = () => {
      head.onpointermove = head.onpointerup = head.onpointercancel = null;
    };
  });

  // Drag to resize via grip
  if (grip) {
    grip.addEventListener('pointerdown', e => {
      e.preventDefault();
      e.stopPropagation();
      grip.setPointerCapture(e.pointerId);
      const startX = e.clientX, startY = e.clientY;
      const startW = panel.offsetWidth, startH = panel.offsetHeight;
      grip.onpointermove = e => {
        panel.style.width  = Math.max(220, startW + e.clientX - startX) + 'px';
        panel.style.height = Math.max(200, startH + e.clientY - startY) + 'px';
      };
      grip.onpointerup = grip.onpointercancel = () => {
        grip.onpointermove = grip.onpointerup = grip.onpointercancel = null;
      };
    });
  }
}

function makeChartSvg(values, color) {
  const cw = _CCW, ch = _CCH, pl = _CPL, pr = _CPR, pt = _CPT, pb = _CPB;
  if (!values || values.length < 2) return '';
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;
  const n = values.length;

  const toX = (i) => pl + (i / (n - 1)) * (cw - pl - pr);
  const toY = (v) => ch - pb - ((v - minV) / range) * (ch - pt - pb);

  // Grid lines + Y-axis labels (4 levels: 0%, 33%, 67%, 100% of range)
  let grid = '';
  for (let g = 0; g <= 3; g++) {
    const frac = g / 3;
    const v = minV + frac * range;
    const y = toY(v).toFixed(1);
    const label = Math.round(v);
    grid += `<line x1="${pl}" y1="${y}" x2="${cw - pr}" y2="${y}" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>`;
    grid += `<text x="${(pl - 4).toFixed(1)}" y="${y}" fill="rgba(122,136,154,0.78)" font-size="8.5" font-family="monospace" text-anchor="end" dominant-baseline="middle">${label}</text>`;
  }

  const xs = values.map((_, i) => toX(i));
  const ys = values.map(v => toY(v));
  const linePts = xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const fillPts = `${xs[0].toFixed(1)},${toY(minV).toFixed(1)} ` + linePts + ` ${xs.at(-1).toFixed(1)},${toY(minV).toFixed(1)}`;

  return `<svg viewBox="0 0 ${cw} ${ch}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">` +
    grid +
    `<polygon points="${fillPts}" fill="${color}" fill-opacity="0.18"/>` +
    `<polyline points="${linePts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>` +
    `<circle class="chart-scrub-dot" cx="-99" cy="-99" r="4.5" fill="#ff4444" stroke="white" stroke-width="1.5" pointer-events="none" opacity="0"/>` +
    `<line class="chart-scrub-line" x1="-99" y1="${pt}" x2="-99" y2="${ch - pb}" stroke="rgba(255,68,68,0.38)" stroke-width="1" pointer-events="none" opacity="0"/>` +
    `<rect class="chart-event-area" x="${pl}" y="0" width="${cw - pl - pr}" height="${ch}" fill="transparent"/>` +
    `</svg>`;
}

function _bindChartScrub(container, data, chartType, cap) {
  if (!container || !data || data.length < 2) return;
  const svg = container.querySelector('.chart-svg-wrap svg');
  if (!svg) return;
  const dot = svg.querySelector('.chart-scrub-dot');
  const scrubLine = svg.querySelector('.chart-scrub-line');
  const area = svg.querySelector('.chart-event-area');
  const statEl = container.querySelector('.chart-stat');
  if (!dot || !area) return;

  const cw = _CCW, ch = _CCH, pl = _CPL, pr = _CPR, pt = _CPT, pb = _CPB;
  const n = data.length;
  const vals = data.map(d => d.v);
  const minV = Math.min(...vals);
  const maxV = Math.max(...vals);
  const range = maxV - minV || 1;

  function scrub(clientX) {
    const rect = svg.getBoundingClientRect();
    // Convert screen X → viewBox X (works regardless of rendered size due to viewBox)
    const vbX = (clientX - rect.left) / rect.width * cw;
    const frac = Math.max(0, Math.min(1, (vbX - pl) / (cw - pl - pr)));
    const idx = Math.min(Math.round(frac * (n - 1)), n - 1);
    const item = data[idx];
    if (!item) return;

    const svgX = (pl + (idx / (n - 1)) * (cw - pl - pr)).toFixed(1);
    const svgY = (ch - pb - ((item.v - minV) / range) * (ch - pt - pb)).toFixed(1);
    dot.setAttribute('cx', svgX);
    dot.setAttribute('cy', svgY);
    dot.setAttribute('opacity', '1');
    if (scrubLine) {
      scrubLine.setAttribute('x1', svgX);
      scrubLine.setAttribute('x2', svgX);
      scrubLine.setAttribute('opacity', '1');
    }
    if (statEl) {
      statEl.textContent = chartType === 'speed'
        ? `${item.v.toFixed(1)} km/h`
        : `${Math.round(item.v)} m`;
    }

    if (state.map && item.lat != null && item.lon != null) {
      if (!_chartScrubMarker) {
        _chartScrubMarker = L.circleMarker([item.lat, item.lon], {
          radius: 8, color: '#ff4444', fillColor: '#ff4444', fillOpacity: 0.85, weight: 2.5,
        }).addTo(state.map);
      } else {
        _chartScrubMarker.setLatLng([item.lat, item.lon]);
      }
    }
  }

  function clearScrub() {
    dot.setAttribute('opacity', '0');
    if (scrubLine) scrubLine.setAttribute('opacity', '0');
    if (_chartScrubMarker && state.map) {
      state.map.removeLayer(_chartScrubMarker);
      _chartScrubMarker = null;
    }
    if (statEl && _activeChartData) {
      if (chartType === 'speed') {
        const s = _activeChartData.speedData;
        const maxS = (_activeChartData.speedCap || 0).toFixed(0);
        const avgS = s.length ? (s.reduce((a, b) => a + b.v, 0) / s.length).toFixed(0) : '0';
        statEl.innerHTML = `top <b>${maxS}</b> &nbsp; avg <b>${avgS}</b> km/h`;
      } else {
        const a = _activeChartData.altData;
        if (a.length > 1) {
          const minA = Math.round(Math.min(...a.map(d => d.v)));
          const maxA = Math.round(Math.max(...a.map(d => d.v)));
          statEl.innerHTML = `range <b>${minA}&ndash;${maxA} m</b>`;
        }
      }
    }
  }

  area.addEventListener('mousemove', e => { e.stopPropagation(); scrub(e.clientX); });
  area.addEventListener('mouseleave', clearScrub);
  area.addEventListener('touchmove', e => {
    e.preventDefault(); e.stopPropagation();
    if (e.touches.length) scrub(e.touches[0].clientX);
  }, { passive: false });
  area.addEventListener('touchend', clearScrub);
}

function showTrackChart(track) {
  const pts = (track.points || []).filter(p => p.lat != null);
  if (pts.length < 2) return;
  const panel = el('track-chart-panel');
  if (!panel) return;
  const titleEl = el('track-chart-title');
  if (titleEl) titleEl.textContent = track.name;

  // Build speed data array with midpoint lat/lon per segment
  const rawSpeeds = [];
  for (let i = 1; i < pts.length; i++) {
    const d = distanceBetween(pts[i - 1], pts[i]);
    const dt = Math.max((pts[i].ts || 0) - (pts[i - 1].ts || 0), 1);
    rawSpeeds.push(d / dt * 3.6);
  }
  const speedCap = speedPercentile(rawSpeeds, 0.95) || 1;
  const speedData = rawSpeeds.map((raw, i) => ({
    v: Math.min(raw, speedCap),
    lat: (pts[i].lat + pts[i + 1].lat) / 2,
    lon: (pts[i].lon + pts[i + 1].lon) / 2,
  }));

  // Build altitude data with per-point lat/lon
  const altData = [];
  for (const p of pts) {
    if (p.alt != null) altData.push({ v: Number(p.alt), lat: p.lat, lon: p.lon });
  }

  _activeChartData = { speedData, altData, speedCap };

  const hasSpeed = speedData.some(d => d.v > 0.5);
  const hasAlt = altData.length > 1;

  let html = '';

  // Speed chart
  html += '<div class="chart-block" data-chart="speed">';
  html += '<div class="chart-label">Speed &nbsp; km/h</div>';
  if (hasSpeed) {
    html += '<div class="chart-svg-wrap">' + makeChartSvg(speedData.map(d => d.v), '#e8b04f') + '</div>';
    const maxS = speedCap.toFixed(0);
    const avgS = (speedData.reduce((a, b) => a + b.v, 0) / speedData.length).toFixed(0);
    html += `<div class="chart-stat">top <b>${maxS}</b> &nbsp; avg <b>${avgS}</b> km/h</div>`;
  } else {
    html += '<div class="chart-nodata">no data</div>';
  }
  html += '</div>';

  // Altitude chart
  html += '<div class="chart-block" data-chart="alt">';
  html += '<div class="chart-label">Altitude &nbsp; m</div>';
  if (hasAlt) {
    html += '<div class="chart-svg-wrap">' + makeChartSvg(altData.map(d => d.v), '#4fc3f7') + '</div>';
    const minA = Math.round(Math.min(...altData.map(d => d.v)));
    const maxA = Math.round(Math.max(...altData.map(d => d.v)));
    html += `<div class="chart-stat">range <b>${minA}&ndash;${maxA} m</b></div>`;
  } else {
    html += '<div class="chart-nodata">no data</div>';
  }
  html += '</div>';

  const body = el('track-chart-body');
  if (body) {
    body.innerHTML = html;
    if (hasSpeed) _bindChartScrub(body.querySelector('[data-chart="speed"]'), speedData, 'speed', speedCap);
    if (hasAlt)   _bindChartScrub(body.querySelector('[data-chart="alt"]'),   altData,   'alt',   null);
  }
  panel.hidden = false;
  _initTrackChartInteractions();
}

function hideTrackChart() {
  const panel = el('track-chart-panel');
  if (panel) {
    panel.hidden = true;
    panel.style.width  = '';
    panel.style.height = '';
    panel.style.top    = '';
    panel.style.left   = '';
    panel.style.bottom = '';
  }
  const titleEl = el('track-chart-title');
  if (titleEl) titleEl.textContent = '';
  const body = el('track-chart-body');
  if (body) body.innerHTML = '';
  if (_chartScrubMarker && state.map) {
    state.map.removeLayer(_chartScrubMarker);
    _chartScrubMarker = null;
  }
  _activeChartData = null;
}

function trackPopup(track) {
  _trackCache[track.id] = track;
  const stats = trackStats(track);
  const pts = track.points || [];
  const startTime = stats?.startTs ? fmtDateTime(stats.startTs) : null;
  const endTime   = stats?.endTs   ? (fmtDate(stats.endTs) === fmtDate(stats.startTs) ? fmtTime(stats.endTs) : fmtDateTime(stats.endTs)) : null;
  const statsHtml = stats ? `
    <table style="width:100%;font-size:11px;margin:6px 0 4px;border-collapse:collapse">
      <tr><td style="color:var(--muted);padding:1px 6px 1px 0">Distance</td><td>${fmtDistance(stats.dist)}</td></tr>
      ${stats.duration > 0 ? `<tr><td style="color:var(--muted);padding:1px 6px 1px 0">Duration</td><td>${fmtDuration(stats.duration)}</td></tr>` : ""}
      ${stats.avgKmh > 0 ? `<tr><td style="color:var(--muted);padding:1px 6px 1px 0">Avg speed</td><td>${stats.avgKmh.toFixed(1)} km/h</td></tr>` : ""}
      ${stats.maxKmh > 0 ? `<tr><td style="color:var(--muted);padding:1px 6px 1px 0">Max speed</td><td>${stats.maxKmh.toFixed(1)} km/h</td></tr>` : ""}
      ${stats.hasAlt ? `<tr><td style="color:var(--muted);padding:1px 6px 1px 0">Alt range</td><td>${Math.round(stats.minAlt)}–${Math.round(stats.maxAlt)} m</td></tr>
      <tr><td style="color:var(--muted);padding:1px 6px 1px 0">Elev ↑↓</td><td>+${Math.round(stats.elevGain)} / −${Math.round(stats.elevLoss)} m</td></tr>` : ""}
      <tr><td style="color:var(--muted);padding:1px 6px 1px 0">Points</td><td>${pts.length}</td></tr>
      ${startTime ? `<tr><td style="color:var(--muted);padding:1px 6px 1px 0">Start</td><td>${startTime}</td></tr>` : ""}
      ${endTime   ? `<tr><td style="color:var(--muted);padding:1px 6px 1px 0">Stop</td><td>${endTime}</td></tr>`   : ""}
    </table>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px;align-items:center">
      <span style="font-size:10px;color:var(--muted)">Color:</span>
      <button class="btn small" onclick="renderTrackColored(${track.id},'speed')">Speed</button>
      <button class="btn small" onclick="renderTrackColored(${track.id},'alt')">Altitude</button>
      <button class="btn small" onclick="renderTrack(_trackCache[${track.id}]);hideTrackColorLegend()">Plain</button>
    </div>` : "";
  return `
    <div style="min-width:220px;max-width:290px">
      <div style="color:var(--accent);font-weight:700;margin-bottom:4px">${esc(track.name)}</div>
      ${track.description ? `<div style="margin-bottom:6px">${esc(track.description)}</div>` : ""}
      ${statsHtml}
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn small" onclick="editTrack(${track.id})">Rename</button>
        <button class="btn small" onclick="createLogFromTrack(${track.id})">Log</button>
        <button class="btn small" onclick="downloadTrack(${track.id}, 'gpx')">GPX</button>
        <button class="btn small" onclick="downloadTrack(${track.id}, 'geojson')">GeoJSON</button>
        <button class="btn small" onclick="trackToDrawing(${track.id})">Drawing</button>
        <button class="btn small danger" onclick="deleteTrack(${track.id})">Delete</button>
      </div>
    </div>`;
}

function renderTrack(track) {
  _trackCache[track.id] = track;
  if (state.map) {
    const old = state.trackLayers.get(track.id);
    if (old) state.map.removeLayer(old);
  }
  const points = track.points || [];
  if (points.length < 2) return;
  const group = L.featureGroup();
  L.polyline(points.map(p => [p.lat, p.lon]), {
    color: track.color || TRACK_COLOR, weight: 4, opacity: 0.9,
  }).addTo(group);
  L.marker([points[0].lat, points[0].lon], { icon: makeTrackEndIcon('S', '#27ae60'), zIndexOffset: 10 }).addTo(group);
  L.marker([points.at(-1).lat, points.at(-1).lon], { icon: makeTrackEndIcon('E', '#e74c3c'), zIndexOffset: 10 }).addTo(group);
  group.bindPopup(trackPopup(track));
  group.on('popupopen', () => showTrackChart(track));
  group.on('popupclose', hideTrackChart);
  state.trackLayers.set(track.id, group);
  if (state.map && state.trackVisible.get(track.id)) group.addTo(state.map);
}

async function loadTracks() {
  const tracks = await api("/api/tracks");
  const active = new Set(tracks.map((track) => track.id));
  for (const [id, layer] of state.trackLayers.entries()) {
    if (!active.has(id)) {
      state.map.removeLayer(layer);
      state.trackLayers.delete(id);
      state.tracks.delete(id);
    }
  }
  tracks.forEach((track) => {
    state.tracks.set(track.id, track);
    renderTrack(track);
  });
  if (typeof syncLogTracks === "function") syncLogTracks(tracks);
  renderTrackList();
}

function renderTrackList() {
  const list = el("track-list");
  if (!list) return;
  const tracks = [...state.tracks.values()].sort((a, b) => b.updated_at - a.updated_at);
  if (!tracks.length) {
    list.innerHTML = '<div class="empty">No GPS tracks yet. Press Track when GPS has a fix.</div>';
    return;
  }
  // Group by folder
  const folderMap = new Map();
  for (const track of tracks) {
    const f = track.folder || "";
    if (!folderMap.has(f)) folderMap.set(f, []);
    folderMap.get(f).push(track);
  }
  // Named folders alphabetically first, ungrouped at end
  const folders = [...folderMap.keys()].sort((a, b) => {
    if (a === "" && b !== "") return 1;
    if (b === "" && a !== "") return -1;
    return a.localeCompare(b);
  });
  let html = "";
  for (const folder of folders) {
    const folderTracks = folderMap.get(folder);
    const collapsed = state.collapsedFolders.has(folder);
    if (folder) {
      html += `<div class="track-folder-header" onclick="toggleTrackFolder('${esc(folder)}')" data-folder="${esc(folder)}">
        <span class="track-folder-icon">${collapsed ? "▶" : "▼"}</span>
        <span class="track-folder-name">${esc(folder)}</span>
        <span class="track-folder-count">${folderTracks.length}</span>
      </div>`;
      if (collapsed) continue;
    }
    for (const track of folderTracks) {
      const vis = !!state.trackVisible.get(track.id);
      const dateStr = track.updated_at ? fmtDate(track.updated_at) : "";
      const pts = track.points?.length || 0;
      const distStr = fmtDistance(track.distance_m || 0);
      const tColor = track.color || TRACK_COLOR;
      html += `
      <div class="list-row${folder ? " track-in-folder" : ""}" onclick="toggleTrackVisibility(${track.id})" title="${vis ? "Click to hide" : "Click to show on map"}">
        <div class="row-icon track-icon" style="background:${vis ? tColor : "var(--surface2)"};color:${vis ? "#111" : "var(--muted)"}">trk</div>
        <div class="row-main">
          <div class="row-title">${esc(track.name)}</div>
          <div class="row-sub">${distStr} · ${pts} pts${dateStr ? " · " + dateStr : ""}</div>
        </div>
        <div class="row-actions">
          <button class="btn small" onclick="event.stopPropagation();flyToTrack(${track.id})">View</button>
          <button class="btn small" onclick="event.stopPropagation();createLogFromTrack(${track.id})">Log</button>
          <button class="btn small" onclick="event.stopPropagation();editTrack(${track.id})">Edit</button>
          <button class="btn small" onclick="event.stopPropagation();downloadTrack(${track.id},'gpx')">GPX</button>
        </div>
      </div>`;
    }
  }
  list.innerHTML = html;
}

function toggleTrackFolder(folder) {
  if (state.collapsedFolders.has(folder)) state.collapsedFolders.delete(folder);
  else state.collapsedFolders.add(folder);
  renderTrackList();
}

function toggleTrackVisibility(id) {
  if (!state.map) return;
  const vis = !state.trackVisible.get(id);
  state.trackVisible.set(id, vis);
  const layer = state.trackLayers.get(id);
  if (layer) {
    if (vis) layer.addTo(state.map);
    else state.map.removeLayer(layer);
  }
  if (!vis) hideTrackColorLegend();
  renderTrackList();
}

function flyToTrack(id) {
  if (!state.map) return;
  if (!state.trackVisible.get(id)) {
    state.trackVisible.set(id, true);
    const l = state.trackLayers.get(id);
    if (l) l.addTo(state.map);
    renderTrackList();
  }
  const layer = state.trackLayers.get(id);
  if (!layer) return;
  state.map.fitBounds(layer.getBounds().pad(0.2), { maxZoom: 16 });
  setTimeout(() => layer.openPopup?.(), 160);
}

async function editTrack(id) {
  const track = state.tracks.get(id);
  if (!track) return;
  _trackSaveSelectedColor = track.color || TRACK_COLOR;
  const result = await showTrackSaveDialog({
    title: "Edit Track",
    name: track.name,
    folder: track.folder || "",
    color: track.color || TRACK_COLOR,
    showDiscard: false,
  });
  if (!result) return;
  try {
    await api(`/api/tracks/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: result.name, folder: result.folder, color: result.color, description: track.description }),
    });
    await loadTracks();
  } catch (err) {
    await appAlert(err.message, "Edit Track");
  }
}

function populateFolderDatalist() {
  const dl = el("track-folder-datalist");
  if (!dl) return;
  const folders = [...new Set([...state.tracks.values()].map((t) => t.folder).filter(Boolean))].sort();
  dl.innerHTML = folders.map((f) => `<option value="${esc(f)}">`).join("");
}

function trackDialogSelectColor(c) {
  _trackSaveSelectedColor = c;
  document.querySelectorAll("#track-save-colors .color-swatch").forEach((s) => {
    s.classList.toggle("selected", s.dataset.color === c);
  });
  const custom = el("track-save-custom-color");
  if (custom) custom.value = c;
}

function renderTrackSaveColors(current) {
  const wrap = el("track-save-colors");
  if (!wrap) return;
  wrap.innerHTML = TRACK_COLORS.map((c) =>
    `<button type="button" class="color-swatch${c === current ? " selected" : ""}" data-color="${c}" style="background:${c}" onclick="trackDialogSelectColor('${c}')"></button>`
  ).join("") +
    `<input type="color" id="track-save-custom-color" class="color-swatch-custom" value="${current}" oninput="trackDialogSelectColor(this.value)" title="Custom colour">`;
}

function showTrackSaveDialog(opts = {}) {
  const { title = "Save Track", info = "", name = "", folder = "", color = TRACK_COLOR, showDiscard = false } = opts;
  return new Promise((resolve) => {
    let settled = false;
    const finish = (val) => { if (!settled) { settled = true; resolve(val); } };

    _trackSaveSelectedColor = color;
    el("track-save-title").textContent = title;
    const infoEl = el("track-save-info");
    infoEl.textContent = info;
    infoEl.style.display = info ? "" : "none";
    el("track-save-name").value = name;
    el("track-save-folder").value = folder;
    populateFolderDatalist();
    renderTrackSaveColors(color);

    const discardBtn = el("track-save-discard");
    const cancelBtn = el("track-save-cancel");
    if (discardBtn) discardBtn.hidden = !showDiscard;

    const dialog = el("track-save-dialog");
    const form = el("track-save-form");

    const cleanup = () => {
      form.onsubmit = null;
      if (discardBtn) discardBtn.onclick = null;
      if (cancelBtn) cancelBtn.onclick = null;
      dialog.oncancel = null;
      dialog.onclose = null;
    };

    form.onsubmit = (e) => {
      e.preventDefault();
      cleanup();
      dialog.close();
      finish({
        name: el("track-save-name").value.trim() || name || "GPS track",
        folder: el("track-save-folder").value.trim(),
        color: _trackSaveSelectedColor,
      });
    };

    if (discardBtn) discardBtn.onclick = () => { cleanup(); dialog.close(); finish("discard"); };
    if (cancelBtn) cancelBtn.onclick = () => { cleanup(); dialog.close(); finish(null); };
    dialog.oncancel = (e) => { e.preventDefault(); cleanup(); dialog.close(); finish(null); };
    dialog.onclose = () => { cleanup(); finish(null); };

    dialog.showModal();
    setTimeout(() => { const ni = el("track-save-name"); if (ni) { ni.focus(); ni.select(); } }, 60);
  });
}

function downloadTrack(id, format) {
  const suffix = format === "geojson" ? "geojson" : "gpx";
  window.open(`/api/tracks/${id}/${suffix}`, "_blank", "noopener");
}

async function trackToDrawing(id) {
  try {
    await api(`/api/tracks/${id}/drawing`, { method: "POST" });
    await loadDrawings();
    await appAlert("Track copied to drawings.", "Track");
  } catch (err) {
    await appAlert(err.message, "Track");
  }
}

async function deleteTrack(id) {
  const track = state.tracks.get(id);
  if (!track || !(await appConfirm(`Delete track "${track.name}"?`, "Delete Track"))) return;
  await api(`/api/tracks/${id}`, { method: "DELETE" });
  await loadTracks();
}

function updateRecordingLayer() {
  if (!state.recording) return;
  const points = state.recording.points;
  if (state.recordingLayer) state.map.removeLayer(state.recordingLayer);
  if (points.length < 2) {
    state.recordingLayer = null;
    return;
  }
  state.recordingLayer = L.polyline(points.map((p) => [p.lat, p.lon]), {
    color: TRACK_COLOR,
    weight: 5,
    opacity: 0.95,
    dashArray: "8 8",
  }).addTo(state.map);
}

function setRecordingButton() {
  const btn = el("track-record-btn");
  const discardBtn = el("track-discard-btn");
  if (!btn) return;
  const active = Boolean(state.recording);
  btn.classList.toggle("active", active);
  btn.textContent = active ? `Stop (${state.recording.points.length})` : "Track";
  if (discardBtn) discardBtn.hidden = !active;
}

async function discardTrackRecording() {
  if (!state.recording) return;
  const pts = state.recording.points.length;
  const ok = await appConfirm(`Discard recording? ${pts} point${pts !== 1 ? "s" : ""} will be lost.`, "Discard Track");
  if (!ok) return;
  state.recording = null;
  if (state.recordingLayer) {
    state.map.removeLayer(state.recordingLayer);
    state.recordingLayer = null;
  }
  setRecordingButton();
  setBanner("");
}

const RECORD_INTERVALS = [5, 10, 30, 60, 120, 300];
let _recMinInterval = (() => {
  const saved = parseInt(localStorage.getItem("rec_interval") || "10", 10);
  return RECORD_INTERVALS.includes(saved) ? saved : 10;
})();

function setRecInterval(secs) {
  _recMinInterval = secs;
  localStorage.setItem("rec_interval", String(secs));
}

function _intervalLabel(idx) {
  const s = RECORD_INTERVALS[idx] ?? 10;
  return s < 60 ? `${s} s` : `${s / 60} min`;
}

function showTrackRecordDialog() {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (val) => { if (!settled) { settled = true; resolve(val); } };
    const dialog    = el("track-record-dialog");
    const form      = el("track-record-form");
    const slider    = el("rec-interval-slider");
    const labelEl   = el("rec-interval-label");
    const cancelBtn = el("track-record-cancel-btn");
    const curIdx = RECORD_INTERVALS.indexOf(_recMinInterval);
    slider.value = curIdx >= 0 ? curIdx : 1;
    labelEl.textContent = _intervalLabel(parseInt(slider.value));
    slider.oninput = () => { labelEl.textContent = _intervalLabel(parseInt(slider.value)); };
    const cleanup = () => {
      form.onsubmit = null;
      cancelBtn.onclick = null;
      dialog.oncancel = null;
      dialog.onclose = null;
      slider.oninput = null;
    };
    form.onsubmit = (e) => {
      e.preventDefault();
      setRecInterval(RECORD_INTERVALS[parseInt(slider.value)] ?? 10);
      cleanup();
      dialog.close();
      finish(true);
    };
    cancelBtn.onclick = () => { cleanup(); dialog.close(); finish(false); };
    dialog.oncancel = (e) => { e.preventDefault(); cleanup(); dialog.close(); finish(false); };
    dialog.onclose  = () => { cleanup(); finish(false); };
    dialog.showModal();
  });
}

function captureGpsPoint() {
  if (!state.recording || !_gpsEnabled || !_gpsState.fix || _gpsState.lat === null || _gpsState.lon === null) return;
  if ((_gpsState.sats || 0) < 4) return;
  const point = {
    lat: Number(_gpsState.lat),
    lon: Number(_gpsState.lon),
    alt: _gpsState.alt,
    sats: _gpsState.sats || 0,
    ts: Math.floor(Date.now() / 1000),
    time: new Date().toISOString(),
  };
  const last = state.recording.points.at(-1);
  if (last) {
    const dist = distanceBetween(last, point);
    const dt = point.ts - (last.ts || 0);
    if (dist < 3 && dt < _recMinInterval) return;
    if (dt > 0 && dist / dt > 100) return;
  }
  state.recording.points.push(point);
  state.recording.ended_at = point.ts;
  updateRecordingLayer();
  setRecordingButton();
  const distance = trackDistance(state.recording.points);
  setBanner(`Recording GPS track - ${state.recording.points.length} pts - ${fmtDistance(distance)}`);
}

async function startTrackRecording() {
  if (!_gpsEnabled) {
    await appAlert("Enable GPS first.", "Track Recording");
    return;
  }
  if (!_gpsState.fix || _gpsState.lat === null) {
    await appAlert("Waiting for a GPS fix before recording.", "Track Recording");
    return;
  }
  const go = await showTrackRecordDialog();
  if (!go) return;
  const ts = Math.floor(Date.now() / 1000);
  state.recording = { points: [], started_at: ts, ended_at: ts };
  captureGpsPoint();
  setRecordingButton();
}

async function stopTrackRecording() {
  const recording = state.recording;
  if (!recording) return;

  if (recording.points.length < 2) {
    state.recording = null;
    if (state.recordingLayer) { state.map.removeLayer(state.recordingLayer); state.recordingLayer = null; }
    setRecordingButton();
    setBanner("");
    await appAlert("Track discarded (fewer than 2 points).", "Track Recording");
    return;
  }

  const pts = recording.points.length;
  const dist = fmtDistance(trackDistance(recording.points));
  const defaultName = `Track ${fmtDateTime(Math.floor(Date.now() / 1000))}`;
  _trackSaveSelectedColor = TRACK_COLOR;

  const result = await showTrackSaveDialog({
    title: "Save Track",
    info: `${pts} point${pts !== 1 ? "s" : ""} · ${dist}`,
    name: defaultName,
    folder: "",
    color: TRACK_COLOR,
    showDiscard: true,
  });

  if (result === null) return; // cancelled — keep recording

  state.recording = null;
  if (state.recordingLayer) { state.map.removeLayer(state.recordingLayer); state.recordingLayer = null; }
  setRecordingButton();
  setBanner("");

  if (result === "discard") return;

  try {
    const saved = await api("/api/tracks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: result.name,
        folder: result.folder,
        color: result.color,
        points: recording.points,
        started_at: recording.started_at,
        ended_at: recording.ended_at,
      }),
    });
    const newId = saved?.track?.id;
    if (newId != null) state.trackVisible.set(newId, true);
    await loadTracks();
    if (newId != null) flyToTrack(newId);
  } catch (err) {
    await appAlert(err.message, "Save Track");
  }
}

async function toggleTrackRecording() {
  if (state.recording) {
    stopTrackRecording();
  } else {
    startTrackRecording();
  }
}

async function importGpxFile(event) {
  const input = event.target;
  const file = input.files?.[0];
  if (!file) return;
  const status = el("data-transfer-status");
  if (status) status.textContent = `Importing ${file.name}...`;
  const form = new FormData();
  form.append("file", file);
  try {
    const result = await api("/api/import/gpx", { method: "POST", body: form });
    input.value = "";
    if (status) status.textContent = `Imported ${result.markers || 0} markers, ${result.drawings || 0} drawings, and ${result.tracks || 0} tracks.`;
    await Promise.all([loadMarkers(), loadDrawings(), loadTracks()]);
    await appAlert(`Imported ${result.markers || 0} markers, ${result.drawings || 0} drawings, and ${result.tracks || 0} tracks.`, "GPX Import");
  } catch (err) {
    input.value = "";
    if (status) status.textContent = `Import failed: ${err.message}`;
    await appAlert(`Import failed: ${err.message}`, "GPX Import");
  }
}

function omSyncUrl() {
  const input = el("om-sync-url");
  const value = (input?.value || "http://localhost:8082").trim().replace(/\/+$/, "");
  if (input) input.value = value;
  localStorage.setItem("mapAppOmSyncUrl", value);
  return value;
}

async function pullFromOverMesh() {
  const status = el("data-transfer-status");
  if (status) status.textContent = "Pulling markings from OverMesh...";
  try {
    const result = await api("/api/om/sync/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: omSyncUrl() }),
    });
    if (status) status.textContent = `Pulled ${result.markers || 0} markers and ${result.drawings || 0} drawings from OM.`;
    await Promise.all([loadMarkers(), loadDrawings()]);
    await appAlert(`Pulled ${result.markers || 0} markers and ${result.drawings || 0} drawings from OM.`, "OverMesh Sync");
  } catch (err) {
    if (status) status.textContent = `Pull failed: ${err.message}`;
    await appAlert(`Pull failed: ${err.message}`, "OverMesh Sync");
  }
}

async function pushToOverMesh() {
  const ok = await appConfirm("Push OPS-TOC markers and drawings to OverMesh? Markers become OM Self Notes; drawings become OM Overlays. Nothing is broadcast over the mesh.", "Push To OM");
  if (!ok) return;
  const status = el("data-transfer-status");
  if (status) status.textContent = "Pushing markings to OverMesh...";
  try {
    const result = await api("/api/om/sync/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: omSyncUrl() }),
    });
    const om = result.om || {};
    if (status) status.textContent = `Pushed to OM: ${om.notes || 0} notes and ${om.layers || 0} overlays.`;
    await appAlert(`Pushed to OM: ${om.notes || 0} notes and ${om.layers || 0} overlays.`, "OverMesh Sync");
  } catch (err) {
    if (status) status.textContent = `Push failed: ${err.message}`;
    await appAlert(`Push failed: ${err.message}`, "OverMesh Sync");
  }
}

async function loadLayers() {
  const data = await api("/api/tile-layers");
  const select = el("layer-select");
  select.innerHTML = "";
  const panelList = el("layers-panel-list");
  if (panelList) panelList.innerHTML = "";

  function addPanelBtn(value, label) {
    if (!panelList) return;
    const btn = document.createElement("button");
    btn.className = "layer-opt";
    btn.dataset.value = value;
    btn.textContent = label;
    btn.type = "button";
    btn.onclick = () => { setLayer(value); setLayersPanelOpen(false); };
    panelList.appendChild(btn);
  }

  if (data.local.length) {
    if (panelList) {
      const lbl = document.createElement("div");
      lbl.className = "layer-group-label";
      lbl.textContent = "Local";
      panelList.appendChild(lbl);
    }
    for (const layer of data.local) {
      const opt = document.createElement("option");
      opt.value = `local:${layer.id}`;
      opt.textContent = `Local: ${layer.name}`;
      opt.dataset.minzoom = layer.minzoom;
      opt.dataset.maxzoom = layer.maxzoom;
      select.appendChild(opt);
      addPanelBtn(opt.value, layer.name);
    }
  }

  if (data.online.length && panelList) {
    const lbl = document.createElement("div");
    lbl.className = "layer-group-label";
    lbl.textContent = "Online";
    panelList.appendChild(lbl);
  }
  for (const layer of data.online) {
    const opt = document.createElement("option");
    opt.value = `online:${layer.id}`;
    opt.textContent = layer.name;
    opt.dataset.url = layer.url;
    opt.dataset.attr = layer.attribution;
    opt.dataset.maxzoom = layer.maxzoom;
    opt.dataset.keyProvider = layer.key_provider || "";
    select.appendChild(opt);
    addPanelBtn(opt.value, layer.name);
  }

  const saved = localStorage.getItem("mapAppLayer");
  select.value = saved && [...select.options].some((o) => o.value === saved)
    ? saved
    : (select.options[0]?.value || "online:voyager");
  setLayer(select.value);
}

function resolveTileUrl(url, layerName = "selected layer") {
  if (url.includes("{apikey}")) {
    const key = localStorage.getItem("thunderforestApiKey") || "";
    if (!key) {
      appAlert(`${layerName} needs a Thunderforest API key. Open Keys and save one first.`, "API Key Required");
    }
    url = url.replace("{apikey}", encodeURIComponent(key));
  }
  if (url.includes("{mtapikey}")) {
    const key = localStorage.getItem("mapTilerApiKey") || "";
    if (!key) {
      appAlert(`${layerName} needs a MapTiler API key. Open Keys and save one first.`, "API Key Required");
    }
    url = url.replace("{mtapikey}", encodeURIComponent(key));
  }
  return url;
}

const TRANSPARENT_TILE_URL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

function createTileLayer(value, magnifier = false) {
  const [type, id] = value.split(":");
  if (type === "local") {
    const opt = [...el("layer-select").options].find((o) => o.value === value);
    const maxNative = Number(opt?.dataset.maxzoom || 18);
    const minNative = Number(opt?.dataset.minzoom || 0);
    return L.tileLayer(`/tiles/${id}/{z}/{x}/{y}.png`, {
      minZoom: minNative,
      maxNativeZoom: maxNative,
      maxZoom: 21,
      attribution: "Local MBTiles",
      detectRetina: !magnifier,
      errorTileUrl: TRANSPARENT_TILE_URL,
    });
  }
  const opt = [...el("layer-select").options].find((o) => o.value === value);
  const rawUrl = opt?.dataset.url || "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";
  return L.tileLayer(resolveTileUrl(rawUrl, opt?.textContent || "selected layer"), {
    maxZoom: Number(opt?.dataset.maxzoom || 19),
    attribution: opt?.dataset.attr || "",
    detectRetina: !magnifier,
    errorTileUrl: TRANSPARENT_TILE_URL,
  });
}

function syncMagnifierLayer() {
  if (!state.magnifierMap || !state.activeLayerValue) return;
  if (state.magnifierLayer) state.magnifierMap.removeLayer(state.magnifierLayer);
  state.magnifierLayer = createTileLayer(state.activeLayerValue, true).addTo(state.magnifierMap);
  if (state.magnifierLatLng) {
    state.magnifierMap.setView(state.magnifierLatLng, state.map.getZoom(), { animate: false });
  }
}

function setLayer(value) {
  if (state.baseLayer) state.map.removeLayer(state.baseLayer);
  state.activeLayerValue = value;
  state.baseLayer = createTileLayer(value).addTo(state.map);
  syncMagnifierLayer();
  localStorage.setItem("mapAppLayer", value);
  const select = el("layer-select");
  if (select) select.value = value;
  document.querySelectorAll("#layers-panel-list .layer-opt").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.value === value);
  });
  const opt = [...(select?.options || [])].find((o) => o.value === value);
  const layersBtn = el("layers-btn");
  if (layersBtn && opt) layersBtn.textContent = opt.textContent;
}

function openSettings(targetId = "") {
  el("tf-api-key-input").value = localStorage.getItem("thunderforestApiKey") || "";
  el("mt-api-key-input").value = localStorage.getItem("mapTilerApiKey") || "";
  el("accent-color-input").value = localStorage.getItem("mapAppAccentColor") || currentAccentColor();
  const savedZoom = Number(localStorage.getItem("mapAppUIZoom") || 100);
  if (el("ui-zoom-input")) { el("ui-zoom-input").value = savedZoom; el("ui-zoom-value").textContent = savedZoom + "%"; }
  el("layer-key-status").textContent = "";
  el("update-status").textContent = "";
  el("version-summary").textContent = "Checking version...";
  el("update-log").hidden = true;
  el("settings-dialog").showModal();
  prepareOfflineSection();
  loadVersionStatus(false);
  if (targetId) {
    setTimeout(() => {
      el(targetId)?.scrollIntoView({ block: "start", behavior: "smooth" });
    }, 80);
  }
}

function setLayersPanelOpen(open) {
  const panel = el("layers-panel");
  const btn = el("layers-btn");
  if (!panel || !btn) return;
  panel.hidden = !open;
  btn.classList.toggle("active", open);
}

function toggleLayersPanel(event) {
  event?.stopPropagation();
  setLayersPanelOpen(el("layers-panel")?.hidden ?? true);
}

function setMarkersMenuOpen(open) {
  const menu = el("markers-menu");
  const btn = el("markers-menu-btn");
  if (!menu || !btn) return;
  menu.hidden = !open;
  btn.classList.toggle("active", open);
}

function toggleMarkersMenu(event) {
  event?.stopPropagation();
  setMarkersMenuOpen(el("markers-menu")?.hidden ?? true);
}

function closeToolsCompact() {
  const m = el("tools-compact-menu");
  if (m) m.hidden = true;
}
function toggleToolsCompact(event) {
  event?.stopPropagation();
  const m = el("tools-compact-menu");
  if (m) m.hidden = !m.hidden;
}

function setHamburgerOpen(open) {
  const menu = el("hamburger-menu");
  const button = el("settings-btn");
  if (!menu || !button) return;
  menu.hidden = !open;
  button.classList.toggle("active", open);
  button.setAttribute("aria-expanded", open ? "true" : "false");
}

function toggleHamburgerMenu(event) {
  event?.stopPropagation();
  setHamburgerOpen(el("hamburger-menu")?.hidden ?? true);
}

function openSettingsFromMenu(targetId) {
  setHamburgerOpen(false);
  openSettings(targetId);
}

function saveLayerKeys(event) {
  event?.preventDefault();
  localStorage.setItem("thunderforestApiKey", el("tf-api-key-input").value.trim());
  localStorage.setItem("mapTilerApiKey", el("mt-api-key-input").value.trim());
  el("layer-key-status").textContent = "Saved.";
  setTimeout(() => {
    setLayer(el("layer-select").value);
  }, 250);
}

function saveAccent(event) {
  event?.preventDefault();
  const hex = el("accent-color-input").value || DEFAULT_ACCENT;
  localStorage.setItem("mapAppAccentColor", hex);
  applyAccentColor(hex);
}

function resetAccent() {
  localStorage.setItem("mapAppAccentColor", DEFAULT_ACCENT);
  el("accent-color-input").value = DEFAULT_ACCENT;
  applyAccentColor(DEFAULT_ACCENT);
}

function closeSettingsOnBackdrop(event) {
  if (event.target === event.currentTarget) {
    event.currentTarget.close();
  }
}

function currentLayerOption() {
  return [...el("layer-select").options].find((o) => o.value === state.activeLayerValue);
}

function currentLayerDownloadDef() {
  const offlineSel = el("offline-layer-select");
  const opt = (offlineSel && offlineSel.options.length)
    ? [...offlineSel.options].find((o) => o.value === offlineSel.value) || offlineSel.options[0]
    : currentLayerOption();
  if (!opt) return null;
  const rawUrl = opt.dataset.url || "";
  if (!rawUrl || opt.value.startsWith("local:")) return null;
  return {
    name: opt.textContent || "Map layer",
    url: resolveTileUrl(rawUrl, opt.textContent || "selected layer"),
    attribution: opt.dataset.attr || "",
    maxzoom: Number(opt.dataset.maxzoom || 19),
    format: rawUrl.includes(".jpg") || rawUrl.includes(".jpeg") ? "jpg" : "png",
  };
}

function currentBoundsPayload() {
  if (state.offlineBounds) return { ...state.offlineBounds };
  if (!state.map) return {}; // map not yet initialized; caller validates
  const b = state.map.getBounds();
  return {
    south: b.getSouth(),
    west: b.getWest(),
    north: b.getNorth(),
    east: b.getEast(),
  };
}

async function updateOfflineEstimate() {
  const layer = currentLayerDownloadDef();
  const estimate = el("offline-estimate");
  if (!layer) {
    estimate.textContent = "Select an online layer first. Local MBTiles do not need downloading again.";
    el("offline-download-btn").disabled = true;
    return;
  }
  if (!state.offlineBounds && !state.map) {
    estimate.textContent = "Open the Map tab first to set a download area.";
    el("offline-download-btn").disabled = true;
    return;
  }
  const minZoom = Number(el("offline-min-zoom").value || (state.map ? state.map.getZoom() : 12));
  const maxZoom = Number(el("offline-max-zoom").value || (state.map ? state.map.getZoom() : 14));
  try {
    const data = await api("/api/download-estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentBoundsPayload(), min_zoom: minZoom, max_zoom: maxZoom }),
    });
    estimate.textContent = `${fmtTileEstimate(data.tiles, data.estimated_bytes)} selected. Size is estimated; check data plan and disk space for large jobs.`;
    el("offline-download-btn").disabled = !data.ok;
  } catch (err) {
    estimate.textContent = err.message;
    el("offline-download-btn").disabled = true;
  }
}

function prepareOfflineSection() {
  const zoom = state.map ? Math.round(state.map.getZoom()) : 12;
  el("offline-min-zoom").value = Math.max(0, zoom - 1);
  el("offline-max-zoom").value = Math.min(18, zoom + 2);
  el("offline-name").value = `Map ${new Date().toISOString().slice(0, 10)}`;
  el("offline-status").textContent = "";
  const offlineSel = el("offline-layer-select");
  if (offlineSel) {
    const mainSel = el("layer-select");
    offlineSel.innerHTML = "";
    [...mainSel.options].forEach((opt) => {
      if (opt.value.startsWith("local:") || !opt.dataset.url) return;
      const o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.textContent;
      o.dataset.url = opt.dataset.url || "";
      o.dataset.attr = opt.dataset.attr || "";
      o.dataset.maxzoom = opt.dataset.maxzoom || "19";
      if (opt.value === state.activeLayerValue) o.selected = true;
      offlineSel.appendChild(o);
    });
  }
  loadTilesets();
  loadDownloadQueue();
  if (!state.queuePoll) state.queuePoll = setInterval(loadDownloadQueue, 2500);
  el("offline-progress").hidden = true;
  el("offline-progress-bar").style.width = "0";
  useCurrentViewForOffline(false);
  updateOfflineEstimate();
}

function useCurrentViewForOffline(updateEstimate = true) {
  state.offlineBounds = null;
  el("offline-bounds-help").textContent = "Using current visible map area.";
  el("offline-region-results").hidden = true;
  el("offline-region-results").innerHTML = "";
  if (updateEstimate) updateOfflineEstimate();
}

async function searchOfflineRegions() {
  const query = el("offline-region-search").value.trim();
  const box = el("offline-region-results");
  if (!query) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = '<div class="empty compact">Searching...</div>';
  try {
    const results = await api(`/api/search?q=${encodeURIComponent(query)}`);
    renderOfflineRegionResults(results);
  } catch (err) {
    box.innerHTML = `<div class="empty compact">${esc(err.message)}</div>`;
  }
}

function renderOfflineRegionResults(results) {
  const box = el("offline-region-results");
  if (!results.length) {
    box.innerHTML = '<div class="empty compact">No regions found.</div>';
    return;
  }
  box.innerHTML = results.map((r, idx) => `
    <button class="search-result compact" type="button" data-index="${idx}">
      <div class="search-result-title">${esc(r.name)}</div>
      <div class="search-result-meta">${esc([r.category, r.type].filter(Boolean).join(" / "))} - ${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}</div>
    </button>`).join("");
  box.querySelectorAll(".search-result").forEach((btn) => {
    btn.onclick = () => selectOfflineRegion(results[Number(btn.dataset.index)]);
  });
}

function selectOfflineRegion(result) {
  const bbox = result.bbox || [];
  if (bbox.length >= 4) {
    const south = Number(bbox[0]);
    const north = Number(bbox[1]);
    const west = Number(bbox[2]);
    const east = Number(bbox[3]);
    if ([south, west, north, east].every(Number.isFinite)) {
      state.offlineBounds = { south, west, north, east };
      state.map.fitBounds([[south, west], [north, east]], { padding: [20, 20] });
      el("offline-bounds-help").textContent = `Using region: ${result.name}`;
    }
  } else {
    state.offlineBounds = null;
    state.map.setView([result.lat, result.lon], Math.max(state.map.getZoom(), 12));
    el("offline-bounds-help").textContent = `No region bounds found; using visible map around ${result.name}.`;
  }
  el("offline-name").value = result.name.split(",")[0].slice(0, 90) || el("offline-name").value;
  el("offline-region-results").hidden = true;
  updateOfflineEstimate();
}

async function pollOfflineJob(jobId) {
  const job = await api(`/api/downloads/${jobId}`);
  const cancelBtn = el("offline-cancel-btn");
  const pauseBtn = el("offline-pause-btn");
  const resumeBtn = el("offline-resume-btn");
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  el("offline-progress").hidden = false;
  el("offline-progress-bar").style.width = `${pct}%`;
  const rate = Number(job.tiles_per_s || 0);
  const eta = Number(job.eta_s || 0);
  const detail = rate > 0 ? ` · ${rate.toFixed(2)} tiles/s${eta > 0 ? ` · ETA ${fmtDuration(eta)}` : ""}` : "";
  const sizeDetail = Number(job.estimated_bytes || 0) > 0 ? ` · est. ${fmtBytes(Number(job.estimated_bytes))}` : "";
  el("offline-status").textContent = `${job.status}: ${job.done}/${job.total} tiles${sizeDetail}, ${job.saved} saved, ${job.failed} failed${detail}`;
  pauseBtn.hidden = !["queued", "running"].includes(job.status);
  resumeBtn.hidden = job.status !== "paused";
  cancelBtn.hidden = !["queued", "running", "paused"].includes(job.status);
  if (job.status === "done" || job.status === "error" || job.status === "cancelled") {
    clearInterval(state.offlinePoll);
    state.offlinePoll = 0;
    state.offlineJobId = null;
    el("offline-download-btn").disabled = false;
    cancelBtn.hidden = true;
    cancelBtn.disabled = false;
    pauseBtn.hidden = true;
    resumeBtn.hidden = true;
    if (job.status === "done") {
      el("offline-status").textContent = `Done. Saved ${job.saved} tiles.`;
    } else if (job.status === "cancelled") {
      el("offline-status").textContent = "Download cancelled.";
    } else {
      el("offline-status").textContent = `Failed: ${job.error || "unknown error"}`;
    }
    await loadTilesets();
    await loadDownloadQueue();
  }
}

async function startOfflineDownload() {
  const layer = currentLayerDownloadDef();
  if (!layer) {
    await appAlert("Select an online map layer before downloading.", "Offline Maps");
    return;
  }
  el("offline-download-btn").disabled = true;
  const minZoom = Number(el("offline-min-zoom").value || (state.map ? state.map.getZoom() : 12));
  const maxZoom = Number(el("offline-max-zoom").value || (state.map ? state.map.getZoom() : 14));
  const payload = {
    ...currentBoundsPayload(),
    min_zoom: minZoom,
    max_zoom: maxZoom,
    name: el("offline-name").value.trim() || "Offline map",
    layer_name: layer.name,
    url: layer.url,
    attribution: layer.attribution,
    format: layer.format,
  };
  try {
    const estimate = await api("/api/download-estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (Number(estimate.tiles || 0) > 100000) {
      const ok = await appConfirm(
        `This download is ${fmtTileEstimate(estimate.tiles, estimate.estimated_bytes)}. Size is estimated. Large jobs can take a very long time and use a lot of storage. Continue?`,
        "Large Offline Map"
      );
      if (!ok) {
        el("offline-download-btn").disabled = false;
        return;
      }
    }
    const job = await api("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    el("offline-progress").hidden = false;
    el("offline-status").textContent = `Started: ${fmtTileEstimate(job.total, job.estimated_bytes)}.`;
    state.offlineJobId = job.id;
    const cancelBtn = el("offline-cancel-btn");
    const pauseBtn = el("offline-pause-btn");
    if (cancelBtn) { cancelBtn.hidden = false; cancelBtn.disabled = false; }
    if (pauseBtn) pauseBtn.hidden = false;
    if (state.offlinePoll) clearInterval(state.offlinePoll);
    state.offlinePoll = setInterval(() => pollOfflineJob(job.id).catch((err) => {
      el("offline-status").textContent = err.message;
    }), 1000);
    await pollOfflineJob(job.id);
  } catch (err) {
    el("offline-download-btn").disabled = false;
    await appAlert(err.message, "Download Failed");
  }
}

async function updateApp() {
  const btn = el("update-app-btn");
  btn.disabled = true;
  el("update-status").textContent = "Updating from GitHub...";
  el("update-log").hidden = true;
  el("update-log").textContent = "";
  try {
    const data = await api("/api/update", { method: "POST" });
    el("update-status").textContent = data.restart ? "Updated. Restarting service and reloading..." : "Already up to date.";
    el("update-log").textContent = data.log || "";
    el("update-log").hidden = !data.log;
    setTimeout(() => window.location.reload(), 3500);
  } catch (err) {
    btn.disabled = false;
    el("update-status").textContent = `Update failed: ${err.message}`;
    if (err.data?.log) {
      el("update-log").textContent = err.data.log;
      el("update-log").hidden = false;
    }
  }
}

async function loadVersionStatus(checkRemote = false) {
  const btn = el("check-update-btn");
  if (btn) btn.disabled = true;
  if (checkRemote) el("version-summary").textContent = "Checking GitHub version...";
  try {
    const data = await api(`/api/version${checkRemote ? "?check=1" : ""}`);
    const parts = [];
    parts.push(`Current: ${data.current || "unknown"}`);
    if (data.branch) parts.push(`Branch: ${data.branch}`);
    if (data.latest) parts.push(`Latest: ${data.latest}`);
    if (data.latest) parts.push(data.up_to_date ? "Up to date" : "Update available");
    el("version-summary").textContent = parts.join(" · ");
    if (data.remote_error) el("update-status").textContent = `Version check warning: ${data.remote_error}`;
    else if (checkRemote) el("update-status").textContent = data.up_to_date ? "Already up to date." : "Update available.";
  } catch (err) {
    el("version-summary").textContent = "Version unavailable.";
    el("update-status").textContent = `Version check failed: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function restartApp() {
  setHamburgerOpen(false);
  const ok = await appConfirm("Restart OPS-TOC? The page will reload automatically.", "Restart");
  if (!ok) return;
  const restartBtn = el("restart-app-btn");
  const menuRestartBtn = el("menu-restart-btn");
  if (restartBtn) restartBtn.disabled = true;
  if (menuRestartBtn) menuRestartBtn.disabled = true;
  el("update-status").textContent = "Restarting OPS-TOC service...";
  showServiceSplash("OPS-TOC restarting...");
  try {
    await api("/api/service/restart", { method: "POST" });
    setTimeout(() => window.location.reload(), 3500);
  } catch (err) {
    hideServiceSplash();
    if (restartBtn) restartBtn.disabled = false;
    if (menuRestartBtn) menuRestartBtn.disabled = false;
    el("update-status").textContent = `Restart failed: ${err.message}`;
  }
}

async function stopApp() {
  setHamburgerOpen(false);
  const ok = await appConfirm("Shutdown OPS-TOC? The page will stop responding until the service is started again.", "Shutdown");
  if (!ok) return;
  const stopBtn = el("stop-app-btn");
  const menuShutdownBtn = el("menu-shutdown-btn");
  if (stopBtn) stopBtn.disabled = true;
  if (menuShutdownBtn) menuShutdownBtn.disabled = true;
  el("update-status").textContent = "Stopping OPS-TOC service...";
  showServiceSplash("OPS-TOC offline. Start it back up from the Dashboard!");
  try {
    await api("/api/service/stop", { method: "POST" });
    el("update-status").textContent = "OPS-TOC is stopping. Start it again from the dashboard when needed.";
  } catch (err) {
    hideServiceSplash();
    if (stopBtn) stopBtn.disabled = false;
    if (menuShutdownBtn) menuShutdownBtn.disabled = false;
    el("update-status").textContent = `Power off failed: ${err.message}`;
  }
}

function syncTargetChanged() {
  const sel = el("sync-target-select");
  const wrap = el("sync-custom-url-wrap");
  if (!sel || !wrap) return;
  wrap.style.display = sel.value === "custom" ? "flex" : "none";
}

function _syncBaseUrl() {
  const sel = el("sync-target-select");
  if (!sel) return "";
  if (sel.value === "custom") return (el("sync-base-url")?.value || "").trim().replace(/\/$/, "");
  return sel.value;
}

async function runFieldSync() {
  const btn = el("sync-now-btn");
  const statusEl = el("sync-status");
  const baseUrl = _syncBaseUrl();
  if (!baseUrl) { if (statusEl) statusEl.textContent = "Select a target first."; return; }
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = "Fetching local entries...";
  try {
    // entries endpoint returns a plain array
    const local = await api("/api/log/entries?limit=9999");
    const allLocal = Array.isArray(local) ? local : [];
    const entries = allLocal.map(e => ({
      uuid: e.uuid, ts: e.ts, category: e.category, body: e.body,
    })).filter(e => e.uuid);
    const knownUuids = entries.map(e => e.uuid);
    if (statusEl) statusEl.textContent = `Syncing ${entries.length} local entries with ${baseUrl}...`;
    const resp = await fetch(`${baseUrl}/api/log/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ known_uuids: knownUuids, entries }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "Sync failed");
    const received = (data.entries || []).length;
    // Import entries received from base into local DB
    if (received > 0) {
      await api("/api/log/sync", {
        method: "POST",
        body: JSON.stringify({ known_uuids: knownUuids, entries: data.entries }),
      });
    }
    if (statusEl) statusEl.textContent = `Done — sent ${data.imported ?? 0} to base, received ${received} from base.`;
    if (received > 0 && typeof loadEntries === "function") loadEntries();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Sync failed: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function hideSearchResults() {
  const box = el("search-results");
  box.hidden = true;
  box.innerHTML = "";
}

function renderSearchResults(results) {
  const box = el("search-results");
  if (!results.length) {
    box.innerHTML = '<div class="empty">No places found.</div>';
    box.hidden = false;
    return;
  }
  box.innerHTML = results.map((r, idx) => `
    <button class="search-result" type="button" data-index="${idx}">
      <div class="search-result-title">${esc(r.name)}</div>
      <div class="search-result-meta">${esc([r.category, r.type].filter(Boolean).join(" / "))} - ${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}</div>
    </button>`).join("");
  box.querySelectorAll(".search-result").forEach((btn) => {
    btn.onclick = () => selectSearchResult(results[Number(btn.dataset.index)]);
  });
  box.hidden = false;
}

function selectSearchResult(result) {
  hideSearchResults();
  const latlng = [result.lat, result.lon];
  if (state.searchMarker) state.map.removeLayer(state.searchMarker);
  state.searchMarker = L.marker(latlng, {
    icon: L.divIcon({
      html: '<div class="marker-chip">⌕</div>',
      className: "",
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    }),
  }).addTo(state.map).bindPopup(`
    <div style="min-width:190px;max-width:280px">
      <div style="color:var(--accent);font-weight:700;margin-bottom:5px">${esc(result.name)}</div>
      <div style="color:var(--muted);font-size:11px">${result.lat.toFixed(5)}, ${result.lon.toFixed(5)}</div>
    </div>`);
  const bbox = (result.bbox || []).map(Number);
  if (bbox.length === 4 && bbox.every(Number.isFinite)) {
    state.map.fitBounds([[bbox[0], bbox[2]], [bbox[1], bbox[3]]], { maxZoom: 16, padding: [24, 24] });
  } else {
    state.map.setView(latlng, Math.max(state.map.getZoom(), 14));
  }
  setTimeout(() => state.searchMarker.openPopup(), 180);
}

async function runSearch(event) {
  event.preventDefault();
  const query = el("search-input").value.trim();
  if (!query) {
    hideSearchResults();
    return;
  }
  el("search-btn").disabled = true;
  try {
    renderSearchResults(await api(`/api/search?q=${encodeURIComponent(query)}`));
  } catch (err) {
    await appAlert(err.message, "Search Failed");
  } finally {
    el("search-btn").disabled = false;
  }
}

function initMap() {
  const saved = JSON.parse(localStorage.getItem("mapAppView") || "null");
  state.map = L.map("map", { zoomSnap: 0.5, zoomDelta: 0.5 })
    .setView(saved ? [saved.lat, saved.lon] : [46.05, 14.5], saved ? saved.zoom : 9);
  state.map.on("moveend", () => {
    const c = state.map.getCenter();
    localStorage.setItem("mapAppView", JSON.stringify({ lat: c.lat, lon: c.lng, zoom: state.map.getZoom() }));
  });
  state.map.on("click", (event) => {
    if (_touchPlacing) return;
    if (!state.tool) return;
    if (state.tool === "marker") {
      openMarkerDialog(null, event.latlng);
      clearTool();
      return;
    }
    addToolPoint(event.latlng);
  });
  state.map.on("mousemove", updateMagnifier);
  state.map.on("mouseout", disableMagnifier);
  const _mapContainer = state.map.getContainer();
  _mapContainer.addEventListener("touchstart", (e) => {
    if (!placementToolActive()) return;
    if (e.touches.length === 1) {
      state.map.dragging.disable();
      const t = e.touches[0];
      const latlng = state.map.mouseEventToLatLng({ clientX: t.clientX, clientY: t.clientY });
      updateMagnifier({ latlng, originalEvent: e });
    } else {
      state.map.dragging.enable();
    }
  }, { passive: true });
  _mapContainer.addEventListener("touchmove", (e) => {
    if (!placementToolActive() || e.touches.length !== 1) return;
    e.preventDefault();
    const t = e.touches[0];
    const latlng = state.map.mouseEventToLatLng({ clientX: t.clientX, clientY: t.clientY });
    updateMagnifier({ latlng, originalEvent: e });
  }, { passive: false });
  _mapContainer.addEventListener("touchend", (e) => {
    if (!placementToolActive()) return;
    if (e.touches.length > 0) return;
    state.map.dragging.enable();
    if (!state.magnifierLatLng) return;
    e.preventDefault();
    _touchPlacing = true;
    setTimeout(() => { _touchPlacing = false; }, 400);
    const latlng = state.magnifierLatLng;
    if (state.tool === "marker") {
      openMarkerDialog(null, latlng);
      clearTool();
    } else {
      addToolPoint(latlng);
    }
  }, { passive: false });
  _mapContainer.addEventListener("touchcancel", () => {
    if (placementToolActive()) state.map.dragging.enable();
  }, { passive: true });
  state.map.on("zoomend", () => {
    if (state.magnifierMap && state.magnifierLatLng) {
      state.magnifierMap.setView(state.magnifierLatLng, state.map.getZoom(), { animate: false });
    }
  });
  state.map.on("dragstart", () => { _gpsFollowMode = 0; _updateGpsBtn(); });
}

function bindUi() {
  applyAccentColor(localStorage.getItem("mapAppAccentColor") || DEFAULT_ACCENT);
  applyUIZoom(localStorage.getItem("mapAppUIZoom") || 100);
  installControlFeedback();
  bindClick("markers-btn", () => setSidePanelClosed(!el("side-panel").classList.contains("closed")));
  bindClick("close-panel-btn", () => setSidePanelClosed(true));
  bindClick("add-marker-btn", () => startTool("marker"));
  bindClick("measure-btn", () => startTool("measure"));
  bindClick("draw-line-btn", () => startTool("line"));
  bindClick("draw-poly-btn", () => startTool("polygon"));
  bindClick("undo-point-btn", undoToolPoint);
  bindClick("finish-tool-btn", finishTool);
  bindClick("cancel-tool-btn", clearTool);
  bindClick("gpx-import-btn", () => el("gpx-import-file")?.click());
  bindEvent("gpx-import-file", "change", importGpxFile);
  bindClick("track-record-btn", toggleTrackRecording);
  bindClick("tracks-refresh-btn", loadTracks);
  bindClick("om-pull-btn", pullFromOverMesh);
  bindClick("om-push-btn", pushToOverMesh);
  bindClick("menu-geojson-btn", () => setHamburgerOpen(false));
  bindClick("menu-manual-btn", openManual);
  bindClick("manual-clear-btn", () => {
    if (el("manual-search")) el("manual-search").value = "";
    renderManual("");
  });
  bindEvent("manual-search", "input", (event) => renderManual(event.target.value));
  const omUrl = localStorage.getItem("mapAppOmSyncUrl");
  if (omUrl && el("om-sync-url")) el("om-sync-url").value = omUrl;
  el("marker-form").onsubmit = saveMarker;
  bindClick("settings-btn", toggleHamburgerMenu);
  bindEvent("settings-dialog", "click", closeSettingsOnBackdrop);
  bindClick("layer-key-save-btn", saveLayerKeys);
  bindClick("accent-save-btn", saveAccent);
  bindClick("accent-reset-btn", resetAccent);
  bindClick("zoom-save-btn", saveZoom);
  bindClick("zoom-reset-btn", resetZoom);
  bindEvent("ui-zoom-input", "input", () => {
    const pct = el("ui-zoom-input").value;
    el("ui-zoom-value").textContent = pct + "%";
    applyUIZoom(pct);
  });
  el("offline-min-zoom").onchange = updateOfflineEstimate;
  el("offline-max-zoom").onchange = updateOfflineEstimate;
  el("offline-min-zoom").oninput = updateOfflineEstimate;
  el("offline-max-zoom").oninput = updateOfflineEstimate;
  bindClick("offline-download-btn", startOfflineDownload);
  bindClick("offline-cancel-btn", cancelOfflineDownload);
  bindClick("offline-pause-btn", pauseOfflineDownload);
  bindClick("offline-resume-btn", resumeOfflineDownload);
  bindClick("offline-use-view-btn", () => useCurrentViewForOffline(true));
  bindClick("offline-region-search-btn", searchOfflineRegions);
  bindEvent("offline-region-search", "keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchOfflineRegions();
    }
  });
  bindClick("sync-now-btn", runFieldSync);
  bindClick("check-update-btn", () => loadVersionStatus(true));
  bindClick("update-app-btn", updateApp);
  bindClick("restart-app-btn", restartApp);
  bindClick("stop-app-btn", stopApp);
  bindClick("menu-restart-btn", restartApp);
  bindClick("menu-shutdown-btn", stopApp);
  el("hamburger-menu")?.querySelectorAll("[data-settings-target]").forEach((item) => {
    item.onclick = () => openSettingsFromMenu(item.dataset.settingsTarget);
  });
  el("search-form").onsubmit = runSearch;
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.tool) clearTool();
    if (event.key === "Escape") hideSearchResults();
    if (event.key === "Escape") setHamburgerOpen(false);
    if (event.key === "Enter" && state.tool && state.toolPoints.length >= 2) finishTool();
    if ((event.key === "Backspace" || event.key === "Delete") && state.tool && state.toolPoints.length) {
      event.preventDefault();
      undoToolPoint();
    }
  });
  document.addEventListener("click", (event) => {
    if (!el("menu-wrap")?.contains(event.target)) setHamburgerOpen(false);
    if (!el("layer-wrap")?.contains(event.target)) setLayersPanelOpen(false);
    if (!el("markers-wrap")?.contains(event.target)) setMarkersMenuOpen(false);
    if (!el("tools-compact-wrap")?.contains(event.target)) closeToolsCompact();
  });
}

let _mapDataLoaded = false;
let _touchPlacing = false;

async function initMapAndData() {
  if (state.map) {
    // already initialized — just invalidate size in case it was hidden
    setTimeout(() => state.map.invalidateSize(), 60);
    return;
  }
  initMap();
  await loadLayers();
  await Promise.all([loadMarkers(), loadDrawings(), loadTracks()]);
  _mapDataLoaded = true;
}

async function boot() {
  bindUi();
  // Map init deferred until MAP tab is first opened
}

boot().catch((err) => appAlert(err.message, "Startup Failed"));

// ===== TILESET MANAGEMENT =====

async function cancelOfflineDownload() {
  if (!state.offlineJobId) return;
  try {
    await api(`/api/downloads/${state.offlineJobId}/cancel`, { method: "POST" });
    el("offline-status").textContent = "Cancelling...";
    el("offline-cancel-btn").disabled = true;
  } catch (e) {
    el("offline-status").textContent = "Cancel failed.";
  }
}

async function pauseOfflineDownload() {
  if (!state.offlineJobId) return;
  try {
    await api(`/api/downloads/${state.offlineJobId}/pause`, { method: "POST" });
    el("offline-status").textContent = "Paused.";
    el("offline-pause-btn").hidden = true;
    el("offline-resume-btn").hidden = false;
    await loadDownloadQueue();
  } catch (e) {
    el("offline-status").textContent = `Pause failed: ${e.message}`;
  }
}

async function resumeOfflineDownload() {
  if (!state.offlineJobId) return;
  try {
    await api(`/api/downloads/${state.offlineJobId}/resume`, { method: "POST" });
    el("offline-status").textContent = "Resuming...";
    el("offline-pause-btn").hidden = false;
    el("offline-resume-btn").hidden = true;
    await loadDownloadQueue();
  } catch (e) {
    el("offline-status").textContent = `Resume failed: ${e.message}`;
  }
}

async function loadTilesets() {
  const list = el("tilesets-list");
  const summary = el("tilesets-summary");
  if (!list) return;
  try {
    const data = await api("/api/tile-layers");
    const local = (data.local || []).filter((l) => l.source_url);
    const totalSize = local.reduce((sum, l) => sum + Number(l.size || 0), 0);
    const totalTiles = local.reduce((sum, l) => sum + Number(l.tile_count || 0), 0);
    if (summary) {
      summary.textContent = local.length
        ? `${local.length} downloaded maps · ${totalTiles.toLocaleString()} tiles · ${fmtBytes(totalSize)}`
        : "No downloaded maps yet.";
    }
    if (!local.length) {
      list.innerHTML = '<p class="field-help" style="color:var(--muted)">No tilesets downloaded yet.</p>';
      return;
    }
    list.innerHTML = local.map((l) => {
      const date = l.mtime ? fmtDateTime(l.mtime) : "-";
      const zoom = `z${l.minzoom}–${l.maxzoom}`;
      const bounds = formatBounds(l.bounds);
      const sub = [l.source_layer_name, zoom, `${Number(l.tile_count || 0).toLocaleString()} tiles`, fmtBytes(l.size), date].filter(Boolean).join(" · ");
      return `<div class="tileset-row">
        <div class="tileset-info">
          <div class="tileset-title">${esc(l.name)}</div>
          <div class="field-help">${esc(sub)}</div>
          <div class="tileset-meta">${esc(bounds)}</div>
          <code class="tileset-url">${esc(l.map_app_tile_url || `/tiles/${l.id}/{z}/{x}/{y}.png`)}</code>
        </div>
        <div class="tileset-actions">
          <button class="btn small" data-action="use" data-id="${esc(l.id)}">Use</button>
          <button class="btn small" data-action="rename" data-id="${esc(l.id)}" data-name="${esc(l.name)}">Rename</button>
          <button class="btn small" data-action="extend" data-id="${esc(l.id)}" data-name="${esc(l.name)}" data-minzoom="${l.minzoom}" data-maxzoom="${l.maxzoom}">Edit Zoom</button>
          <button class="btn small" data-action="repair" data-id="${esc(l.id)}" data-name="${esc(l.name)}">Repair</button>
          <button class="btn small" data-action="refresh" data-id="${esc(l.id)}" data-name="${esc(l.name)}">Refresh</button>
          <button class="btn small danger" data-action="delete" data-id="${esc(l.id)}" data-name="${esc(l.name)}">Delete</button>
        </div>
      </div>`;
    }).join("");
    list.querySelectorAll("[data-action]").forEach((btn) => {
      btn.onclick = () => {
        const id = btn.dataset.id;
        const name = btn.dataset.name || id;
        if (btn.dataset.action === "use") useTileset(id);
        if (btn.dataset.action === "rename") renameTileset(id, name);
        if (btn.dataset.action === "extend") extendTileset(id, name, Number(btn.dataset.minzoom), Number(btn.dataset.maxzoom));
        if (btn.dataset.action === "repair") repairTileset(id, name);
        if (btn.dataset.action === "refresh") refreshTileset(id, name);
        if (btn.dataset.action === "delete") deleteTileset(id, name);
      };
    });
  } catch (e) {
    if (summary) summary.textContent = "Failed to load downloaded maps.";
    list.innerHTML = '<p class="field-help" style="color:var(--muted)">Failed to load tilesets.</p>';
  }
}

function formatBounds(bounds) {
  const parts = String(bounds || "").split(",").map(Number);
  if (parts.length !== 4 || !parts.every(Number.isFinite)) return "Bounds unavailable";
  const [west, south, east, north] = parts;
  return `Bounds ${south.toFixed(4)}, ${west.toFixed(4)} to ${north.toFixed(4)}, ${east.toFixed(4)}`;
}

function useTileset(layerId) {
  const value = `local:${layerId}`;
  const select = el("layer-select");
  if (![...select.options].some((o) => o.value === value)) {
    loadLayers().then(() => useTileset(layerId)).catch((err) => appAlert(err.message, "Map Layer"));
    return;
  }
  select.value = value;
  setLayer(value);
  el("settings-dialog").close();
}

async function renameTileset(layerId, name) {
  const nextName = await appPrompt("Downloaded map name", name || "Offline map", "Rename Map");
  if (nextName === null) return;
  const cleanName = nextName.trim();
  if (!cleanName || cleanName === name) return;
  try {
    await api(`/api/tile-layers/${layerId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: cleanName }),
    });
    await loadTilesets();
    await loadLayers();
  } catch (e) {
    await appAlert(`Rename failed: ${e.message}`, "Error");
  }
}

async function deleteTileset(layerId, name) {
  const ok = await appConfirm(`Delete "${name}"? This cannot be undone.`, "Delete Tileset");
  if (!ok) return;
  try {
    await api(`/api/tile-layers/${layerId}`, { method: "DELETE" });
    await loadTilesets();
    await loadLayers();
  } catch (e) {
    await appAlert(`Delete failed: ${e.message}`, "Error");
  }
}

function appZoomDialog(name, currentMin, currentMax) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.style.cssText = "background:var(--surface);color:var(--fg);border:1px solid var(--border);border-radius:10px;padding:22px 24px;min-width:260px;max-width:340px;box-shadow:0 8px 32px #0008";
    dlg.innerHTML = `
      <form method="dialog" style="display:flex;flex-direction:column;gap:14px">
        <h2 style="margin:0;font-size:15px;font-weight:600">Edit Zoom Range</h2>
        <p style="margin:0;font-size:13px;color:var(--muted)">"${esc(name)}" — current range: z${currentMin}–z${currentMax}</p>
        <div style="display:flex;gap:12px">
          <label style="flex:1;font-size:13px;display:flex;flex-direction:column;gap:5px">Min zoom
            <input id="zoom-dlg-min" type="number" min="0" max="22" value="${currentMin}"
              style="background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:14px;width:100%;box-sizing:border-box">
          </label>
          <label style="flex:1;font-size:13px;display:flex;flex-direction:column;gap:5px">Max zoom
            <input id="zoom-dlg-max" type="number" min="0" max="22" value="${currentMax}"
              style="background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:14px;width:100%;box-sizing:border-box">
          </label>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px">
          <button id="zoom-dlg-cancel" class="btn" value="cancel" type="button">Cancel</button>
          <button class="btn primary" value="default" type="submit">Download</button>
        </div>
      </form>`;
    document.body.appendChild(dlg);
    const cleanup = () => { dlg.remove(); };
    dlg.querySelector("form").onsubmit = (e) => {
      e.preventDefault();
      const minVal = parseInt(dlg.querySelector("#zoom-dlg-min").value, 10);
      const maxVal = parseInt(dlg.querySelector("#zoom-dlg-max").value, 10);
      cleanup();
      resolve({ min: minVal, max: maxVal });
    };
    dlg.querySelector("#zoom-dlg-cancel").onclick = () => { cleanup(); resolve(null); };
    dlg.oncancel = () => { cleanup(); resolve(null); };
    dlg.showModal();
    setTimeout(() => dlg.querySelector("#zoom-dlg-min")?.focus(), 60);
  });
}

async function extendTileset(layerId, name, currentMin, currentMax) {
  const result = await appZoomDialog(name, currentMin, currentMax);
  if (result === null) return;
  const minZ = Math.max(0, Math.min(22, Number.isFinite(result.min) ? result.min : currentMin));
  const maxZ = Math.max(0, Math.min(22, Number.isFinite(result.max) ? result.max : currentMax));
  if (minZ === currentMin && maxZ === currentMax) {
    await appAlert("No zoom range change — nothing to add.", "Edit Zoom Range");
    return;
  }
  try {
    const estimate = await api(`/api/tile-layers/${layerId}/extend-estimate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ min_zoom: minZ, max_zoom: maxZ }),
    });
    const tileCount = Number(estimate.tiles || 0);
    if (tileCount <= 0) {
      await appAlert("No new or missing tiles in that zoom range.", "Edit Zoom Range");
      return;
    }
    if (tileCount > 100000) {
      const ok = await appConfirm(
        `Adding this zoom range requires ${fmtTileEstimate(tileCount, estimate.estimated_bytes)}. Size is estimated from this map's average tile size. For a large area, high zoom levels can take days or weeks and use a lot of storage. Continue?`,
        "Large Zoom Extension"
      );
      if (!ok) return;
    }
    const job = await api(`/api/tile-layers/${layerId}/extend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ min_zoom: minZ, max_zoom: maxZ }),
    });
    trackOfflineJob(job, `Extending "${name}" to z${minZ}–z${maxZ}: ${fmtTileEstimate(job.total, job.estimated_bytes)}.`);
  } catch (e) {
    await appAlert(`Extend failed: ${e.message}`, "Error");
  }
}

async function refreshTileset(layerId, name) {
  const ok = await appConfirm(`Re-download all tiles for "${name}"? This will overwrite the existing file.`, "Refresh Tileset");
  if (!ok) return;
  try {
    const job = await api(`/api/tile-layers/${layerId}/refresh`, { method: "POST" });
    trackOfflineJob(job, `Refreshing "${name}": ${job.total} tiles.`);
  } catch (e) {
    await appAlert(`Refresh failed: ${e.message}`, "Error");
  }
}

async function repairTileset(layerId, name) {
  try {
    const job = await api(`/api/tile-layers/${layerId}/repair`, { method: "POST" });
    trackOfflineJob(job, `Repairing "${name}": ${job.total} missing tiles.`);
  } catch (e) {
    await appAlert(`Repair failed: ${e.message}`, "Error");
  }
}

function trackOfflineJob(job, message) {
  state.offlineJobId = job.id;
  el("offline-progress").hidden = false;
  el("offline-progress-bar").style.width = "0";
  el("offline-status").textContent = message;
  el("offline-cancel-btn").hidden = false;
  el("offline-cancel-btn").disabled = false;
  el("offline-pause-btn").hidden = false;
  el("offline-resume-btn").hidden = true;
  if (state.offlinePoll) clearInterval(state.offlinePoll);
  state.offlinePoll = setInterval(() => pollOfflineJob(job.id).catch((err) => {
    el("offline-status").textContent = err.message;
  }), 1000);
  pollOfflineJob(job.id).catch((err) => {
    el("offline-status").textContent = err.message;
  });
  loadDownloadQueue();
}

async function updateAllTilesets() {
  const ok = await appConfirm("Queue refresh jobs for all downloaded maps with stored source URLs?", "Update All Maps");
  if (!ok) return;
  try {
    const data = await api("/api/tile-layers/update-all", { method: "POST" });
    if (data.jobs?.length) trackOfflineJob(data.jobs[0], `Queued ${data.jobs.length} update jobs.`);
    else await appAlert("No update jobs were queued.", "Update All Maps");
    await loadDownloadQueue();
  } catch (e) {
    await appAlert(`Update all failed: ${e.message}`, "Error");
  }
}

async function repairAllTilesets() {
  try {
    const data = await api("/api/tile-layers/repair-all", { method: "POST" });
    if (data.jobs?.length) trackOfflineJob(data.jobs[0], `Queued ${data.jobs.length} repair jobs.`);
    else await appAlert("No missing tiles found in downloaded maps.", "Repair Missing");
    await loadDownloadQueue();
  } catch (e) {
    await appAlert(`Repair all failed: ${e.message}`, "Error");
  }
}

async function loadDownloadQueue() {
  const box = el("download-queue-list");
  const summary = el("download-queue-summary");
  if (!box) return;
  try {
    const data = await api("/api/downloads");
    const allJobs = data.jobs || [];
    const activeJobs = allJobs.filter((j) => !["done", "cancelled", "error"].includes(j.status));
    const finishedJobs = allJobs.filter((j) => ["done", "cancelled", "error"].includes(j.status));
    if (summary) {
      const failed = finishedJobs.filter((j) => j.status === "error").length;
      summary.textContent = `${activeJobs.length} active · ${finishedJobs.length} finished${failed ? ` · ${failed} failed` : ""}`;
    }
    const jobs = activeJobs.slice(0, 12);
    if (!jobs.length) {
      box.innerHTML = '<p class="field-help" style="color:var(--muted)">No queued or running jobs.</p>';
      return;
    }
    box.innerHTML = jobs.map((j) => {
      const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
      const eta = j.eta_s ? ` · ETA ${fmtDuration(j.eta_s)}` : "";
      const rate = j.tiles_per_s ? ` · ${j.tiles_per_s} tiles/s` : "";
      return `<div class="queue-row">
        <div class="queue-main">
          <div class="tileset-title">${esc(j.name)} <span class="queue-kind">${esc(j.kind || "download")}</span></div>
          <div class="field-help">${esc(j.status)} · ${Number(j.done || 0).toLocaleString()}/${Number(j.total || 0).toLocaleString()} tiles · ${Number(j.saved || 0).toLocaleString()} saved · ${Number(j.failed || 0).toLocaleString()} failed${esc(rate)}${esc(eta)}</div>
          <div class="queue-progress"><span style="width:${pct}%"></span></div>
        </div>
        <div class="tileset-actions">
          <button class="btn small" data-job-action="pause" data-id="${esc(j.id)}" ${["running", "queued"].includes(j.status) ? "" : "disabled"}>Pause</button>
          <button class="btn small" data-job-action="resume" data-id="${esc(j.id)}" ${j.status === "paused" ? "" : "disabled"}>Resume</button>
          <button class="btn small danger" data-job-action="cancel" data-id="${esc(j.id)}">Cancel</button>
        </div>
      </div>`;
    }).join("");
    box.querySelectorAll("[data-job-action]").forEach((btn) => {
      btn.onclick = async () => {
        await api(`/api/downloads/${btn.dataset.id}/${btn.dataset.jobAction}`, { method: "POST" });
        await loadDownloadQueue();
      };
    });
  } catch (e) {
    if (summary) summary.textContent = "Failed to load jobs.";
    box.innerHTML = '<p class="field-help" style="color:var(--muted)">Failed to load queue.</p>';
  }
}

function fmtDuration(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  if (m < 60) return `${m}m ${rem}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

async function clearFinishedDownloads() {
  const ok = await appConfirm("Clear finished, cancelled, and failed download job records? Downloaded maps stay untouched.", "Clear Finished Jobs");
  if (!ok) return;
  try {
    const data = await api("/api/downloads/clear-finished", { method: "POST" });
    await appAlert(`Cleared ${data.cleared || 0} job records.`, "Download Queue");
    await loadDownloadQueue();
  } catch (e) {
    await appAlert(`Clear failed: ${e.message}`, "Download Queue");
  }
}

function setZoomPreset(minZ, maxZ) {
  el("offline-min-zoom").value = minZ;
  el("offline-max-zoom").value = maxZ;
  updateOfflineEstimate();
}

// ── GPS ────────────────────────────────────────────────────────────────────

let _gpsState   = { fix: false, lat: null, lon: null, alt: null, sats: 0, sats_view: 0 };
let _gpsEnabled = false;
let _gpsMarker  = null;
let _gpsTimer   = null;
let _gpsPrevPos = null; // { lat, lon, ts } for speed calculation
let _gpsCurrentSpeed = 0; // km/h, smoothed
// GPS follow modes: 0=off, 1=soft (pan when near edge), 2=hard (always centered)
let _gpsFollowMode = 0;

// ── Track chart scrub ──────────────────────────────────────────────────────
let _chartScrubMarker = null;
let _activeChartData = null; // { speedData, altData, speedCap }

const _GPS_MODE_LABEL = ["⊙ GPS", "⊙ GPS soft", "⊙ GPS lock"];
const _GPS_MODE_TITLE = [
  "GPS position — click for hard follow",
  "GPS soft follow — pans when near edge — click to lock / drag to stop",
  "GPS locked — always centered — click for soft / drag to stop",
];

function _updateGpsBtn() {
  const btn = el("gps-btn");
  if (!btn) return;
  btn.textContent = _GPS_MODE_LABEL[_gpsFollowMode];
  btn.title = _GPS_MODE_TITLE[_gpsFollowMode];
  btn.classList.toggle("active", _gpsFollowMode === 2);
  btn.classList.toggle("btn-soft", _gpsFollowMode === 1);
}

function _updateSpeedHud() {
  const hud = el("speed-hud");
  if (!hud) return;
  if (!_gpsEnabled || !_gpsState.fix) {
    hud.hidden = true;
    return;
  }
  hud.hidden = false;
  const valEl = hud.querySelector(".speed-hud-value");
  if (valEl) valEl.textContent = Math.round(_gpsCurrentSpeed);
}

function _gpsUpdateDot() {
  const dot = el("gps-dot");
  if (!dot) return;
  dot.className = "gps-dot " + (_gpsEnabled
    ? (_gpsState.fix ? "fix" : "acquiring")
    : "off");
  // also update the always-visible GPS header text for LOG/MISSIONS tabs
  const txt = el("gps-header-text");
  if (txt) {
    txt.textContent = (_gpsEnabled && _gpsState.fix && _gpsState.lat != null)
      ? `${Number(_gpsState.lat).toFixed(4)}, ${Number(_gpsState.lon).toFixed(4)}`
      : "";
  }
}

function _gpsUpdateMarker() {
  if (!state.map) return; // map not initialized yet (deferred until MAP tab opened)
  if (!_gpsState.fix || _gpsState.lat === null) {
    if (_gpsMarker) { state.map.removeLayer(_gpsMarker); _gpsMarker = null; }
    return;
  }
  const ll = [_gpsState.lat, _gpsState.lon];
  if (!_gpsMarker) {
    const icon = L.divIcon({
      className: "",
      html: '<div style="width:14px;height:14px;background:#e8b04f;border:2px solid #fff;border-radius:50%;box-shadow:0 0 6px rgba(232,176,79,0.65)"></div>',
      iconSize: [14, 14], iconAnchor: [7, 7],
    });
    _gpsMarker = L.marker(ll, { icon, zIndexOffset: 1000 })
      .bindPopup(() => {
        const s = _gpsState;
        return `<b>GPS Position</b><br>${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}<br>Alt: ${s.alt ?? "—"}m · Sats: ${s.sats}`;
      })
      .addTo(state.map);
  } else {
    _gpsMarker.setLatLng(ll);
  }
  if (_gpsFollowMode === 2) {
    state.map.panTo(ll, { animate: true, duration: 0.8 });
  } else if (_gpsFollowMode === 1) {
    const sz = state.map.getSize();
    const pt = state.map.latLngToContainerPoint(ll);
    const m = 0.22;
    if (pt.x < sz.x * m || pt.x > sz.x * (1 - m) || pt.y < sz.y * m || pt.y > sz.y * (1 - m)) {
      state.map.panTo(ll, { animate: true, duration: 0.6 });
    }
  }
}

async function _gpsPoll() {
  try {
    const d = await api("/api/gps");
    _gpsEnabled = d.enabled || false;
    _gpsState   = { fix: d.fix, lat: d.lat, lon: d.lon, alt: d.alt, sats: d.sats, sats_view: d.sats_view };

    // Speed from position delta
    if (_gpsEnabled && d.fix && d.lat != null && d.lon != null) {
      const now = Date.now() / 1000;
      if (_gpsPrevPos) {
        const dt = now - _gpsPrevPos.ts;
        if (dt >= 1 && dt <= 12) {
          const dist = distanceBetween(_gpsPrevPos, { lat: d.lat, lon: d.lon });
          const raw = (dist / dt) * 3.6;
          _gpsCurrentSpeed = _gpsCurrentSpeed * 0.35 + raw * 0.65;
        }
      }
      _gpsPrevPos = { lat: d.lat, lon: d.lon, ts: now };
    } else {
      _gpsCurrentSpeed = 0;
    }

    _gpsUpdateDot();
    _updateSpeedHud();
    _gpsUpdateMarker();
    captureGpsPoint();
    // update status text in settings panel if visible
    const row = el("gps-status-row");
    const txt = el("gps-status-text");
    if (row && txt) {
      if (!d.enabled) {
        row.hidden = true;
      } else {
        row.hidden = false;
        if (d.fix) {
          txt.textContent = `Fix ✓ — ${Number(d.lat).toFixed(5)}, ${Number(d.lon).toFixed(5)} · Alt ${d.alt ?? "—"}m · Sats ${d.sats}`;
        } else {
          txt.textContent = `No fix — Sats in view: ${d.sats_view || 0}${d.error ? " · " + d.error : ""}`;
        }
      }
    }
  } catch (_) {}
}

function gpsGoTo() {
  if (!state.map) return;
  // Cycle: off(0) → hard(2) → soft(1) → off(0)
  _gpsFollowMode = _gpsFollowMode === 0 ? 2 : (_gpsFollowMode === 2 ? 1 : 0);
  _updateGpsBtn();
  if (_gpsFollowMode > 0 && _gpsState.fix && _gpsState.lat !== null) {
    state.map.setView([_gpsState.lat, _gpsState.lon], Math.max(state.map.getZoom(), 15));
  }
}

async function gpsScanPorts() {
  const sel = el("gps-port-select");
  if (!sel) return;
  try {
    const d    = await api("/api/gps/ports");
    const prev = sel.value;
    sel.innerHTML = '<option value="">— select port —</option>' +
      (d.ports || []).map((p) => {
        const dev = p.device || p;
        const lbl = p.label || dev;
        return `<option value="${esc(dev)}">${esc(lbl)}</option>`;
      }).join("");
    if (prev) sel.value = prev;
  } catch (_) {}
}

function gpsSourceChanged() {
  const v   = (el("gps-source-select") || {}).value;
  const row = el("gps-port-row");
  if (row) row.style.display = (v === "direct") ? "block" : "none";
}

async function gpsSaveSettings() {
  const enabled  = el("gps-enabled").checked;
  const port     = (el("gps-port-select") || {}).value || "";
  const src      = el("gps-source-select");
  const om_proxy = src ? src.value === "proxy" : true;
  await api("/api/gps", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, port, om_proxy, om_url: "http://localhost:8082" }) });
  await _gpsPoll();
}

async function initGps() {
  const saveBtn = el("gps-save-btn");
  const scanBtn = el("gps-scan-btn");
  const srcSel  = el("gps-source-select");
  if (saveBtn) saveBtn.onclick = gpsSaveSettings;
  if (scanBtn) scanBtn.onclick = gpsScanPorts;
  if (srcSel)  srcSel.onchange = gpsSourceChanged;
  // Pre-populate settings panel when opened
  document.querySelectorAll("[data-settings-target='gps-section']").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const d  = await api("/api/gps");
      const cb = el("gps-enabled");
      if (cb) cb.checked = d.enabled || false;
      const src = el("gps-source-select");
      if (src) { src.value = (d.om_proxy !== false) ? "proxy" : "direct"; gpsSourceChanged(); }
      await gpsScanPorts();
      const sel = el("gps-port-select");
      if (sel && d.port) sel.value = d.port;
      await _gpsPoll();
    });
  });
  await _gpsPoll();
  _gpsTimer = setInterval(_gpsPoll, 3000);
}

// Hook into existing DOMContentLoaded / init cycle
document.addEventListener("DOMContentLoaded", () => {
  // initMap is already called — hook GPS after a short delay to let map init settle
  setTimeout(initGps, 500);
});
