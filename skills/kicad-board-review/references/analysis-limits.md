# What the analysis pack cannot see

- **DC only.** No AC impedance, no field solving, no resonance. Crosstalk uses the 1/(1+(D/h)^2) rule of thumb; Z0 is
  closed-form microstrip over the nearest copper layer (stripline overstated).
- **Copper at 20 C**, no plating build-up on outer layers, 20 um via plating, solder in plated holes ignored. Hot
  copper is about 0.39 % per C worse.
- **Components are not in the DC model.** Fuses, FETs, shunts, PTCs, connector contacts and wires add their own drops
  (`path_budget.py` adds them to the operating point; `thermal.py` adds their heat).
- **Zone fills are KiCad's saved fills** after the pack's refill of a copy. If the user's file was saved without a
  refill, the user's board can differ until they refill.
- **Grid artefacts.** A pad cell isolated by grid alignment reports an absurd drop; re-run at another pitch.
- **Hotspot limits** are IPC-2221 isolated-trace figures, pessimistic for planes.
- **Net classes come from regexes** in `review_config.json`, plus switch nodes derived from the netlist. A net that
  falls through to "slow" is not checked for reference continuity; `emc.md` lists them, longest first, under "What was
  classified". Classify anything long, exposed or near noisy copper.
- **Load currents are inputs**, not measurements: use connector/fuse ratings for power paths and datasheet peaks for
  radios and MCUs, and say which.
- **Hot-loop distances** are pad centre to pad centre; subtract half pad widths before calling a capacitor far away.
  The hot-loop table also has a DC solve of each loop's ground return and supply side (copper within 5 mm of the IC
  and capacitor): it shows a return forced through one via, but it is DC, not inductance.
- **Derived roles** (switch nodes, switching ICs, hot-loop candidates, ground) come from netlist structure and IC pin
  functions (`topology.py`). A switch node driven only by discrete FETs has no derived hot loop (reported as
  underived), and a derived candidate is a prompt to confirm against the datasheet, not a datasheet rule.
- **Crossings are not parallel runs**; a high crosstalk figure on a short overlap is usually an artefact.
- **Heat (`thermal.py`, `thermal.md`) is a steady-state board model, not an enclosure model.** The losses are only as
  good as their inputs (currents, efficiencies, R_DS(on) at temperature): every row names its basis, and a part with no
  data is UNKNOWN and left out of the temperatures (the coverage says so). The solve conducts heat through each copper
  layer (nets kept apart), FR4 between layers (k 0.3 W/mK by default) and via barrels, and loses it from both faces
  through one effective film coefficient h (convection plus radiation) to one ambient temperature; h comes from the
  enclosure (`"enclosed"` 5 / 7 / 10 W/m^2K per face, `"bare"` 9 / 12 / 16), and unset it is the closed box. Not modelled: the
  enclosure's air and walls (ambient is the air around the board, so a closed box's own rise must be added to it or
  folded into a lower h), airflow, heat leaving through wires, cells, connectors, screws or a chassis (often large on a
  small board: the model is pessimistic there), the parts' own bodies and their top-side convection (heat enters at the
  pads), transients (the report gives the bare board's time constant: a corner shorter than that does not reach the
  steady temperature), copper resistance rising with temperature (not iterated), and tracks running diagonally across
  cells (they conduct less than they should; planes and pours are unaffected). **h is the dominant uncertainty**: still
  air is roughly 5-10 W/m^2K effective inside a closed box and 10-15 in open air, which is why every temperature is shown
  at a low, nominal and high h. The board average P / (A (h_top + h_bottom)) is exact for any layout; layout only
  changes how far the peak sits above it. Junction temperatures use the datasheet's psi_JB or theta_JC where given;
  psi_JB was measured on a JEDEC board, so treat Tj as an estimate within several kelvin. A part's heat enters at its
  thermal pad or tab when it has one, else at all its pads. Exposed pads are judged on the solved step from the pad to
  the next layer; the via count against a rule of thumb (0.3 mm vias at 1.0 mm pitch) or `thermal.pads` is a reference.
- **Same-net isolation** (`islands.py`) is checked only for the islands the config declares, on KiCad's saved fills
  of the copy; an island's pad list must name every pad that belongs to it (any other pad of the net in the piece is a
  merge).
- **Decoupling paths** (`decoupling.py`) follow the net's own copper as KiCad connects it: `boarddump.py` records
  KiCad's own connectivity (the links behind the ratsnest and DRC's unconnected items: thermal-relief spokes, tracks
  across a pour, overlapping pads, arcs, vias on the layers they span), and the script only measures. A FAIL "no
  capacitor reachable" is therefore copper DRC also reports unconnected; the coverage compares the unconnected count
  of the links with KiCad's and DRC's. Lengths are approximate where copper meets: two tracks at their closest points,
  a via or pad at the track point nearest its centre, a fill piece from a via or pad centre or from where a track's
  centreline enters it, and a straight line across the piece (a plane path around a slot is longer than that). Copper
  board.json does not record (a copper shape, a footprint's own zone) still joins, as a straight line (a warning says
  so). Inductance: microstrip
  per-length value per track (closed form over the nearest copper layer) plus via barrels; plane spreading inductance
  and the capacitor's own mounting are not included. Supply pins are found by pin type, supply-pin name or a power
  class; an imported symbol with every pin "passive" and odd names can hide one.
- **Differential pairs**: Zdiff is the closed-form edge-coupled microstrip estimate from the measured median width and
  gap; the grounded-coplanar figure is a single-ended estimate at the nearest pour gap. Neither replaces a field
  solver or the fab's calculator; the pour-gap flag says where the edge-coupled number is too high.
- **Design intent is not in the pack.** The scripts and DRC measure copper and rules, not whether a block follows its
  datasheet layout (single-point grounds, hot-loop parts at the pins) or the intended netlist. Check those against the
  references themselves (datasheet figure, netspec file); kicad-pcb-workflow `checks.md` lists what each check misses.
