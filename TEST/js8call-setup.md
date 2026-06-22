# Apps / JS8

## SDR++ Setup

- [ ] Confirm RTL-SDR toggle switch is ON (physical switch on faceplate)
- [ ] Check Dashboard SDR bar — must show green "free" (release if busy)
- [ ] Release GPS from OPS-TOC if needed (GPS bar → Release)
- [ ] Launch SDR++ from Dashboard tile

## SDR++ Configuration

- [ ] Source: RTL-SDR Blog V4 (device index 0)
- [ ] Tune to 14.074 MHz (20m JS8 calling freq)
- [ ] Mode: USB (Upper Sideband)
- [ ] Bandwidth: ~3000 Hz
- [ ] Gain: start at 30–40 dB, adjust to avoid clipping (waterfall not all red)
- [ ] Confirm audio output is active (SDR++ audio bar shows signal)
- [ ] Confirm sdrpp-launch.sh has redirected audio to JS8Call_Loopback (automatic)

## Start & Verify

- [ ] Launch JS8 tile from Dashboard (starts JS8Call + js8-app automatically)
- [ ] JS8Call window opens — confirm waterfall is live and showing noise/signals
- [ ] JS8Call audio input shows JS8Call_Loopback.monitor (Settings → Audio → Input)
- [ ] Wait 1–2 min for first decodes to appear
- [ ] js8-app opens at localhost:5500 — Feed tab shows decoded messages

## Band Selection

- [ ] 20m (14.074 MHz) — best daytime propagation, most active globally
- [ ] 40m (7.078 MHz) — evening/night when 20m closes, better regional coverage
- [ ] Use band buttons in js8-app Feed tab to switch (sends RIG.SET_FREQ to JS8Call)

## Shutdown

- [ ] Close js8-app via Dashboard JS8 tile Stop button
- [ ] Confirm SDR++ audio redirected back to default output (or close SDR++)
- [ ] RTL-SDR is released and available for other apps
