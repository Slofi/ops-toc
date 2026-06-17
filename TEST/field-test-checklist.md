# CD Field Test Checklist
*Camping trip — 2026-06-18 — Rock 5B + Argus*

---

## 1. CD Hardware & Power
- [ ] Battery charged / power bank ready
- [ ] Rock 5B powers on cleanly
- [ ] Display connected + working
- [ ] M70 keyboard connected
- [ ] USB hub seated properly
- [ ] RTL-SDR dongle connected
- [ ] WiFi adapter (RTL8812AU) connected
- [ ] u-blox GPS dongle connected
- [ ] CC1101 module connected
- [ ] Argus (MC node) connected via USB
- [ ] Fan / cooling adequate
- [ ] All cables secured

## 2. CD Dashboard & Services
- [ ] Dashboard loads at :8080
- [ ] All tiles visible with correct status
- [ ] OPS-TOC tile — port 8090
- [ ] OM tile — port 8082
- [ ] ADS-B tile — port 5400
- [ ] Banshee tile — port 5200
- [ ] Casper tile — port 5300
- [ ] mbtileserver running — port 8092
- [ ] OPS-TOC — check for update
- [ ] OM — check for update
- [ ] ADS-B App — check for update

## 3. GPS
- [ ] u-blox detected (OPS-TOC auto port)
- [ ] GPS fix acquired
- [ ] Satellite count ≥ 8
- [ ] Position accurate (matches known location)
- [ ] OPS-TOC position marker on map
- [ ] ADS-B receiver position correct (Auto source)
- [ ] OM GPS disabled (OPS-TOC owns port — expected)

## 4. OPS-TOC
- [ ] App loads at :8090
- [ ] Map loads — online layer
- [ ] Offline map loads — Slovenia tiles
- [ ] Offline layer switch works
- [ ] Place search works (Nominatim)
- [ ] Add marker → saved
- [ ] Edit marker → saved
- [ ] Delete marker → confirmed
- [ ] Draw line / polygon
- [ ] GPS recording — start track
- [ ] Walk 100m+ with GPS active
- [ ] Stop track — save with name + colour
- [ ] Track shows on map correctly
- [ ] Export track as GPX
- [ ] LOG tab — add entry (category + text)
- [ ] LOG tab — filter by category
- [ ] MISSIONS tab — create mission
- [ ] MISSIONS tab — log entry to mission
- [ ] SOP tab — complete a section
- [ ] CHECKLIST tab — all checklists load
- [ ] Settings — GPS port shown correctly
- [ ] App restart from Settings works

## 5. OverMesh (OM)
- [ ] App loads at :8082
- [ ] CD MT node visible on dashboard
- [ ] Argus (MC) visible on dashboard
- [ ] Mobile EDC MC node visible on dashboard
- [ ] MC primary — messages flowing
- [ ] MT ↔ MC bridge active
- [ ] Send message from OM
- [ ] Receive message in OM
- [ ] Telemetry updating (battery, signal, position)

## 6. MeshCore (MC) — Argus + EDC node
- [ ] Argus powered on + visible in OM
- [ ] Mobile EDC MC node powered on + visible in OM
- [ ] DM: CD → EDC node (delivered)
- [ ] DM: EDC node → CD (delivered)
- [ ] Relay test: message routed via Argus (3-node chain)
- [ ] Telemetry visible on both MC nodes
- [ ] Range test — EDC node, record max distance
- [ ] Standalone test: Argus + EDC node talking without CD in range
- [ ] rc-collector DMs appearing in OM from Argus
- [ ] Intel flow: MC traffic → DMs → OM visible

## 7. Meshtastic (MT) — CD node
- [ ] CD MT node connected + visible in OM
- [ ] MT node telemetry showing (battery, signal)
- [ ] Send MT message from CD
- [ ] MT ↔ MC bridge relaying correctly
- [ ] MT coverage from camp — signal visible at perimeter

## 8. ADS-B App
- [ ] RTL-SDR toggled ON in Settings
- [ ] dump1090 started from Settings panel
- [ ] dump1090 status dot green
- [ ] Aircraft appearing on map
- [ ] Aircraft DB loaded (registration + type visible)
- [ ] Airline name showing (operators.json)
- [ ] Country of registration showing
- [ ] Track trails visible
- [ ] Range rings on
- [ ] Closest / farthest shown in header
- [ ] Follow mode — tap aircraft → Follow
- [ ] History tab — aircraft gone >60s listed
- [ ] MBTiles offline map layer working

## 9. Intercept / SDR
- [ ] RTL8812AU in monitor mode
- [ ] WiFi networks detected (iw scan)
- [ ] Banshee loads at :5200
- [ ] Banshee — passive WiFi scan
- [ ] Banshee — handshake capture attempt
- [ ] acarsdec — ACARS on 131.725 MHz
- [ ] dumpvdl2 — VDL2 on 136.900 MHz
- [ ] AIS-catcher — AIS 161.975 / 162.025 MHz (if near water)
- [ ] Kismet running (if set up on CD)

## 10. Casper (CC1101)
- [ ] Casper loads at :5300
- [ ] CC1101 module detected
- [ ] Sub-GHz scan — 433 MHz band
- [ ] Signal captured (gate remote, weather sensor, etc.)
- [ ] Signal logged / saved
- [ ] Replay test (own device only)

---
*Total items: 92*
