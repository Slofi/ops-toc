// Paste this into the browser console while OPS-TOC (:8090) is open.
// Sets the field test checklists and reloads the CHECKLIST tab.

(function () {
  const uid = () => Math.random().toString(36).slice(2, 9) + Date.now().toString(36);
  const it  = (text) => ({ id: uid(), text, done: false });
  const cl  = (name, items) => ({ id: uid(), name, items: items.map(it), collapsed: false });

  const data = [
    cl("CD Hardware & Power", [
      "Battery charged / power bank ready",
      "Rock 5B powers on cleanly",
      "Display connected + working",
      "M70 keyboard connected",
      "USB hub seated properly",
      "RTL-SDR dongle connected",
      "WiFi adapter (RTL8812AU) connected",
      "u-blox GPS dongle connected",
      "CC1101 module connected",
      "Argus (MC node) connected via USB",
      "Fan / cooling adequate",
      "All cables secured",
    ]),
    cl("CD Dashboard & Services", [
      "Dashboard loads at :8080",
      "All tiles visible with correct status",
      "OPS-TOC tile — port 8090",
      "OM tile — port 8082",
      "ADS-B tile — port 5400",
      "Banshee tile — port 5200",
      "Casper tile — port 5300",
      "mbtileserver running — port 8092",
      "OPS-TOC — check for update",
      "OM — check for update",
      "ADS-B App — check for update",
    ]),
    cl("GPS", [
      "u-blox detected (OPS-TOC auto port)",
      "GPS fix acquired",
      "Satellite count ≥ 8",
      "Position accurate (matches known location)",
      "OPS-TOC position marker on map",
      "ADS-B receiver position correct (Auto source)",
      "OM GPS disabled (OPS-TOC owns port — expected)",
    ]),
    cl("OPS-TOC", [
      "App loads at :8090",
      "Map loads — online layer",
      "Offline map loads — Slovenia tiles",
      "Offline layer switch works",
      "Place search works (Nominatim)",
      "Add marker → saved",
      "Edit marker → saved",
      "Delete marker → confirmed",
      "Draw line / polygon",
      "GPS recording — start track",
      "Walk 100m+ with GPS active",
      "Stop track — save with name + colour",
      "Track shows on map correctly",
      "Export track as GPX",
      "LOG tab — add entry (category + text)",
      "LOG tab — filter by category",
      "MISSIONS tab — create mission",
      "MISSIONS tab — log entry to mission",
      "SOP tab — complete a section",
      "CHECKLIST tab — all checklists load",
      "Settings — GPS port shown correctly",
      "App restart from Settings works",
    ]),
    cl("OverMesh (OM)", [
      "App loads at :8082",
      "MT nodes visible on dashboard",
      "MC nodes visible (Argus shown)",
      "MT ↔ MC bridge working",
      "Send mesh message from OM",
      "Receive mesh message in OM",
      "OM telemetry updating (battery, signal)",
      "Argus node status green",
      "Node positions updating",
    ]),
    cl("Meshtastic Nodes", [
      "EDC1 on air — visible in OM",
      "EDC2 on air — visible in OM",
      "EDC3 on air — visible in OM",
      "Send DM between nodes",
      "Broadcast received by all nodes",
      "Telemetry visible (battery %, RSSI)",
      "GPS position updating (if node has GPS)",
      "Range test — record farthest distance",
      "Node-to-node message without CD relay",
    ]),
    cl("Argus (rc-collector)", [
      "Argus powered on",
      "Visible as MC node in OM",
      "RPTR relay active (forwarding MC messages)",
      "rc-collector DMs appearing in OM",
      "Intel flow: mesh → DMs → OM visible",
      "Range test at distance from CD",
      "Standalone run (no laptop dependency)",
    ]),
    cl("ADS-B App", [
      "RTL-SDR toggled ON in Settings",
      "dump1090 started from Settings panel",
      "dump1090 status dot green",
      "Aircraft appearing on map",
      "Aircraft DB loaded (registration + type visible)",
      "Airline name showing (operators.json)",
      "Country of registration showing",
      "Track trails visible",
      "Range rings on",
      "Closest / farthest shown in header",
      "Follow mode — tap aircraft → Follow",
      "History tab — aircraft gone >60s listed",
      "MBTiles offline map layer working",
    ]),
    cl("Intercept / SDR", [
      "RTL8812AU in monitor mode",
      "WiFi networks detected (iw scan)",
      "Banshee loads at :5200",
      "Banshee — passive WiFi scan",
      "Banshee — handshake capture attempt",
      "acarsdec — ACARS on 131.725 MHz",
      "dumpvdl2 — VDL2 on 136.900 MHz",
      "AIS-catcher — AIS 161.975 / 162.025 MHz (if near water)",
      "Kismet running (if set up on CD)",
    ]),
    cl("Casper (CC1101)", [
      "Casper loads at :5300",
      "CC1101 module detected",
      "Sub-GHz scan — 433 MHz band",
      "Signal captured (gate remote, weather sensor, etc.)",
      "Signal logged / saved",
      "Replay test (own device only)",
    ]),
  ];

  localStorage.setItem("ops_toc_checklists", JSON.stringify(data));

  // Reload into CHECKLIST tab
  if (typeof checklistLoad === "function") {
    checklistLoad();
    checklistRender();
    showTab("checklist");
    console.log("✓ Checklists loaded — " + data.length + " lists, " + data.reduce((s, l) => s + l.items.length, 0) + " items.");
  } else {
    location.reload();
  }
})();
