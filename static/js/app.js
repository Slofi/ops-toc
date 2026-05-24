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
};

const el = (id) => document.getElementById(id);

function fmtDistance(meters) {
  if (!Number.isFinite(meters)) return "0 m";
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(meters < 10000 ? 2 : 1)} km`;
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
  el("finish-tool-btn").hidden = !state.tool || state.toolPoints.length < 2;
  el("cancel-tool-btn").hidden = !state.tool;
  el("measure-card").classList.toggle("show", state.tool === "measure");
}

function clearTool() {
  state.toolMarkers.forEach((m) => state.map.removeLayer(m));
  state.toolMarkers = [];
  if (state.toolLine) state.map.removeLayer(state.toolLine);
  state.toolLine = null;
  state.toolPoints = [];
  state.tool = null;
  setBanner("");
  setToolButtons(null);
}

function startTool(tool) {
  clearTool();
  state.tool = tool;
  if (tool === "marker") setBanner("Tap map to place a marker");
  if (tool === "measure") setBanner("Tap points for the ruler. Drag points to adjust.");
  if (tool === "line") setBanner("Tap points for a line, then Finish.");
  if (tool === "polygon") setBanner("Tap area corners, then Finish.");
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
    state.toolLine = L.polyline(latlngs, { color: state.tool === "measure" ? "#4ade80" : "#f59e0b", weight: 3 }).addTo(state.map);
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
  const color = state.tool === "measure" ? "#4ade80" : "#f59e0b";
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

async function finishTool() {
  if (!state.tool || state.toolPoints.length < 2) return;
  if (state.tool === "measure" || state.tool === "line" || state.tool === "polygon") {
    const kind = state.tool === "measure" ? "measure" : state.tool;
    const name = prompt("Name this drawing:", kind === "measure" ? "Ruler path" : kind === "polygon" ? "Area" : "Line");
    if (name === null) return;
    try {
      await api("/api/drawings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim() || kind,
          kind,
          color: kind === "measure" ? "#4ade80" : "#f59e0b",
          data: { points: state.toolPoints },
        }),
      });
      clearTool();
      await loadDrawings();
    } catch (err) {
      alert(err.message);
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
  if (!marker || !confirm(`Delete marker "${marker.name}"?`)) return;
  await api(`/api/markers/${id}`, { method: "DELETE" });
  await loadMarkers();
}

async function shareMarkerLater(id) {
  try {
    await api(`/api/om/share-marker/${id}`, { method: "POST" });
  } catch (err) {
    alert(`${err.message}\n\nThis is intentional for v0.1: Map owns markers, OM integration comes next.`);
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
  if (!drawing || !confirm(`Delete drawing "${drawing.name}"?`)) return;
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
    select.appendChild(opt);
  }
  const saved = localStorage.getItem("mapAppLayer");
  select.value = saved && [...select.options].some((o) => o.value === saved)
    ? saved
    : (select.options[0]?.value || "online:voyager");
  setLayer(select.value);
}

function setLayer(value) {
  if (state.baseLayer) state.map.removeLayer(state.baseLayer);
  const [type, id] = value.split(":");
  if (type === "local") {
    state.baseLayer = L.tileLayer(`/tiles/${id}/{z}/{x}/{y}.png`, {
      maxZoom: 18,
      attribution: "Local MBTiles",
    }).addTo(state.map);
  } else {
    const opt = [...el("layer-select").options].find((o) => o.value === value);
    state.baseLayer = L.tileLayer(opt?.dataset.url || "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      maxZoom: Number(opt?.dataset.maxzoom || 19),
      attribution: opt?.dataset.attr || "",
    }).addTo(state.map);
  }
  localStorage.setItem("mapAppLayer", value);
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
}

function bindUi() {
  el("markers-btn").onclick = () => el("side-panel").classList.toggle("closed");
  el("close-panel-btn").onclick = () => el("side-panel").classList.add("closed");
  el("add-marker-btn").onclick = () => startTool("marker");
  el("measure-btn").onclick = () => startTool("measure");
  el("draw-line-btn").onclick = () => startTool("line");
  el("draw-poly-btn").onclick = () => startTool("polygon");
  el("finish-tool-btn").onclick = finishTool;
  el("cancel-tool-btn").onclick = clearTool;
  el("marker-form").onsubmit = saveMarker;
  el("layer-select").onchange = (event) => setLayer(event.target.value);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.tool) clearTool();
    if (event.key === "Enter" && state.tool && state.toolPoints.length >= 2) finishTool();
  });
}

async function boot() {
  bindUi();
  initMap();
  await loadLayers();
  await Promise.all([loadMarkers(), loadDrawings()]);
}

boot().catch((err) => alert(err.message));
