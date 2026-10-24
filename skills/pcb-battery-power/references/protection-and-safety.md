# Protection and safety

A charger controls the normal case. Protection handles the faults: a charger that fails or is set wrong, a shorted
output, a cell run flat and left, a reversed lead, a crushed pack. Source codes in brackets are in `sources.md`.

## Primary protection: protector IC + dual N-FET

Every bare lithium cell gets one, on the board or in the pack's PCM - the cell maker requires a PCM against
overcharge, over-discharge and overcurrent [Dubilier LP-503759 s6.9]. The usual circuit is a protector IC in the
negative lead driving two back-to-back N-FETs (common drain), one blocking charge and one blocking discharge
[TI BQ297xx p1, s5.1.4-5.1.5]:
- **Overcharge (OVP):** opens the charge FET above a fixed voltage, a backup to the charger's regulation. Pick a
  variant with OVP above the charger's maximum regulation but at or below the cell's absolute maximum (BQ29700:
  4.275 V; HV variants 4.35-4.45 V [TI BQ297xx p3]).
- **Over-discharge (UVP):** opens the discharge FET at the low cutoff (BQ29700: 2.8 V; other variants 2.0-2.8 V
  [TI BQ297xx p3]). Choose a threshold at or above the cell's discharge cutoff.
- **Discharge overcurrent (OCD) and short circuit (SCD):** the IC measures the voltage across the two FETs, so the trip
  current is V_threshold / (R_DS(on),CHG + R_DS(on),DSG). Example (hypothetical): BQ29700's 100 mV OCD with two
  FETs of 10 mOhm each trips near 5 A after 20 ms; its 0.5 V short-circuit threshold trips within about 250 us
  [TI BQ297xx p3, p6]. R_DS(on) rises with temperature and falls with gate drive (the gate is driven from the cell, so
  use R_DS(on) at about 2.5-3.5 V Vgs) - compute the trip current at both ends, and check the cell, wire and
  connector survive the highest one [TI BQ297xx p19-20].
- **Size the trip current for the real load at the real gate drive.** The protector drives the FET gates from the
  cell, so read R_DS(on) at Vgs equal to the cell's minimum (about 3 V at the over-discharge end), not the 4.5 V or
  10 V headline figure: the trip current is lowest when the cell is nearly empty, which is also when a boost load draws
  the most current. A boost from the cell draws I_in = P_out / (eta x V_cell_min): 12 W at 90 % from a 3.0 V cell is
  about 4.4 A, plus inductor ripple at the peak. Hobby DW01-class protectors with 8205A-class dual FETs are commonly
  reported to trip somewhere around 3-5 A (practice, unverified - compute it from the actual parts), which a
  multi-amp boost load can exceed: choose lower-R_DS(on) FETs or a protector variant with a higher threshold, and keep
  the trip below what the cells, wiring and connector survive.
- **Charge overcurrent (OCC)** and zero-volt charging for depleted cells are also typical [TI BQ297xx p1].
- **Drain:** the protector draws current permanently (BQ2970x: 4 uA typical, 5.5 uA maximum in normal mode
  [TI BQ297xx p5]) - include it in the sleep budget.
- FETs: logic-level N-FETs (dual in one package is common), V_DS rated above the charger's maximum input, and a
  5 MOhm-class gate-source resistor where the datasheet recommends one [TI BQ297xx p20]. Hobby pouch-cell PCMs commonly
  use a DW01A-type IC with an 8205A dual FET (practice; check the thresholds of the actual parts).

If a pack already has a PCM, a second protector on the board is not needed; a fuse still is (below). An unprotected
18650 in a holder needs the full protector on the board.

## Secondary protection

- **Fuse or PTC** in series with the cell for the case where the protector or its FETs fail short. Size it above the
  highest normal peak and below what the wiring and connector can carry (JST-PH: 2 A [JST PH series page]). PTC
  hold current falls with temperature; rate it at the enclosure temperature (the **pcb-power-supply** skill's
  `input-protection.md`).
- **Charger features** are a second line too: input OVP, safety timers, thermal regulation, battery short detection
  (`charging.md`). Do not disable them.

## Reverse polarity on the battery input

If a user can connect a pack the wrong way (a JST lead from another vendor, a holder that accepts a reversed cell), a
reversed cell drives large current through every ESD diode and body diode on the board. Options: a P-FET in the
positive lead (gate to ground, Vgs clamped), an ideal-diode controller, or a series Schottky for very low current -
see the **pcb-power-supply** skill's `input-protection.md`. Note that a P-FET on the battery lead must still allow
charging current to flow back into the cell (it conducts both ways once on); a series diode would block charging.
Keyed connectors and holders that physically reject a reversed cell are the cheapest protection.

## Thermal and mechanical

- Keep the cell away from heat sources (regulators, chargers, power resistors, LEDs, motors). Cell temperature, not
  ambient, decides the charge window and the aging rate.
- **Puncture and crushing:** no sharp parts, screws, component leads or through-hole pins pressing on a pouch cell;
  no cell movement inside the housing [Dubilier LP-503759 s6.16]. Put the cell on a smooth surface (foam pad or
  the enclosure wall), not on the back of a populated board.
- **Swelling:** pouch cells grow in thickness with age and abuse; leave some clearance above the cell and do not clamp
  it tightly. Do not bend or fold the pouch or its sealing edge [Dubilier LP-503759 s6.13-6.15]. The heat-seal edge of a
  pouch is electrically conductive - keep it off terminals and copper [Dubilier LP-503759 s6.12].
- **Venting:** cylindrical cells vent from the positive end; do not seal it against a hard surface or the board.
  Avoid airtight battery housings [Dubilier LP-503759 s6.16].

## Development habits

- **Never leave a new design charging unattended**, and never leave an unprotected cell charging. Do the first
  charges on a non-flammable surface (ceramic tile, metal tray) with the board in sight.
- Bring up the charger with a bench supply in constant-voltage mode with a current limit, and a cell simulator or a
  resistor + capacitor load before a real cell (`verification.md`).
- Measure the charge voltage at the cell terminals with a calibrated meter before connecting a cell to a new or
  modified charger.
- Keep loose cells in a case or with taped terminals; stacked or jumbled cells short against each other [Panasonic
  PLI-PSDS-01-EN p1].

## If a cell swells, gets hot, hisses or smells

Disconnect the charger if it can be done safely. Do not puncture, press or keep using it. Move it (with tongs or
gloves, if it is not too hot) to a non-flammable place outdoors or into a metal container with sand, away from
anything that can burn, and leave it. Leave the area if it vents smoke - the vapour irritates eyes and lungs, and
lithium-ion fires release toxic gases. For fire, Panasonic's safety data sheet lists alcohol-resistant foam and dry
sand as effective and advises fighting from the windward side [Panasonic PLI-PSDS-01-EN s5]; for anything more than a
small cell, call the fire service. A swollen cell is finished: dispose of it as below, never recharge it.

## Storage, shipping and disposal

- **Storage:** room temperature, about 30-50 % charge [Panasonic PLI-PSDS-01-EN s7], away from heat and sunlight. A
  stored cell keeps self-discharging (plus protector and board drain), so a device left on the shelf can run its
  cell below the over-discharge limit; provide a ship mode / disconnect (`power-path-and-gauging.md`) and top up
  periodically - one maker says keep stored cells between 3.7 and 4.1 V [Dubilier LP-503759 s6.7].
- **Shipping:** lithium cells and batteries are dangerous goods for air transport. Lithium-ion batteries shipped on
  their own (UN 3480) must be at no more than 30 % state of charge and cannot go on passenger aircraft without
  approval; batteries packed with or contained in equipment are UN 3481 [IATA Lithium Battery Guidance 2026 p4, p8].
  Thresholds at 20 Wh per cell and 100 Wh per battery (Wh = rated Ah x nominal V) change which rules apply [IATA
  Lithium Battery Guidance 2026 p6-7, p10], and the cell maker must provide a UN 38.3 test summary [IATA Lithium
  Battery Guidance 2026 p8]. For a hobby board: buy cells from a seller who ships them legally, and when you send a
  board to someone, check the carrier's rules or ship it without the cell.
- **Disposal:** never in household waste or fire (risk of explosion above about 100 C [Panasonic PLI-PSDS-01-EN p1]).
  Tape the terminals and take it to a battery recycling point.

## Standards (for orientation)

Consumer lithium cells and packs are certified to IEC 62133-2 (safety of portable sealed secondary lithium cells and
batteries under intended use and reasonably foreseeable misuse) [IEC 62133-2:2017 scope] and transport-tested to
UN 38.3. A hobby board cannot claim either; buying a certified pack is how a hobby project gets their benefit.
