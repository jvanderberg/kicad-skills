# Layout and mechanical

Follow the charger's and protector's datasheet layout sections first; then check against this list. General
regulator layout (hot loops, feedback, grounds) is in the **pcb-power-supply** skill's `layout.md`.

## Charger

- **Thermal pad and copper.** A linear charger turns (Vin - Vbat) x Icharge into heat in its package
  (`charging.md`); the copper is the heatsink. Solder the exposed pad to a ground pour with a grid of thermal vias into
  the inner planes and a bottom pour, and give the pour area on the top layer around the IC. The thermal pad is often
  also the main ground connection (BQ2407x: connect it to ground with plenty of vias; VSS must still be connected
  [BQ2407x p9, s12.1]). Microchip's layout uses the VSS copper and vias as the heatsink [MCP73831 s6.2].
- Keep the charger away from the cell and the NTC: a hot charger next to the thermistor reads as a hot cell, and
  next to the cell it warms the cell.
- Input and output capacitors at the pins with short returns to the thermal-pad ground [BQ2407x s12.1]; the
  battery-side capacitor at least the datasheet's minimum (MCP73831: 4.7 uF on VBAT for stability with the battery's
  inductive leads [MCP73831 s6.1.1.4]).
- Program resistors (ISET, ILIM, PROG, TMR) next to their pins, returned to the IC's ground, not routed past the
  inductor of a switching charger. A shorted or open program pin is a fault some chargers detect; a long noisy trace
  is not.
- Switching chargers: hot-loop and switch-node rules as for a buck.

## Battery current path

- Battery connector -> fuse -> protector FETs -> system: short and wide, sized for the protector's overcurrent trip
  (the highest current that can flow before it opens), with the DC drop checked (kicad-board-review `power.py`).
- **Protector sensing:** the IC measures the voltage across the FETs between its V- and VSS pins; route those
  connections from the FET pads themselves, so trace resistance does not shift the trip current, and keep the
  protector's supply RC filter (from the datasheet) next to the IC.
- **Fuel gauge sense resistor:** Kelvin-connect SRP/SRN from the inner ends of the 10 mOhm shunt pads as a pair, SRP to
  the battery side [BQ27441-G1 p4]; route the gauge's battery voltage sense directly to the cell's positive terminal.
- All charge current returns through the cell's negative lead: keep the cell negative, protector and charger ground
  close together and on a solid pour.

## NTC thermistor

- Place it where it measures the cell: against the cell body (taped or in the pack), or on the board right under a
  board-mounted cell, with a copper island that does not connect it thermally to hot parts. Many packs bring out a
  third wire for a built-in NTC - use it when present.
- Wire it as a pair (TS and its ground return) to the charger's TS pin and the charger's ground, not a noisy shared
  return; add the filter capacitor if the datasheet shows one.
- If the NTC is on a cable, protect the TS pin from ESD and give the thermistor footprint a fixed-resistor alternative
  for bench tests (`verification.md`).

## Battery connector and cell

- Place the connector at the board edge where the lead reaches the cell without tension or a sharp bend, with strain
  relief (a tie point, glue or a slot in the enclosure). Pull-out by the wire is how pouch tabs and crimps fail.
- **Silkscreen + and - at the connector,** large and unambiguous; the 2-pin JST-PH polarity of bought packs varies
  (`chemistries.md`).
- Test points on battery +, battery -, the protected system rail, TS and the charger status line.
- **Keep-outs under and around the cell:** no tall parts, no through-hole leads or sharp solder points under a
  board-mounted or adjacent pouch cell; a smooth area (or a foam pad) for it to sit on, with room for swelling; mount
  holes and screws away from the cell; draw the cell's outline on a user layer so later changes respect it.
- Coin-cell holders: the negative contact is often a pad under the cell - follow the holder's land pattern exactly
  and keep traces from running under it unprotected (the cell can short to them through scratched mask).
- Cylindrical cell holders: rate the contacts for the peak current; position so the positive (venting) end is not
  sealed against a wall.

## Enclosure

Ventilation for the cell, no airtight sealing [Dubilier LP-503759 s6.16], the cell held so it cannot move, and
nothing in the enclosure that can press on it when the lid closes.
