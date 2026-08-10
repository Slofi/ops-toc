type:: project-overview
project:: ops-toc
tags:: #overview #ops-toc #map-app #leaflet #offline-maps #field-log #cyberdeck
updated:: 2026-08-11

# OPS-TOC — Overview Card

> Quick-reference card — crucial info for Filip + Haskill. Full context, history & changelog → `ops-toc/status.md`.

## Overview

| Field | Value |
|-------|-------|
| **Status** | active — Dashboard-started, **not enabled at boot** (user service is `disabled`; a reboot leaves it stopped)<br>**Track recording is SERVER-SIDE since 2026-08-10** — Flask records, the browser is only a viewer; closing the tab no longer stops a recording<br>**Track Debrief** (after-action report + annotatable stop timeline) landed 2026-08-10 — backend verified on CD against the real DB; **frontend browser validation still pending**<br>✅ **Stop detection FIXED 2026-08-11 (S404)** — halts are now bracketed by two at-rest markers; verified live on CD (79 s park → 1 stop, 79 s). ⚠️ **Tracks recorded BEFORE this date still show no stops** — see Troubleshooting |
| **Type** | app (Flask) |
| **Device / Host** | Cyberdeck (rock-5b)<br>Tailscale 100.97.104.107 |
| **Ports** | 8090 |
| **Access** | `http://localhost:8090`<br>`/lite` — compact HD 5" touch UI |
| **Repo** | github.com/Slofi/ops-toc<br>checkout `~/Projects/ops-toc/`<br>branch **master** (not main)<br>✅ **fully pushed as of 2026-08-10** (Track Debrief + server-side recorder)<br>**no hashes or counts here on purpose** — both go stale the moment you commit again. Ask the repo: `git -C ~/Projects/ops-toc log --oneline @{u}..HEAD`<br>⚠️ `.git` is inside the Syncthing `Projects/` folder, so TestBox and CD share git state — don't run git on both at once |
| **Service** | ops-toc.service (user systemd, **not** boot-enabled) |
| **Key paths** | App `~/Projects/ops-toc/app.py`<br>DB `~/maps/map_app.db`<br>Tiles `~/maps/mbtiles/`<br>Log DB `~/overmesh/overmesh_prefs.db` (toc_log)<br>Live recording buffer `~/maps/active_track.json` (exists only while a track is being recorded or is stopped-but-unsaved) |
| **GPS** | u-blox USB dongle (`auto`) or internal BN-280 (`/dev/ttyS3`)<br>gpsd masked so OPS-TOC owns the port |
| **Depends on** | OM shared log DB (toc_log)<br>mbtileserver :8092 (shared tiles) |
| **Updated** | 2026-08-11 (S404 — **stop detection fixed**: halts bracketed by two at-rest markers, verified live on CD, 79 s park → 1 stop of 79 s, distance unchanged at 693.7 m) · 2026-08-10 (server-side recorder landed & verified on CD) |

## Quick Commands

| Command | What it does |
|---------|--------------|
| `systemctl --user restart ops-toc` | restart the app |
| `systemctl --user start ops-toc` / `stop ops-toc` | start / stop |
| `journalctl --user -u ops-toc -f` | follow logs |
| `curl -s localhost:8090/api/gps` | check GPS / speed feed |
| `curl -s localhost:8090/api/recording` | is a track being recorded right now? (`active`, `count`, `distance_m`) |
| `curl -s -X POST localhost:8090/api/recording/start -H 'Content-Type: application/json' -d '{"min_interval":10}'` | start recording without a browser |
| `curl -s -X POST localhost:8090/api/recording/stop` | halt capture, keep the buffer for saving |
| `git -C ~/Projects/ops-toc log --oneline @{u}..HEAD` | what is committed locally but not pushed (branch is **master**, not main — `origin/main..HEAD` silently returns nothing) |

## Troubleshooting / Recovery

- **GPS "port busy" / no fix:** gpsd grabbed the receiver (it's masked, but if it returns) → `sudo systemctl mask --now gpsd.service gpsd.socket`. Internal BN-280 needs explicit `/dev/ttyS3` (`auto` is USB-only).
- **Flask import breaks after a Syncthing sync:** venv got cross-machine contaminated → rebuild `python3.12 -m venv venv && venv/bin/pip install -r requirements.txt` (venvs are Syncthing-ignored).
- **Frontend change not showing:** `app.js`/templates are static — reload the browser tab, no service restart needed. ⚠️ **There is no `?v=` cache-bust on `app.js`/`app.css`**, so a normal reload can serve the old bundle and make a new feature look broken. **Hard-reload** (Ctrl+Shift+R) when checking anything just shipped.
- **A track shows no stops:** three separate causes, in order of likelihood. (1) It was recorded **before 2026-08-11** — the stop-detection bug below. (2) It was saved **before the Debrief code first ran on CD (2026-08-10)**, so stops were never materialised. (3) It genuinely has none — detection is 1 km/h / ≥60 s, so a continuous drive correctly returns 0. Stops are materialised **server-side at save time**; `POST /api/tracks/<id>/detect-stops` previews without writing.
- **Service isn't running after a reboot:** by design — the user unit is `disabled` and the CD Dashboard tile starts it. `systemctl --user start ops-toc` to bring it up manually.
- **Track recording produced nothing:** since 2026-08-10 the recorder is **inside Flask**, so a closed tab is no longer the cause. What still stops it: `ops-toc.service` not running, GPS with no fix, or fewer than 4 satellites. Check with `curl -s localhost:8090/api/recording` — if `active` is false, nothing is being recorded.
- **A recording seems lost after a restart:** it shouldn't be. The buffer is flushed to `~/maps/active_track.json` (at most every 5 s) and reloaded at startup, so a service restart or crash resumes mid-track. Up to 5 s of movement can be lost. If the file is gone, the track was saved or discarded.
- **The Track button says `Save (N)`:** the recorder was stopped without saving and the points are still buffered server-side. Tap it to open the save dialog (or `POST /api/recording/discard` to throw them away). A new recording won't start until that buffer is cleared.
- ✅ **Stop detection was broken until 2026-08-11 (S404) — fixed.** *Old behaviour:* a halt collapsed into ONE point whose timestamp advanced but whose `speed` stayed at whatever it was when captured (e.g. 50 km/h, recorded while still moving). `_detect_stops()` walks consecutive **pairs** and `_seg_speed_kmh()` prefers the stored `speed` over distance÷time, so an 80 s halt averaged `(50+0)/2 = 25 km/h` and never tripped `STOP_KMH = 1.0`. Measured then: `dt=84 s, dist=13.9 m` → **25.00 km/h** with speed, **0.59 km/h** without. A single point cannot express "at rest from t1 to t2" — it takes a pair.
  *Fix:* a halt is now bracketed by **two at-rest markers** (halt-start + halt-end), both pinned to the arrival coordinates and both carrying the real near-zero speed — so they add **zero** distance. Verified live on CD: the same synthetic route that produced **0 stops** now yields **1 stop of 79 s** (the route's park is exactly 79 s), with distance **identical to the pre-fix run at 693.7 m**.
  ⚠️ **Tracks recorded before 2026-08-11 still show no stops** — their points carry the stale speeds, so the data itself is unfixable by re-running detection *as-is*. A one-off re-detect that ignores stored `speed` would recover them (it falls back to distance÷time, which is correct for a parked vehicle) — **not done; it rewrites historical tracks, so it's Filip's call.** The non-persisting `POST /api/tracks/<id>/detect-stops` preview is unaffected and still won't find them.
- **Restart:** `systemctl --user restart ops-toc` · **logs:** `journalctl --user -u ops-toc -f`.

