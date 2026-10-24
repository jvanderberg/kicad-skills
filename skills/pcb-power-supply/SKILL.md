---
name: pcb-power-supply
description: Designing the power supply on a PCB - choosing between LDO, buck, boost, buck-boost or a module; choosing the controller IC; sizing the inductor, capacitors, feedback/enable dividers and protection; picking real parts that are in stock; laying it out; and verifying it. Use it whenever a board needs a new rail or a regulator is added, changed, questioned or reviewed ("what regulator for 5-24 V in, 5 V out", "is this inductor big enough", "why is my buck noisy/hot", "do I need an LDO", "review the 3.3 V supply"), and for input protection (reverse polarity, surge, inrush, hot-plug).
---

# Power supply design for PCBs

Most board failures that are not wiring mistakes are power mistakes: a regulator that will not start from the lowest
input, an inductor that saturates at the current limit, ceramic capacitors that have lost most of their capacitance at
the working voltage, a hot loop drawn across the board, an input that rings to twice its voltage when a cable is
plugged in. Each step below is there to catch one of those. Work through them in order and write the numbers down
(schematic notes or the design doc) - a supply whose values cannot be traced to a calculation cannot be reviewed.

References (read the one you need):
- `references/power-stage.md` - equations for buck, boost, buck-boost and LDO sizing, with worked examples
- `references/components.md` - inductors, capacitors (DC bias!), diodes/FETs, resistors: what the datasheet numbers mean
- `references/layout.md` - hot loops per topology, placement order, switch node, feedback, grounds, thermal
- `references/input-protection.md` - reverse polarity, surge/TVS, hot-plug overshoot, inrush, fusing, UVLO
- `references/webench.md` - driving TI WEBENCH Power Designer from the browser: what it gives, what needs a login
- `references/sources.md` - the app notes and datasheets these are drawn from

## 1. Pin down the requirement

For every rail: input range (minimum *after* upstream drops: diodes, ideal diodes, fuses, cable), output voltage and
tolerance, continuous and peak load current (radios and motors have peaks far above average), startup and sequencing
needs (does the MCU's own supply depend on anything else?), noise sensitivity of the loads (ADC references, RF, audio),
efficiency or heat budget, and the environment (enclosure temperature, airflow). Also: what happens with the input
reversed, shorted output, a hot-plugged cable, or the highest surge the input can see.

Battery-powered boards (cell choice, charger, protection, gauging, sleep current): see the **pcb-battery-power** skill.

## 2. Choose the topology

| Situation | Choice |
|---|---|
| Vin a little above Vout, low current, or a noise-sensitive load | **LDO** - check P = (Vin - Vout) x I and dropout at the lowest Vin |
| Vin always above Vout with margin, more than ~100-200 mW of loss in an LDO | **Buck** (synchronous for efficiency) |
| Vin always below Vout | **Boost** - output current limited by the switch current limit and duty cycle; no short-circuit protection by nature |
| Vin range spans Vout (e.g. 5-24 V in, 5 V out; battery 3-4.2 V in, 3.3 V out) | **Buck-boost** (4-switch for power, or SEPIC) |
| Need isolation, very high ratio, or not worth the board risk | **Module** (check price, stock, height, EMI) |
| Clean rail from a switcher | Switcher then LDO, or a switcher with good PSRR follow-on filter |

LDO loss is the whole voltage difference times the current: 24 V to 5 V at 0.5 A is 9.5 W - impossible in a small
package. A buck at 90 % on the same job dissipates about 0.3 W.

## 3. Choose the controller IC

- Input range including surge (abs max well above the TVS clamp), output current with margin, current limit (peak
  switch limit, not load rating), switching frequency (higher = smaller L and C, more switching loss and EMI; 0.5-2.2
  MHz is typical), light-load mode (PFM/PSM saves power but makes variable-frequency noise; forced PWM is quieter and
  wastes power at light load), spread spectrum if EMI matters, soft start, power-good, enable/UVLO pin.
- Integrated FETs for up to a few amps; controller + external FETs above that.
- **Startup independence:** the MCU's own supply must come up on its own - a converter that needs I2C configuration
  before its output turns on cannot power the thing that configures it.
- **Variant suffixes** change the part (forced PWM vs auto, fixed vs adjustable output, automotive grade). Read the
  ordering table.
- Stock and assembly class with the **pcb-part-selection** skill. Regulators are rarely JLC Basic; plan for the
  extended-part fee. Prefer the plentiful variant when equivalent.
- **Run the requirement through TI WEBENCH Power Designer** in the browser when browser tools are available
  (`references/webench.md`): in a couple of minutes it lists every TI part that fits with efficiency, area, cost and
  a full power-stage BOM - a fast shortlist and a cross-check on your own sizing. Ask the user before accepting TI's
  terms. Optionally, if the user logs in to myTI themselves, it also gives real MPNs with DC-bias-derated capacitance,
  phase margin and crossover, inductor/IC loss and junction temperature, capacitor RMS currents, and transient
  simulations. For other vendors use their tools (ADI LTpowerCAD, MPS, Richtek) or the
  datasheet's design procedure, which also covers compensation for externally compensated parts.

## 4. Size the power stage

Follow the datasheet's "Detailed Design Procedure" first - it is specific to the part - and cross-check with
`references/power-stage.md`. Essentials:
- **Inductor:** value from the ripple target (20-40 % of output current for a buck), then **I_sat above the IC's peak
  current limit** (so a short or overload does not saturate it) and I_rms above the maximum average inductor current
  with thermal margin. DCR loss = I_rms^2 x DCR.
- **Output capacitors:** within the datasheet's stable range *after DC-bias derating*; enough for ripple and for the
  load step.
- **Input capacitors:** at the pins, rated for the input RMS current (buck: up to Iout/2), voltage rating with margin
  over the maximum input including surge, and enough bulk to damp the input (hot-plug ringing).
- **Feedback divider:** from Vref; bottom resistor typically 10-100 k (datasheet suggests); recompute Vout with the
  standard values chosen; budget the output accuracy (reference tolerance + resistor tolerance).
- **Enable/UVLO divider:** from the EN threshold and hysteresis current; check the EN pin's abs max at the highest
  input; set turn-on above where the converter can actually regulate and below the lowest real input.
- **Bootstrap, soft-start, frequency-set, compensation, spread-spectrum** parts from the datasheet equations.

## 5. Part it out

Real part numbers for every component, checked for stock (pcb-part-selection). Inductor: shielded (molded or
shielded-drum) for anything near sensitive circuitry, with I_sat and DCR from its datasheet at your temperature.
Capacitors: X5R/X7R, chosen from the part's DC-bias curve so the *derated* capacitance still meets the requirement -
usually a larger case size; a higher voltage rating in the same case does not reliably help and can lose more
(`references/components.md`). Resistors 1 % (0.1 % only where accuracy needs it). Put the
calculations and chosen values in the design doc.

## 6. Lay it out

Copy the datasheet's layout example; then check against `references/layout.md`. In order: input capacitor at the
pins (the hot loop), then the IC, inductor and output capacitors, then the small-signal parts (feedback, enable,
soft start) on the quiet side; switch node copper as small as the current allows; feedback taken from the output
capacitor and routed away from the inductor and switch node; ground pour unbroken under the power stage with vias to
the plane at the IC's ground and the capacitors' grounds; AGND/PGND joined where the datasheet says; thermal vias in the
exposed pad.

## 7. Verify

- Calculations reviewed against the datasheet procedure; numbers in the doc.
- Worst-case startup: lowest input after all upstream drops still above UVLO and enough for regulation; highest input
  plus surge below every abs max.
- Losses and temperature: converter efficiency curve at your operating point x load; LDO P = dV x I; check theta-JA
  against the copper you actually gave it.
- Layout review (kicad-board-review skill): hot loop distances edge-to-edge, switch node area, FB/EN routing not
  splitting the local ground, return paths, thermal.
- On the bench (say this in the report; it is not optional for a new design): output ripple with a short ground spring,
  load-step response, startup at minimum and maximum input, temperature at full load, hot-plug of the real cable.
