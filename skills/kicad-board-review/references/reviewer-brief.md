# Adversarial reviewer brief

Spawn the reviewer as a separate agent (a fork if you want it to share the conversation's context, otherwise a
general-purpose agent with this brief and the paths filled in). Give it the same tools you have. Then verify every
finding yourself before reporting it.

---

You are reviewing a KiCad PCB design before it is manufactured. Assume it has mistakes, including in the most recent
changes and in the analysis you are given, and try hard to find them. Do not soften findings; do not pad the list.

**Inputs**
- Project: `<project_dir>` (schematics `*.kicad_sch`, board `*.kicad_pcb`, project libraries, docs).
- Analysis pack: `<pack_dir>` - `netlist.md` (pin-level netlist), `board_overview.md`, `power.md`, `emc.md`, `thermal.md`, `drc.md`,
  and the JSON behind them. Treat it as evidence to challenge: the DC solver, plane and EMC scripts have known blind
  spots (see `analysis-limits.md`), and net classes come from name patterns.
- Tools: `scripts/power.py <pack> --net N --source R:P --sink R:P=A` for any current path; `region.py <pack> LAYER
  x0 y0 x1 y1` to list copper in a box; `view.py` to render a layer window; kicad-cli for DRC/ERC/netlist/renders.
- Design intent: `<what the board does, input range, load currents, environment, assembly constraints, accepted decisions>`.
- Stackup: `<as built / unconfirmed - if unconfirmed assume 1 oz outer, 0.5 oz inner and say so>`.

**Do**
1. Read `netlist.md` end to end and check every IC against its datasheet (download it): abs max per pin including pin
   current, required external parts, variant suffix, power-up behaviour, addresses, land pattern. Cite page/section.
2. Walk every power path from connector to load under normal load, short, reverse polarity, surge, min/max input and
   one-of-several inputs present. Check fuse/PTC coordination and derating, clamp voltage vs downstream abs max,
   UVLO/EN thresholds vs worst-case input. Solve the current with the source and path resistance
   (`pcb-power-supply/scripts/path_budget.py`) rather than accepting P / V, and check start-up: each load switch's
   turn-on vs its converter's soft-start, inrush vs every upstream trip, and which trips latch.
3. Use the power results and run your own: neck-downs, thin inner copper, via fields, ground return under full load.
4. Check every inner-layer track and every slot in a plane: what return current crosses it.
4b. Attack the heat result (`thermal.md`): every UNKNOWN row and every "negligible" reason; the corner currents (solved
   with the path resistance, at the lowest source voltage?); R_DS(on) at the real gate drive and hot; efficiencies at the
   operating point, not the headline; the series path's own loss (FETs, fuse, BATFET, copper) next to the converters';
   the ambient (inside the enclosure?) and h; a hot part on a pour with no via to a plane of its net. If the pack has
   no thermal inputs, heat was NOT CHECKED: say so as a finding.
5. Check every fast and exposed signal: reference continuity, layer changes and return vias, crosstalk, termination,
   length, edge proximity, ESD at connectors.
6. Check regulator layouts against their datasheet layout examples item by item.
7. Check sourcing (stock in the assembler's region from `sourcing.json`, with the date; special parts), derived values
   against the fitted parts (`derived_check.py`), assembly constraints, 3D clearances, silkscreen.
8. Run the mechanical pin audits at the end of `netlist.md` and confirm each flagged pin against its datasheet:
   power pins on unconnected nets, active-low pins tied to a rail, data direction, LED resistor power. Then trace
   every serial/memory/UART line driver-to-receiver against both datasheets yourself - a swapped direction passes
   every automated check.
9. Look hardest at whatever changed most recently (`git diff` against the last commit or the previous review).

10. Read the pack's "Coverage and warnings" and "What was classified" sections first and attack them: nets that fell
    through to "slow" but carry fast edges or sensitive signals, derived hot loops that are not the datasheet's,
    configured items that matched nothing, defaults the pack used. An empty table is not evidence until its coverage is.
11. Every isolation rule in the datasheets (single-point or quiet ground, a pour that must not join the plane): is it
    declared in "islands" and proven on the filled copper? A same-net merge is invisible to DRC. Every IC supply pin in
    the "Decoupling" table: is the capacitor at the pin, and is the rail track-fed?
12. Use the right model for every number you report (kicad-board-review `SKILL.md`, R29): loop inductance of a track
    over a plane from its microstrip per-length value, not 1 nH/mm; a limit from the part's own datasheet, not a
    general rule. Datasheets are in `<project>/docs/datasheets/`; a pin you cannot check against one is "unverified",
    and say which datasheet is missing.

**Report** (markdown, written to `<pack_dir>/adversarial_review.md`)
- Blocker / Major / Minor, numbered. Each: what (refdes, net, coordinates), evidence (pack number, datasheet section,
  netlist line, your own solver run), consequence, concrete fix and its cost.
- Problems with the analysis pack itself (wrong numbers, blind spots that hid something).
- What you checked and found fine.
- What you could not verify.
