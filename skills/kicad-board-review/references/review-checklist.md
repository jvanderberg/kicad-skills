# Design review checklist

What to look at, why it matters, and how to check it with evidence. Each item names the pack file or tool that measures
it. "Example" lines are illustrative, with typical numbers; use them to calibrate what a real problem looks like, not
as values to reuse.

Contents: 1 Power entry and protection - 1b Start-up, shutdown and transients - 2 Copper capacity and heat - 3 Ground and return paths - 4 Regulators and
decoupling - 5 Signal integrity and EMC - 6 ESD and external interfaces - 7 Datasheet compliance and derating -
8 Sourcing and assembly - 9 Mechanical and silkscreen - 10 Firmware-visible consequences - 11 Audits worth scripting

---

## 1. Power entry and protection

Trace every input from the connector to the last load and ask what happens at each step under: normal full load,
reversed polarity, a short on an output, a hot-plug surge, the lowest and highest input voltage, and one input present
while others are absent.

- **Connector and wire rating.** Terminal blocks and jacks have a current rating per pin; at the rated current the
  contact resistance is part of the drop and the heat. Is the rating met with margin at the board's claimed current?
- **Fuse coordination.** Upstream fuse (blade/cartridge) vs downstream resettable fuses (PTC):
  - A PTC's hold current derates with temperature (example: 3 A rated, 2.55 A at 40 C, 2.28 A at 50 C). Rate outputs
    for the enclosure temperature, not the 25 C headline: an output advertised at the 25 C hold current may need
    re-rating well below it.
  - A PTC's maximum interrupt current (I_max) must exceed what the upstream source can deliver into a short, or the PTC
    can be destroyed rather than trip; check I_max >= the upstream fuse's let-through (often 2x its rating is the
    working rule).
  - Blade fuses and holders are rated for continuous current at a derating (commonly 80 %); a rail behind a "20 A"
    fuse is a 16 A continuous rail.
  - Do you need both levels? Even with current measurement and a fast upstream fuse, per-output PTCs still protect the
    wiring of a single output, which the upstream fuse cannot (a 2 A cable on a 20 A fuse). Keep them unless every
    output's wiring is rated for the upstream fuse.
- **Reverse polarity.** Series diode (simple, lossy), P-FET, or ideal-diode controller + N-FET (low loss, needs layout
  care). Check the FET's V_DS and V_GS ratings against the max input plus surge, its R_DS(on) loss at full current,
  and that every part downstream survives the moment before the protection acts.
- **Operating point with the source's and the path's resistance.** For every power path, solve the current instead
  of dividing power by voltage: `pcb-power-supply/scripts/path_budget.py` with each element's resistance (cell or
  cable, FETs at the real gate drive, fuse, BATFET, connector, copper from `power.py`'s R_eff) and the source's corners.
  Compare the solved current and node voltage with every element's limit, latching trips first (example: 15 W from a
  3.0 V cell through ~87 mOhm is 7.1 A, not 5.6 A, past a charger BATFET trip that latches until USB returns).
- **Series-path loss and heat.** Add up fuse resistance + FET R_DS(on) + shunt + connector contacts + copper. Example:
  a 3 mOhm fuse, 1.5 mOhm FET, 2 mOhm shunt and some copper at 20 A is roughly 0.2 V and 4 W per path; several such
  paths are real heat that needs copper area and airflow, and a number the user should know.
- **Surge clamps (TVS).** The clamp voltage at the surge current, not the standoff voltage, is what downstream parts
  see. Compare it with every downstream part's absolute maximum on that rail. Example: a TVS with a 26 V standoff can
  clamp around 42 V at its rated surge, above a 40 V abs max on a sense amplifier or regulator on the same rail -
  acceptable only with input series resistance and the pin-current limit checked, and documented as a known limit.
- **Inputs combined from several sources** (OR-ing diodes, several power inputs feeding a logic supply): the lowest-voltage
  source alone must still start everything. Compute worst case: lowest input - path drops - diode drop - copper drop vs
  the regulator's UVLO / EN threshold. Example: a 5 V input that arrives at the regulator as about 4.3 V after diodes
  and copper is too close to a 4.1 V EN turn-on; lower the threshold (EN divider) or the drops.
- **Enable / UVLO pins.** Check the pin's abs max at the highest input (a divider, not a direct tie, if VIN can exceed
  it), the threshold and hysteresis from the datasheet equation, and that the threshold sits above brown-out behaviour.
- **Power headers that bring rails out.** Can a slipped jumper short a high rail to a low one? Put ground between
  rails, fuse the raw input pin, label pins plainly.
- **Inrush.** Large bulk capacitance behind an ideal diode or hot-swap part: does the controller or the upstream fuse
  tolerate the charging current?

- **Paralleled inputs.** Several connectors tied to one rail need deliberate OR-ing or a stated "one supply only"
  rule; otherwise two supplies back-feed each other.
- **Every output that leaves on a cable** has its own overcurrent element rated for that wire.
- **A small-signal zener is not a surge clamp.** A 500 mW zener across a rail has a tiny pulse rating; use a TVS rated
  by peak pulse power / I_pp.

## 1b. Start-up, shutdown and transients

A board that is fine in steady state can trip, latch or lose a part in the first millisecond. For every rail:
- **Each output switch** (load switch, disconnect FET, eFuse, ideal diode): compute its turn-on time from the gate
  network (gate RC, or Q_g over the drive current) and compare it with the upstream converter's soft-start time. A
  switch that closes before the converter regulates puts the load capacitance straight on the converter's input path;
  for a boost that path is always there (VIN -> inductor -> rectifier body diode -> VOUT), so the inrush is limited
  only by the source and the path.
- **Inrush current** = C_load x dV/dt for every switch-on and hot-plug, added to the load already running, against
  every upstream current trip with its delay (protector OCD/SCD delay, BATFET over-current - often immediate and
  latching - eFuse, PTC/fuse I^2t): `path_budget.py` "transients". Example: a 10 nF gate capacitor turned a P-FET load
  switch on in ~0.1 ms, ~5 A into 100 uF on top of the running load; 100 nF made it ~1 ms and ~0.5 A.
- **Datasheet start-up rules**: maximum output capacitance for soft-start, capacitance-ratio rules for disconnect FETs
  (e.g. capacitance after the FET at most 10x the converter's own output capacitance), required EN delay or sequence.
- **Sequencing**: which rails come up in which order, from what (EN thresholds and dividers), and what is powered while
  the controller is not; nothing back-feeds an unpowered rail through an IO pin or a body diode.
- **Hot-plug**: input capacitance plus cable inductance rings to up to twice the input (pcb-power-supply
  `input-protection.md`); the peak stays under every abs max on that rail.
- **Shutdown and brown-out**: output capacitors discharge somewhere defined; a disabled converter is not back-driven by
  its load; at low battery a load step times the path resistance is smaller than the converter's UVLO hysteresis, or
  the rail oscillates on and off.

## 2. Copper capacity and heat  (`power.md`, `power.py`, `view.py`)

- **Measure the drop and the loss of every high-current path** with the DC solver: input terminal to fuse, fuse to
  FET, FET to shunt, shunt to every load, and the whole ground return at full load. Look at worst-sink drop, copper W,
  and the current density map.
- **Neck-downs.** The current density map (A per mm of copper width) shows where a pour narrows. Rough IPC-2221 limits
  for an isolated 1 mm trace at about 20 C rise: 3.2 A/mm outer, 1.6 A/mm inner. Planes spread heat much better, so a
  hotspot above these is "look here", but a 1.5 mm neck carrying 20 A (13 A/mm) is a real problem. Removing a via
  field or trimming a pour around a power FET can leave exactly that.
- **Thin inner copper.** 0.5 oz inner copper has about 1 mOhm per square. A 200 mm x 1 mm 3.3 V trace on it is about
  0.2 Ohm: 150 mV at a radio's 750 mA peak; 4 mm wide brings it under 40 mV. When there is room, be generous - copper
  is free.
- **Vias carrying current.** `power.py` reports current per via. A 0.3 mm drill via with 20 um plating is about 1.3
  mOhm; at 2 A it dissipates about 5 mW - negligible thermally when both ends land in pours, and it fuses well above
  10 A. The "1 A per via" rules of thumb assume an isolated barrel. What matters more: enough vias that the array's
  drop is small next to the rail's, and that they sit where the current actually flows (the row nearest the load takes
  the most). Example: a dozen vias sharing 20 A unevenly (1-2.5 A each) drop a few mV, small next to tens of mV in
  the rail beyond them.
- **Via grids in planes.** A dense grid of vias through a plane carves it into diamonds; with island removal off, those
  become isolated copper, and with it on, the plane loses area. Use a pitch that leaves webs (about 0.95 x 1.05 mm for
  0.6/0.3 vias with 0.1 mm clearance) and check `planes.py` / DRC `isolated_copper` after.
- **Shunt resistors.** Use the manufacturer's land pattern (wide-terminal shunts need long pads); Kelvin-connect the
  sense lines from the inner ends of the pads; check power rating at the max current (I^2 R) with derating.
- **Heat sources.** List every part dissipating more than about 0.25 W (FETs, fuses, shunts, regulators, PTCs at
  load) and check it has copper and is not stacked next to another hot part or under a tall part that blocks airflow.

## 3. Ground and return paths  (`power.md` ground sections, `planes.py`, `emc.md`)

- **A plane is not zero ohms.** Sheet resistance is about 0.5 mOhm/square (1 oz) or 1 mOhm/square (0.5 oz); 80 A
  across one square of 0.5 oz plane would drop 80 mV. Real planes stay low because current spreads over width and
  layers. Limits are thin copper, current crowding where it enters and leaves (a single terminal pin can funnel the
  whole return), and holes and cuts. Example: tens of amps of load return can lift the board ground tens of mV above
  the input terminal and dissipate watts in the plane, while logic outside the return path stays within a millivolt or
  two of the MCU's ground.
- **Every track on a plane layer cuts the plane.** `planes.py` lists inner-layer tracks and the slots they make, with
  what cuts each slot. For each one: which return currents must detour around it (high-current DC returns and the
  return of any fast signal on the adjacent layer)? Example: a few signal tracks routed on both inner planes across a
  high-current return path can raise the ground loss by half and leave fast signals without a reference.
- **Respect the board's layer plan.** If the designer kept signals off the inner layers, a "quick" inner-layer route
  breaks their intent. Route on the outer layers, reuse existing escape routes, or ask.
- **Stitching.** Ground pours on outer layers need vias to the plane (`weakly_stitched_gnd_pieces`); board edges and
  connectors where cables leave need stitching (`edge_stitch` gaps > 10 mm near cable exits matter for emissions).
- **Inner-layer crossings: how to judge them.** Screen every inner-layer signal segment for its nearest reference and
  the plane slot it makes. A crossing is acceptable when a short, continuous alternate return is verified: the other
  plane is solid there, or a stitching via pair sits within about 1-2 mm on both sides of the cut. Vias alone do not
  repair breaks that line up in *both* planes. Do not chase zero geometric flags by making routes longer; review the
  flagged ones individually, sensitive nets (switching, feedback, analog, protection sense) first. Report counts as
  "needs review", not as proven failures.
- **Split grounds** (AGND/PGND, analog vs digital): join at the single point the datasheet specifies (often the
  regulator's VCC/AGND capacitor) with a net tie, and make sure no signal crosses the split.

## 4. Regulators and decoupling  (`emc.md` hot loops, datasheet layout example)

- **Hot loop first.** For a buck, the input capacitor - high-side switch - low-side switch loop; for a boost, the output
  side; for a buck-boost, both. The capacitor must sit at the pins (measure edge-to-edge; `emc.py` reports pad centres),
  on the same layer, with the ground return directly under or beside it. Compare with the datasheet's layout example
  item by item - it is usually explicit, and small items (a high-frequency capacitor at VOUT, the AGND/PGND tie point)
  are easy to miss without it. Diff the datasheet's typical application against the schematic part by part
  (`kicad-pcb-workflow/scripts/refparts.py` with the project's `reference-parts.json`; write one if it has none):
  a vendor tool's BOM or "a capacitor of that kind nearby" is not evidence that the datasheet's part is there.
  Check each hot loop's electrical numbers in `emc.md` too (ground return resistance, share through the busiest
  via): a 2 mm loop whose return dives through one 0.2 mm via is not a tight loop. Use the project's layout reference pack and compliance file if it has them
  (kicad-pcb-workflow `layout-stages.md`), and re-tick each rule against a net-coloured render (`view.py`) rather than
  trusting the file: a blanket ground pour or a stitching via beside every pad silently breaks single-point analog
  grounds. A deviation marked "no room" needs evidence of what was tried (smaller package, other value, position).
- **Switch node.** Keep its copper area as small as the current allows (`switch_copper`), away from sensitive lines and
  the board edge; nothing sensitive on the layer under it without a plane between.
- **Feedback and enable lines** are high impedance: short, away from the switch node and inductor, and they must not
  split the regulator's local ground pour into islands (if they do, reroute them on another layer as the datasheet's
  layout figure shows).
- **Component limits.** Inductor I_sat above the converter's current limit (not just the load current); capacitor
  voltage rating with DC-bias derating (a 10 uF 25 V MLCC at 20 V may be 3 uF); output capacitance within the
  datasheet's stable range.
- **Spread spectrum / dithering.** If the converter supports it, enabling it lowers conducted and radiated peaks for one
  capacitor (check the modulation-frequency equation).
- **Decoupling.** Every IC power pin has its capacitor within a few mm with a direct via to ground; check the MCU
  core regulator's special requirements (some MCUs' internal switching regulators need a specific, sometimes
  polarity-marked, inductor).

- **LDO heat in small packages.** SOT-23-5 is roughly 200-250 C/W on a typical board: 0.25 W is already a 50-60 C rise.
- **Inductor package sanity.** A 0603/0805 chip or multilayer "inductor" on a switcher is a red flag; check I_sat and
  DCR against the IC's current limit.

## 5. Signal integrity and EMC  (`emc.md`)

- **Reference continuity.** Every fast signal (clocks, SPI/QSPI, USB, SWD, switch-node-adjacent lines, edge-rate-fast
  GPIO) needs an unbroken plane directly beneath it. `emc.md` lists spans over another net's pour or over nothing, with
  coordinates. A span over a different-voltage pour is acceptable only if that pour is well decoupled to ground right
  there; a span over a void is a slot antenna.
- **Layer changes.** When a fast signal changes layers and therefore reference planes, its return current needs a path
  between those planes right there: a ground via within about 1 mm (`layer_changes` lists the distance).
- **Crosstalk.** `emc.md` lists parallel runs with coupled length and a rough coupling factor
  k = 1/(1 + (D/h)^2) (D centre spacing, h height to the plane). Long parallel runs of clocks next to data or of a bus
  next to a sensitive line deserve 3x-width spacing or a ground track. Broadside coupling to the adjacent layer counts
  too. Sanity-check high numbers - short crossings are not parallel runs.
- **Termination and edge rates.** Source-series resistors (22-33 Ohm) on clocks and SPI clocks that run more than a few
  cm; required series resistors per the MCU datasheet (some MCUs need series resistors, often 27 Ohm, on USB D+/D-).
  Where there is no room, slow the edges in firmware (slew rate, drive strength) and say so.
- **Route length.** Long, meandering high-speed buses (e.g. a radio's SPI link wandering across the whole board to
  reuse old routes) are both an SI and an emissions problem; shorter is the fix.
- **Edges and cables.** Fast copper within 1 mm of the board edge (`edge_proximity`) radiates; anything that leaves the
  board on a cable (LED strips, sensors, long buses) is an antenna - series resistance at the driver, filtering, and stitching
  near the connector.
- **Differential pairs.** Length matched (skew in `diff_pairs`), coupled, same layer, no stubs, impedance near target.
- **I2C and other slow buses.** Slow does not mean immune. Check total bus capacitance (about 10 pF per device plus
  about 1 pF/cm of trace) against the pull-up for the rise time at the chosen speed (t_r ~ 0.85 R C must be under
  1000 ns at 100 kHz, 300 ns at 400 kHz); route away from switching nodes and noisy pours; keep it on outer layers if
  the board's discipline requires it.

- **Classify interface speed from the chip's datasheet**, not the connector: a full-speed (12 Mbit/s) USB device on a
  short run needs no 90 Ohm controlled impedance. Rule for when a trace needs termination: knee frequency ~0.35 / t_rise;
  terminate when the trace is longer than about 1/6 of the rise-time distance (~15 cm/ns on FR4).

## 6. ESD and external interfaces

- Every pin that reaches a connector or a button the user can touch: TVS or ESD array at the connector, with the
  series resistor (if any) between the TVS and the IC so the TVS takes the energy and the resistor limits what is left
  (example: a TVS on each data output at the connector side of its series resistor).
- Inputs from the outside world (IR receivers, sensors on cables): series resistor plus a clamp to the rail
  (e.g. about 1 k in series and a Schottky clamp to the logic rail at the connector).
- USB: ESD array close to the connector, shield connected per the design intent, any series resistors the MCU requires
  placed at the MCU.
- TVS standoff above the normal signal level, clamp below the protected part's abs max at the surge current, and low
  capacitance on fast lines.
- Ground the ESD return directly to the plane with short, wide connections; ESD current that has to find its way
  through a thin trace upsets everything on the way.

- **ESD level and parts:** user-touched ports usually target IEC 61000-4-2 level 4 (+/-8 kV contact, +/-15 kV air).
  The contact first peak is about 3.75 A per kV (30 A at 8 kV): judge an ESD part by its datasheet clamp voltage at the
  IEC level, not by its 8/20 us I_pp.
- User-accessible sockets (microSD) and long-cable data links count as external interfaces.
- **Off-board accessory pinouts** (3.5 mm jacks, generic headers) have no standard: check against the real accessory, and
  check an external 5 V signal against the exact GPIO's tolerance (5 V tolerance often excludes ADC-capable pins).

## 7. Datasheet compliance and derating (per IC, actually read the PDF)

Derate everything; datasheet maxima are limits, not targets:
- Capacitors with voltage margin over the maximum (1.5-2x is common practice, not a manufacturer rule); MLCC capacitance
  checked *after* DC-bias derating from the part's own curve - a higher voltage rating in the same case can lose more (a 10 uF 25 V
  0805 at 12 V can be under half its value). Ceramics at the pins, bulk at power entry.
- Resistors at 50 % of rated power or less (hot resistors drift; shunt tempco sets current accuracy - keep shunts and
  their amplifiers away from hot parts).
- Semiconductors: SOA at the worst-case voltage and current at the real case temperature, not 25 C; theta-JA ratings
  assume a copper area - check the board gives that area.
- Every pin of every IC deliberately handled: tied, pulled, or explicitly no-connect per the datasheet (example of what
  goes wrong: mode pins hard-tied to the wrong level, status LEDs fed from a rail that can exceed the pin rating).
  A no-connect flag makes ERC silent, so audit them: `kicad-pcb-workflow/scripts/nc_audit.py` lists every unused pin,
  every pin the symbol types no_connect, and every input strapped to a rail; each row needs the datasheet's pin-table
  instruction (`--datasheet REF=ds.pdf` prints it). A symbol's NC type is the symbol author's guess, not a decision:
  an "NC" pin can be one the datasheet says to ground.

For every IC and every non-trivial discrete:
- **Absolute maximum per pin**, including pin current limits (example: when a TVS clamps above a sense input's voltage
  abs max, series resistance that keeps the pin current within its few-mA limit is what makes it acceptable).
- **Required external parts** and their values (series resistors, pull-ups for pins that reset with pull-downs, a pull-
  up on a second chip select, bootstrap caps): every part in the datasheet's typical application, matched to the
  schematic part that satisfies it (`refparts.py`), or a recorded reason it is left out.
- **Variant suffixes** that change the part: voltage (memories and regulators sold in 3.3 V and 1.8 V versions that
  differ by one suffix letter), forced PWM vs auto light-load mode, automotive vs commercial, package.
- **Power-up behaviour** (example: some converters need I2C configuration before their output turns on - unacceptable
  for the MCU's own supply).
- **Addresses and straps** from the address table, and **register semantics** (signed vs unsigned, LSB size).
- **Pin functions** confirmed in the SDK header or reference design, not from memory.
- **Land pattern** from the datasheet, compared against the footprint used (imported footprints are often off: pad
  positions, missing courtyards, 3D model offsets).
Download PDFs and read them (`pdftotext -layout`; render figures with `pdftoppm`). LCSC datasheet links return an HTML
page that contains the real PDF link.

- **Data direction: make absolutely sure it is not swapped. Check it twice, then a third time.** A swapped DI/DO,
  TX/RX or MOSI/MISO pair passes ERC, DRC and parity and kills the board. For every serial, memory and UART connection,
  trace each line from the driving pin to the receiving pin and confirm the direction from *both* datasheets: an
  output must meet an input (TX -> RX, MOSI/SDO/DO -> SDI/DI, MISO/SDI <- DO/SDO), and numbered data lines (D0, IO0,
  SD0...) must meet the same index on the other side as the MCU's reference design shows. Names are relative to each
  chip, so matching names is not evidence; "DO to DO" can be right or wrong depending on whose DO it is.
- **Active level of every enable / OE / reset / CS / shutdown pin** from the datasheet truth table, never from the
  symbol label: imported symbols often drop the overbar.
- **Supply and ground pins after any symbol or footprint swap**: every one connected. Imported symbols often type
  pins as passive, so ERC does not complain about a floating ground.
- `netdigest.py` prints mechanical audits for these at the end of `netlist.md` - a prompt to check, not a substitute.
- **Resistor power on high rails:** every LED / pull resistor's I^2 R at the highest rail voltage (a 1 k 0402 on 12 V
  dissipates 100 mW against a 62.5 mW rating; at 24 V a 0402 at 50 % derating allows about 1.4 mA).

## 8. Sourcing and assembly  (the **pcb-part-selection** skill, `bom_check.py`)

- **Every BOM part has its datasheet link and sourcing data**, in the schematic and on the board, identical in both
  (`kicad-pcb-workflow/scripts/partfields.py check SHEET BOARD`; `netlist.md` section 7 lists BOM parts with no
  link). A blank Datasheet on a part with an LCSC number means a stage threw the link away; it is a finding, and the
  reviewer cannot have read a datasheet the board does not name.
- Every part in stock for the order quantity plus attrition, in the region the assembler buys from; re-check right
  before ordering (stock moves daily; a part with a handful of units can sell out or be restocked within a week).
- Special parts with no substitute (polarity-marked inductors, specific crystals, modules): find the second source or
  plan consignment now, not at order time.
- Package sizes the assembler can place economically (no 0201 at JLC economic), Economic vs Standard assembly per part,
  extended-part fees, single-sided assembly if that is the plan.
- Avoid single-source, NRND/EOL and counterfeit-prone parts; note approved alternates for anything critical. Check
  lifecycle on the manufacturer's page, not by distributor stock (`pcb-part-selection/scripts/part_gate.py`; a 404
  product page = treat as discontinued), and check that each design value came from the datasheet of the exact
  orderable variant fitted. Keyed,
  retained connectors for anything a user plugs in (no bare pin headers in production).
- A project stock policy is worth stating explicitly (example: at least 1,000 listed units per MPN, with named
  user-approved exceptions), then checked mechanically.
- Every polarised or oriented part checked in the assembler's placement preview; fix rotation permanently with
  `Rotation Offset` / `Position Offset` fields on the symbol rather than per order.
- Fabrication outputs (gerbers, BOM, CPL) regenerated after the last change - compare their timestamps with the board's
  (stale exports are a common release blocker).

## 9. Mechanical and silkscreen

- Tall parts: 3D clearance between them and nearby parts (fuse holders, terminal blocks, electrolytics, connectors) -
  render in 3D, check model offsets. Run `kicad-pcb-workflow/scripts/board_lint.py` first: a missing 3D model file
  renders as bare pads and looks like an empty spot; it also lists footprints without courtyards (invisible to DRC's
  overlap check) and silkscreen text on other parts' bodies (DRC does not check silk against bodies).
- Mounting holes: keepout around the screw head and washer; no copper or parts under it unless intended.
- Connectors at the edge, oriented so cables leave the board cleanly; polarity marked.
- Heat: spread hot parts apart; keep precision analog, electrolytics and oscillators away from FETs and regulators;
  thermal reliefs on pads in big pours so they solder; thermal vias under hot pads but never unfilled via-in-pad on
  pads that get paste (solder wicks away). Mechanically support heavy parts and connectors (a mounting hole near the
  connector so cable tugs do not load solder joints). Creepage and clearance on high-voltage nets.
- Test and production: test points for every rail, ground and key signals, on one side, labelled, with a ground pad
  nearby; board name and revision on silk matching the BOM and gerbers; fiducials if the assembler wants them; parts
  clear of panel edges; rework access; tall parts not shadowing short ones.
- Silkscreen: readable size (>= 1 mm text, >= 0.15 mm lines), not on pads, labels that match the function (and the
  physical order, or the firmware must remap), plain - no decoration the user did not ask for.
- External connections usable without the schematic: every connector and solder pad labelled with its function (both
  sides if wires are soldered from either side), polarity and pin 1 marked, one pad-shape convention, pairs in the same
  order everywhere.

- **Thermal vias:** a 0.3 mm plated via through 1.6 mm is roughly 100-200 C/W each, so they work in numbers: about 9 at
  1.0-1.2 mm pitch under a 3x3 mm exposed pad, or the datasheet's pattern.
- **Electrolytic life** roughly doubles per 10 C below its rating (L = L0 x 2^((T_rated - T_actual)/10)): keep them away
  from hot parts.
- **Test points:** about 1 mm pads at >= 2-2.54 mm pitch, one side, >= 3 mm from the edge for fixtures; SWD and boot
  reachable with the board in its enclosure.
- **Fab capabilities** (re-check on the fab's site for the chosen service; they change): minimum trace/space, drill,
  via diameter and annular ring (via and PTH separately), aspect ratio (0.2 mm drill in 1.6 mm = 8:1, a common limit),
  copper-to-edge clearance, filled/capped via-in-pad cost, solder-mask web between fine-pitch pads (0.4 mm-pitch QFN
  leaves ~0.1 mm of web - at the minimum; check the mask expansion or accept a ganged opening). Tie any cost claim to
  the fab's current price page.

## 10. Firmware-visible consequences

A review should end with what the firmware must know or enforce, because hardware compromises often land there:
current and power limits that protect hardware (PTC derating, continuous ratings per output or rail), sensor polarity
or wiring differences (example: a current monitor wired with swapped inputs reads negative, and its bus-voltage pin may
sit on the other side of the shunt), I2C addresses, calibration needs (zero offset with the loads off), pin drive and
slew settings standing in for missing series resistors, and startup ordering.

## 11. Audits worth scripting

Some properties are cheap to prove with a script and expensive to discover on a built board:
- **Net intent:** after KiCad loads and refills the board, every track and via still has the net you assigned. Vias
  touching only pours can be re-netted by KiCad (mark stitching and thermal vias `(free yes)`), and moved pads rename
  the tracks attached to them.
- **Kelvin sense:** temporarily give the sense trace its own net name in a copy, run DRC, and confirm it touches only
  the intended shunt pad (not the pour or the power trace beside it).
- **Paste and vias:** exposed-pad paste coverage (about 50 % in a window pattern is typical), no via drill under a
  paste aperture, tenting requested for vias near pads.
- **Capture contract:** `kicad-pcb-workflow/scripts/netspec.py` asserts the topology you meant (SPLIT, SHORT, MISSING,
  UNEXPECTED against an intended netlist). It catches silently dropped symbols, miswired series parts and shorts that
  ERC passes.
- **Exemptions:** if the project filters its DRC report, every exemption must name the item and the reason
  (`drc_summary.py --accept`); a filter that drops a whole violation type is itself a finding.
- **Change scope:** `board_diff.py` (kicad-pcb-workflow) against the last commit, so a rebuild cannot quietly revert
  someone else's edits.

Keep the distinction explicit in reports: these are *design* checks. Electrical, thermal, reflow and load
qualification on real hardware are separate, and a board is not "ready to fabricate" because the design checks pass.
