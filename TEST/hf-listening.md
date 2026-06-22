# HF / General Listening

## Antenna Setup — Inverted V

- [ ] Apex as high as possible (tree, mast, anything — every metre counts)
- [ ] Arms angled ~120–135° from vertical — not flat, slight droop is correct
- [ ] Feedpoint at apex: coax center → one arm, coax braid → other arm
- [ ] Keep feed cable away from arms for first metre (reduces common-mode noise)
- [ ] Orient arms N–S or E–W depending on which direction you want to favour
- [ ] Ends of wire tied off and clear of ground (>0.5m if possible)
- [ ] Coax run away from CD equipment (noise source — more cable = less interference)

## SDR++ Configuration for HF

- [ ] Source: RTL-SDR Blog V4
- [ ] Enable Direct Sampling: Q Branch (in source settings — required for HF below ~24 MHz)
- [ ] Gain: start at 10–20 dB (HF signals are much stronger than UHF — avoid clipping)
- [ ] Waterfall range: adjust so noise floor is visible but not saturated
- [ ] Tune to a known strong signal first to confirm reception (e.g. 9.400 MHz shortwave)
- [ ] Mode: USB for ham bands above 10 MHz / LSB for ham bands below 10 MHz / AM for broadcast

## Daytime — Best Bands (09:00–18:00)

- [ ] **20m — 14.000–14.350 MHz** — best daytime band; your 10m wire is near-resonant here
  - USB above 14.150 / CW below 14.150
  - JS8Call digital: 14.074 MHz
  - FT8: 14.074 MHz (same as JS8, tune around)
  - SSB voice: 14.150–14.350 MHz
- [ ] **17m — 18.068–18.168 MHz** — less crowded than 20m, good DX
  - USB throughout
  - FT8: 18.100 MHz
- [ ] **15m — 21.000–21.450 MHz** — good when solar flux is decent (we're near cycle 25 peak)
  - USB throughout
  - FT8: 21.074 MHz
- [ ] **10m — 28.000–29.700 MHz** — solar cycle dependent; when open, amazing DX
  - USB for SSB / FM simplex: 29.600 MHz
  - FT8: 28.074 MHz
- [ ] **Shortwave broadcast — 31m band: 9.400–9.900 MHz** — BBC, RFI, DW, Vatican
- [ ] **Shortwave broadcast — 25m band: 11.600–12.100 MHz**
- [ ] **Shortwave broadcast — 19m band: 15.100–15.800 MHz**

## Evening — Best Bands (18:00–22:00)

- [ ] **40m — 7.000–7.200 MHz** — opens at dusk, best European regional band
  - LSB throughout (European ham convention)
  - FT8: 7.074 MHz
  - JS8Call: 7.078 MHz
  - SSB voice: 7.060–7.200 MHz
- [ ] **20m — 14 MHz** — still usable early evening, fades after ~21:00
- [ ] **80m — 3.500–3.800 MHz** — starts opening, strong regional (300–1000 km)
  - LSB throughout
  - CW/digital: 3.500–3.600 MHz
  - SSB voice: 3.600–3.800 MHz
- [ ] **Shortwave broadcast** — most broadcasters target this window, all SW bands active

## Night — Best Bands (22:00–06:00)

- [ ] **40m — 7 MHz** — excellent, covers Europe + North Africa well
- [ ] **80m — 3.5 MHz** — strong regional, lots of voice + CW
- [ ] **60m — 5.300–5.405 MHz** — limited ham allocation, some activity, good NVIS
- [ ] **20m — 14 MHz** — can still have long-path DX openings (trans-equatorial)

## Quick Reference — Notable Fixed Frequencies

- [ ] **Time signals — WWV (USA):** 2.500 / 5.000 / 10.000 / 15.000 / 20.000 MHz (AM)
- [ ] **Weather fax — DWD Hamburg:** 3.855 / 7.880 / 13.882 MHz (USB, use WEFAX decoder)
- [ ] **Maritime SSB (calling):** 4.125 / 8.291 / 16.522 MHz
- [ ] **Aviation HF (Shanwick):** 5.598 / 8.906 / 13.306 MHz — North Atlantic traffic (USB)
- [ ] **FT8 summary:** 3.573 / 7.074 / 10.136 / 14.074 / 18.100 / 21.074 / 28.074 MHz
- [ ] **JS8Call summary:** 7.078 / 14.074 / 21.078 MHz

## Propagation Tips

- [ ] If 20m is noisy/dead → try 17m or 15m (higher bands, less QRM)
- [ ] If nothing above 10 MHz → try 40m even during day (shorter skip, regional only)
- [ ] Lots of signals but can't decode speech → check mode (USB vs LSB vs AM)
- [ ] Signal strength varies — wait 2–5 min before giving up on a band
- [ ] Inverted V favours broadside directions (perpendicular to the wire arms)
- [ ] Solar flux > 150: 10m likely open. Check: prop.kc2g.com or DX cluster spots
