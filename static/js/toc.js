'use strict';

// ── Constants ─────────────────────────────────────────────────────────
const CATS = ['NOTE','SITREP','PLAN','ALERT','ACTION','COMMS','CONTACT','POSITION','INTEL','WEATHER'];

const CAT_COLORS = {
  NOTE:'#9ca3af', SITREP:'#f59e0b', PLAN:'#60a5fa', ALERT:'#ef4444',
  ACTION:'#fb923c', COMMS:'#4ade80', CONTACT:'#c084fc', POSITION:'#22d3ee',
  INTEL:'#fbbf24', WEATHER:'#7dd3fc',
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
};

// ── State ─────────────────────────────────────────────────────────────
let _entries       = [];
let _editId        = null;
let _catFilter     = 'ALL';
let _missionFilter = '';
let _searchQuery   = '';
let _missions      = [];
let _attachedGPS   = null;
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
  localStorage.setItem('tocActiveTab', name);
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

function jsSafe(s) {
  return String(s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n').replace(/\r/g, '');
}

function escAttr(s) { return esc(s); }
function jsAttr(s) { return escAttr(jsSafe(s)); }
function classToken(s) {
  return String(s || '').replace(/[^a-zA-Z0-9_-]/g, '-');
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
  loadEntries();
  loadMissions();

  // Start on last active tab, default to log
  const savedTab = localStorage.getItem('tocActiveTab') || 'log';
  showTab(savedTab);

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
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
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
  return parts.join('\n');
}

function stripMissionLine(body) {
  return String(body || '').replace(/^\*\*(?:Mission|Mission \/ Folder):\*\*[^\n]*\n?/i, '').trim();
}

async function saveEntry() {
  const body = assembleBody();
  if (!body) { toast('Body required', 'err'); return; }
  const catSel    = document.getElementById('cat-select');
  const missInput = document.getElementById('mission-input');
  const cat       = catSel ? catSel.value : 'NOTE';
  const mission   = missInput ? missInput.value.trim() : '';
  const fullBody  = mission ? `**Mission / Folder:** ${mission}\n${body}` : body;

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
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  const catSel = document.getElementById('cat-select');
  const missInput = document.getElementById('mission-input');
  if (catSel) catSel.value = e.category;
  if (missInput) missInput.value = e.mission || '';
  const body   = stripMissionLine(e.body || '');
  renderFields(e.category, parseBodyToFields(body, e.category));
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
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  const catSel = document.getElementById('cat-select');
  const missInput = document.getElementById('mission-input');
  if (catSel) catSel.value = 'NOTE';
  if (missInput) missInput.value = '';
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
  const line = document.getElementById('gps-line');
  if (line) line.style.display = 'none';
  const catSel = document.getElementById('cat-select');
  const missInput = document.getElementById('mission-input');
  if (catSel) catSel.value = e.category || 'NOTE';
  if (missInput) missInput.value = e.mission || '';
  const body = stripMissionLine(e.body || '');
  renderFields(e.category || 'NOTE', parseBodyToFields(body, e.category || 'NOTE'));
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
  if (_missionFilter) list = list.filter(e => (e.mission || '').toLowerCase() === _missionFilter.toLowerCase());
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
  const missBadge = e.mission
    ? `<span class="mission-badge" onclick="setMissionFilter('${jsAttr(e.mission)}')" title="Filter by mission">${esc(e.mission)}</span>`
    : '';
  const isEditing = _editId === e.id ? ' editing' : '';
  return `<div class="toc-entry${isEditing}" id="entry-${e.id}">
  <div class="toc-entry-header">
    <span class="toc-entry-ts">${dt}</span>
    <span class="toc-cat-badge toc-cat-${catClass}">${esc(cat)}</span>
    ${missBadge}${gpsBadge}
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
    .replace(/\*\*([^*\n]+):\*\*/g,'<span class="toc-field-key">$1:</span>')
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\n{2,}/g,'<br><br>')
    .replace(/\n/g,'<br>')
    .trim();
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

function setMissionFilter(val) {
  _missionFilter = val;
  const sel = document.getElementById('mission-filter');
  if (sel) sel.value = val;
  document.querySelectorAll('.mission-chip').forEach(c => {
    c.classList.toggle('active', c.dataset.mission === val);
  });
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
    renderMissionManager();
  } catch (_) {}
}

function renderMissionsStrip() {
  const strip = document.getElementById('missions-strip');
  if (!strip) return;
  if (!_missions.length) { strip.innerHTML = ''; return; }
  strip.innerHTML = _missions.map(m =>
    `<span class="mission-chip${_missionFilter===m.name?' active':''}"
           data-mission="${escAttr(m.name)}"
           onclick="setMissionFilter('${jsAttr(m.name)}'===_missionFilter?'':'${jsAttr(m.name)}')"
           >${esc(m.name)}<span class="mc-count">${m.count}</span
           ><button class="mc-btn" title="Rename" onclick="event.stopPropagation();renameMission('${jsAttr(m.name)}')">✎</button
           ><button class="mc-btn" title="Remove mission tag" onclick="event.stopPropagation();deleteMission('${jsAttr(m.name)}')">×</button
    ></span>`
  ).join('');
}

function renderMissionManager() {
  const list = document.getElementById('mission-manager-list');
  if (!list) return;
  if (!_missions.length) {
    list.innerHTML = '<div class="toc-empty">No missions yet. Add a Mission / Folder name in the Log composer.</div>';
    return;
  }
  list.innerHTML = _missions.map(m => {
    const cats = Object.entries(m.categories || {}).sort((a, b) => b[1] - a[1]);
    const catHtml = cats.length
      ? cats.map(([cat, n]) => `<span class="toc-cat-badge toc-cat-${classToken(cat)}">${esc(cat)} ${n}</span>`).join('')
      : '<span style="color:var(--muted)">No categories</span>';
    return `<div class="mission-card">
      <div class="mission-card-main">
        <div class="mission-card-name">${esc(m.name)}</div>
        <div class="mission-card-meta">${m.count} entr${m.count===1?'y':'ies'} · Last ${tocFormatTs(m.last_ts||0)}</div>
        <div class="mission-card-cats">${catHtml}</div>
      </div>
      <div class="mission-card-actions">
        <button class="btn small" onclick="openMission('${jsAttr(m.name)}')">View</button>
        <button class="btn small" onclick="renameMission('${jsAttr(m.name)}')">Rename</button>
        <button class="btn small danger" onclick="deleteMission('${jsAttr(m.name)}')">Remove tag</button>
      </div>
    </div>`;
  }).join('');
}

function openMission(name) {
  setMissionFilter(name);
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
  sel.innerHTML = '<option value="">All missions</option>' +
    _missions.map(m => `<option value="${esc(m.name)}">${esc(m.name)} (${m.count})</option>`).join('');
  sel.value = cur;
}

function updateMissionsDatalist() {
  const dl = document.getElementById('missions-datalist');
  if (!dl) return;
  dl.innerHTML = _missions.map(m => `<option value="${esc(m.name)}">`).join('');
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
    localStorage.setItem(sopKey(section, id), '1');
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
