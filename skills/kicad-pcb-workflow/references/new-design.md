# A new design from nothing: project, schematic, board

kicad-cli cannot create a project, draw a schematic or update a board from a schematic, and pcbnew's python cannot
set the stackup. These scripts cover that gap. Each one owns one fiddly job (file syntax, escaping, uuids, net names),
so a generator describes the design and never formats KiCad text itself:

| Job | Script | Runs in |
|---|---|---|
| Intended connectivity, checked against KiCad's netlist | `netspec.py` | python3 |
| Redraw symbols readably, pins numbered for the footprint | `symgen.py` (library) | python3 |
| Draw the schematic as wired blocks; geometry checks; locate shorts | `schgen.py` (library) | python3 |
| Footprint facts: courtyard, pad count / body vs package, pins vs pads | `fpcheck.py` | python3 |
| Add missing courtyards to imported footprints | `add_courtyard.py` | python3 |
| Board from the netlist: footprints, symbol links, nets, fields, outline, placement, pad labels | `new_board.py` | python3 |
| JLC stackup block, design rules, net classes | `board_setup.py` | python3 |
| Tracks, vias, zones, keepouts as data, checked before writing | `router.py` | `$PY` (shapely) |
| Unused and strapped pins as decisions | `nc_audit.py` | python3 |
| Datasheet typical-application parts vs the schematic | `refparts.py` | python3 |
| A project's own input files, found one way | `projfiles.py` | python3 |
| Tools present; kicad-skills revision pinned | `preflight.py`, `skills_rev.py` | python3 |
| Every BOM part's Datasheet / LCSC present; schematic and board fields equal | `partfields.py check` | python3 |

All of them write through `kicad_sexpr` (no KiCad text is formatted in the scripts), with stable uuids: an unchanged
design regenerates byte-identical. If you are tempted to write `'(property %s %s ...)' % (...)` in a project
generator, add what you need to one of these (or to the layer) instead. Hand-written format strings caused a stray `'''` inside a schematic and a duplicated property name on a
real board; the shared writers assert against both.

## 0. Pin the toolchain

A generated project is only reproducible with the generator revision and KiCad version it was built with (R15, R21).
At the start, and whenever you deliberately move to a newer kicad-skills:
1. `scripts/preflight.py --for all` - every tool the scripts need.
2. Copy `assets/kskills.py` to the project's `tools/` and import it first in every generator: it puts kicad-skills'
   scripts on `sys.path` (from `KICAD_SKILLS`, default `~/git/kicad-skills`) and stops the build if the checkout is not
   the pinned commit, has uncommitted changes under `skills/`, or KiCad's version differs.
3. `scripts/skills_rev.py pin <project>` writes `kicad-skills.lock` (commit and KiCad major.minor); commit it. It
   refuses a dirty checkout or a commit on no remote branch: a project pinned to an unpublished commit cannot be
   rebuilt by anyone else. To move to a newer revision: check it out, regenerate, review the diff (`board_diff.py`,
   `git diff`), then re-pin in the same commit.
4. Building an older project: `git -C ~/git/kicad-skills worktree add ~/git/kicad-skills-<rev> <rev>` and
   `KICAD_SKILLS=~/git/kicad-skills-<rev>`; your main checkout stays where it is.

Keep the project's own kicad-skills inputs where `projfiles.py` finds them (`docs/` at the repository root works):
`pin-decisions.json`, `drc-accept.json`, `field-exemptions.json`, `reference-parts.json`, `review_config.json`,
`kicad-skills.lock`.

## 1. Write the circuit down as data first

Before drawing anything, write the intended netlist: `{net: ["REF.PIN", ...]}` in a JSON file or a `NETS = {...}`
python file (see `netspec.py`). It is the design, independent of how it is drawn; every later step is checked against
it. Pin numbers are the footprint's pad numbers, so pick the footprints now (`fpcheck.py` below).

## 2. Symbols

- A redrawn symbol keeps the data of the one it replaces: `symgen.ic(..., inherit=SymLib('JLCImport',
  'JLCImport.kicad_sym').libsym('JLCImport:<name>'))` takes over its Datasheet, Footprint, Description, LCSC,
  manufacturer and MPN wherever the call does not give them.
- Library symbols are fine where they read well. Redraw a symbol when it does not: an imported one with pins in package
  order, "unspecified" pin types, off-grid pins. `symgen.ic()` groups pins by function (inputs and supplies left,
  outputs right, supply pins top, ground bottom, related pins adjacent) with real types from the datasheet pin table,
  and stacks duplicate pins (several GND or SW pins) on one point.
- **Number pins for the footprint you will use**, and prove it: `fpcheck.py FOOTPRINT --symbol LIB.kicad_sym:NAME`
  lists symbol pins with no pad and pads with no pin. Example: KiCad's NexFET VSON-8 footprint merges source pins 5-8
  into one pad "5", so a FET symbol numbered 1-8 leaves pads unconnected; `symgen.fet()` renumbers a Device FET
  symbol to the footprint's pads.

## 3. Draw the schematic so a person can read it

The default an agent reaches for - every pin gets a net label - produces a sheet nobody can review. Instead:
- **One functional block per area, drawn with real wires.** Power symbols for rails and ground. Net labels only for
  signals that travel between blocks.
- **Flow left to right**: inputs on the left, outputs on the right; supplies at the top, ground at the bottom.
- **Ladder layout for shunt parts**: the rail runs along the top, decoupling and divider parts hang below it with their
  ground symbols, and signal wires run below the lowest ground symbol - never through a shunt part's span. Most drawing
  faults on generated sheets are a shunt part's pin landing on a signal wire that passes under the rail.
- Minimise crossings; junction dots only at real T-joins (`schgen` adds them where three or more ends meet).
- Values and references beside the part, not on its body or on wires.

With `schgen.Sch`: place parts, `wire()` between pin points (`part.p('VIN')` or `part.p(3)`), `power()` for rails,
`label()` between blocks, then **before writing**: `s.collisions()` (pins on wire interiors, overlapping wires, wires
through bodies, overlapping bodies) must be empty and `find_merges(s, NETS)` must return nothing. Then `s.write()`.

## 4. Verify the schematic

1. `python3 scripts/netspec.py check nets.py sheet.kicad_sch` - must print "netlist matches the spec". It reports
   SPLIT / SHORT / MISSING / UNEXPECTED. ERC does not replace this: a generated sheet with a supply shorted to GND
   passed ERC with one unrelated warning; netspec caught it at once, and `find_merges()` then named the pin and
   coordinate where the two nets touched.
2. `kicad-cli sch erc` - clean, or every remaining item explained.
3. `python3 scripts/nc_audit.py sheet.kicad_sch --require-notes` - every unused pin, every pin the symbol types
   no_connect, and every input strapped to a rail gets a recorded decision from the datasheet pin table (notes in the
   project's `pin-decisions.json`, found by `projfiles.py`; `--datasheet U5=ds.pdf` prints the pin-table row next to
   each pin).
4. `python3 scripts/partfields.py check sheet.kicad_sch` - every BOM part has a datasheet link and an LCSC/MPN. Run it
   again with the board once it exists (`partfields.py check sheet.kicad_sch board.kicad_pcb`): every field must match.
5. Render the PDF (`kicad-cli sch export pdf`, `pdftoppm -r 150`) and **look at every page**: overlapping text,
   labels on wires, values on bodies, crossings that could be avoided. A clean ERC is not a readable sheet.

## 5. Footprints

- **Prefer KiCad's library footprint whenever the package is standard** (chip passives, SOT/SOD, SOIC/TSSOP, standard
  QFN/SON variants, common connectors and fuses). Keep an imported footprint only for genuinely part-specific packages.
  KiCad's are drawn to one convention, have courtyards and fab layers, and are maintained.
- Check every assignment, library or imported: `fpcheck.py FOOTPRINT --package "<LCSC package string>" --symbol ...`
  (pad count, body size, numbering). Automatic matchers (jlcimport's included) propose wrong pin counts and body sizes
  often enough that each suggestion needs this check; the datasheet's land-pattern figure decides pad sizes and pitch.
- Imported footprints without a courtyard: `add_courtyard.py LIB.pretty` (DRC cannot see overlaps otherwise).

## 6. The board

```
kicad-cli sch export netlist --format kicadxml -o net.xml proj.kicad_sch
python3 scripts/new_board.py net.xml proj.kicad_pcb --layers 4 --outline 50x40 --origin 100,100 --corner-r 1 \
    --placement place.json --labels labels.json
python3 scripts/board_setup.py proj.kicad_pro --stackup JLC04161H-7628 --class Power:track=0.8,clearance=0.2 \
    --assign Power=GND,VBUS,+5V        # or --pattern 'Power=+*'
```
- Run `new_board.py` before `board_setup.py`: new_board writes a minimal `.kicad_pro` next to a new board if there is
  none (KiCad fills in its defaults), and board_setup then edits it.
- Regenerating over an existing board keeps every footprint's uuid (new_board reads OUT first; `--previous FILE` to
  read another, `--previous none` for none). Routing comes from `router.py apply ... --previous <the routed board
  before regeneration>` (e.g. a copy of HEAD's board), so tracks, vias and zones keep theirs too. Then `board_diff.py
  HEAD` and `git diff` show only what changed.
- `board_setup.py --list` shows the stackups it knows; the numbers come from `kicad-new-board`'s
  `references/jlcpcb-stackups.md` and need re-checking on jlcpcb.com before an order.
- An empty schematic for a brand-new project: `Sch('name').write('name.kicad_sch')` with `schgen`.
- Placement lives in a data file (`place.json`, mm relative to the outline's top-left), and the board is regenerated
  from schematic + placement + route plan. GUI edits must be folded back into those files before the next regeneration,
  or they are lost (`board_diff.py HEAD` shows what a regeneration would revert).
- Then layout in stages with `references/layout-stages.md`, routing with `router.py` (`references/routing.md`), and
  `check.sh` after every stage.

## Example (labelled): what this replaced on one board

minipc-power (USB-C PD + 1S2P charger + three converters, 4 layers) was built this way: `schgen` drew 105 parts with
192 wires, `netspec` checked 77 nets, `new_board.py` + `board_setup.py` + `router.py` rebuilt the routed board from the
netlist with DRC clean apart from two known, named silk warnings.
