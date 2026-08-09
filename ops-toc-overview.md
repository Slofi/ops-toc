type:: project-overview
project:: ops-toc
tags:: #overview #ops-toc #map-app #leaflet #offline-maps #field-log #cyberdeck
updated:: 2026-08-10

# OPS-TOC — Overview Card

> Quick-reference card — crucial info for Filip + Haskill. Full context, history & changelog → `ops-toc/status.md`.

## Overview

| Field | Value |
|-------|-------|
| **Status** | active — Dashboard-started, **not enabled at boot** (user service is `disabled`; a reboot leaves it stopped)<br>**Track Debrief** (after-action report + annotatable stop timeline) landed 2026-08-10 — backend verified on CD against the real DB; **frontend browser validation still pending** |
| **Type** | app (Flask) |
| **Device / Host** | Cyberdeck (rock-5b)<br>Tailscale 100.97.104.107 |
| **Ports** | 8090 |
| **Access** | `http://localhost:8090`<br>`/lite` — compact HD 5" touch UI |
| **Repo** | github.com/Slofi/ops-toc<br>checkout `~/Projects/ops-toc/`<br>latest **pushed** `061847a` (stable — that one really is on GitHub)<br>⚠️ **1 unpushed local commit** (Track Debrief, 2026-08-10) — **no hash here on purpose**: a hash in prose is stale the moment you amend or commit again. Ask the repo: `git -C ~/Projects/ops-toc log --oneline -1`<br>⚠️ `.git` is inside the Syncthing `Projects/` folder, so TestBox and CD share git state — don't run git on both at once |
| **Service** | ops-toc.service (user systemd, **not** boot-enabled) |
| **Key paths** | App `~/Projects/ops-toc/app.py`<br>DB `~/maps/map_app.db`<br>Tiles `~/maps/mbtiles/`<br>Log DB `~/overmesh/overmesh_prefs.db` (toc_log) |
| **GPS** | u-blox USB dongle (`auto`) or internal BN-280 (`/dev/ttyS3`)<br>gpsd masked so OPS-TOC owns the port |
| **Depends on** | OM shared log DB (toc_log)<br>mbtileserver :8092 (shared tiles) |
| **Updated** | 2026-08-10 — Track Debrief committed (unpushed); backend verified on CD against the real DB; card brought current |

## Quick Commands

| Command | What it does |
|---------|--------------|
| `systemctl --user restart ops-toc` | restart the app |
| `systemctl --user start ops-toc` / `stop ops-toc` | start / stop |
| `journalctl --user -u ops-toc -f` | follow logs |
| `curl -s localhost:8090/api/gps` | check GPS / speed feed |

## Troubleshooting / Recovery

- **GPS "port busy" / no fix:** gpsd grabbed the receiver (it's masked, but if it returns) → `sudo systemctl mask --now gpsd.service gpsd.socket`. Internal BN-280 needs explicit `/dev/ttyS3` (`auto` is USB-only).
- **Flask import breaks after a Syncthing sync:** venv got cross-machine contaminated → rebuild `python3.12 -m venv venv && venv/bin/pip install -r requirements.txt` (venvs are Syncthing-ignored).
- **Frontend change not showing:** `app.js`/templates are static — reload the browser tab, no service restart needed. ⚠️ **There is no `?v=` cache-bust on `app.js`/`app.css`**, so a normal reload can serve the old bundle and make a new feature look broken. **Hard-reload** (Ctrl+Shift+R) when checking anything just shipped.
- **A track shows no stops:** stops are materialised **server-side at save time**, so any track saved before the Debrief code first ran on CD (2026-08-10) has none — this is expected, not a fault. Use the **non-persisting** `POST /api/tracks/<id>/detect-stops` preview to re-scan an old track without writing to it. Detection is 1 km/h / ≥60 s, so a continuous drive genuinely returns 0.
- **Service isn't running after a reboot:** by design — the user unit is `disabled` and the CD Dashboard tile starts it. `systemctl --user start ops-toc` to bring it up manually.
- **Track recording produced nothing:** recording lives in the *browser page* — no open OPS-TOC tab = no recording (backend recorder still pending).
- **Restart:** `systemctl --user restart ops-toc` · **logs:** `journalctl --user -u ops-toc -f`.

