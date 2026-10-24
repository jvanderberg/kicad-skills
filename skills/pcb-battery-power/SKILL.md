---
name: pcb-battery-power
description: Designing a battery-powered PCB - choosing the chemistry and cell (Li-ion/Li-polymer, LiFePO4, NiMH, alkaline/lithium primary, coin cells, supercaps), the charger IC (linear vs switching, power path, input current limit, NTC/JEITA), USB-C 5 V charging (CC pull-downs, current advertisement), solar charging, cell protection (protector IC + FETs, fuses), fuel gauging, regulation from a 3.0-4.2 V cell, sleep-current budgets and battery-life estimates, battery connectors and holders, layout, shipping and bench verification. Use it whenever a board runs from or charges a battery, even if the user only mentions a LiPo, 18650, coin cell, AA pack, "how long will it last on a battery", "which charger IC", "USB-C charging", "do I need a protection circuit", "fuel gauge", "JST battery connector", or "why does my board drain the battery".
---

# Battery-powered boards

A battery changes three things about a board. The supply is no longer constant (a lithium cell runs from 4.2 V down
to about 3 V, and its capacity depends on temperature, age and load). Sleep current becomes a design parameter as
important as the active load. And the energy store can hurt someone: a lithium cell that is overcharged, shorted,
punctured or charged below freezing can vent and burn. Every step below catches one of those. Write the numbers down
(design doc or schematic notes) so the battery life and the safety limits can be reviewed.

**Scope.** This is for hobby and personal projects. Single-cell (1S) lithium, small NiMH packs and primary cells are
in scope. Multi-cell series lithium packs, fast charging, high-power packs (e-bikes, power tools, anything with tens
of amps) and anything safety-critical or to be sold should use a certified pack with its own BMS and a certified
charger or charger module, with professional review. Lithium is where a hobby board can start a fire: a protector on
every bare cell, a charger that respects the cell's voltage, current and temperature limits, and never an unattended
first charge are not optional.

References (read the one you need):
- `references/chemistries.md` - chemistry comparison table, coin cells, primaries, NiMH, LiFePO4, supercaps; choosing
  and buying cells and packs, holders, connectors, wire
- `references/charging.md` - CC/CV, C-rate, termination, precharge, timers, NTC and JEITA, linear vs switching, input
  current limit and DPM, power path, USB-C sink, solar, NiMH charging; worked heat example
- `references/protection-and-safety.md` - protector IC + dual FET, fuses/PTC, reverse polarity, thermal and mechanical
  protection, development practice, storage, shipping, disposal, what to do with a swelling or hot cell
- `references/power-path-and-gauging.md` - regulating 3.3 V from a cell, sleep-current audit, battery-life estimate
  (worked example), voltage measurement, fuel gauges, ship mode, low-battery cutoff
- `references/layout-and-mechanical.md` - charger thermal copper, sense resistors, NTC, connector placement, keep-outs
- `references/verification.md` - bench tests and review checklist items
- `references/sources.md` - the datasheets and app notes the numbers come from

## 1. Pin down the requirement

Ask (offer a default with each, as the **kicad-new-board** interview does):
- **Runtime target** and the usage pattern: how long between charges or battery changes, and what the board does in
  that time (always on, wake every minute, used an hour a day).
- **Load profile:** average and peak current per mode (sleep, idle, active, radio TX, motor/LED). Peaks set the cell's
  current rating, the protector's overcurrent threshold and the voltage sag; the average sets the runtime.
- **Sleep current budget:** the sum of everything left powered (regulator Iq, protector, gauge, dividers, pull-ups,
  LEDs, sensors). It often dominates battery life in devices that sleep most of the time.
- **Charge source and time:** USB-C 5 V (most hobby boards), a DC jack, solar, or none (primary cells). Charge time
  follows from the charge current, which the cell datasheet limits.
- **Temperature:** operating range and, separately, the *charging* range. Lithium cells typically may not be charged
  below 0 C (and charge at reduced current below about 10 C); outdoor boards need this designed in.
- **Size and weight,** replaceable vs built-in, and **shipping** (lithium cells by air are dangerous goods; see
  `protection-and-safety.md`).

Estimate the battery life early with `power-path-and-gauging.md`: capacity / average current, derated for the usable
voltage window, temperature, aging and self-discharge. If the estimate misses the target by a large factor, change
the architecture (bigger cell, lower sleep current, less frequent wake), not the arithmetic.

## 2. Choose the chemistry

Use the table in `references/chemistries.md`. Short version:
- **1S Li-ion / Li-polymer** (3.0-4.2 V, some 4.35 V cells): default for rechargeable hobby boards - best energy,
  simple single-chip charging, but needs protection and temperature-limited charging.
- **LiFePO4** (3.65 V charge, flat ~3.2-3.3 V): safer and longer-lived, lower energy, flat curve makes voltage-based
  state of charge poor. Needs a charger set for 3.6-3.65 V - never a 4.2 V Li-ion charger.
- **NiMH** (1.2 V per cell): forgiving cells, awkward charging (peak/-dV detection, temperature, timers); a small
  timer-limited trickle or a dedicated NiMH charger IC.
- **Alkaline / lithium primary** (AA/AAA, Li-FeS2): no charger, long shelf life; never charge them.
- **Coin cells** (CR2032 etc.): for microamp-average loads only; high internal resistance limits pulses.
- **Supercapacitors:** hold-up and energy harvesting, not long runtime.

## 3. Choose the cell or pack

Buy genuine cells from a reputable source (counterfeit 18650s with inflated ratings are common), prefer pouch cells
with a built-in protection circuit module (PCM) or protected cylindrical cells, use a holder or factory-welded tabs
(never solder to a cylindrical cell), and **check connector polarity with a meter before the first plug-in** - 2-pin
JST-PH battery leads are not wired the same way by every vendor. Details in `references/chemistries.md`.

## 4. Design the charger

Choose a charger IC with `references/charging.md`. For a USB-powered 1S lithium board, a linear charger with power
path (the system runs from the input while the cell charges, and runs with a dead or missing cell), an NTC input,
an input current limit for weak USB sources and a safety timer covers most cases. Set:
- the charge voltage to the cell's datasheet value (4.20 V for most Li-ion; check for 4.35 V cells and LiFePO4);
- the charge current to the cell datasheet's standard rate (often 0.5C, lower below 10 C), and check the linear
  charger's dissipation (Vin - Vbat) x Icharge against its package and copper;
- the termination current, precharge and timers per the charger datasheet;
- an NTC thermistor against the cell, wired to the charger's TS input, so it stops charging outside the cell's range;
- the input: USB-C sink with 5.1 k pull-downs on CC1 and CC2, input current limit and VIN-DPM so a weak port is not
  dragged down; a TVS and input protection per the **pcb-power-supply** skill's `input-protection.md`.

## 5. Protect the cell

Every bare lithium cell gets a protector IC with a dual N-FET (overcharge, over-discharge, overcurrent, short
circuit), on the board or in the pack's PCM. Add a fuse or PTC rated for the wiring, reverse-polarity protection on any
battery input a user can plug the wrong way, and keep the cell away from heat and sharp or pressing parts. See
`references/protection-and-safety.md`, which also covers safe development habits, storage, shipping and disposal.

## 6. Regulate, measure and budget the power

Choose the regulator from the cell's *whole* voltage range down to the cutoff (3.3 V from a Li-ion needs a buck-boost,
or a very low-dropout LDO / 100 %-duty buck that accepts losing the tail of the discharge). Audit the quiescent
current of every part that stays powered. Measure the battery with a switched or high-value divider, add a fuel
gauge if state of charge matters, provide a ship-mode or load disconnect for storage, and cut off at low battery in
firmware **and** in hardware. See `references/power-path-and-gauging.md`; regulator sizing itself is in the
**pcb-power-supply** skill.

## 7. Lay it out

Give the charger its thermal pad copper and vias, route sense resistors with Kelvin connections, put the NTC against
the cell, place the battery connector where the cable has strain relief, keep high-current paths short and wide, and
keep heat sources, sharp parts and tall components away from the cell. See `references/layout-and-mechanical.md`.

## 8. Verify

Before ordering: run the design through `references/verification.md` and the **kicad-board-review** skill. On the
bench (state this in the report - it is not optional for a lithium design): the charge profile with a real cell
(current, CV voltage, termination), the temperature cutoff using resistors in place of the NTC, the protector's
short-circuit response with a current-limited supply first, and the sleep current with a meter that resolves
microamps.

## Hand-offs

- Requirements and power budget: **kicad-new-board** (its power step).
- Regulators, inductors, capacitors, input protection: **pcb-power-supply**.
- Real parts, stock, datasheet values: **pcb-part-selection** - charger and protector ICs are rarely JLC Basic parts.
- Review before ordering: **kicad-board-review**.
