# kicad_sexpr

One place that owns the KiCad 10 file formats, so generators and edit scripts never format s-expression text by
hand. Pure Python 3.9+, no dependencies, MIT like the rest of the repo.

- **A generic, lossless tree** (`sexp.py`) for every KiCad s-expression file: `.kicad_sch`, `.kicad_pcb`,
  `.kicad_sym`, `.kicad_mod`, `fp-lib-table` / `sym-lib-table`. Nothing is modelled as a fixed class, so no token is
  ever unknown or dropped. The writer is a port of KiCad's own formatter: a file KiCad saved comes back
  **byte-identical** after `dumps(loads(text))`, and every other file comes back token-identical.
- **Typed builders on top** (`schematic.py`, `board.py`, `symbol_lib.py`, `project.py`) for the items generators
  make all the time. Each builder returns the node it inserted, so anything a builder does not cover can still be set
  on that node, or added with `add(Node(...))`.
- **The format rules live here and nowhere else**: quoting and escaping (`"`, `\`, newline, CR) happen only in the
  writer, KiCad 10 version headers, fresh uuids that are unique within the document (checked again before every
  save), `{slash}` in board net names that come from a netlist (`board_net_name()`), and the layouts KiCad 10
  writes (zones, rule areas, stackup, symbol instances, ...).

Why: hand-written format strings in the minipc-power generators caused a stray `'''` inside a format string, a
duplicated property name, a keepout copied from a library footprint because the syntax was unknown, and a stackup
block found by grepping other projects. See `EVALUATION.md` for why this is not built on kiutils / kicad-skip /
KiCadFiles / the IPC API.

## Use

```python
import sys; sys.path.insert(0, '<kicad-skills>/skills/kicad-pcb-workflow/scripts')
from kicad_sexpr import Board, Project, Schematic, SymbolLibrary, stackup, Node, load, save
```

### A schematic block (from `examples/quickstart.py`)

```python
lib = {n: SymbolLibrary.load(f'{KICAD}/symbols/{n}.kicad_sym', n) for n in ('Device', 'power', 'Connector')}
sch = Schematic.new('demo', paper='A4', title='RC filter', date='2026-10-24', rev='1')
r1 = sch.add_symbol('Device:R', 'R1', '10k', (55.88, 50.8), angle=90, lib=lib['Device'],
                    footprint='Resistor_SMD:R_0402_1005Metric', fields={'LCSC': 'C25744'})
c1 = sch.add_symbol('Device:C', 'C1', '100n', (63.5, 55.88), lib=lib['Device'],
                    footprint='Capacitor_SMD:C_0402_1005Metric')
c1.set_field('Value', at=(66.04, 57.15))          # move / show / hide / turn / justify any field
sch.wire(r1.pin(2), (c1.pin(1)[0], r1.pin(2)[1]), c1.pin(1))   # pin() = connection point after rotation + mirror
gnd = sch.power('power:GND', (c1.pin(2)[0], c1.pin(2)[1] + 5.08), lib=lib['power'])
sch.wire(c1.pin(2), gnd.pin(1))
sch.label('OUT', (c1.pin(1)[0], r1.pin(2)[1]))
sch.junction((c1.pin(1)[0], r1.pin(2)[1]))
sch.text('fc = 159 Hz\n(R1 x C1)', (38.1, 73.66))  # the newline is escaped on output, never written raw
sch.save('demo.kicad_sch')                        # refuses to write duplicate uuids / references
```

`add_symbol` embeds the library symbol in `lib_symbols` (derived `extends` symbols are flattened), writes the
instance with every library field (positions rotated and mirrored with the symbol), one `(pin ...)` per pin and the
`(instances (project ... (path ...)))` block. Also: `global_label`, `hierarchical_label`, `no_connect`, `bus`,
`polyline`, `sheet` (hierarchical sheet block with pins), `Schematic.load()` + `symbol(ref)` to edit existing sheets.

### A board with tracks, vias, zones (condensed from the same example)

```python
b = Board.new(copper_layers=2)
b.set_stackup(stackup([0.035, 0.035], [('core', 1.51, 'FR4', 4.5, 0.02)]))
R1 = b.add_footprint(f'{KICAD}/footprints/Resistor_SMD.pretty/R_0402_1005Metric.kicad_mod',
                     'Resistor_SMD:R_0402_1005Metric', 'R1', '10k', (108, 106), angle=0, side='F',
                     path='/' + sch.symbol('R1').uuid, fields={'LCSC': 'C25744'},
                     pad_nets={'1': '/IN', '2': '/OUT'})
b.track([R1.pad_position(2), (110, 108.54), (110, 109.5)], 0.25, 'F.Cu', '/OUT')
b.via((110, 110), 0.6, 0.3, 'GND', free=True)
b.zone('GND', 'B.Cu', [(100, 100), (120, 100), (120, 120), (100, 120)], name='GND', priority=1)
b.rule_area('B.Cu', [(114, 113), (118, 113), (118, 117), (114, 117)], name='no pour')   # keepout: no copper pour
b.gr_text('RC', (113, 104), 'F.SilkS')
b.outline_rect(100, 100, 20, 20, corner_radius=1)
b.save('demo.kicad_pcb')

pro = Project.new('demo.kicad_pro')               # or Project.load(): net classes, assignments, design rules
pro.netclass('Power', clearance=0.2, track_width=0.8); pro.assign('VBUS', 'Power'); pro.save()
```

`python3 examples/quickstart.py OUT_DIR` writes the complete demo project; the test suite checks that it has ERC 0,
DRC 0, 0 unconnected and parity 0.

`add_footprint` loads the `.kicad_mod`, gives every item a fresh uuid, stores pad and text angles the way KiCad does
(absolute: footprint angle + local angle), adds Datasheet/Description fields like pcbnew, links the symbol (`path`),
sets pad nets, and flips to the back side (`side='B'`). Placement and flipping were checked item by item against
pcbnew's `SetLayerAndFlip()` / `SetOrientationDegrees()` output for 20 library footprints (arcs, polygons, custom
pads, chamfered pads, rule areas inside footprints, unlocked fields).

### Read, modify, write

```python
b = Board.load('x.kicad_pcb')
b.footprint('R3').set_pad_net(1, 'NEW_NET')       # typed helpers ...
for v in b.items('via'):                          # ... or the raw tree
    v.set('size', 0.6)
b.save()                                          # untouched parts of a KiCad-saved file stay byte-identical
```

Anything is reachable through the tree: `node.find('layer')`, `node.need('at').number(1)`, `node.walk('pad')`,
`node.set('width', 0.2)`, `node.remove_all('filled_polygon')`, `Node('anything', ...)` + `board.add(node)`.

### Net names

Pads, tracks and zones take the name exactly as the board stores it. Names from a kicad-cli netlist export go
through `board_net_name()` first (`Net-(U1-EN/UVLO)` -> `Net-(U1-EN{slash}UVLO)`). Local labels on the root sheet
appear in the netlist as `/NAME`; power symbols and global labels as `NAME`.

## Coverage

| | generic tree (lossless read / write) | typed builders |
|---|---|---|
| `.kicad_sch` | every item | symbol instances (rotation, mirror, unit, fields, pins, instances), lib_symbols embedding, wire, bus, junction, no_connect, label, global_label, hierarchical_label, text, polyline, sheet + sheet pins, title block |
| `.kicad_sym` | every item | library symbol (properties, units, pins, rectangle, polyline), flattening of derived symbols, pin list |
| `.kicad_pcb` | every item | header + layer table + setup for N copper layers, stackup, footprints (place / flip / fields / pad nets / pad positions), segment, arc, via (through, blind, micro), copper zone, keepout rule area, gr_line / gr_arc / gr_circle / gr_rect / gr_poly / gr_text, rounded-rectangle outline |
| `.kicad_mod` | every item | `new_footprint()` skeleton (pads and graphics as plain `Node`s) |
| `.kicad_pro` (JSON) | everything (dict) | net classes, assignments, patterns, design rules, track / via presets |

Items with no builder are still kept exactly and can be created with `Node(...)`: dimensions, images, groups,
tables, text boxes, tuning patterns (`generated`), teardrop settings, embedded files, net ties, bus entries,
rule areas in schematics, and so on.

## Tests

```
python3 tests/run.py            # or: python3 -m pytest tests
KICAD_SEXPR_CORPUS='/path/proj/*.kicad_pcb:/path/proj/*.kicad_sch' python3 tests/run.py corpus
```

KiCad itself is the judge wherever possible: kicad-cli netlist export and ERC for schematics (pin positions in all
12 rotation/mirror combinations, a wired block, a hierarchical sheet), DRC with zone refill for boards, `upgrade
--force` re-saves to show KiCad keeps everything, pcbnew placement for footprints, and round-trips of the installed
symbol and footprint libraries. Tests that need KiCad skip when it is missing (`KICAD_CLI`, `KICAD_PYTHON`,
`KICAD_SHARE` override the macOS defaults).

## Limits

- Typed builders cover what generators commonly need; the rest is raw `Node` work (see the table). There is no
  geometry checking (clearances, overlaps): that stays with DRC and the routing helpers.
- `Board.new()` writes the layer table and default setup that pcbnew 10.0.1 writes; boards for KiCad 9 are not
  generated (files of any version are still read and written losslessly).
- Flipping footprints follows pcbnew 10.0.1 measured on library footprints; text angles that are not multiples of
  90 degrees in the library, and footprints with inner-layer-only pads, were not covered by that comparison.
- Symbol-instance `(pin ...)` entries are written for the pins of the placed unit; multi-unit symbols are placed
  one unit per `add_symbol` call (pin positions and netlists checked for single-unit symbols only).
- Footprint `add_footprint` does not resolve library nicknames: pass the `.kicad_mod` path.
- Filled zone polygons are not computed: leave zones unfilled and run `kicad-cli pcb drc --refill-zones --save-board`.
