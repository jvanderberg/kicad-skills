# Layout rules to apply while editing

These are the judgments to make *while* placing and routing, so the review does not have to catch them later. The
kicad-board-review skill's checklist has the full reasoning and how to measure each one.

## Respect the board's layer plan

- Find out what each layer is for before routing: look at where signals already run. Many boards keep inner layers as
  continuous planes; then **no signals on inner layers** without the user's explicit agreement. "Shortest path" is not
  a reason.
- Every track on a plane layer cuts that plane. Before adding one, list what return currents cross the cut (DC power
  returns, and fast signals on the adjacent layer) and what it passes under or over (other nets' pours, signals on the
  layer above/below). Report it.
- Reuse existing routing: removing a part removes its escape routing, and a new part on the same pins can often use it
  (look in `git log -p` / older revisions). The user will notice when you route a long new path next to an old one.

## Power copper

- Size it generously when there is room - copper is free; "adequate" is not the goal. Check with the solver
  (`power.py --net ...`) instead of a rule of thumb.
- No neck-downs on high-current paths: removing a via field or a pour corner can leave a narrow strip carrying the
  whole current.
- Via fields between layers of a power path: enough that their drop is small next to the pour's; check current per via.
  In ground planes, pitch them so copper webs remain (0.95 x 1.05 mm for 0.6/0.3 vias at 0.1 mm clearance).
- Thin inner layers (often 0.5 oz) carry half what outer layers do; long rails on them need width.
- Shunts: datasheet land pattern, Kelvin sense lines from the inner pad ends, on one layer if possible.

## Regulators

Follow the datasheet layout example item by item: input cap at the pins on the same layer, hot loop minimal, switch
node small, feedback and enable lines short, away from the switch node, and not splitting the local ground pour into
islands; AGND/PGND joined at the specified point.

## Signals

- Fast signals over an unbroken reference plane; a ground via next to every layer change; series resistors at the
  source for clocks and long SPI lines (and any the MCU datasheet requires, such as series resistors on USB D+/D-).
- Keep buses short; keep exposed lines away from the board edge and behind ESD protection at the connector, with the
  series resistor between the TVS and the IC.
- Lane order: a group of parallel tracks keeps its order through bends; plan the order at both ends before routing
  (swapping two lines at one end to "fix" the order makes one wrap around and cross the others).

## Placement and mechanical

- Respect the assembly plan (e.g. everything on top). Check tall parts in 3D (fuse holders, terminal blocks, inductors)
  and model offsets; keep parts out of mounting-hole keepouts; leave room for connectors' mating plugs.
- Courtyards on every footprint: imported ones often lack them, and DRC's overlap check cannot see a part without one
  (`board_lint.py` lists them; `add_courtyard.py` adds them to the library). Fixed pitches for rows of passives with
  real clearance (e.g. about 2.0 mm for 0805s; 1.75 mm is tight).
- Budget area for what is not a component: edge connectors and solder pads (pitch x count per edge), mounting-hole
  keepouts, connector overhang and mating clearance. A board size promised before a placement pass is provisional.

## Silkscreen

Plain and readable: text >= 1 mm, lines >= 0.15 mm, never on pads, labels that say what the thing is. No decoration
(knockouts, dashes) unless asked. Once the user accepts a silk position, leave it. Labels must also clear other parts'
bodies, which DRC does not check (`board_lint.py` does).

## External connections are a user interface

Every connector, solder pad, switch and test point is used by a person who does not have the schematic. Give each one:
- a **function label** on the silkscreen (on both sides when wires can be soldered from either side; `new_board.py
  --labels` writes both, mirrored on the bottom);
- **polarity and orientation** marks: +/- or pin 1, a keyed footprint where one exists, and one pad-shape convention
  kept across the board (for example square = positive or signal, round = ground), stated in the board's docs;
- a **consistent order** for pairs and groups (always + then GND, the same order on every connector);
- labels clear of pads, other silk and part bodies.
Check them in a silk render and a 3D render, not only in DRC.
