# Verification

Design checks first, then the bench. The bench tests are what qualify a battery design; say so in any review report.

## Review checklist (before ordering)

Use with the **kicad-board-review** skill (`review-checklist.md` sections 1, 4, 7 and 10).
- [ ] Cell datasheet on file; charge voltage, charge current (and the cold rate), charge and discharge temperature
      ranges, cutoff voltage and maximum discharge current recorded in the design doc.
- [ ] Charger regulation voltage variant matches the cell (4.20 / 4.35 V / LiFePO4 3.6 V); the ordering suffix checked.
- [ ] Charge current from the program resistor at the K-factor extremes stays within the cell's limit.
- [ ] Linear charger worst-case dissipation (Vin_max - V_precharge_threshold) x I_charge computed and covered by copper
      or thermal regulation.
- [ ] Battery-path heat at the lowest cell voltage and full load (protector FETs, reverse-block FET, fuse, BATFET,
      copper: I^2 R at the solved current, R_DS(on) hot) and the charger's loss while charging and running, in the
      review's heat-source table with board temperatures (kicad-board-review `thermal.md`).
- [ ] NTC fitted against the cell, wired to TS; trip temperatures computed for the actual thermistor and within the
      cell's charge range. TS not disabled.
- [ ] Safety timers enabled and long enough for the capacity at the programmed current.
- [ ] Input: USB-C CC1 and CC2 each with its own 5.1 k; input current limit fits the source; TVS and OVP rated for
      the input.
- [ ] Input power covers system peak and charging at the same time (`charging.md` "Charging while running").
- [ ] With a PD sink: the charger's input current limit is within the negotiated contract, the fallback when the
      requested voltage is not offered is known (or designed for), and the D+/D- (BC1.2) wiring decision is recorded.
- [ ] Protector trip current at the cell's minimum voltage covers the peak load: the boost input current **solved with
      the path resistance** (cell, FETs, fuse, BATFET, copper; `pcb-power-supply/scripts/path_budget.py`), not
      P / (eff x V_cell_min), and the same current checked against the charger's BATFET over-current limit (some latch
      off until the input returns) and the converters' UVLO at the resulting system voltage.
- [ ] Start-up: every load switch turns on after its converter is regulating, and the inrush (C x dV/dt) plus the
      running load stays under every upstream trip at an empty cell (kicad-board-review checklist s1b).
- [ ] Power path: the system runs with no cell and with a dead cell; downstream regulators rated for the highest
      system voltage.
- [ ] Protector on every bare cell (or PCM confirmed in the pack); OVP / UVP thresholds suit the cell; overcurrent trip
      current computed from the FETs' R_DS(on) at the real gate drive, hot and cold; wire, connector and fuse rated for
      it.
- [ ] Reverse-polarity behaviour of the battery input known (protected, or keyed, or documented as a risk).
- [ ] Regulator works over the full cell range to the chosen cutoff, including the sag at peak current.
- [ ] Sleep-current audit totalled; battery-life estimate with derating in the doc.
- [ ] Battery measurement divider draws an acceptable current and stays within the ADC range at maximum charge voltage.
- [ ] Firmware low-battery cutoff above the protector's UVP, and a hardware cutoff (EN/UVLO or supervisor).
- [ ] Ship mode or disconnect for storage, if the device sits on a shelf.
- [ ] Layout: charger thermal pad vias, Kelvin sense routing, NTC position, connector strain relief, keep-outs under
      the cell, polarity on the silkscreen, test points.

## Bench tests

Do them in this order, on a non-flammable surface, with the board in sight.

1. **Charger without a cell.** Bench supply on the input (5 V, current-limited). Check the system rail, the status
   pins and the open-circuit battery-pin behaviour (many chargers toggle charge/done with no cell - expected
   [BQ25185 s6.3.10]). Measure the CV voltage at the battery pin with a calibrated meter before a cell is ever
   connected.
2. **Simulated cell.** A second bench supply set to 3.0-3.7 V, able to sink current (or a supply with a power
   resistor in parallel so it absorbs the charge current), or an electronic load in CV mode, at the battery terminals.
   Step its voltage through precharge, CC and CV regions and watch the current: precharge level, fast-charge current,
   taper and termination.
3. **Temperature cutoff.** Replace the NTC with fixed resistors equal to the thermistor's value at the cold and hot
   trip temperatures (from its R-T table) plus and minus a few degrees, and confirm charging stops and resumes where
   expected. For JEITA chargers, also check the reduced-current and reduced-voltage bands.
4. **Real cell, first charge, attended.** A partly discharged genuine cell. Log voltage and current (and the cell's
   surface temperature) through a full charge: CC current, CV voltage at the cell terminals (4.20 V +/- the charger's
   tolerance, never above the cell's maximum), termination current, total time against the safety timer. Check the
   charger temperature with a thermocouple or thermal camera at the start of fast charge.
5. **Protection.** First with a current-limited bench supply in place of the cell: raise the voltage past OVP and
   lower it past UVP and confirm the FETs open (and recover as specified). Then the overcurrent and short-circuit
   test: with the bench supply's current limit set above the expected trip, apply an electronic load step or a short
   on the system side and confirm the protector opens within its delay. Only after that, a brief short test with a
   real cell, if at all - and never with an unprotected cell.
6. **Sleep current.** A meter that resolves microamps in series with the battery (a uA range of a good DMM, a
   source-measure unit or a dedicated power profiler that also captures the wake pulses, since a DMM's burden voltage
   on a uA range can brown the board out during a wake). Measure every sleep state and with the charger input
   removed; compare with the audit. Then measure the wake-cycle average and recompute the life estimate.
7. **Runtime.** Run a full discharge at a representative load profile and confirm the low-battery cutoff acts before
   the protector's UVP, at room temperature and, if the board must work cold, at the low end.
