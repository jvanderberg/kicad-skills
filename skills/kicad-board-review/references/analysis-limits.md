# What the analysis pack cannot see

- **DC only.** No AC impedance, no field solving, no resonance. Crosstalk uses the 1/(1+(D/h)^2) rule of thumb; Z0 is
  closed-form microstrip over the nearest copper layer (stripline overstated).
- **Copper at 20 C**, no plating build-up on outer layers, 20 um via plating, solder in plated holes ignored. Hot
  copper is about 0.39 % per C worse.
- **Components are not in the model.** Fuses, FETs, shunts, PTCs, connector contacts and wires add their own drops.
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
- **No thermal model.** Copper loss in watts is reported; temperature rise needs judgment (area, airflow, neighbours).
- **Design intent is not in the pack.** The scripts and DRC measure copper and rules, not whether a block follows its
  datasheet layout (single-point grounds, hot-loop parts at the pins) or the intended netlist. Check those against the
  references themselves (datasheet figure, netspec file); kicad-pcb-workflow `checks.md` lists what each check misses.
