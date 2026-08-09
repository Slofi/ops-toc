type:: project-overview
project:: ops-toc
tags:: #overview #ops-toc #map-app #leaflet #offline-maps #field-log #cyberdeck
updated:: 2026-08-10

# OPS-TOC — Overview Card

> Quick-reference card — crucial info for Filip + Haskill. Full context, history & changelog → `ops-toc/status.md`.

## Overview

| Field | Value |
|-------|-------|
| **Status** | active — Dashboard-started, **not enabled at boot** (user service is `disabled`; a reboot leaves it stopped)<br>**Track recording is SERVER-SIDE since 2026-08-10** — Flask records, the browser is only a viewer; closing the tab no longer stops a recording<br>**Track Debrief** (after-action report + annotatable stop timeline) landed 2026-08-10 — backend verified on CD against the real DB; **frontend browser validation still pending**<br>⚠️ **Known bug:** stop detection never fires on tracks from a speed-reporting GPS — see Troubleshooting |
| **Type** | app (Flask) |
| **Device / Host** | Cyberdeck (rock-5b)<br>Tailscale 100.97.104.107 |
| **Ports** | 8090 |
| **Access** | `http://localhost:8090`<br>`/lite` — compact HD 5" touch UI |
| **Repo** | github.com/Slofi/ops-toc<br>checkout `~/Projects/ops-toc/`<br>latest **pushed** `061847a` (stable — that one really is on GitHub)<br>⚠️ **1 unpushed local commit** (Track Debrief, 2026-08-10) — **no hash here on purpose**: a hash in prose is stale the moment you amend or commit again. Ask the repo: `git -C ~/Projects/ops-toc log --oneline -1`<br>⚠️ `.git` is inside the Syncthing `Projects/` folder, so TestBox and CD share git state — don't run git on both at once |
| **Service** | ops-toc.service (user systemd, **not** boot-enabled) |
| **Key paths** | App `~/Projects/ops-toc/app.py`<br>DB `~/maps/map_app.db`<br>Tiles `~/maps/mbtiles/`<br>Log DB `~/overmesh/overmesh_prefs.db` (toc_log)<br>Live recording buffer `~/maps/active_track.json` (exists only while a track is being recorded or is stopped-but-unsaved) |
| **GPS** | u-blox USB dongle (`auto`) or internal BN-280 (`/dev/ttyS3`)<br>gpsd masked so OPS-TOC owns the port |
| **Depends on** | OM shared log DB (toc_log)<br>mbtileserver :8092 (shared tiles) |
| **Updated** | 2026-08-10 — server-side recorder landed & verified on CD (filters, restart-persistence, save); stop-detection bug found and documented |

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
| `git -C ~/Projects/ops-toc log --oneline origin/main..HEAD` | what is committed locally but not pushed |

## Troubleshooting / Recovery

- **GPS "port busy" / no fix:** gpsd grabbed the receiver (it's masked, but if it returns) → `sudo systemctl mask --now gpsd.service gpsd.socket`. Internal BN-280 needs explicit `/dev/ttyS3` (`auto` is USB-only).
- **Flask import breaks after a Syncthing sync:** venv got cross-machine contaminated → rebuild `python3.12 -m venv venv && venv/bin/pip install -r requirements.txt` (venvs are Syncthing-ignored).
- **Frontend change not showing:** `app.js`/templates are static — reload the browser tab, no service restart needed. ⚠️ **There is no `?v=` cache-bust on `app.js`/`app.css`**, so a normal reload can serve the old bundle and make a new feature look broken. **Hard-reload** (Ctrl+Shift+R) when checking anything just shipped.
- **A track shows no stops:** stops are materialised **server-side at save time**, so any track saved before the Debrief code first ran on CD (2026-08-10) has none — this is expected, not a fault. Use the **non-persisting** `POST /api/tracks/<id>/detect-stops` preview to re-scan an old track without writing to it. Detection is 1 km/h / ≥60 s, so a continuous drive genuinely returns 0.
- **Service isn't running after a reboot:** by design — the user unit is `disabled` and the CD Dashboard tile starts it. `systemctl --user start ops-toc` to bring it up manually.
- **Track recording produced nothing:** since 2026-08-10 the recorder is **inside Flask**, so a closed tab is no longer the cause. What still stops it: `ops-toc.service` not running, GPS with no fix, or fewer than 4 satellites. Check with `curl -s localhost:8090/api/recording` — if `active` is false, nothing is being recorded.
- **A recording seems lost after a restart:** it shouldn't be. The buffer is flushed to `~/maps/active_track.json` (at most every 5 s) and reloaded at startup, so a service restart or crash resumes mid-track. Up to 5 s of movement can be lost. If the file is gone, the track was saved or discarded.
- **The Track button says `Save (N)`:** the recorder was stopped without saving and the points are still buffered server-side. Tap it to open the save dialog (or `POST /api/recording/discard` to throw them away). A new recording won't start until that buffer is cleared.
- ⚠️ **Stop detection finds 0 stops even after a long halt** — **known bug, not yet fixed** (confirmed on CD 2026-08-10 with a synthetic 80 s halt). While stationary the recorder refreshes the last point's timestamp but leaves its **old `speed` value** in place; `_seg_speed_kmh()` prefers stored speed over distance÷time, so the halt reads as ~25–50 km/h and never trips the 1 km/h threshold. Same data with the `speed` field stripped correctly yields 2 stops. Affects any track from a speed-reporting receiver (the u-blox does) — i.e. the Debrief stop timeline is effectively non-functional. Fix = keep two at-rest points (halt start + halt end, both speed 0) instead of one timestamp-refreshed point. Details in `status.md`.
- **Restart:** `systemctl --user restart ops-toc` · **logs:** `journalctl --user -u ops-toc -f`.

