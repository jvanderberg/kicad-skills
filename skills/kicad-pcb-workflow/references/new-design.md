# A new design from nothing: project, schematic, board

**Requirements first.** A new board starts with the **kicad-new-board** skill's interview and its
`docs/requirements.md`. Do not start a schematic until that document exists and the user has agreed it (its status
line says `agreed`); if it is missing, run the interview first instead of picking the parts and architecture yourself.

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
| Thermal-via footprint with paste windows clear of the drills (and 0.3 mm drills) | `paste_clear.py` | python3 |
| JLCPCB order files (Gerbers, drill, BOM, CPL with solved rotations) and the placement / stock check | `jlcimport-cli production` (JLCImport main; pcb-part-selection "Order files") | pipx |
| Board from the netlist: footprints, symbol links, nets, fields, assembly attributes (DNP, BOM, position file), outline, placement, pad labels | `new_board.py` | python3 |
| JLC stackup block, design rules, net classes | `board_setup.py` | python3 |
| Tracks, vias, zones, keepouts as data, checked before writing | `router.py` | `$PY` (shapely; re-runs itself there) |
| What DRC misses (courtyards, models, silk on bodies, vias in pads, paste on holes, copper under hardware) | `board_lint.py` | `$KICAD_PYTHON` (pcbnew; re-runs itself there) |
| Is KiCad holding the project? (lock file vs a running editor) | `kicad_locks.py`, `kicad_open.sh` | python3 |
| Which interpreter has what; run a script that needs pcbnew and shapely | `interp.py which`, `interp.py run` | python3 |
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
   scripts on `sys.path` (from `KICAD_SKILLS`, default `~/git/kicad-skills`, else the newest Claude Code plugin install
   under `~/.claude/plugins/cache/`) and stops the build if the scripts are not the pinned ones, or KiCad's version
   differs.
3. `scripts/skills_rev.py pin <project>` writes `kicad-skills.lock` (commit, a hash of the files under `skills/`, and
   KiCad major.minor); commit it. It refuses a dirty checkout or a commit on no remote branch: a project pinned to an
   unpublished commit cannot be rebuilt by anyone else. Installed as a plugin (no `.git`), run the plugin's own
   `skills_rev.py`: it pins the plugin version from `.claude-plugin/plugin.json` and the file hash, and `check` fails
   when a plugin update changed any file, whatever its version number. To move to a newer revision: check it out
   (or update the plugin), regenerate, review the diff (`board_diff.py`, `git diff`), then re-pin in the same commit.
4. Building an older project: `git -C ~/git/kicad-skills worktree add ~/git/kicad-skills-<rev> <rev>` and
   `KICAD_SKILLS=~/git/kicad-skills-<rev>`; your main checkout stays where it is.

Keep the project's own kicad-skills inputs where `projfiles.py` finds them (`docs/` at the repository root works):
`pin-decisions.json`, `drc-accept.json`, `field-exemptions.json`, `reference-parts.json`, `review_config.json`,
`kicad-skills.lock`, `sourcing.json` (assembler and LCSC region: pcb-part-selection `sourcing.py`) and
`design-values.json` (derived values and the part parameters they came from: `derived_check.py`).

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
  faults on generated sheets are a shunt part's pin landing on a signal wire that passes under the rail. Draw the rail
  as one wire and declare the shunt pins on it as taps (`s.tap(c1.p(1), c2.p(1), ...)`): `collisions()` then reports
  only the pins that land on a wire by accident.
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
   again with the board once it exists (`partfields.py check sheet.kicad_sch board.kicad_pcb`): every field and every
   assembly attribute (DNP, in BOM, in position files) must match.
5. **Reset states of interface lines (R12).** For every control, strobe, enable and chip-select between two chips,
   write down the level on each side in every state - power-up, the driver in reset, the driver unprogrammed or in its
   bootloader, the driver unpowered, the receiver in reset - from both datasheets' pin default states (internal pull-up,
   pull-down, high impedance). Where no strong default holds the line in its safe state, add a resistor to that
   level. A weak pull-down on one chip against a weak pull-up on the other sits mid-rail on every reset. The review
   pack's `netlist.md` lists inter-IC control lines with no pull resistor ("reset-state decision needed") as a prompt;
   record the decision next to the pin decisions.
6. **Bus and lane order (R10).** For every bus between two packages, compare the pin order on both sides: two chips
   that number their pins the same way round cannot meet on one layer without reversing the order. Fix the pin
   assignment now (most MCUs allow remapping), not at layout.
7. **Assembly method per part (R12, R22).** Assembled, hand-soldered or not fitted, decided on each symbol at capture:
   `schgen` `add(..., in_bom=False)` for a hand-soldered part (its `in_pos_files` follows), `dnp=True` for not fitted,
   `in_pos_files=False` on its own when needed. `new_board.py` carries them to the footprint (DNP, exclude from BOM,
   exclude from position files), so the assembler's BOM and position file follow the schematic; check the exported
   position file lists only the assembled parts. A part whose orientation matters but which the assembler's library
   treats as non-polar (an inductor or capacitor with a polarity mark) gets an order note and a placement-preview check.
8. Render the PDF (`kicad-cli sch export pdf`, `pdftoppm -r 150`) and **look at every page**: overlapping text,
   labels on wires, values on bodies, crossings that could be avoided. A clean ERC is not a readable sheet.

## 5. Footprints

- **Parts JLCPCB assembles use JLC's own EasyEDA footprint** (`jlcimport-cli import`, pcb-part-selection "Importing
  into KiCad"): JLC places each part with that footprint at the CPL position and rotation, so rotation and polarity
  come out right without a bridge between two conventions. A KiCad library footprint is fine for unpolarised chip
  resistors and capacitors (symmetric pads) and for a geometry-checked match without a polarity caveat, and is the
  default for a board JLCPCB does not assemble.
- Check every assignment, library or imported: `fpcheck.py FOOTPRINT --package "<LCSC package string>" --symbol ...`
  (pad count, body size, numbering; it reads EasyEDA package names such as `SOT-23-3_L2.9-W1.3-...` too). The
  datasheet's land-pattern figure decides pad sizes and pitch.
- Most EasyEDA footprints have no courtyard, so DRC cannot report them overlapping their neighbours. Leave them as
  they are and space parts by the rules of thumb in `layout-rules.md` "Placement and mechanical".

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
- **A build script stops at the first failed stage (R28)** and proves each stage wrote its output before the next one
  reads it:
  ```bash
  set -euo pipefail
  trap 'python3 "$K/kicad_locks.py" status "$HW" --clean >/dev/null || true' EXIT   # locks kicad-cli left
  rm -f "$S/router.log"
  $PY "$K/router.py" apply "$PCB" "$S/pack0/board.json" tools/route_plan.py > "$S/router.log" 2>&1 || rc=$?
  grep -q '^wrote ' "$S/router.log" || { echo "router did not write the board"; exit 1; }
  ! grep -E '^ +(VIOLATION|REJECTED)' "$S/router.log" || { echo "router rejected items: fix the plan"; exit 1; }
  ```
  Never `|| true` around a generator, and never run DRC or the review pack on a board a failed stage left behind.

## Example (labelled): what this replaced on one board

minipc-power (USB-C PD + 1S2P charger + three converters, 4 layers) was built this way: `schgen` drew 105 parts with
192 wires, `netspec` checked 77 nets, `new_board.py` + `board_setup.py` + `router.py` rebuilt the routed board from the
netlist with DRC clean apart from two known, named silk warnings.
