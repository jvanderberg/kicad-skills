# Switching regulator layout

The datasheet's layout example is the primary reference: follow it item by item, then check against this list.
Sources: TI SNVA021 (AN-1149), SLYT614, SLVA773, SLVA535B; listed in `sources.md`.

## 1. Find the hot loop first

The hot loop is the path whose current switches abruptly every cycle; its area sets the radiated and conducted noise
and the switch-node ringing.

| Topology | Hot loop | Placed first, closest to the IC |
|---|---|---|
| Buck | input capacitor -> high-side switch -> low-side switch -> back to the input capacitor ground | **input** capacitor |
| Boost | output capacitor -> rectifier/high-side switch -> low-side switch -> back to output capacitor ground | **output** capacitor |
| 4-switch buck-boost | both of the above | input **and** output capacitors |
| Inverting / SEPIC / flyback | per the datasheet; usually two loops | per the datasheet |

Put a small high-frequency ceramic (e.g. 100 nF 0402) right at the IC's VIN/PGND (or VOUT/PGND) pins on the same
layer, then the larger ceramics, then bulk. No vias in the hot loop if it can be avoided; if the return must change
layer, use several vias right at the capacitor pad.

## 2. Placement order

1. IC.
2. Hot-loop capacitors (above), on the same layer as the IC.
3. Inductor, close to the switch pin(s), so the switch node is short.
4. Output capacitors, with their ground returning directly to the IC's power ground.
5. Small-signal parts (feedback divider, compensation, soft-start, frequency set, enable divider) on the quiet side
   of the IC, near their pins, away from the inductor and switch node.
6. Input filter / bulk / protection between the connector and the input capacitors.

## 3. Switch node

Only as much copper as the current needs: it is the strongest radiator on the board (fast dV/dt). Keep it away from
feedback, analog and clock traces, and from the board edge. Do not route sensitive traces on the layer directly below
it unless a solid ground plane is in between. Leave room for an optional RC snubber across the low-side switch if the
datasheet suggests one.

## 4. Feedback and sensing

- Take the feedback from the output capacitor (the point you want regulated), not from the inductor end.
- Put the divider next to the FB pin so the high-impedance node is millimetres long; the long trace runs at Vout, low
  impedance.
- Route FB, COMP, enable and current-sense lines away from the inductor and switch node, and do not let them cut the
  regulator's local ground pour into islands.
- Current-sense lines (ISP/ISN, CS): Kelvin connections from the inner ends of the shunt pads, as a pair.

## 5. Grounds

- A solid ground plane under the whole power stage (on the adjacent layer in a 4-layer board) with vias at every
  capacitor ground pad and at the IC's ground pads/exposed pad.
- If the IC has separate AGND and PGND, join them at the single point the datasheet specifies (often at the IC or the
  VCC/bypass capacitor) - a net tie in KiCad - and keep switching currents out of AGND [SLYT614, SLVA773].
- No slots or signal tracks through the ground plane under the hot loop.

## 6. Thermal

- Exposed pad: soldered to a copper area with thermal vias (often a 3x3 to 5x5 grid of 0.3 mm vias at ~1.0-1.2 mm
  pitch) into the inner ground planes and a bottom-side pour. Follow the datasheet's pattern and its paste guidance;
  use a windowed paste pattern (about 50 % coverage) so the part does not float.
- The datasheet's theta-JA is measured on a JEDEC test board and is not your board's number; heat leaves mostly through
  the board copper, so copper area and vias matter more than the package [TI SPRA953D].
- Spread hot parts (inductor, IC, rectifier) apart; keep electrolytics and precision analog away from them.

## 7. Via current

Published "current per via" rules disagree (one via per 200 mA vs one per amp) and do not state the via size; use a
via current calculator or the DC drop solver for your drill and plating, and put enough vias in parallel that their
drop and heating are negligible next to the trace's.

## 8. Input filter (if needed for conducted EMI)

An LC filter at the input must not destabilise the converter: put its resonance at least a decade below the switching
frequency and damp it - a damping capacitor of at least 4x the converter's input capacitance with ESR around
sqrt(L_filter / C_in) is the usual approach [TI SNVA489].

## 9. Checks after layout

Measure (kicad-board-review skill, `emc.md` hot loops) the hot-loop capacitor distance edge-to-edge, switch-node copper
area, FB/EN routing, ground pour continuity; then on the bench: switch-node ringing with a short ground spring,
output ripple, load-step response (a well-damped response shows no more than a few rings; more indicates low phase
margin [TI SLVA115A]), and temperature at full load.
