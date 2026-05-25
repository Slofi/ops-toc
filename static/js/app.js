const state = {
  map: null,
  baseLayer: null,
  markers: new Map(),
  markerLayers: new Map(),
  drawings: new Map(),
  drawingLayers: new Map(),
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
};

const el = (id) => document.getElementById(id);
const DEFAULT_ACCENT = "#4ade80";

function bindClick(id, handler) {
  const node = el(id);
  if (node) node.onclick = handler;
}

function bindEvent(id, eventName, handler) {
  const node = el(id);
  if (node) node.addEventListener(eventName, handler);
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

function appDialog({ title = "Message", message = "", mode = "alert", value = "", placeholder = "" }) {
  return new Promise((resolve) => {
    const dialog = el("app-dialog");
    const form = el("app-dialog-form");
    const inputWrap = el("app-dialog-input-label");
    const input = el("app-dialog-input");
    const cancel = el("app-dialog-cancel");
    el("app-dialog-title").textContent = title;
    el("app-dialog-message").textContent = message;
    inputWrap.hidden = mode !== "prompt";
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
      resolve(mode === "prompt" ? input.value : true);
    };
    cancel.onclick = (event) => {
      event.preventDefault();
      cleanup();
      dialog.close();
      resolve(mode === "confirm" || mode === "prompt" ? null : false);
    };
    dialog.oncancel = (event) => {
      event.preventDefault();
      cleanup();
      dialog.close();
      resolve(mode === "confirm" || mode === "prompt" ? null : false);
    };
    dialog.onclose = () => cleanup();
    dialog.showModal();
    if (mode === "prompt") setTimeout(() => input.focus(), 60);
  });
}

function appAlert(message, title = "Map App") {
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

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
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
  if (!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);
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
    el(id).classList.toggle("active", active === id);
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
  el("main").classList.toggle("panel-closed", closed);
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

async function loadLayers() {
  const data = await api("/api/tile-layers");
  const select = el("layer-select");
  select.innerHTML = "";
  for (const layer of data.local) {
    const opt = document.createElement("option");
    opt.value = `local:${layer.id}`;
    opt.textContent = `Local: ${layer.name}`;
    select.appendChild(opt);
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

function createTileLayer(value, magnifier = false) {
  const [type, id] = value.split(":");
  if (type === "local") {
    return L.tileLayer(`/tiles/${id}/{z}/{x}/{y}.png`, {
      maxZoom: 18,
      attribution: "Local MBTiles",
      detectRetina: !magnifier,
    });
  }
  const opt = [...el("layer-select").options].find((o) => o.value === value);
  const rawUrl = opt?.dataset.url || "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";
  return L.tileLayer(resolveTileUrl(rawUrl, opt?.textContent || "selected layer"), {
    maxZoom: Number(opt?.dataset.maxzoom || 19),
    attribution: opt?.dataset.attr || "",
    detectRetina: !magnifier,
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
}

function openSettings(targetId = "") {
  el("tf-api-key-input").value = localStorage.getItem("thunderforestApiKey") || "";
  el("mt-api-key-input").value = localStorage.getItem("mapTilerApiKey") || "";
  el("accent-color-input").value = localStorage.getItem("mapAppAccentColor") || currentAccentColor();
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
  const minZoom = Number(el("offline-min-zoom").value || state.map.getZoom());
  const maxZoom = Number(el("offline-max-zoom").value || state.map.getZoom());
  try {
    const data = await api("/api/download-estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentBoundsPayload(), min_zoom: minZoom, max_zoom: maxZoom }),
    });
    estimate.textContent = `${data.tiles.toLocaleString()} tiles selected. No hard limit; check data plan and disk space for large jobs.`;
    el("offline-download-btn").disabled = !data.ok;
  } catch (err) {
    estimate.textContent = err.message;
    el("offline-download-btn").disabled = true;
  }
}

function prepareOfflineSection() {
  const zoom = Math.round(state.map.getZoom());
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
  el("offline-status").textContent = `${job.status}: ${job.done}/${job.total} tiles, ${job.saved} saved, ${job.failed} failed`;
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
  const minZoom = Number(el("offline-min-zoom").value || state.map.getZoom());
  const maxZoom = Number(el("offline-max-zoom").value || state.map.getZoom());
  try {
    const job = await api("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...currentBoundsPayload(),
        min_zoom: minZoom,
        max_zoom: maxZoom,
        name: el("offline-name").value.trim() || "Offline map",
        layer_name: layer.name,
        url: layer.url,
        attribution: layer.attribution,
        format: layer.format,
      }),
    });
    el("offline-progress").hidden = false;
    el("offline-status").textContent = `Started: ${job.total} tiles.`;
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
  const restartBtn = el("restart-app-btn");
  const menuRestartBtn = el("menu-restart-btn");
  if (restartBtn) restartBtn.disabled = true;
  if (menuRestartBtn) menuRestartBtn.disabled = true;
  setHamburgerOpen(false);
  el("update-status").textContent = "Restarting Map App service...";
  try {
    await api("/api/service/restart", { method: "POST" });
    setTimeout(() => window.location.reload(), 3500);
  } catch (err) {
    if (restartBtn) restartBtn.disabled = false;
    if (menuRestartBtn) menuRestartBtn.disabled = false;
    el("update-status").textContent = `Restart failed: ${err.message}`;
  }
}

async function stopApp() {
  setHamburgerOpen(false);
  const ok = await appConfirm("Shutdown Map App? The page will stop responding until the service is started again.", "Shutdown");
  if (!ok) return;
  const stopBtn = el("stop-app-btn");
  const menuShutdownBtn = el("menu-shutdown-btn");
  if (stopBtn) stopBtn.disabled = true;
  if (menuShutdownBtn) menuShutdownBtn.disabled = true;
  el("update-status").textContent = "Stopping Map App service...";
  try {
    await api("/api/service/stop", { method: "POST" });
    el("update-status").textContent = "Map App is stopping. Start it again from the dashboard when needed.";
  } catch (err) {
    if (stopBtn) stopBtn.disabled = false;
    if (menuShutdownBtn) menuShutdownBtn.disabled = false;
    el("update-status").textContent = `Power off failed: ${err.message}`;
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
  state.map.on("zoomend", () => {
    if (state.magnifierMap && state.magnifierLatLng) {
      state.magnifierMap.setView(state.magnifierLatLng, state.map.getZoom(), { animate: false });
    }
  });
}

function bindUi() {
  applyAccentColor(localStorage.getItem("mapAppAccentColor") || DEFAULT_ACCENT);
  bindClick("markers-btn", () => setSidePanelClosed(!el("side-panel").classList.contains("closed")));
  bindClick("close-panel-btn", () => setSidePanelClosed(true));
  bindClick("add-marker-btn", () => startTool("marker"));
  bindClick("measure-btn", () => startTool("measure"));
  bindClick("draw-line-btn", () => startTool("line"));
  bindClick("draw-poly-btn", () => startTool("polygon"));
  bindClick("undo-point-btn", undoToolPoint);
  bindClick("finish-tool-btn", finishTool);
  bindClick("cancel-tool-btn", clearTool);
  el("marker-form").onsubmit = saveMarker;
  el("layer-select").onchange = (event) => setLayer(event.target.value);
  bindClick("settings-btn", toggleHamburgerMenu);
  bindClick("layer-key-save-btn", saveLayerKeys);
  bindClick("accent-save-btn", saveAccent);
  bindClick("accent-reset-btn", resetAccent);
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
  });
}

async function boot() {
  bindUi();
  initMap();
  await loadLayers();
  await Promise.all([loadMarkers(), loadDrawings()]);
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
      const date = l.mtime ? new Date(l.mtime * 1000).toLocaleString() : "-";
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
  if (!box) return;
  try {
    const data = await api("/api/downloads");
    const jobs = (data.jobs || []).filter((j) => !["done", "cancelled"].includes(j.status)).slice(0, 12);
    if (!jobs.length) {
      box.innerHTML = '<p class="field-help" style="color:var(--muted)">No queued or running jobs.</p>';
      return;
    }
    box.innerHTML = jobs.map((j) => {
      const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
      return `<div class="queue-row">
        <div class="queue-main">
          <div class="tileset-title">${esc(j.name)} <span class="queue-kind">${esc(j.kind || "download")}</span></div>
          <div class="field-help">${esc(j.status)} · ${Number(j.done || 0).toLocaleString()}/${Number(j.total || 0).toLocaleString()} tiles · ${Number(j.saved || 0).toLocaleString()} saved · ${Number(j.failed || 0).toLocaleString()} failed</div>
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
    box.innerHTML = '<p class="field-help" style="color:var(--muted)">Failed to load queue.</p>';
  }
}

function setZoomPreset(minZ, maxZ) {
  el("offline-min-zoom").value = minZ;
  el("offline-max-zoom").value = maxZ;
  updateOfflineEstimate();
}
