type:: project
status:: active
tags:: #ops-toc #map-app #leaflet #offline-maps #field-log #cyberdeck
updated:: 2026-07-11

# OPS-TOC

> OPS-TOC is the Cyberdeck's main map-management and field-operations app. It owns markers, drawings, GPS tracks, offline tile downloads, LOG, MISSIONS, SOP, and CHECKLIST. Shared tile DB feeds Sonde App, OM, and future apps.

> **📇 Quick-reference card → [[ops-toc-overview]]** (`ops-toc-overview.md`)
> Crucial info / Quick Commands / Troubleshooting-Recovery live in the card (for Filip + Haskill).
> This file = full context, decisions & changelog (for Claude).

## Access

| Resource | Value |
|----------|-------|
| App URL  | http://localhost:8090 (on CD) |
| Lite URL | http://localhost:8090/lite — compact touch UI for HD 5" screen (same backend/JS, `lite.css` skin) |
| App path | ~/Projects/ops-toc/ |
| Service  | systemctl --user start/stop/restart ops-toc |

## Key Paths

| Item | Path |
|------|------|
| App | ~/Projects/ops-toc/app.py |
| Template | ~/Projects/ops-toc/templates/index.html |
| JS | ~/Projects/ops-toc/static/js/app.js |
| CSS | ~/Projects/ops-toc/static/css/app.css |
| Venv | ~/Projects/ops-toc/venv/ |
| Service | ~/.config/systemd/user/ops-toc.service |
| DB | ~/maps/map_app.db |
| MBTiles | ~/maps/mbtiles/ |
| Shared log DB | ~/overmesh/overmesh_prefs.db (`toc_log`) |

## Current Integration

- OPS-TOC owns all map-specific controls: markers, drawings, GPS tracks, offline downloads, and downloaded-map management.
- OPS-TOC owns the standalone field workflow: LOG, MISSIONS, SOP, and CHECKLIST tabs.
- CHECKLIST is pure frontend state in localStorage key `ops_toc_checklists`. It supports folders, multiple editable checklists, progress bars, reset, item reorder, text/JSON export, and import from JSON/TXT/MD. In Markdown: H1 sets the folder, H2+ creates checklists, `- [ ]`/`- [x]` are items. Field test checklist: `~/Projects/ops-toc/TEST/field-test-checklist.md`. See CHECKLIST System section in Full Reference for full format spec and authoring guide.
- LOG/MISSIONS read and write OM's shared `toc_log` table directly in `~/overmesh/overmesh_prefs.db`.
- OM and OPS-TOC now share the same TOC category set, including `WEATHER`.
- `log-app.service` / standalone TOC-app is retired, stopped, and disabled.
- `ops-toc.service` is the manual/Dashboard-controlled OPS-TOC service and is not enabled at boot.
- Map data remains intentionally split: markers/drawings/tracks stay in `~/maps/map_app.db`; OM may consume map data read-only later but should not co-own map edit controls.
- CD GPS receiver is the u-blox GNSS USB device. OPS-TOC owns it directly (`gps_config.json`: enabled true, port `auto`, `om_proxy=false`).
- 2026-06-09 field boot issue: `gpsd` auto-claimed `/dev/ttyACM0`, making OPS-TOC show "Device or resource busy". Persistent fix applied: `gpsd.service` and `gpsd.socket` are now masked to `/dev/null` on the CD.
- GPS port selection defaults to `auto`: OPS-TOC scans USB-serial devices, matches USB product/manufacturer strings against a GPS/GNSS keyword list (u-blox, GNSS, GPS, Beitian, Garmin, …), and resolves the match to its `/dev/serial/by-id/*` symlink. Works on either CD USB-A socket and across dongle swaps without reconfiguration. Manual override (a specific by-id or raw device) still available in GPS settings.

**made by Codex — start**

- The MAP toolbar now includes a `Live` operational-overlay panel for OverMesh nodes, ADS-B aircraft, AIS vessels, and radiosondes. Offline specialist apps are shown grey with disabled toggles; running apps expose persisted display toggles and source/decoder status.
- OPS-TOC consumes specialist-app data read-only through local adapters. OM still owns all MT/MC state and transmissions; OPS-TOC's node popups proxy DM and position/status requests back through OM so Silent Running and radio-specific behavior remain authoritative there.
- Live-object popups include source details and a structured `Log` action. MC contacts heard by multiple radios are deduplicated for the map, and stale/archived mesh positions are faded.
- ADS-B markers update in place through a keyed Leaflet marker registry rather than being destroyed/recreated each poll; overlay polling is guarded against overlapping cycles. This fixed the intermittent lag/display-loss behavior and was confirmed by Filip on the Cyberdeck on 2026-07-11.
- Operational-overlay implementation and changelog were pushed to OPS-TOC `master` as commit `4d2b267` (`Add operational map overlays`) on 2026-07-11.

**made by Codex — end**

**[Claude] 2026-07-13 — overlay performance & robustness pass (frontend only, backend proxy untouched):**
- The in-place keyed-marker registry (ADS-B only until now) is **shared by all sources**. AIS, OverMesh (MT/MC contacts/radios), and Sonde previously cleared and rebuilt their whole marker group every cycle (OM rebuilt ~283 positioned markers every 15 s); all now update markers in place and remove only what left the feed.
- Removed the global "freeze all overlays while any popup is open" workaround (it also leaned on Leaflet's private `map._popup`). The open popup's marker is tracked via public `popupopen`/`popupclose` events and left untouched during refresh, so one open popup no longer pauses the other sources.
- **Viewport culling:** every marker stays in the in-memory registry, but only those within a padded viewport are added to the map layer; pan/zoom re-flows membership with no network fetch. Disable via `OVERLAY_CULL` in `app.js` (`OVERLAY_CULL_PAD` = margin).
- **Sonde TTL:** the accumulating radiosonde stream drops objects with no telemetry for 30 min (`SONDE_TTL_SEC`) via a per-update sweep + 30 s timer, so landed/dead sondes stop lingering. Poll feeds (OM/AIS/ADS-B) already self-expire via their `active` lists.

**[Claude] 2026-07-13 — Comms panel (Phase 1, read-only):**
- New toolbar `Comms` button opens a **right-side drawer** over the map showing OverMesh messages as threads: MT + MC **channels and DMs**, master-detail (thread list → message view), unread badges, chat bubbles, polled every 4 s only while open.
- Backend proxy `GET /api/comms/messages` fans out to OM (MT `/api/chat/messages` + `/api/chat/channels`; each connected MC radio's `/api/mc/<id>/messages`), normalized + threaded client-side. **Read-only — OM owns the radios & Silent Running.** MC's live `/channels` query (~30 s device call) is intentionally not used; MC channels are labelled `CHn` from the message index.
- Verified live: 345 messages correctly threaded (MT channel names resolve; MC channels CH0–2; MT+MC DMs). Frontend rendering pending an on-CD browser check.
- MC channel names now resolve to real names (lazy background-cached device query, 30-min TTL — shows `CHn` only until the first fetch completes). Thread list is split by network (Meshtastic/MeshCore × Channels/Direct). Remaining minor gap: MC DM peers with no stored name still show their hex key.
- **Phase 2 (reply composer) DONE:** in-thread composer proxies sends via `POST /api/comms/send` (MT `/api/chat/send`; MC `/send_chan` / `/send_dm`). OM owns TX + Silent Running — composer greys proactively via the `silent` flag (`/api/silent_mode`) and surfaces OM's 409. First live send confirmed by Filip (MC channel). **Phase 3a (map↔comms link) DONE:** OM node popups → "💬 Comms" button opens that node's DM thread (synthesizes + pins an empty thread if none yet, so you can start a DM from the map). **Also fixed OM** so MC sends broadcast to OM's own UI live (`push_to_sse` in `routes/mc.py`; OM restarted on CD). **Phase 3b (live SSE) DONE → Phase 3 COMPLETE:** same-origin SSE proxy `GET /api/comms/stream` relays OM's `/api/chat/stream`; frontend EventSource uses it as a "refresh now" trigger (debounced `loadComms()`) so the 4s poll stays source-of-truth and a dropped SSE degrades to the poll. Proven non-blocking (Flask threaded; concurrent reqs ~0.08s while SSE held). New MT/MC messages now appear ~sub-second.

## Pending

**made by Codex — start**

- **Live-overlay remaining field check:** Filip confirmed the OverMesh and ADS-B overlays working in the live Cyberdeck browser on 2026-07-11. AIS and Sonde still need validation while their source apps are active. Actual OM DM/position/status transmission buttons were intentionally not test-fired during development.

**made by Codex — end**

- **[Claude] Overlay performance pass (2026-07-13) needs a live browser check on the CD** — especially viewport culling (markers appear/disappear correctly on pan/zoom, nothing important hidden) and the in-place updates for AIS/OM/Sonde. Escape hatch if culling ever hides something it shouldn't: set `OVERLAY_CULL = false` in `app.js` (one line, reload the tab). Folds into the still-open AIS/Sonde source validation above.

- **Internal GPS (BN-280 on UART3 /dev/ttyS3) is electrically working but reception is flickery.** Confirmed 2026-06-30: OPS-TOC must use explicit `/dev/ttyS3`; `auto` only follows USB GPS dongles. Morning balcony test produced a real direct fix (`fix=true`, `lat=46.039179`, `lon=14.497671`, `alt=302`, `sats=8`, `sats_view=13`). Evening balcony retest in the same place showed no fix and `sats_view=0`, while an exclusive serial baud sweep confirmed the module was still emitting clean NMEA at 9600 (`$GNRMC`, `$GNGGA`, `$GPGSV`, `$GLGSV`) with fix quality 0 and zero satellites. Current interpretation: not dead and not an OPS-TOC parser/config issue; likely RF/antenna orientation/case/noise/placement sensitivity or intermittent module behavior.

- **MapTiler Topo offline — Slovenia z9–16:** Subscribe to MT Flex ($25/month), open OPS-TOC on CD, confirm MapTiler API key is set (Settings → Keys), start MT Topo z9–16 download for Slovenia. ~899k tiles, ~$65 total ($25 base + ~$40 extra at $0.10/1000). Should finish in a few hours with 16-worker downloader. Copy `.mbtiles` to HD via rsync when done. Cancel Flex subscription after. File lands at `~/maps/mbtiles/` — works immediately with mbtileserver on both CD and HD.

- **Backend track recording — THE top open item. Spec sharpened 2026-08-10 (Claude, code-verified):**
  **Mechanism (why it fails):** `gps.py` already owns the device server-side and Flask serves `/api/gps` — that half is fine. But the *recording* lives in the page: the browser polls `/api/gps` on a timer and, inside that same poll handler (`app.js:5252`), calls `captureGpsPoint()`, which filters the point and pushes it onto a **JS array in the tab's memory**, mirrored to `localStorage` (`ops_toc_active_track`). On Save the browser POSTs the whole array to `/api/tracks`. **So the browser's poll cycle IS the recording loop** — no rendered page (tab closed, browser crash, device asleep, app switched) = no points.
  ⚠️ **Why it's invisible when it happens:** `gps.py` carries on serving `/api/gps` to everything else, so **OM Lite still shows a moving marker** and the whole system looks healthy. A moving marker proves the GPS works; it says NOTHING about whether anything is writing a track. That's what cost the first 27 km of the 2026-07-07 drive home.
  **The fix:** a recorder loop inside Flask appending points to `map_app.db` while recording is on; frontend becomes start/stop/status + viewer. Well-bounded because every hard piece exists already (`gps.py` reads, `_gps_payload()` shapes, `/api/tracks` writes) — what's missing is the loop between them.
  🔴 **The trap, name it before anyone builds:** the filters (multipath rejection, minimum-movement gate, interval throttle) currently live INSIDE `captureGpsPoint()` in JS. Do **not** copy them into Python and leave the JS copies in place — that is exactly how Mesh-Torry got a frontend soldier-upkeep calculation that had drifted from the backend's (showed 4 where 1 was charged; fixed by adding `GET /soldiers/upkeep` so both share one implementation). **Backend owns filtering + recording; frontend only displays.** Two implementations of "is this point real?" will agree today and diverge later.
  Original note:  recording currently lives in the browser page (`captureGpsPoint()` in app.js + localStorage) — no open/rendered OPS-TOC page = no recording, even though the GPS backend runs and feeds other apps (a moving marker on OM Lite ≠ recording; this cost the first 27km of the 07-07 drive home). Move recording into the Flask backend: service appends points to DB while recording is on, survives browser/tab/restart; frontend becomes start/stop/status + viewer. Well-bounded: backend recorder thread + API + frontend switch. Candidate for Codex or a dedicated session.
- **Recording filter bugs found in the 07-07 track data:** (1) ✅ FIXED 2026-07-11 — multipath jump rejection (`spd<5 && dist>50`) now catches the 9.4 km parked jumps the old `dist/dt>100` test missed; (2) ✅ FIXED 2026-07-11 — minimum-movement gate (GPS `speed<3` km/h, or `dist<3` fallback) stops parked jitter-distance accumulation; (3) ✅ RESOLVED 2026-07-11 (different approach) — Filip rejected auto-stop/auto-save (fragments trips, risks false-positive on a jam/stakeout). Instead the **after-action report now separates moving vs stopped**: Total time / Moving / Stopped (+ stop count) / Moving avg, added to the track summary popup. Stops classified via real GPS speed (<1 km/h ≈ at rest; a run counts as a discrete stop at ≥60s). Recording stays continuous — no auto-stop.

- **OPS-TOC Lite on HD — deploy steps (do at device):** `git pull` on HD, open `http://localhost:8090/lite` in the fullscreen browser window. Interim (while HD still runs 1920×1080): set ~185% page zoom (Ctrl++, Vivaldi remembers per-site) so the CSS viewport is ~1024×600. Proper fix (fold into the hand-deck openbox kiosk session): drive the panel at native 1024×600 — mode is NOT in its HDMI mode list, needs a custom modeline (`cvt 1024 600` → `xrandr --newmode` + `--addmode HDMI-1`), then crisp 1:1 pixels and no zoom workaround.
- Decide whether to support PMTiles in addition to MBTiles
- Add KML import/export
- Add marker categories, filters, and styling
- Add route profile / segment list for ruler paths
- Add optional GPS marker endpoint once CD/HD GPS source is decided
- Add per-source throttling/concurrency settings and clearer retry/backoff behavior
- Add cleanup/repair tool for orphan `.part` files and corrupt MBTiles
- Later: OM consumes Map App markers read-only
- Later: optional "Share via OM" mesh broadcast action for selected markers, separate from local sync
- Later: **Search pattern generator** — define a polygon area → auto-generate systematic coverage route (grid/spiral/sector) → export as GPX track. Ref: Fields2Cover algorithm (github.com/Fields2Cover/Fields2Cover). Use case: search & rescue, area clearing, field survey. Found 2026-06-09.

## Changelog

**2026-07-17** — [Claude] **Track Debrief (after-action report + annotatable stops) — backend done & API-verified, frontend awaiting on-CD browser check.** New per-track "Debrief": general-purpose flavour with a light field-ops edge (not "tactical", per Filip). *Data model (map_app.db, JSON-blob style like points_json):* two new `tracks` columns via try/except ALTER — `report_json` (`{purpose,summary,outcome,followup,activity}`) and `stops_json` (array of `{seq,start_ts,end_ts,duration_s,lat,lon,note,tag}`). Also **fixed a latent gap**: `_clean_track_points` was stripping `speed` (captureGpsPoint stores it) → saved tracks fell back to derived speed; now persisted, so moving/stopped stats + stop detection are accurate on reload. *Stops:* materialized server-side at save from the point list via `_detect_stops()` (STOP_KMH=1, MIN_STOP_S=60 — mirrors app.js `trackStats` so counts agree); notes/tags added later. *Endpoints:* POST/PUT `/api/tracks` accept `report` + `stops` (PUT preserves stop notes; re-detects only if points change); new `POST /api/tracks/<id>/detect-stops` = non-persisting re-scan (preview) so a re-detect never clobbers annotations before Save. *Frontend:* optional collapsed "Report" `<details>` in the save dialog (fast field-save unaffected; shows "N stops detected"); a **Debrief dialog** (stats header + report fields + editable **stop timeline** with per-stop note/tag + "Map" jump + markdown Export) opened via a new "Debrief" button in the track popup. app.js/toc.js `node --check` OK, app.py `py_compile` OK. **Verified end-to-end via live API** (create→auto-stop+report, detect-stops preview, PUT note/tag+outcome persist, GET reflects, speed kept, cleanup). **Phase 4 DONE too — "Tracks" sub-view inside the LOG tab:** new `Entries | Tracks` sub-nav at the top of the LOG tab (`showLogView()` in toc.js just toggles which LOG elements show — composer/filter/missions/timeline vs `#log-tracks-view`); the Tracks list reads `_logTracks` (already synced from `/api/tracks`), newest-first, each row = name + dist/dur/time + `N stops`/`debrief` badges + Debrief/Log/Map buttons. **Data stays in map_app.db — nothing moved into OM's shared toc_log** (the approved link approach); `createLogFromTrack` now forces Entries view first (composer is hidden in Tracks view). No `?v=` cache-bust on app.js/app.css here → hard-reload a stale tab. **2026-08-10 (S402, Claude) — BACKEND NOW VERIFIED ON CD ITSELF, not just TestBox.** CD was powered on; `ops-toc.service` is a **user** service and is **disabled** (it does not auto-start — the CD Dashboard tile launches it), so this code had never actually executed on CD. Started it and tested against the real `~/maps/map_app.db`: save-time stop materialisation ✅ (synthetic track with a deliberate 90 s park → 1 stop, `duration_s=89`), report stored ✅, `speed` persisted on points ✅ (the `_clean_track_points` fix holds), stop note/tag via PUT persists ✅, non-persisting `/detect-stops` preview writes nothing ✅. Test track deleted — **62 tracks before and after**. Also: the preview returned **0 stops** for real track 66 and that is CORRECT — independently recomputed the same rule (1 km/h, 60 s) over its 4757 points: an 87-minute continuous drive with no stationary run ≥60 s (only 33/4756 segments under 1 km/h). ⚠️ `/api/tracks/<id>` has no GET route (405) — the list endpoint returns full tracks including points. **STILL PENDING: on-CD browser validation** — the save-dialog Report section, the Debrief dialog (render/edit stop-timeline/export), and the LOG→Tracks sub-view. **Not committed/pushed yet — awaiting Filip's browser test**, then reconcile the stale overview card (`updated:: 2026-07-11`, `latest pushed 061847a`) + commit.
**2026-07-11** — [Claude] **Dynamic zoom rings.** New "Dynamic zoom rings" toggle in Range Rings settings (`opsTocRingsDynamic`, default off). When on, finer close-range rings (from the sequence 500/250/100/50/25/10 m) fade in as you zoom closer and disappear when you zoom out, on top of the configured base rings. A fine ring shows only once its on-screen radius exceeds `_RINGS_DYN_MIN_PX` (45 px) and only if it's finer than the base `_ringsStep`; drawn dashed/thinner as secondary. `_drawRangeRings()` now redraws on `zoomend` when dynamic is active (draw-key includes zoom so the 3s poll still skips redundant redraws). At 46°N/5 km base step: 500m ≈ z13.5, +250m z14.5, +100m z16, +50m z17. Toggle is in the shared template so it appears on Lite too. `node --check` OK. Committed & pushed (`cbe1c99`).
**2026-07-11** — [Claude] **After-action moving/stopped breakdown.** Track summary popup (`trackStats` + `renderTrackPopup`) now shows Total time / Moving / Stopped (+ discrete-stop count) / Moving avg alongside distance & max. Segments classified stopped at `<1 km/h` (≈ at rest / zero — 1 not a literal 0 because a parked GPS blips <1 km/h Doppler noise); a contiguous stopped run counts as a discrete stop only at `≥60s` (all stopped seconds still sum into Stopped regardless). Uses real per-point GPS speed (`segmentSpeeds()`), so accuracy is sharp on new recordings; older tracks fall back to jittery derived speed and under-report discrete stops. Filip's design: NO auto-stop/auto-save — recording stays continuous, stops are just *reported*. `node --check` OK; math verified against tracks 47/48. Committed & pushed (`ee2001e`).
**2026-07-11** — [Claude] **Real GPS speed everywhere (root-cause fix for the jumping speed badge + recording filters).**
- *The bug:* upper-right speed badge jumped (cruise at 60 → drop to ~20 → spike to ~82) even with clean GPS on the roof dongle. Cause: `gps.py` only parsed GGA/GSV and **threw away RMC/VTG**, so `app.js` faked speed as Δposition ÷ Δt using the *browser* capture clock — decoupled from the GPS fix epochs. That aliases: a poll window catching one GPS epoch halves the speed, one catching two doubles it (why 2s→1s didn't help). Proven against tracks 48/49 ("from work I/II"): positions clean, but derived speed swung 20↔100 at steady cruise.
- *Backend (`gps.py`):* now parses `$xxRMC`/`$xxVTG` → real Doppler speed-over-ground exposed as `speed` (km/h) in `/api/gps`; u-blox init also enables VTG; OM-proxy forwards `speed`. Verified live on CD parked: steady 0.0 km/h (old method jittered fake motion).
- *HUD (`app.js`):* badge uses `d.speed` directly; position-delta kept only as a de-aliased fallback (recomputes only on real movement).
- *Recording (`app.js` `captureGpsPoint`):* each point now stores `speed`. Added **multipath rejection** (`spd<5 && dist>50` → drop — catches the parked 9.4 km jumps the old `dist/dt>100` test missed across time gaps) and a **minimum-movement gate** (stationary = `speed<3` km/h, or `dist<3` when speed unknown → refresh last point's time instead of accumulating jitter distance). Measured: removes ~1275 m of sub-5m jitter from the 77 km track 47.
- *Chart/stats (`app.js`):* new `segmentSpeeds()` helper prefers each point's stored GPS speed, falls back to position-delta for older tracks — so the track speed chart + max-speed stat now reflect true GPS speed.
- *Also in this commit:* the previously-uncommitted Lite "position-instruments pod" (`#pos-cluster` — docks speed HUD + GPS follow button on-map for the in-car Lite UI; scoped to `window.OPS_TOC_LITE`/`.hd-lite`, no effect on the normal UI). Our prior-session work, committed together at Filip's request.
- Verified: `py_compile` gps.py/app.py, `node --check` app.js, live `/api/gps` speed sampling. Requires a **browser reload** for the frontend to take effect. Committed & pushed to `Slofi/ops-toc` master 2026-07-11.
**2026-07-07** — [Claude] OPS-TOC Lite added: `/lite` route serves the same template with `hd_lite` flag → `lite.css` skin + `window.OPS_TOC_LITE` (BASE_UI_SCALE 1.0). Same backend, same app.js — deliberately NOT a fork (OM/OM-Lite drift lesson). Compact frosted toolbar (GPS + Track kept per Filip), overlay side panel, touch-sized rows/inputs, viewport-capped scrollable dropdowns + dialogs. **HD display myth corrected via EDID:** panel = MPI5005, native 1024×600; it DOWNSCALES 1920×1080 input (everything visible at ~53% size) — it does not crop. June 30 revert post-mortem: built on the wrong crop premise. Deploy steps in Pending.
**2026-07-06** — [Claude] venv rebuilt on CD (python3.12) after cross-machine Syncthing contamination (HD's python3.9 venv synced over during the paused-folder recovery — flask import broke). venvs now Syncthing-ignored on CD+TestBox; never sync venvs. Service verified: HTTP 200, /api/gps responding.
**2026-06-30** — Internal BN-280 GPS diagnosis corrected and refined. The receiver is not dead: direct `/dev/ttyS3` balcony test produced a real fix with 8 satellites used / 13 in view. Later same-balcony retest dropped back to `sats_view=0`; raw UART confirmed clean NMEA at 9600 but the GPS itself reported no satellites. Treat as flickery RF/placement/module behavior. Keep OPS-TOC configured to explicit `/dev/ttyS3`; `auto` is USB-only.
**2026-06-28** — Track chart overhaul: removed toolbar Discard button (Stop dialog only); fixed SVG text deformation on panel resize (dynamic viewBox re-render); 2-pass median filter eliminates GPS jitter spikes; 20%/10% headroom on speed/altitude; time axis with 5-min ticks (4 styles: hour/half/quarter/5-min); scrub tooltip bubble on both charts simultaneously; red dot + scrub line on both charts; timestamp-based X positioning throughout.
**2026-06-23** — Internal Cyberdeck GPS (Rock 5B UART3 /dev/ttyS3): `gps.py` lists it as first-class source, `port_present()` handles ttyS* via filesystem check, u-blox NMEA init also enables UART1. README + API docs updated.
**2026-06-23** — Styled full-page shutdown splash: big "OPS-TOC" in accent, restart command, Dashboard hint. Commit `417734d`
**2026-06-23** — GPS source fix also committed to docs. Commit `312b4df`
**2026-06-23** — Marker folder/sub-folder support: markers now group by `Parent / Sub` folder hierarchy in the left panel, same UX as tracks. Folder field in Add/Edit dialog with autocomplete datalist. New folders auto-collapse. State persisted separately from track folders. DB migration adds `folder` column to markers table. `a3c38dc`. *(recovered 2026-07-06 from paused-sync TestBox copy)*
**2026-06-22** — GPS enabled flag bug fixed: `api_gps_set()` defaulting `enabled=False` on absent key — silenced any partial settings save. Commit `abc69a2`.

**2026-06-18** — Touch targets: sub-chips 10→11px font, 2→4px vertical padding; mc-btn (rename/delete) 13px, 28×28px min tap area. Commit `ffd8a6c`.
**2026-06-18** — Multi-track stats: `_updateTrackFormFields()` combines Distance/Points/Start/End/Duration across all attached tracks. Duration field added to TRACK template. `assembleBody()` outputs individual `**Track:** name (#id)` lines, not the "N tracks" label. `_enrichTrack()` restores full data from `_logTracks` on edit. Commit `61ac8d4`.
**2026-06-18** — Multiple tracks per log entry: `_attachedTracks[]` replaces single track; first track sets TRACK category/fields, subsequent append to bar with × remove buttons; dedup check; `parseTracksFromBody()` restores on edit. Commit `41212b1`.
**2026-06-18** — Track sub-folders: ` / ` separator in track `folder` field; two-level collapsible track list; save/edit dialog uses prefix select + sub-folder input. Commit `310af31`.
**2026-06-18** — Cardinal directions on range rings: Off/4/8 toggle; dashed spoke lines from position center to ring edge; N/S/E/W/NE/NW/SE/SW letter labels at 1.18× outerKm. Dialog close bug fixed (`type="button"`), localStorage init bug fixed.
**2026-06-18** — Mission sub-folders: ` / ` separator convention; folder groups with sub-chips in strip; prefix select + name input in composer; cycleFolderFilter(), folder-exclude mode, Mission Manager tree view.
**2026-06-18** — UI zoom: `BASE_UI_SCALE` reduced 1.15 → 1.09; 100% no longer overflows 1920×1200 screen (speed HUD was partially off-screen). Commit `19c97da`.
**2026-06-18** — Checklist import: H1 now sets folder context (no more "Imported" default for MD files), H2+ creates checklist cards, dividers/plain text skipped. Round-trip with OPS-TOC text export preserved. `ad39768`.
**2026-06-18** — CHECKLIST tab added (Codex): editable CHECKLIST tab after SOP, with localStorage persistence (`ops_toc_checklists`), folders/types, collapsible checklist cards, rename/delete/reset, progress counts/bars, item add/edit/delete/toggle/reorder, text/JSON export, and import from JSON/TXT/MD. Removed the temporary "Load field templates" button and cleaned out the backend `/api/checklists/seed` route, since Import now covers saved/template files. Copied Desktop test checklist files into repo `TEST/` without removing the Desktop originals. Header clock now shows 24h time with seconds and date in `DD.MM.YY`. Settings/App Control UI was enlarged for touch. In-app UI Zoom now has a built-in 1.15x base scale so visible `100%` matches the user's previous `115%`; old saved `115%` is migrated to `100%` once.

**2026-06-16** — Three-state mission chip toggle in LOG tab: click cycles all → include (teal) → exclude (red/strikethrough) → all. Entry badge clicks land in include mode. `a3ac0c4`. *(recovered 2026-07-06 from paused-sync TestBox copy)*
**2026-06-16** — Fixed GPS port conflict: OPS-TOC's `gps_config.json` had the NRF52840 (MT node) saved as GPS port instead of the u-blox dongle. Root cause of no-fix was port contention: OM and OPS-TOC both trying to read `/dev/ttyACM2` simultaneously. Fix: disabled OM GPS to release port, changed OPS-TOC config to `port: "auto"` (auto-detects u-blox correctly). Also filtered `list_ports()` in `gps.py` to exclude `ttyS*` internal serial ports (not USB, not GPS). Port dropdown in Settings → GPS is already present (visible when "Direct serial" is selected). Running `fix: true`, 12 sats. Not committed yet.

**2026-06-15** — Compact toolbar for 5" screens (≤1024px): Tools ▾ dropdown consolidates Markers/Ruler/Draw/GPS/Track; brand text hidden; GPS moved into dropdown. Layers panel touch-scrollable (`max-height` + `overflow-y: auto` + `-webkit-overflow-scrolling`). Git auth fix in service: explicit SSH key + BatchMode + no prompt. `gps.py` Python 3.9 compat (`from __future__ import annotations`). Parallel tile downloader restored (accidentally reverted, fixed). HD deployment: git HTTPS remote initialized, in-app update working. `cf5b312`, `ecf9ff5`, `b69dceb`, `40edbff`, `78a3be4`. *(recovered 2026-07-06 from paused-sync TestBox copy)*

**2026-06-14** — Parallelized tile downloader (16 workers, 64-tile batches, ~33× speedup: 1.57 → ~52 tiles/s). `af00804`.

**2026-06-12** — Offline map hub and controls polish pushed to GitHub (`4d33754 Improve offline maps and controls`). OPS-TOC now shows estimated download size for offline map jobs, estimates zoom extensions before queueing, avoids queueing zero-tile extensions, and can rename downloaded MBTiles maps through the UI/API. Zoom extension jobs now repair/copy the existing MBTiles into the `.part` file before adding missing zooms, so editing a downloaded map cannot replace it with only the new zoom range. Missing-tile estimation was optimized to avoid per-tile DB lookups. Completed/cancelled/error download jobs no longer carry large payloads in API responses. App controls now have click/press feedback animations. GPS settings were tidied with an iPhone-style receiver switch. Restart and shutdown buttons now show black service splash screens: `OPS-TOC restarting...` and `OPS-TOC offline. Start it back up from the Dashboard!`. Verified with JS syntax check, Python compile check, `git diff --check`, service restart, empty download queue check, and live extend estimate.

**2026-06-09** — GPS auto-detect: added `detect_gps_port()` which scans `/dev/ttyACM*` and `/dev/ttyUSB*` devices, matches USB product/manufacturer strings against a GPS/GNSS keyword list (u-blox, gnss, gps, beitian, garmin, navilock, holux, globalsat, skytraq, mtk, sirf, navigation), and resolves the match to a `/dev/serial/by-id/*` symlink for persistence. Falls back to the only device present when no keyword matches. New synthetic `"auto"` entry leads the `/api/gps/ports` dropdown (label shows the currently-detected device). `gps_config.json` defaults to `port: "auto"`, so swapping dongles or sockets needs no reconfiguration. Manual override still works (any by-id or raw device path). Verified: u-blox detected automatically, fix true, 12 sats used.

**2026-06-09** — GPS detection socket-independent: `list_ports()` returns both raw `/dev/tty*` devices and their stable `/dev/serial/by-id/*` symlinks, with by-id entries listed first and labeled "(stable, recommended)". `port_present()` resolves symlinks before comparing against detected ports. Persistent fix for `gpsd` reclaiming the port applied via `sudo systemctl mask --now gpsd.service gpsd.socket`. Verified live: direct source, by-id port, fix true, 12 sats used / 13 in view.

**2026-06-09** — CD field boot fix: OPS-TOC was showing GPS port busy on `/dev/ttyACM0`. Root cause was system `gpsd` auto-start/udev ownership of the u-blox receiver (`SYSTEMD_WANTS=gpsdctl@ttyACM0.service` and `gpsd.service` running). Stopped `gpsd.service` + `gpsd.socket`, disabled `gpsd.socket`, restarted `ops-toc.service`, and verified OPS-TOC direct GPS live on `/dev/ttyACM0` with fix true, 12 sats used / 14 in view. (Persistent mask applied later same day — see entry above.)

**2026-06-09** — Fixed lower-left empty trace-review popup: `#track-chart-panel` starts with the `hidden` attribute in HTML, but its CSS set `display:flex`, overriding browser hidden behavior and leaving an empty chart panel visible on the map before any track popup was opened. Added `#track-chart-panel[hidden] { display: none !important; }` and clear chart title/body in `hideTrackChart()` so stale trace-review content cannot flash. Also kept transparent `errorTileUrl` fallback for local/online Leaflet tile failures as defensive cleanup. JS syntax check passed with `node --check static/js/app.js`; OPS-TOC restarted.

**2026-06-06** — GPS recording: added speed-based outlier rejection (drops points implying >100 m/s = 360 km/h, catching GPS jumps) and minimum 4-satellite requirement. Prevents erratic jumps in recorded tracks caused by brief signal loss/re-acquisition.

**2026-06-05** — Track UX overhaul: removed Discard toolbar button (now only accessible via Save dialog); replaced sequential appPrompt stop flow with a single Save Track dialog (name + folder + colour swatches + custom colour input, Discard option when stopping). Track list now groups tracks by folder with collapsible headers. Track Edit dialog includes name, folder, and colour. Markers and Add Marker buttons consolidated into a Markers ▾ dropdown. App-dialog buttons made larger for touch.

**2026-06-04** — Fixed track naming on mobile: `onclose` (backdrop-tap path) was returning null instead of `input.value`, silently discarding the typed name. `b8c4499`.
**2026-06-04** — Fixed track stop dialog: name input now hidden during confirm step (CSS `hidden` attribute override by `label{display:block}` — switched to `style.display`). Track end markers changed from plain squares to SVG teardrop location-pin shape. GPS port scan now shows device names (`ttyACM1 — u-blox GNSS receiver`) via sysfs. GPS port-row visibility fixed same way as dialog. pyserial added to requirements.txt. GPS configured on ttyACM1 (was wrongly set to ttyACM2 — mapping shifted). Added Restart confirmation dialog. `9e221b7`, `3f30627`, `fd5e8c5`.
**2026-06-03** — Fixed track save dialog never resolving on mobile (backdrop tap fires only `onclose`, not `oncancel`, leaving the promise hung). Added `settled` guard + `onclose` now always resolves promise. Auto-save with default name when dialog is dismissed; banner notifies user. Added **Discard** button (red, toolbar, visible only during recording) with confirm before discarding live recording. Committed `c45e38e`, pushed to GitHub.
**2026-06-03** — Git repo consolidated: `~/Projects/ops-toc/` is now the real git checkout (was `~/Projects/map-app/`). In-app update (git pull + service restart) now works. `map-app/` is stale/unused. All future commits go directly from `ops-toc/`.
**2026-06-02** — Final Codex bug sweep pushed to GitHub (`ce5fa38`): downloaded-map Repair endpoint now returns/enqueues repair jobs; LOG/MISSIONS rendering escapes mission names/categories from shared OM `toc_log`; OPS-TOC and Dashboard health verified.
**2026-06-02** — Local rename completed: checkout moved to `~/Projects/ops-toc`, user service renamed to `ops-toc.service`, Dashboard tile now launches OPS-TOC on port 8090, and stale `map-app.service` was retired. Shared DB names remain `~/maps/map_app.db` and `MAP_APP_*` for compatibility with other map consumers.
**2026-06-02** — GitHub repository renamed from `Slofi/map-app` to `Slofi/ops-toc`; local `origin` updated to `git@github.com:Slofi/ops-toc.git`.
**2026-06-02** — Codex compatibility/service pass: OPS-TOC log filtering now applies category/mission/search before the 500-row display limit, so older matching entries are found. Mission rename/remove is case-insensitive. OM was updated to support the shared `WEATHER` category. `log-app.service` was stopped/disabled; former `map-app.service` was active but disabled at boot. Pushed to GitHub (`127e5d5` in `Slofi/ops-toc`, `aee724b` in `Slofi/overmesh`).
**2026-06-02** — Added SOP tab: 8 interactive checklist sections (Activation, Pre-Departure, En Route, Arrival, Open Station, Close Station, Comms Degraded, RC Run) + 2 reference sections (Log Discipline, Category Reference). Progress bars, collapse/expand, per-section and global reset, state persisted in localStorage. Pushed to GitHub (d0b9ea0).
**2026-06-02** — Renamed to OPS-TOC. UI polish: font 15px, toolbar 56px, burger+GPS pinned right, UI zoom slider (80–130%) in Appearance. Custom split clipboard+pin SVG brand icon. Pushed to GitHub (26217d5).
**2026-06-02** — Bug sweep 2: offline settings crash from LOG/MISSIONS tab fixed (prepareOfflineSection, updateOfflineEstimate, currentBoundsPayload, startOfflineDownload all guarded against null state.map). renderBody leading blank line on mission-tagged entries fixed. Deployed to CD (b2d799f).
**2026-06-02** — Bug sweep 1: LOG/MISSIONS tabs were 300px wide (grid layout fix), GPS marker crashed every 3s when map not yet opened, edit entry reset timestamp to now. Deployed to CD (0be590e).
**2026-06-02** — Deployed to CD (d2df5fd). log-app service disabled + retired, TOC-app launcher tile removed. Map App now owns all LOG + MISSIONS functionality on CD.
**2026-06-02** — Merged TOC-app into Map App. Added LOG tab (entry composer, all 10 categories, mission/GPS attach, filter bar, timeline) and MISSIONS tab (mission manager). Backend adds /api/log/* routes sharing overmesh_prefs.db toc_log table with OM. Toolbar restructured: main tabs always visible, map tools hidden on LOG/MISSIONS. GPS status badge always visible. Map init deferred to first MAP tab open. Log export/import added to hamburger.
**2026-05-25** — Pulled CD/GitHub download-management work to TestBox. Added richer downloaded map catalog, total map/tile/size summary, per-map Use/Repair/Refresh/Delete actions, queue panel, pause/resume/cancel controls, Repair Missing, Update All, safe `.part` replacement for refresh/update, and app-package-style settings UI. Current implementation uses an in-memory Flask queue with one worker thread. (Session continuation)
**2026-05-25** — Added local SQLite persistence for download jobs. Jobs are stored in `download_jobs` inside `~/maps/map_app.db`; queued jobs survive restart, paused jobs remain paused until resumed, and running jobs are restored as queued so the app can retry them after restart. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local partial MBTiles resume and per-tile retry/backoff. Restarted/interrupted jobs now keep readable `.part` files, validate them, skip already-saved tiles, and fetch only missing tiles. Finished/error/cancelled job history is retained for 7 days by default via `MAP_APP_DOWNLOAD_JOB_RETENTION_DAYS`; tile retries default to 2 via `MAP_APP_TILE_DOWNLOAD_RETRIES`. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local queue management polish. Download jobs now expose elapsed time, tile rate, and ETA; the Download Queue panel shows active/finished/failed counts and a Clear Finished button that removes completed/cancelled/error job records without touching MBTiles. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local GPX import/export. Export writes markers as GPX waypoints and drawings as GPX tracks. Import reads GPX waypoints into markers and GPX tracks/routes into line drawings through a Settings → Import / Export panel. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local Map App ↔ OM marking exchange. Map App now has Pull From OM / Push To OM controls in Import / Export, using OM's `/api/map_exchange/export` and `/api/map_exchange/import`. Pull imports OM Marks, Self Notes, and Overlays into Map App markers/drawings. Push sends Map App markers as OM Self Notes and drawings as OM Overlays. This is local-only and does not broadcast over mesh. Not deployed to CD yet. (Session continuation)
**2026-05-25** — Added local in-app manual. Hamburger menu now includes Manual, opening a searchable app-native manual modeled after OM's section-card manual. It covers map basics, markers, drawings/ruler, offline maps, download queue, import/export/OM sync, appearance, keys, and app control. Not deployed to CD yet. (Session continuation)
**2026-05-24** — Offline download UX: layer dropdown, cancel button, tileset management (delete/refresh), zoom presets, backend cancel/delete/refresh endpoints. Pushed from CD. (Session 308)
**2026-05-24** — Added to CD Dashboard (tile + start/stop). mbtileserver start/stop added to Dashboard settings panel. (Session 308)
**2026-05-24** — Shared tile architecture implemented: Map App downloads to ~/maps/mbtiles/, mbtileserver serves on :8092 to all CD apps. (Session 308)

---
---
---
# ////// FULL REFERENCE //////

## CHECKLIST System

Pure frontend — no backend. All state lives in browser `localStorage`.

### Storage keys
| Key | Contents |
|-----|----------|
| `ops_toc_checklists` | JSON array of all checklists |
| `ops_toc_checklist_folders_collapsed` | JSON array of collapsed folder names |
| `ops_toc_checklists_backup_<timestamp>` | Auto-backup taken before each import |

### Data structure
```json
[
  {
    "id": "abc123",
    "name": "CD Hardware & Power",
    "folder": "CD Field Test Checklist",
    "collapsed": false,
    "items": [
      { "id": "def456", "text": "Battery charged", "done": false },
      { "id": "ghi789", "text": "Rock 5B powers on", "done": true }
    ]
  }
]
```

### Import — supported formats

**Markdown (recommended for authoring):**
```markdown
# Folder Name           ← H1 sets folder for everything below
## Checklist Name       ← H2 creates a new checklist card
- [ ] Unchecked item
- [x] Checked item
## Another Checklist    ← next H2 = new card, same folder
- [ ] Item
```
- H1 = folder context. No checklist is created from H1.
- H2+ = checklist name. All items below it belong to it.
- Items: `- [ ]`, `- [x]`, `☐`, `✓`, `☑` all recognised.
- Dividers (`---`), italics, plain text lines → skipped (ignored).
- No H1 → all checklists land in "Imported" folder.
- `[Folder] Name` prefix on any heading → explicit folder override.

**OPS-TOC text export (round-trip):**
```
[Folder] Checklist Name
  ☐ Item 1
  ✓ Done item
```

**JSON export (round-trip):** re-import the exported `.json` directly.

### Export
- **Text export** → plain text file, `[Folder] Name` + `☐`/`✓` items. Human-readable.
- **JSON export** → full data dump, preserves done state. Use for backup/restore.

### Field test checklist
- Source file: `~/Projects/ops-toc/TEST/field-test-checklist.md`
- 10 sections, 92 items, folder = "CD Field Test Checklist"
- To load: CHECKLIST tab → Import → select that file
- To update: edit the `.md` file, re-import (backs up current before replacing)

### How to create or edit a checklist (for Claude)
Write a `.md` file with this structure and import it via the Import button:

```markdown
# Folder Name
## Section / Checklist Name
- [ ] Item one
- [ ] Item two
- [x] Pre-checked item

## Another Section
- [ ] Item
```

Each `##` becomes a separate card inside the folder set by `#`.
Multiple folders in one file: add a new `#` heading to switch folders mid-file.
To update a single checklist: delete it in the UI, re-import the updated file
(or edit items directly in the UI with the pencil icon).

### In-app editing
- Rename checklist: pencil icon on card header
- Add item: `+ Add item` at bottom of card
- Edit/delete item: pencil/trash on each row
- Reorder items: drag handle
- Reset progress: circular arrow (unchecks all items)
- Delete checklist: trash icon on card header

## Architecture

```
OPS-TOC / Map App (port 8090)
  Flask backend           → serves HTML, markers, drawings, tile proxy
  Offline downloader      → downloads tiles from online sources
  Tile manager            → manages ~/maps/mbtiles/ (delete, refresh)
  LOG/MISSIONS/SOP        → shares OM toc_log in ~/overmesh/overmesh_prefs.db
  Marker/drawing owner    → SQLite DB at ~/maps/map_app.db
        ↓ writes MBTiles to ~/maps/mbtiles/
mbtileserver (port 8092)  → serves all apps: Sonde App, OM (opt-in), future apps
```

**Design rule:** OPS-TOC owns all map-specific controls (markers, drawings, tracks, downloads). OM may consume map data read-only later but must not own add/edit/delete controls.

## Shared Tile Workflow

How offline tiles flow across CD apps:

1. Open Map App → toolbar → **Offline**
2. Pan/zoom map to the area you want, or use a region preset
3. Select layer (OSM, Esri Satellite, etc.)
4. Set zoom range with preset buttons (Country z6–10 / Region z9–14 / Local z12–16 / Detail z14–17) or set manually
5. Hit **Download** — progress bar shows, Cancel available during download
6. When done, tileset appears in "Downloaded Tilesets" list (name · layer · zoom range · size · date)
7. **All CD apps immediately see the new tileset** — no restart needed
   - Sonde App: toolbar → Local → pick from list
   - OM: Settings → Offline Maps → enable "Use shared local tile DB"

**Tile freshness:** Refresh is always manual (data cap protection). Each tileset shows its download date. Use Refresh button to re-download same area + zoom levels.

**Key rule:** OM must stay fully standalone. Shared tile server is opt-in via toggle, default off.

## Download Management

Current behavior after the CD/GitHub update:

- New downloads, refreshes, repairs, and update-all requests are queued through Map App.
- The backend uses one worker thread, so jobs run one at a time instead of hammering tile providers.
- Jobs are persisted in SQLite in `download_jobs`, including the original tile payload needed to retry.
- After restart, queued jobs are queued again, paused jobs stay paused, and running jobs are restored as queued.
- Readable `.part` files are reused after restart; the downloader scans existing tiles and downloads only missing entries.
- Unreadable `.part` files are discarded and rebuilt from scratch.
- Individual tile requests retry with short backoff before counting as failed.
- Job API responses include elapsed seconds, tile rate, and ETA for queue display.
- Finished/cancelled/error job records can be cleared manually from the Download Queue panel.
- Running jobs can be paused, resumed, or cancelled from the Offline Download controls and the Download Queue panel.
- Refresh/update writes to `<tileset>.mbtiles.part` and replaces the existing MBTiles only after the job finishes.
- Cancelled or failed refresh/update jobs remove the `.part` file and leave the previous good MBTiles file in place.
- Repair copies the existing MBTiles into a `.part` file and downloads only missing tiles.
- Delete refuses to remove a tileset while a queued/running/paused job targets the same file.
- Downloaded Tilesets shows map count, total tile count, total size, source layer, zoom range, bounds, tile URL, and per-map actions.

Current caveats:

- Resume is tile-level, not byte-range HTTP resume. A partially downloaded individual tile is retried as a whole tile.
- Finished/error/cancelled job records are pruned on startup after 7 days by default.

## Zoom Level Guide

| Level | What you see |
|-------|-------------|
| z6  | Country overview |
| z9  | City / region |
| z12 | Streets |
| z14 | Detailed streets |
| z16 | Buildings / paths |

Range z11–14 is the practical sweet spot for field use (orientation + street navigation). z15–16 only for small high-detail areas.

## Online Layer Catalog

- OSM, CARTO Voyager/No Labels, Positron, Dark Matter/No Labels
- Esri Dark Gray, Satellite, Streets, Topo, Hillshade
- Stadia/Stamen Toner Lite, Toner Dark, Terrain, Stadia Outdoors
- Thunderforest Landscape/Outdoors/Pioneer/Atlas (API key)
- MapTiler Satellite Hybrid/Topo/Streets/Winter (API key)

API keys stored in browser localStorage: `thunderforestApiKey`, `mapTilerApiKey` (same keys as OM).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/markers` | GET | All markers (read-only for OM) |
| `/api/export/geojson` | GET | Export markers + drawings |
| `/api/export/gpx` | GET | Export markers as waypoints and drawings as tracks |
| `/api/import/gpx` | POST | Import GPX waypoints/tracks/routes |
| `/api/exchange/markings` | GET | Export markers/drawings for app-to-app exchange |
| `/api/exchange/import` | POST | Import app-to-app GeoJSON markings |
| `/api/om/sync/pull` | POST | Pull OM markings from configured OM URL |
| `/api/om/sync/push` | POST | Push Map App markings to configured OM URL |
| `/api/search` | GET | Place search (Nominatim proxy) |
| `/api/tile-layers` | GET | List downloaded tilesets (includes source_url, mtime) |
| `/tiles/<layer>/<z>/<x>/<y>.png` | GET | Serve local MBTile |
| `/api/downloads` | POST | Start offline download job |
| `/api/downloads` | GET | List current in-memory download jobs |
| `/api/downloads/clear-finished` | POST | Clear done/error/cancelled job records only |
| `/api/downloads/<id>` | GET | Poll job status |
| `/api/downloads/<id>/cancel` | POST | Cancel running download |
| `/api/downloads/<id>/pause` | POST | Pause queued/running download job |
| `/api/downloads/<id>/resume` | POST | Resume paused download job |
| `/api/tile-layers/<id>` | DELETE | Delete tileset file |
| `/api/tile-layers/<id>/refresh` | POST | Re-download tileset (same area + zoom) |
| `/api/tile-layers/<id>/repair` | POST | Download missing tiles for existing tileset |
| `/api/tile-layers/update-all` | POST | Queue refresh jobs for all refreshable tilesets |
| `/api/tile-layers/repair-all` | POST | Queue repair jobs for all refreshable tilesets |
| `/api/om/share-marker/<id>` | POST | Placeholder, returns 501 |
| `/api/download-estimate` | POST | Estimate tile count before download |
| `/api/tracks` | GET | List saved GPS tracks |
| `/api/tracks` | POST | Save a new GPS track |
| `/api/tracks/<id>` | PUT | Update track name/description/color |
| `/api/tracks/<id>` | DELETE | Delete track |
| `/api/tracks/<id>/gpx` | GET | Export track as GPX |
| `/api/tracks/<id>/geojson` | GET | Export track as GeoJSON |
| `/api/tracks/<id>/drawing` | POST | Convert track to a drawing |

## GPS / Position Update — 2026-06-23

OPS-TOC now supports the Cyberdeck internal Beitian BN-220/BN-280-style GPS on the Rock 5B GPIO UART as a first-class GPS source.

Hardware and system state:

- GPS module markings are `P G T R V B`.
- Correct wiring:
  - `V` -> Rock 5B pin 1, 3.3V
  - `G` -> Rock 5B pin 9, GND
  - `T` -> Rock 5B pin 35, `UART3_RX_M1`
  - `R` -> Rock 5B pin 12, `UART3_TX_M1`
  - `P` is PPS, not power; leave unconnected unless PPS is needed.
  - `B` remains unconnected.
- `/dev/ttyS3` is the Rock 5B UART3 M1 serial device.
- `uart3-m1` is enabled in `/boot/armbianEnv.txt`.
- `gpsd` and `gpsd.socket` were stopped/disabled so OPS-TOC can own `/dev/ttyS3`.

Code changes:

- `gps.py`
  - Lists `/dev/ttyS3` as `Internal BN-220 / BN-280 GPS - Rock 5B UART3 (/dev/ttyS3)`.
  - Keeps `Auto-detect USB GPS` for USB dongles.
  - Treats `/dev/ttyS*` ports as present via filesystem existence checks, because pyserial's USB port listing does not cover the GPIO UART cleanly.
  - u-blox NMEA init now enables messages on UART1 as well as USB, so direct serial over GPIO continues emitting NMEA.
- `templates/index.html`
  - GPS/Position copy now distinguishes USB dongle, internal BN-220/BN-280, and OM proxy.
- `app.py`
  - Adds `GET /api/settings/gps`, returning the same live payload as `/api/gps`.

Current verified OPS-TOC config:

```json
{
  "enabled": true,
  "port": "/dev/ttyS3",
  "om_proxy": false,
  "om_url": "http://localhost:8082",
  "manual": false
}
```

Live verification:

- `systemctl --user is-active ops-toc.service` -> `active`
- `GET /api/gps/ports` returns:
  - `auto` / `Auto-detect USB GPS - no USB dongle found`
  - `/dev/ttyS3` / `Internal BN-220 / BN-280 GPS - Rock 5B UART3 (/dev/ttyS3)`
- `GET /api/settings/gps` returned a real direct fix from `/dev/ttyS3`:
  - lat around `46.03918`
  - lon around `14.49765`
  - altitude around `331-337m`
  - `sats: 5`
  - `sats_view: 7-8`
  - `source: direct`

Proxy integration:

- Other CD apps that support OM-style GPS proxy can use OPS-TOC as the provider by setting the proxy base URL to `http://localhost:8090` on the same machine.
- They should poll `http://localhost:8090/api/settings/gps`.
- The response includes `fix`, `lat`, `lon`, `alt`, `sats`, `sats_view`, `enabled`, `port`, `running`, `port_present`, `source`, and config fields.

Caveat:

- A backup from the original live GPS patch remains in the checkout as `gps.py.before-ttyS-gps`.

## Internal GPS Field Diagnosis — 2026-06-28

Cyberdeck was tested outside with the internal BN-280-style GPS on Rock 5B UART3 (`/dev/ttyS3`).

- UART3 hardware path is working:
  - `/dev/ttyS3` exists.
  - `uart3-m1` is enabled in `/boot/armbianEnv.txt`.
  - `gpsd.service` and `gpsd.socket` are masked/inactive.
  - OPS-TOC is the only normal owner of `/dev/ttyS3`.
- Raw 9600 baud serial showed valid u-blox binary frames (`b5 62 ...`), so the module is powered and communicating digitally.
- OPS-TOC reader only parses NMEA. The module was outputting UBX/binary-first, so `gps.py` was patched to force UART1 output protocol to NMEA before enabling GGA/GSV messages.
- With OPS-TOC stopped and the receiver forced to NMEA-only, the module emitted clean NMEA:
  - `$GNGGA,,,,,,0,00,99.99,,,,,,*56`
  - `$GPGSV,1,1,00*79`
  - `$GLGSV,1,1,00*65`
- A 45-second exclusive read outside repeatedly showed `0` GPS satellites and `0` GLONASS satellites in view.
- u-blox hardware monitor:
  - `aStatus=2`
  - `aPower=1`
  - `jamInd=0`
- GNSS config:
  - GPS enabled.
  - GLONASS enabled.
  - SBAS/QZSS enabled.
  - Galileo/BeiDou disabled.

Current conclusion:

- Rock 5B UART communication is fixed/confirmed.
- OPS-TOC can configure the receiver for NMEA and read it.
- Remaining failure is RF/reception-side: `sats_view` stays `0` despite outdoor clear-sky test.
- User reported the module power wire had previously been connected to `P` for a few minutes instead of `V`. On the `P G T R V B` marking, `P` is PPS, not power. This may have stressed/damaged the receiver even though UART still works.
- Next isolation test if resumed: remove/raise the BN-280 from the faceplate/case, power only correct `V/G`, connect module `T` to Rock RX, white ceramic patch facing sky, keep it away from deck electronics for 5-10 minutes. If `sats_view` remains `0`, replace the BN-280.
