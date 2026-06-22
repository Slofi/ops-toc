# Cyberdeck / Field Test

## Hardware & Power

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

## Dashboard & Services

- [ ] Dashboard loads at :8080
- [ ] All tiles visible with correct status
- [ ] OPS-TOC tile — port 8090
- [ ] OM tile — port 8082
- [ ] ADS-B tile — port 5400
- [ ] Banshee tile — port 5200
- [ ] Casper tile — port 5300
- [ ] Intercept tile present
- [ ] mbtileserver running — port 8092

## GPS

- [ ] u-blox detected (OPS-TOC auto port)
- [ ] GPS fix acquired
- [ ] Satellite count ≥ 8
- [ ] Position accurate (matches known location)
- [ ] OPS-TOC position marker on map
- [ ] ADS-B receiver position correct (Auto source)
- [ ] OM GPS disabled (OPS-TOC owns port — expected)

## OPS-TOC

- [ ] App loads at :8090
- [ ] Online map loads
- [ ] Offline map loads — Slovenia tiles
- [ ] GPS position marker showing
- [ ] LOG tab — add test entry, save ok

## OverMesh

- [ ] App loads at :8082
- [ ] CD MT node visible
- [ ] Argus (MC) visible
- [ ] Mobile EDC MC node visible

## MeshCore

- [ ] Argus powered on + visible in OM
- [ ] MT ↔ MC bridge active
- [ ] Send DM — delivered to EDC node
- [ ] Receive DM from EDC node
- [ ] rc-collector traffic flowing (DMs visible in OM)

## Meshtastic

- [ ] CD MT node connected + visible in OM
- [ ] MT ↔ MC bridge relaying correctly

## ADS-B

- [ ] RTL-SDR toggled ON in Dashboard Settings
- [ ] dump1090 running — status dot green
- [ ] Aircraft appearing on map

## Intercept

- [ ] Tile loads
- [ ] WiFi adapter in monitor mode (Dashboard monitor toggle)
- [ ] Drone Intel — interface showing detected devices

## Casper

- [ ] Tile loads at :5300
- [ ] CC1101 module detected
- [ ] 433 MHz scan — signals visible
