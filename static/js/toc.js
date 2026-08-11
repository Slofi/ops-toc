
// app.js loads first and defines safeSetItem (quota-safe localStorage write);
// fall back locally in case that ever changes, so a full store can never crash
// a tab switch or an SOP tick. See the S404 sweep note in app.js.
function tocSetItem(key, value) {
  if (typeof safeSetItem === "function") return safeSetItem(key, value);
  try { localStorage.setItem(key, value); return true; } catch (_) { return false; }
}

'use strict';

// ── Constants ─────────────────────────────────────────────────────────
const CATS = ['NOTE','SITREP','PLAN','ALERT','ACTION','COMMS','CONTACT','POSITION','INTEL','WEATHER','TRACK'];

const CAT_COLORS = {
  NOTE:'#9ca3af', SITREP:'#f59e0b', PLAN:'#60a5fa', ALERT:'#ef4444',
  ACTION:'#fb923c', COMMS:'#4ade80', CONTACT:'#c084fc', POSITION:'#22d3ee',
  INTEL:'#fbbf24', WEATHER:'#7dd3fc', TRACK:'#e8b04f',
};

const FIELDS = {
  NOTE: null,
  SITREP: [
    {name:'Time', hint:'Time of report (e.g. 14:35)'},
    {name:'Location / Area', hint:'Site, route, grid, or operating area'},
    {name:'Situation', hint:'What is happening now', multiline:true},
    {name:'Status', hint:'Normal, degraded, blocked, urgent...'},
    {name:'Known Nodes / Assets', hint:'Nodes, teams, vehicles, stations'},
    {name:'Issues / Risks', hint:'Outages, safety issues, weather, access, interference'},
    {name:'Intent / Plan', hint:'Next steps or operating plan', multiline:true},
    {name:'Next Update', hint:'When another report is expected'},
    {name:'Notes', hint:'Extra context', multiline:true},
  ],
  PLAN: [
    {name:'Time', hint:'Plan start time or window (e.g. 09:00–17:00)'},
    {name:'Area / Route', hint:'Basecamp, route, work area, or planned collection point'},
    {name:'Objective', hint:'What should be achieved', multiline:true},
    {name:'Window / Timing', hint:'Start time, end time, update cadence, or time limit'},
    {name:'People / Assets', hint:'Operators, nodes, vehicles, stations'},
    {name:'Setup', hint:'Radios, channels, antenna, power, GPS', multiline:true},
    {name:'Checkpoints / Triggers', hint:'When to log POSITION, COMMS, CONTACT, ALERT, or SITREP', multiline:true},
    {name:'Risks / Constraints', hint:'Weather, power, access, RF path, time, safety', multiline:true},
    {name:'Comms Plan', hint:'Who to ping, where to report, fallback', multiline:true},
    {name:'Abort Criteria', hint:'When to stop, return, or switch mode'},
    {name:'Notes', hint:'Extra planning context', multiline:true},
  ],
  ALERT: [
    {name:'Time', hint:'Time of alert or event'},
    {name:'Priority', hint:'Low, medium, high, urgent'},
    {name:'Type', hint:'Safety, weather, power, comms, security, other'},
    {name:'Location', hint:'Place, grid, coordinates, or affected area'},
    {name:'Affected', hint:'Who or what is affected'},
    {name:'Details', hint:'What happened and why it matters', multiline:true},
    {name:'Immediate Action', hint:'Action already taken or needed now', multiline:true},
    {name:'Status', hint:'Open, monitoring, contained, resolved'},
    {name:'Follow-up', hint:'Who checks next and when'},
    {name:'Notes', hint:'Extra details', multiline:true},
  ],
  ACTION: [
    {name:'Time', hint:'Time assigned or scheduled'},
    {name:'Task / Action', hint:'Specific action to perform', multiline:true},
    {name:'Assigned To', hint:'Person, node, or team'},
    {name:'Location', hint:'Where the action applies'},
    {name:'Due / Time', hint:'Deadline or execution time'},
    {name:'Status', hint:'Planned, in progress, blocked, complete'},
    {name:'Result', hint:'Outcome after action', multiline:true},
    {name:'Follow-up', hint:'Next action or check-in'},
    {name:'Notes', hint:'Extra context', multiline:true},
  ],
  COMMS: [
    {name:'Time', hint:'Time of contact or check'},
    {name:'From', hint:'Calling station'},
    {name:'To', hint:'Receiving station or group'},
    {name:'Network / Channel', hint:'Channel, frequency, or room'},
    {name:'Message / Check', hint:'What was sent or tested', multiline:true},
    {name:'Signal', hint:'SNR/RSSI/readability'},
    {name:'Result', hint:'Good copy, weak, no ack, delayed, failed...'},
    {name:'Follow-up', hint:'Retry, change channel, monitor...'},
    {name:'Notes', hint:'Extra RF/path context', multiline:true},
  ],
  CONTACT: [
    {name:'Time', hint:'Time of first contact'},
    {name:'Node / Station', hint:'Node or station heard'},
    {name:'Callsign / Handle', hint:'Operator, callsign, or informal handle'},
    {name:'Network / Channel', hint:'Channel, frequency, or room'},
    {name:'Signal', hint:'SNR/RSSI/quality report'},
    {name:'Distance', hint:'Estimated distance if known'},
    {name:'Position', hint:'Coordinates, place, grid, or unknown'},
    {name:'Action / Follow-up', hint:'DM sent, pinged, added to contacts, monitor...'},
    {name:'Notes', hint:'Extra contact details', multiline:true},
  ],
  POSITION: [
    {name:'Time', hint:'Time of position fix or observation'},
    {name:'Node / Asset', hint:'Node, person, vehicle, or station'},
    {name:'Coordinates / Place', hint:'Lat/lon, grid, landmark, or route point'},
    {name:'Source', hint:'GPS, manual, report, map pick, inferred'},
    {name:'Accuracy', hint:'Exact, approximate, stale, unknown'},
    {name:'Movement / Heading', hint:'Static, moving, heading/speed if known'},
    {name:'Notes', hint:'Extra position context', multiline:true},
  ],
  INTEL: [
    {name:'Time', hint:'Time of observation or report'},
    {name:'Who / Source', hint:'Person, node, station, team, or reporting source'},
    {name:'Where / Location', hint:'Place, coordinates, grid, route, or area'},
    {name:'When Observed', hint:'Exact time, time window, or age of report'},
    {name:'What Happened', hint:'Observed activity, object, contact, change, or report', multiline:true},
    {name:'Intel Tags', hint:'Personnel, Recon, Location, Signal, Movement, Infrastructure, custom...'},
    {name:'Reliability', hint:'Confirmed, likely, possible, unconfirmed, stale'},
    {name:'Source Type', hint:'Direct observation, radio report, relay, passive RF, map, inference'},
    {name:'Assessment', hint:'Why it matters or likely meaning', multiline:true},
    {name:'Required Action', hint:'Monitor, verify, contact, avoid, dispatch, none'},
    {name:'Notes', hint:'Extra context', multiline:true},
  ],
  WEATHER: [
    {name:'Time', hint:'Time of observation'},
    {name:'Temperature', hint:'°C, feel, trend'},
    {name:'Wind', hint:'Direction, speed, gusts'},
    {name:'Conditions', hint:'Clear, overcast, fog, rain, snow...'},
    {name:'Visibility', hint:'km, good/limited/poor'},
    {name:'Precipitation', hint:'None, light rain, heavy rain, snow, hail...'},
    {name:'Pressure', hint:'hPa, rising/falling/stable'},
    {name:'Forecast', hint:'Expected changes', multiline:true},
    {name:'Notes', hint:'Extra weather context', multiline:true},
  ],
  TRACK: [
    {name:'Track', hint:'Saved GPS track name and id'},
    {name:'Distance', hint:'Track distance'},
    {name:'Points', hint:'Number of recorded points'},
    {name:'Start', hint:'Track start time'},
    {name:'End', hint:'Track end time'},
    {name:'Duration', hint:'Elapsed time (auto-calculated from timestamps)'},
    {name:'Use / Result', hint:'Patrol, route taken, search pattern, perimeter check, survey result...', multiline:true},
    {name:'Notes', hint:'Extra track context', multiline:true},
  ],
};

// ── State ─────────────────────────────────────────────────────────────
let _entries       = [];
let _editId        = null;
let _catFilter     = 'ALL';
let _missionFilter     = '';
let _missionFilterMode = ''; // '' | 'include' | 'exclude' | 'folder' | 'folder-exclude'
let _searchQuery       = '';
let _missions      = [];
let _attachedGPS    = null;
let _attachedTracks = [];
let _logTracks      = [];
let _searchTimer   = null;
let _toastTimer    = null;
let _activeTab     = 'log';

// ── Tab switching ─────────────────────────────────────────────────────
function showTab(name) {
  _activeTab = name;
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.main-tab').forEach(b => b.classList.remove('active'));
  const pane = document.getElementById('tab-' + name);
  const btn  = document.getElementById('tab-btn-' + name);
  if (pane) pane.classList.add('active');
  if (btn)  btn.classList.add('active');

  const mapTools = document.getElementById('map-tools');
  if (mapTools) mapTools.hidden = (name !== 'map');

  if (name === 'map') {
    // defer map invalidate to after display:grid is applied
    setTimeout(() => { if (typeof state !== 'undefined' && state.map) state.map.invalidateSize(); }, 60);
    initMapAndData();
  }
  tocSetItem('tocActiveTab', name);
}

// ── Toast ─────────────────────────────────────────────────────────────
function toast(msg, type) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'show ' + (type || '');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { t.className = ''; }, 2800);
}

// ── Helpers ───────────────────────────────────────────────────────────
function tocFormatTs(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return `${date}  ${time}`;
}

// jsSafe/jsAttr now live in app.js (which loads first and already provides
// esc(), on which this file has always depended). One definition, one place.
function escAttr(s) { return esc(s); }
function classToken(s) {
  return String(s || '').replace(/[^a-zA-Z0-9_-]/g, '-');
}

function parseMission(name) {
  if (!name) return { folder: null, sub: null };
  const idx = name.indexOf(' / ');
  if (idx === -1) return { folder: null, sub: name };
  return { folder: name.slice(0, idx), sub: name.slice(idx + 3) };
}

function groupMissions(missions) {
  const folders = Object.create(null);
  const standalone = [];
  for (const m of missions) {
    const p = parseMission(m.name);
    if (p.folder) {
      if (!folders[p.folder]) folders[p.folder] = { name: p.folder, count: 0, subs: [] };
      folders[p.folder].count += m.count;
      folders[p.folder].subs.push({ ...m, subName: p.sub });
    } else {
      standalone.push(m);
    }
  }
  return { folders, standalone };
}

function getMissionValue() {
  const prefix = document.getElementById('mission-folder-prefix')?.value || '';
  const input  = (document.getElementById('mission-input')?.value || '').trim();
  if (!input) return '';
  return prefix ? `${prefix} / ${input}` : input;
}

function setMissionInputs(fullName) {
  const sel = document.getElementById('mission-folder-prefix');
  const inp = document.getElementById('mission-input');
  if (!fullName) {
    if (sel) sel.value = '';
    if (inp) inp.value = '';
    return;
  }
  const p = parseMission(fullName);
  if (sel) sel.value = p.folder || '';
  if (inp) inp.value = p.sub !== null ? p.sub : fullName;
}

// ── GPS header text ───────────────────────────────────────────────────
function updateGpsHeaderText() {
  const txt = document.getElementById('gps-header-text');
  if (!txt) return;
  if (typeof _gpsState === 'undefined') return;
  if (_gpsState.fix && _gpsState.lat != null) {
    txt.textContent = `${Number(_gpsState.lat).toFixed(4)}, ${Number(_gpsState.lon).toFixed(4)}`;
  } else {
    txt.textContent = '';
  }
}

// ── Init ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  buildFilterBar();
  renderFields('NOTE');
  loadLogTracks();
  loadEntries();
  loadMissions();

  // Start on last active tab, default to log
  const tabs = new Set(['log', 'missions', 'map', 'sop', 'checklist']);
  const savedTab = localStorage.getItem('tocActiveTab') || 'log';
  if (!tabs.has(savedTab)) tocSetItem('tocActiveTab', 'log');
  showTab(tabs.has(savedTab) ? savedTab : 'log');

  // GPS header text refreshed alongside existing GPS poll
  setInterval(updateGpsHeaderText, 3500);
});

// ── Composer ──────────────────────────────────────────────────────────
function autoResizeTA(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 300) + 'px';
}

function renderFields(cat, values = {}) {
  const container = document.getElementById('composer-fields');
  if (!container) return;
  const fields = FIELDS[cat];
  if (!fields) {
    container.innerHTML = `<textarea id="body-input" class="toc-body-input" placeholder="Entry text..." oninput="autoResizeTA(this)"></textarea>`;
    const ta = container.querySelector('textarea');
    if (values._freeText) { ta.value = values._freeText; autoResizeTA(ta); }
    return;
  }
  container.innerHTML = fields.map(f => `
    <div class="toc-field-row">
      <label class="toc-field-label">${f.name}</label>
      ${f.multiline
        ? `<textarea class="toc-field-input" data-field="${escAttr(f.name)}" placeholder="${escAttr(f.hint)}" oninput="autoResizeTA(this)" rows="2"></textarea>`
        : `<input type="text" class="toc-field-input" data-field="${escAttr(f.name)}" placeholder="${escAttr(f.hint)}">`
      }
    </div>`).join('');
  for (const [k, v] of Object.entries(values)) {
    const el = container.querySelector(`[data-field="${escAttr(k)}"]`);
    if (el) { el.value = v; if (el.tagName === 'TEXTAREA') autoResizeTA(el); }
  }
}

function onCatChange() {
  _attachedGPS = null;
  _attachedTracks = [];
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  _renderTrackLine();
  const sel = document.getElementById('cat-select');
  if (sel) renderFields(sel.value);
}

function insertNow() {
  const now = new Date();
  const hhmm = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
  const el = document.querySelector('#composer-fields [data-field="Time"]');
  if (el) { el.value = hhmm; el.focus(); return; }
  const ta = document.getElementById('body-input');
  if (ta) { ta.value = (ta.value ? ta.value + '\n' : '') + hhmm; autoResizeTA(ta); }
}

function attachGPS() {
  const gpsState = (typeof _gpsState !== 'undefined') ? _gpsState : null;
  if (!gpsState || !gpsState.fix || gpsState.lat == null) {
    toast('No GPS fix', 'err'); return;
  }
  _attachedGPS = `${Number(gpsState.lat).toFixed(6)}, ${Number(gpsState.lon).toFixed(6)}`;
  const line = document.getElementById('gps-line');
  if (line) { line.style.display = ''; line.textContent = `GPS: ${_attachedGPS}`; }
  toast('GPS attached', 'ok');
}

async function loadLogTracks() {
  try {
    const r = await fetch('/api/tracks');
    if (!r.ok) return;
    _logTracks = await r.json();
    updateTrackAttachSelect();
  } catch (_) {}
}

function updateTrackAttachSelect() {
  const sel = document.getElementById('track-attach-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">+Track</option>' +
    _logTracks.map(t => `<option value="${t.id}">${esc(t.name || ('Track #' + t.id))}</option>`).join('');
  sel.value = '';
}

function syncLogTracks(tracks) {
  if (!Array.isArray(tracks)) return;
  _logTracks = tracks;
  updateTrackAttachSelect();
  if (_logView === 'tracks') renderLogTracksView();
}

// ---- LOG tab sub-view: Entries | Tracks -----------------------------------
// Tracks are a *view* under LOG — the data stays in map_app.db (not the shared
// OM toc_log). Switching just toggles which LOG-tab elements are visible.
let _logView = 'entries';
const _LOG_ENTRY_ELS = ['composer-panel', 'log-filter-bar', 'missions-strip', 'timeline'];

function showLogView(view) {
  _logView = view === 'tracks' ? 'tracks' : 'entries';
  const tracks = _logView === 'tracks';
  _LOG_ENTRY_ELS.forEach(id => {
    const e = document.getElementById(id);
    if (e) e.style.display = tracks ? 'none' : '';
  });
  const tv = document.getElementById('log-tracks-view');
  if (tv) tv.style.display = tracks ? '' : 'none';
  document.querySelectorAll('#log-subnav .log-subnav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.view === _logView);
  });
  if (tracks) { if (!_logTracks.length) loadLogTracks().then(renderLogTracksView); else renderLogTracksView(); }
}

function renderLogTracksView() {
  const box = document.getElementById('log-tracks-view');
  if (!box) return;
  const tracks = Array.isArray(_logTracks) ? _logTracks.slice() : [];
  if (!tracks.length) {
    box.innerHTML = `<div class="log-tracks-empty">No saved tracks yet. Record one from the MAP tab.</div>`;
    return;
  }
  tracks.sort((a, b) => (b.ended_at || b.started_at || 0) - (a.ended_at || a.started_at || 0));
  box.innerHTML = tracks.map(t => {
    const dur = (t.started_at && t.ended_at && t.ended_at > t.started_at) ? fmtDuration(t.ended_at - t.started_at) : '';
    const meta = [fmtLogTrackDistance(t.distance_m || 0), dur, t.started_at ? fmtLogTrackTime(t.started_at) : ''].filter(Boolean).join(' · ');
    const nStops = Array.isArray(t.stops) ? t.stops.length : 0;
    const hasReport = t.report && Object.keys(t.report).length > 0;
    const badges = [];
    if (nStops) badges.push(`<span class="log-track-badge">${nStops} stop${nStops !== 1 ? 's' : ''}</span>`);
    if (hasReport) badges.push(`<span class="log-track-badge report">debrief</span>`);
    return `<div class="log-track-row">
      <div class="log-track-main">
        <div class="log-track-name">${esc(t.name || ('Track #' + t.id))}</div>
        <div class="log-track-meta">${esc(meta)}${badges.length ? ' ' + badges.join(' ') : ''}</div>
      </div>
      <div class="log-track-actions">
        <button class="btn small" onclick="showTrackDebrief(${t.id})">Debrief</button>
        <button class="btn small" onclick="createLogFromTrack(${t.id})">Log</button>
        <button class="btn small" onclick="_logTrackShow(${t.id})">Map</button>
      </div>
    </div>`;
  }).join('');
}

function _logTrackShow(id) {
  if (typeof showTab === 'function') showTab('map');
  if (typeof flyToTrack === 'function') flyToTrack(id);
}

function fmtLogTrackDistance(meters) {
  const n = Number(meters || 0);
  if (!Number.isFinite(n)) return '0 m';
  if (typeof fmtDistance === 'function') return fmtDistance(n);
  return n < 1000 ? `${Math.round(n)} m` : `${(n / 1000).toFixed(2)} km`;
}

function fmtLogTrackTime(ts) {
  return ts ? tocFormatTs(ts) : '';
}

function fmtDuration(secs) {
  if (!secs || secs <= 0) return '';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, '0')}s`;
  return `${s}s`;
}

function trackLogFields(track) {
  const points = track.point_count ?? (Array.isArray(track.points) ? track.points.length : 0);
  const dur = (track.started_at && track.ended_at && track.ended_at > track.started_at)
    ? fmtDuration(track.ended_at - track.started_at) : '';
  return {
    Track: `${track.name || 'GPS track'} (#${track.id})`,
    Distance: fmtLogTrackDistance(track.distance_m || 0),
    Points: String(points),
    Start: fmtLogTrackTime(track.started_at),
    End: fmtLogTrackTime(track.ended_at),
    Duration: dur,
  };
}

function _enrichTrack(t) {
  const full = _logTracks.find(lt => Number(lt.id) === Number(t.id));
  if (!full) return t;
  return {
    id: full.id,
    name: full.name || t.name,
    distance_m: full.distance_m || 0,
    points: full.point_count ?? (Array.isArray(full.points) ? full.points.length : 0),
    started_at: full.started_at || null,
    ended_at: full.ended_at || null,
  };
}

function _updateTrackFormFields() {
  const catSel = document.getElementById('cat-select');
  if (!catSel || catSel.value !== 'TRACK') return;
  if (!_attachedTracks.length) return;
  const totalDist = _attachedTracks.reduce((s, t) => s + (t.distance_m || 0), 0);
  const totalPts  = _attachedTracks.reduce((s, t) => s + (t.points || 0), 0);
  const starts    = _attachedTracks.map(t => t.started_at).filter(Boolean);
  const ends      = _attachedTracks.map(t => t.ended_at).filter(Boolean);
  const earliest  = starts.length ? Math.min(...starts) : null;
  const latest    = ends.length   ? Math.max(...ends)   : null;
  const n = _attachedTracks.length;
  const setFld = (name, val) => {
    const el = document.querySelector(`#composer-fields [data-field="${escAttr(name)}"]`);
    if (el) el.value = val;
  };
  setFld('Track', n === 1
    ? `${_attachedTracks[0].name} (#${_attachedTracks[0].id})`
    : `${n} tracks`);
  setFld('Distance', fmtLogTrackDistance(totalDist));
  setFld('Points', String(totalPts));
  setFld('Start', earliest ? fmtLogTrackTime(earliest) : '');
  setFld('End', latest ? fmtLogTrackTime(latest) : '');
  setFld('Duration', (earliest && latest && latest > earliest)
    ? fmtDuration(latest - earliest) : '');
}

function setAttachedTrack(track, opts = {}) {
  if (!track) return;
  if (_attachedTracks.some(t => t.id === track.id)) {
    toast('Track already attached', 'err'); return;
  }
  const isFirst = _attachedTracks.length === 0;
  _attachedTracks.push({
    id: track.id,
    name: track.name || 'GPS track',
    distance_m: track.distance_m || 0,
    points: track.point_count ?? (Array.isArray(track.points) ? track.points.length : 0),
    started_at: track.started_at || null,
    ended_at: track.ended_at || null,
  });
  if (isFirst) {
    const catSel = document.getElementById('cat-select');
    if (catSel) catSel.value = 'TRACK';
    renderFields('TRACK', { ...trackLogFields(track), ...(opts.values || {}) });
  }
  _updateTrackFormFields();
  _renderTrackLine();
  const sel = document.getElementById('track-attach-select');
  if (sel) sel.value = '';
}

function _renderTrackLine() {
  const line = document.getElementById('track-line');
  if (!line) return;
  if (!_attachedTracks.length) { line.style.display = 'none'; return; }
  const label = _attachedTracks.length === 1 ? 'Track:' : 'Tracks:';
  const items = _attachedTracks.map((t, i) =>
    `<span class="track-attach-item"
      ><button class="btn small" type="button" onclick="openLogTrack(${t.id})">${esc(t.name)}</button
      ><button class="btn small danger track-remove-btn" type="button" onclick="removeAttachedTrack(${i})" title="Remove track">×</button
    ></span>`
  ).join('');
  line.style.display = '';
  line.innerHTML = `<span class="track-attach-label">${label}</span>${items}`;
}

function removeAttachedTrack(idx) {
  _attachedTracks.splice(idx, 1);
  _updateTrackFormFields();
  _renderTrackLine();
}

async function attachTrackFromSelect(sel) {
  const id = Number(sel?.value || 0);
  if (!id) return;
  if (!_logTracks.length) await loadLogTracks();
  const track = _logTracks.find(t => Number(t.id) === id);
  if (!track) { toast('Track not found', 'err'); return; }
  setAttachedTrack(track);
  toast('Track attached', 'ok');
}

async function createLogFromTrack(id) {
  if (typeof showLogView === 'function') showLogView('entries');  // composer is hidden in Tracks view
  if (!_logTracks.length) await loadLogTracks();
  let track = _logTracks.find(t => Number(t.id) === Number(id));
  if (!track && typeof state !== 'undefined' && state.tracks) track = state.tracks.get(Number(id));
  if (!track) { toast('Track not found', 'err'); return; }
  _editId = null;
  _attachedGPS = null;
  _attachedTracks = [];
  const gpsLine = document.getElementById('gps-line');
  if (gpsLine) gpsLine.style.display = 'none';
  setAttachedTrack(track);
  if (track.folder && !getMissionValue()) setMissionInputs(track.folder);
  const title = document.getElementById('composer-title');
  const cancel = document.getElementById('btn-cancel-edit');
  const panel = document.getElementById('composer-panel');
  if (title) title.textContent = 'New Track Entry';
  if (cancel) cancel.style.display = 'none';
  showTab('log');
  if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function parseTracksFromBody(body) {
  const out = [];
  const re = /\*\*Track:\*\*\s*([^\n#(]*?)\s*\(#(\d+)\)/gi;
  let m;
  while ((m = re.exec(body)) !== null) {
    out.push({ name: m[1].trim() || 'GPS track', id: Number(m[2]) });
  }
  return out;
}

function parseBodyToFields(body, cat) {
  const fields = FIELDS[cat];
  if (!fields) return { _freeText: body };
  const values = {};
  const lines = body.split('\n');
  let key = null, buf = [];
  for (const line of lines) {
    const m = line.match(/^\*\*(.+?):\*\*\s*(.*)/);
    if (m) {
      if (key) values[key] = buf.join('\n').trim();
      key = m[1]; buf = [m[2]];
    } else if (key) {
      buf.push(line);
    }
  }
  if (key) values[key] = buf.join('\n').trim();
  return values;
}

function assembleBody() {
  const catSel = document.getElementById('cat-select');
  const cat = catSel ? catSel.value : 'NOTE';
  const fields = FIELDS[cat];
  if (!fields) {
    return document.getElementById('body-input')?.value.trim() || '';
  }
  const parts = [];
  document.querySelectorAll('#composer-fields [data-field]').forEach(el => {
    const val = el.value.trim();
    if (val) parts.push(`**${el.dataset.field}:** ${val}`);
  });
  if (_attachedGPS) parts.push(`**GPS:** ${_attachedGPS}`);
  if (_attachedTracks.length > 0) {
    if (cat === 'TRACK') {
      // Remove the auto-populated Track field ("N tracks" label) and replace with individual lines
      const ti = parts.findIndex(p => /^\*\*Track:\*\*/i.test(p));
      if (ti !== -1) parts.splice(ti, 1);
      parts.unshift(..._attachedTracks.map(t => `**Track:** ${t.name} (#${t.id})`));
    } else {
      for (const t of _attachedTracks) {
        parts.unshift(`**Track:** ${t.name} (#${t.id})`);
      }
    }
  }
  return parts.join('\n');
}

function stripMissionLine(body) {
  return String(body || '').replace(/^\*\*(?:Mission|Mission \/ Folder):\*\*[^\n]*\n?/i, '').trim();
}

async function saveEntry() {
  const body = assembleBody();
  if (!body) { toast('Body required', 'err'); return; }
  const catSel  = document.getElementById('cat-select');
  const cat     = catSel ? catSel.value : 'NOTE';
  const mission = getMissionValue();
  const fullBody = mission ? `**Mission / Folder:** ${mission}\n${body}` : body;

  const url    = _editId ? `/api/log/entries/${_editId}` : '/api/log/entries';
  const method = _editId ? 'PUT' : 'POST';
  const payload = { category: cat, body: fullBody };
  if (_editId) {
    const orig = _entries.find(x => x.id === _editId);
    if (orig) payload.ts = orig.ts; // preserve original timestamp on edit
  }
  try {
    const r = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) { toast(d.error || 'Error saving', 'err'); return; }
    toast(_editId ? 'Entry updated' : 'Entry saved', 'ok');
    cancelEdit();
    loadEntries();
    loadMissions();
  } catch (_) { toast('Network error', 'err'); }
}

function editEntry(id) {
  const e = _entries.find(x => x.id === id);
  if (!e) return;
  _editId = id;
  _attachedGPS = null;
  _attachedTracks = [];
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  const catSel = document.getElementById('cat-select');
  if (catSel) catSel.value = e.category;
  setMissionInputs(e.mission || '');
  const body   = stripMissionLine(e.body || '');
  renderFields(e.category, parseBodyToFields(body, e.category));
  _attachedTracks = parseTracksFromBody(body).map(_enrichTrack);
  _renderTrackLine();
  const title  = document.getElementById('composer-title');
  const cancel = document.getElementById('btn-cancel-edit');
  const panel  = document.getElementById('composer-panel');
  if (title)  title.textContent = `Edit #${id}`;
  if (cancel) cancel.style.display = '';
  if (panel)  { panel.classList.add('editing'); panel.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}

function cancelEdit() {
  _editId = null;
  _attachedGPS = null;
  _attachedTracks = [];
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  _renderTrackLine();
  const catSel = document.getElementById('cat-select');
  if (catSel) catSel.value = 'NOTE';
  setMissionInputs('');
  renderFields('NOTE');
  const title  = document.getElementById('composer-title');
  const cancel = document.getElementById('btn-cancel-edit');
  const panel  = document.getElementById('composer-panel');
  if (title)  title.textContent = 'New Entry';
  if (cancel) cancel.style.display = 'none';
  if (panel)  panel.classList.remove('editing');
}

async function deleteEntry(id) {
  const ok = await appDialog({ title: 'Delete Entry', message: 'Delete this entry?', mode: 'confirm' });
  if (!ok) return;
  try {
    const r = await fetch(`/api/log/entries/${id}`, { method: 'DELETE' });
    if (!r.ok) { toast('Error deleting', 'err'); return; }
    toast('Deleted', 'ok');
    if (_editId === id) cancelEdit();
    loadEntries();
    loadMissions();
  } catch (_) { toast('Error deleting', 'err'); }
}

function duplicateEntry(id) {
  const e = _entries.find(x => x.id === id);
  if (!e) return;
  _editId = null;
  _attachedGPS = null;
  _attachedTracks = [];
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  const catSel = document.getElementById('cat-select');
  if (catSel) catSel.value = e.category || 'NOTE';
  setMissionInputs(e.mission || '');
  const body = stripMissionLine(e.body || '');
  renderFields(e.category || 'NOTE', parseBodyToFields(body, e.category || 'NOTE'));
  _attachedTracks = parseTracksFromBody(body).map(_enrichTrack);
  _renderTrackLine();
  const title  = document.getElementById('composer-title');
  const cancel = document.getElementById('btn-cancel-edit');
  const panel  = document.getElementById('composer-panel');
  if (title)  title.textContent = `Duplicate #${id}`;
  if (cancel) cancel.style.display = '';
  if (panel)  { panel.classList.remove('editing'); panel.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}

// ── Entries ───────────────────────────────────────────────────────────
async function loadEntries() {
  try {
    const r = await fetch('/api/log/entries');
    _entries = await r.json();
    renderEntries();
  } catch (_) {}
}

function renderEntries() {
  let list = _entries;
  if (_catFilter && _catFilter !== 'ALL') list = list.filter(e => e.category === _catFilter);
  if (_missionFilter) {
    const fl = _missionFilter.toLowerCase();
    if (_missionFilterMode === 'folder') {
      list = list.filter(e => {
        const ml = (e.mission || '').toLowerCase();
        return ml === fl || ml.startsWith(fl + ' / ');
      });
    } else if (_missionFilterMode === 'folder-exclude') {
      list = list.filter(e => {
        const ml = (e.mission || '').toLowerCase();
        return ml !== fl && !ml.startsWith(fl + ' / ');
      });
    } else if (_missionFilterMode === 'exclude') {
      list = list.filter(e => (e.mission || '').toLowerCase() !== fl);
    } else {
      list = list.filter(e => (e.mission || '').toLowerCase() === fl);
    }
  }
  if (_searchQuery) {
    const q = _searchQuery.toLowerCase();
    list = list.filter(e => e.body.toLowerCase().includes(q));
  }
  const tl = document.getElementById('timeline');
  if (!tl) return;
  if (!list.length) {
    tl.innerHTML = '<div class="toc-empty">No entries match the current filters.</div>';
    return;
  }
  tl.innerHTML = list.map(renderEntry).join('');
}

function renderEntry(e) {
  const dt  = tocFormatTs(e.ts);
  const cat = e.category || 'NOTE';
  const catClass = classToken(cat);
  const hasGps = e.lat != null;
  const gpsBadge = hasGps
    ? `<span class="has-gps-badge" title="Has GPS">⊙ GPS</span>`
    : '';
  const trackBadge = e.track_id
    ? `<span class="track-log-badge" onclick="openLogTrack(${Number(e.track_id)})" title="Open saved track">trk #${Number(e.track_id)}</span>`
    : '';
  const missBadge = e.mission
    ? `<span class="mission-badge" onclick="setMissionFilter('${jsAttr(e.mission)}')" title="Filter by mission">${esc(e.mission)}</span>`
    : '';
  const isEditing = _editId === e.id ? ' editing' : '';
  return `<div class="toc-entry${isEditing}" id="entry-${e.id}">
  <div class="toc-entry-header">
    <span class="toc-entry-ts">${dt}</span>
    <span class="toc-cat-badge toc-cat-${catClass}">${esc(cat)}</span>
    ${missBadge}${gpsBadge}${trackBadge}
    <div class="toc-entry-actions">
      <button class="btn small" onclick="editEntry(${e.id})">Edit</button>
      <button class="btn small" onclick="duplicateEntry(${e.id})">Dup</button>
      <button class="btn small danger" onclick="deleteEntry(${e.id})">Del</button>
    </div>
  </div>
  <div class="toc-entry-body">${renderBody(e.body)}</div>
</div>`;
}

function renderBody(body) {
  if (!body) return '<em style="color:var(--muted)">—</em>';
  return body
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(Mission|Mission \/ Folder):\*\*[^\n]*\n?/gi, '')
    .replace(/\*\*GPS:\*\*[^\n]*\n?/g, '')
    .replace(/\*\*Track:\*\*\s*([^\n#]*?)\s*\(#(\d+)\)\n?/gi,
      (_, name, id) => `<div class="log-track-ref"><span class="toc-field-key">Track:</span> ${name.trim() || 'GPS track'} <button class="btn small" onclick="openLogTrack(${Number(id)})">Open track</button></div>`)
    .replace(/\*\*([^*\n]+):\*\*/g,'<span class="toc-field-key">$1:</span>')
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\n{2,}/g,'<br><br>')
    .replace(/\n/g,'<br>')
    .trim();
}

async function openLogTrack(id) {
  const trackId = Number(id);
  if (!trackId) return;
  showTab('map');
  try {
    if (typeof initMapAndData === 'function') initMapAndData();
    if (typeof loadTracks === 'function') await loadTracks();
    if (typeof state !== 'undefined' && state.trackVisible) state.trackVisible.set(trackId, true);
    if (typeof flyToTrack === 'function') setTimeout(() => flyToTrack(trackId), 120);
  } catch (_) {
    toast('Could not open track', 'err');
  }
}

// ── Filters ───────────────────────────────────────────────────────────
function buildFilterBar() {
  const row = document.getElementById('cat-filter-row');
  if (!row) return;
  row.innerHTML = ['ALL', ...CATS].map(c =>
    `<button class="toc-cat-filter${c==='ALL'?' active':''}" data-cat="${c}"
             onclick="setCatFilter('${c}',this)">${c}</button>`
  ).join('');
}

function setCatFilter(cat, el) {
  _catFilter = cat;
  document.querySelectorAll('.toc-cat-filter').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
  renderEntries();
}

function cycleMissionFilter(name) {
  if (_missionFilter !== name) {
    _missionFilter = name;
    _missionFilterMode = 'include';
  } else if (_missionFilterMode === 'include') {
    _missionFilterMode = 'exclude';
  } else {
    _missionFilter = '';
    _missionFilterMode = '';
  }
  const sel = document.getElementById('mission-filter');
  if (sel) sel.value = _missionFilter;
  renderMissionsStrip();
  renderEntries();
}

function setMissionFilter(val) {
  _missionFilter = val;
  _missionFilterMode = val ? 'include' : '';
  const sel = document.getElementById('mission-filter');
  if (sel) sel.value = val;
  renderMissionsStrip();
  renderEntries();
}

function cycleFolderFilter(folderName) {
  if (_missionFilter !== folderName || !_missionFilterMode.startsWith('folder')) {
    _missionFilter = folderName;
    _missionFilterMode = 'folder';
  } else if (_missionFilterMode === 'folder') {
    _missionFilterMode = 'folder-exclude';
  } else {
    _missionFilter = '';
    _missionFilterMode = '';
  }
  const sel = document.getElementById('mission-filter');
  if (sel) sel.value = _missionFilter;
  renderMissionsStrip();
  renderEntries();
}

function debounceSearch(val) {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => { _searchQuery = val; renderEntries(); }, 250);
}

// ── Missions ──────────────────────────────────────────────────────────
async function loadMissions() {
  try {
    const r = await fetch('/api/log/missions');
    _missions = await r.json();
    renderMissionsStrip();
    updateMissionSelect();
    updateMissionsDatalist();
    updateFolderPrefixSelect();
    renderMissionManager();
  } catch (_) {}
}

function renderMissionsStrip() {
  const strip = document.getElementById('missions-strip');
  if (!strip) return;
  if (!_missions.length) { strip.innerHTML = ''; return; }

  const { folders, standalone } = groupMissions(_missions);
  let html = '';

  for (const folder of Object.values(folders)) {
    const isFolder  = _missionFilter === folder.name && _missionFilterMode === 'folder';
    const isFolderX = _missionFilter === folder.name && _missionFilterMode === 'folder-exclude';
    const cls = isFolder ? ' active' : isFolderX ? ' exclude' : '';
    const tip = isFolder ? 'Click to exclude folder' : isFolderX ? 'Click to clear filter' : 'Filter by folder';
    html += `<div class="folder-group">`;
    html += `<span class="mission-chip folder-chip${cls}"
      data-folder="${escAttr(folder.name)}"
      onclick="cycleFolderFilter('${jsAttr(folder.name)}')"
      title="${tip}"
      ><span class="mc-folder-icon">▸</span
      ><span class="mc-label">${esc(folder.name)}</span
      ><span class="mc-count">${folder.count}</span
    ></span>`;
    html += `<div class="sub-chips">`;
    for (const sub of folder.subs) {
      const isInclude = _missionFilter === sub.name && _missionFilterMode === 'include';
      const isExclude = _missionFilter === sub.name && _missionFilterMode === 'exclude';
      const scls = isInclude ? ' active' : isExclude ? ' exclude' : '';
      html += `<span class="mission-chip sub-chip${scls}"
        data-mission="${escAttr(sub.name)}"
        onclick="cycleMissionFilter('${jsAttr(sub.name)}')"
        title="${esc(sub.subName)}"
        ><span class="mc-label">${esc(sub.subName)}</span
        ><span class="mc-count">${sub.count}</span
        ><button class="mc-btn" title="Rename" onclick="event.stopPropagation();renameMission('${jsAttr(sub.name)}')">✎</button
        ><button class="mc-btn" title="Remove tag" onclick="event.stopPropagation();deleteMission('${jsAttr(sub.name)}')">×</button
      ></span>`;
    }
    html += `</div></div>`;
  }

  for (const m of standalone) {
    const isInclude = _missionFilter === m.name && _missionFilterMode === 'include';
    const isExclude = _missionFilter === m.name && _missionFilterMode === 'exclude';
    const cls = isInclude ? ' active' : isExclude ? ' exclude' : '';
    const tip = isInclude ? 'Click to exclude this mission' : isExclude ? 'Click to clear filter' : 'Filter by mission';
    html += `<span class="mission-chip${cls}"
      data-mission="${escAttr(m.name)}"
      onclick="cycleMissionFilter('${jsAttr(m.name)}')"
      title="${tip}"
      ><span class="mc-label">${esc(m.name)}</span><span class="mc-count">${m.count}</span
      ><button class="mc-btn" title="Rename" onclick="event.stopPropagation();renameMission('${jsAttr(m.name)}')">✎</button
      ><button class="mc-btn" title="Remove mission tag" onclick="event.stopPropagation();deleteMission('${jsAttr(m.name)}')">×</button
    ></span>`;
  }

  strip.innerHTML = html;
}

function _missionCardHtml(m, name, isSubCard) {
  const cats = Object.entries(m.categories || {}).sort((a, b) => b[1] - a[1]);
  const catHtml = cats.length
    ? cats.map(([cat, n]) => `<span class="toc-cat-badge toc-cat-${classToken(cat)}">${esc(cat)} ${n}</span>`).join('')
    : '<span style="color:var(--muted)">No categories</span>';
  const cardCls = isSubCard ? 'mission-card sub-mission-card' : 'mission-card';
  return `<div class="${cardCls}">
    <div class="mission-card-main">
      <div class="mission-card-name">${esc(name)}</div>
      <div class="mission-card-meta">${m.count} entr${m.count===1?'y':'ies'} · Last ${tocFormatTs(m.last_ts||0)}</div>
      <div class="mission-card-cats">${catHtml}</div>
    </div>
    <div class="mission-card-actions">
      <button class="btn small" onclick="openMission('${jsAttr(m.name)}')">View</button>
      <button class="btn small" onclick="renameMission('${jsAttr(m.name)}')">Rename</button>
      <button class="btn small danger" onclick="deleteMission('${jsAttr(m.name)}')">Remove tag</button>
    </div>
  </div>`;
}

function renderMissionManager() {
  const list = document.getElementById('mission-manager-list');
  if (!list) return;
  if (!_missions.length) {
    list.innerHTML = '<div class="toc-empty">No missions yet. Add a Mission / Folder name in the Log composer.</div>';
    return;
  }

  const { folders, standalone } = groupMissions(_missions);
  let html = '';

  for (const folder of Object.values(folders)) {
    html += `<div class="mission-folder-group">
      <div class="mission-folder-header">
        <div class="mission-folder-title">
          <span class="mission-folder-icon">▸</span>
          ${esc(folder.name)}
          <span class="mission-folder-count">${folder.count} total</span>
        </div>
        <div class="mission-folder-actions">
          <button class="btn small" onclick="openFolderFilter('${jsAttr(folder.name)}')">View all</button>
        </div>
      </div>`;
    for (const sub of folder.subs) {
      html += _missionCardHtml(sub, sub.subName, true);
    }
    html += `</div>`;
  }

  for (const m of standalone) {
    html += _missionCardHtml(m, m.name, false);
  }

  list.innerHTML = html;
}

function openMission(name) {
  setMissionFilter(name);
  showTab('log');
}

function openFolderFilter(folderName) {
  _missionFilter = folderName;
  _missionFilterMode = 'folder';
  const sel = document.getElementById('mission-filter');
  if (sel) sel.value = folderName;
  renderMissionsStrip();
  renderEntries();
  showTab('log');
}

async function renameMission(name) {
  const newName = await appDialog({
    title: 'Rename Mission',
    message: `Rename "${name}" to:`,
    mode: 'prompt',
    value: name,
  });
  if (!newName || newName.trim() === name) return;
  try {
    const r = await fetch('/api/log/missions/rename', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_name: name, new_name: newName.trim() }),
    });
    const d = await r.json();
    if (!r.ok) { toast(d.error || 'Rename failed', 'err'); return; }
    if (_missionFilter === name) _missionFilter = newName.trim();
    toast(`Renamed — ${d.updated} entr${d.updated===1?'y':'ies'} updated`, 'ok');
    loadEntries();
    loadMissions();
  } catch (_) { toast('Network error', 'err'); }
}

async function deleteMission(name) {
  const ok = await appDialog({
    title: 'Remove Mission Tag',
    message: `Remove mission tag "${name}" from all entries? Entries are kept, only the tag is removed.`,
    mode: 'confirm',
  });
  if (!ok) return;
  try {
    const r = await fetch('/api/log/missions/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const d = await r.json();
    if (!r.ok) { toast(d.error || 'Delete failed', 'err'); return; }
    if (_missionFilter === name) _missionFilter = '';
    toast(`Tag removed from ${d.updated} entr${d.updated===1?'y':'ies'}`, 'ok');
    loadEntries();
    loadMissions();
  } catch (_) { toast('Network error', 'err'); }
}

function updateMissionSelect() {
  const sel = document.getElementById('mission-filter');
  if (!sel) return;
  const cur = sel.value;
  const { folders, standalone } = groupMissions(_missions);
  let html = '<option value="">All missions</option>';
  for (const folder of Object.values(folders)) {
    html += `<optgroup label="▸ ${esc(folder.name)} (${folder.count})">`;
    for (const sub of folder.subs) {
      html += `<option value="${esc(sub.name)}">${esc(sub.subName)} (${sub.count})</option>`;
    }
    html += '</optgroup>';
  }
  for (const m of standalone) {
    html += `<option value="${esc(m.name)}">${esc(m.name)} (${m.count})</option>`;
  }
  sel.innerHTML = html;
  sel.value = cur;
}

function updateMissionsDatalist() {
  const dl = document.getElementById('missions-datalist');
  if (!dl) return;
  const { folders, standalone } = groupMissions(_missions);
  const options = [];
  for (const folder of Object.values(folders)) {
    for (const sub of folder.subs) {
      options.push(`<option value="${esc(sub.subName)}">`);
    }
  }
  for (const m of standalone) {
    options.push(`<option value="${esc(m.name)}">`);
  }
  dl.innerHTML = options.join('');
}

function updateFolderPrefixSelect() {
  const sel = document.getElementById('mission-folder-prefix');
  if (!sel) return;
  const { folders } = groupMissions(_missions);
  const cur = sel.value;
  sel.innerHTML = '<option value="">No folder</option>' +
    Object.keys(folders).map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join('');
  if (Object.keys(folders).includes(cur)) sel.value = cur;
}

// ── Log import ────────────────────────────────────────────────────────
async function doLogImport() {
  const textarea = document.getElementById('log-import-input');
  const status   = document.getElementById('log-import-status');
  if (!textarea) return;
  const raw = textarea.value.trim();
  if (!raw) { toast('Paste data first', 'err'); return; }
  if (status) status.textContent = 'Importing…';
  try {
    const r = await fetch('/api/log/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: raw }),
    });
    const d = await r.json();
    if (!r.ok) {
      if (status) status.textContent = d.error || 'Error';
      toast(d.error || 'Import failed', 'err');
      return;
    }
    if (status) status.textContent = `Imported ${d.imported}`;
    toast(`Imported ${d.imported} entries`, 'ok');
    textarea.value = '';
    loadEntries();
    loadMissions();
  } catch (_) {
    if (status) status.textContent = 'Error';
    toast('Network error', 'err');
  }
}

// ── SOP ───────────────────────────────────────────────────────────────

const SOP_SECTIONS = ['activate','depart','enroute','arrival','static-open','static-close','comms-down','rc-run'];

function sopKey(section, id) { return 'sop.' + section + '.' + id; }

function sopUpdate(cb) {
  const section = cb.dataset.section;
  const id = cb.dataset.id;
  if (cb.checked) {
    tocSetItem(sopKey(section, id), '1');
  } else {
    localStorage.removeItem(sopKey(section, id));
  }
  cb.closest('.sop-item').classList.toggle('done', cb.checked);
  sopRefreshSection(section);
}

function sopRefreshSection(section) {
  const checks = document.querySelectorAll(`.sop-check[data-section="${section}"]`);
  if (!checks.length) return;
  const total = checks.length;
  const done = Array.from(checks).filter(c => c.checked).length;
  const fill = document.getElementById('sop-fill-' + section);
  const text = document.getElementById('sop-text-' + section);
  const sec  = document.getElementById('sop-sec-' + section);
  if (fill) fill.style.width = (total ? (done / total * 100) : 0) + '%';
  if (text) text.textContent = done + '/' + total;
  if (sec)  sec.classList.toggle('complete', done === total && total > 0);
}

function sopReset(section) {
  document.querySelectorAll(`.sop-check[data-section="${section}"]`).forEach(cb => {
    localStorage.removeItem(sopKey(section, cb.dataset.id));
    cb.checked = false;
    cb.closest('.sop-item').classList.remove('done');
  });
  sopRefreshSection(section);
}

function sopResetAll() {
  SOP_SECTIONS.forEach(sopReset);
}

function sopToggle(section) {
  const body = document.getElementById('sop-body-' + section);
  const head = body && body.previousElementSibling;
  if (!body) return;
  const hidden = body.hasAttribute('hidden');
  body.toggleAttribute('hidden', !hidden);
  if (head) head.classList.toggle('collapsed', !hidden);
}

function sopInit() {
  document.querySelectorAll('.sop-check').forEach(cb => {
    const section = cb.dataset.section;
    const id = cb.dataset.id;
    if (localStorage.getItem(sopKey(section, id))) {
      cb.checked = true;
      cb.closest('.sop-item').classList.add('done');
    }
  });
  SOP_SECTIONS.forEach(sopRefreshSection);
}

document.addEventListener('DOMContentLoaded', sopInit);
