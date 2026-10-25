# What each check proves, and what it does not

Every automated check has blind spots. A clean result means "nothing of the kinds this tool looks for", nothing more.
For each check below, the right-hand column is what you must still cover with a targeted check or by looking.
Say in the report which checks ran and which blind spots were covered how.

**A check that stands in for the authority is never looser than it (R7).** A pre-check that runs before DRC (the
router's clearance check, a script's own spacing test) must flag everything DRC would: measure exactly (centre lines
and radii, not approximated polygons), and when a shape is approximated, let the error shrink the measured gap, never
widen it. A tolerance meant for one comparison (approximated pad outlines) that also applies to another (track to
track) passes violations that DRC then finds after the routing has been built around them. The same holds for any
proxy: a lock file stands in for "KiCad is open" and is wrong whenever kicad-cli left it (R19).

| Check | Proves | Does NOT cover - cover it with |
|---|---|---|
| ERC (`kicad-cli sch erc`) | pin-type conflicts, unconnected pins without a no-connect flag, unlabelled power nets | **wrong connections** that are type-correct (a supply shorted to GND passed ERC): `netspec.py`. Pins with a no-connect flag pass silently: `nc_audit.py`. Readability: render the PDF and look |
| `netspec.py` | the drawn netlist equals the intended one | whether the intended one is right: datasheet review (`pcb-part-selection`), `nc_audit.py` for unused and strapped pins |
| DRC (`check.sh`) | clearances, widths, annular rings, hole spacing, edge clearance, unconnected items, schematic parity, courtyard overlaps **between footprints that have courtyards** | footprints with **no courtyard** (invisible to the overlap check): `board_lint.py`, `add_courtyard.py`. **Silk under component bodies** (DRC checks silk against pads, other silk and the edge only): `board_lint.py`, 3D render. **Datasheet layout rules** (hot loops, single-point grounds, sense routing): the compliance file in `layout-stages.md`. Plane cuts and return paths: `planes.py`, `view.py` |
| `board_lint.py` | courtyards present, 3D model files exist, no silk text on other parts' bodies, no via on a pad of its own net (VIA IN PAD; exposed-pad vias as NOTE), no paste aperture over a drilled hole (PASTE ON HOLE; exposed-pad paste coverage as NOTE), no other-net track, via or pad within the hardware radius of a mounting hole on either outer layer (UNDER HARDWARE) | model **offsets** and orientation, tall-part collisions: 3D render. Silk graphics (not text) on bodies, and silk-to-silk inside one footprint (a script-placed label touching its own pad outline): silk render. The real washer or standoff size: give `--hardware-r` |
| 3D render (`render.py --3d`) | what the assembled board looks like | parts with a missing model show as bare pads and look like "nothing there": run `board_lint.py` first |
| Full-board copper render | coarse layout | once a ground pour exists everything is one colour: use `view.py` (nets coloured and labelled, with a grid) for routing checks |
| `router.py` checks | new copper clears other nets (net-class clearance, measured exactly: never looser than DRC), hole-to-hole for every drill, no via on or beside a same-net pad, board edge; REJECTED / VIOLATION lines and exit 1 | custom `.kicad_dru` rules, zone fills, thermal reliefs: DRC after applying. A plan that "applies" with REJECTED lines has failed (R28) |
| `pour_check.py` (kicad-board-review) | every pour piece has 2 vias to its plane; no track span over a void on the nearest layer (in a window, right after a zone edit) | other-net planes under a fast signal, crosstalk, everything else of `emc.py`: the full pack |
| `islands.py` (kicad-board-review) | each declared island (single-point or quiet ground, local pour) is one piece on the filled copper, holds no other pad of its net, and joins other layers only as allowed | islands nobody declared: write one per datasheet isolation rule. DRC passes every same-net merge |
| `kicad_open.sh` | an editor holds the folder (OPEN) or no process does (lock files STALE) | a KiCad running on another machine against a network share: ask |
| `partfields.py check` | every BOM part has a datasheet link and an LCSC/MPN in schematic and board; every schematic field equals the board's | that the link is the right part's datasheet: `--online` checks it loads and names the MPN; that the LCSC number is the right part: `bom_check.py`, by hand |
| `bom_check.py` / `part_gate.py` | stock now, lifecycle where a product page can be read | that the LCSC number is the part the symbol means (value, voltage, package, pinout): check by hand; stock moves daily: re-run before ordering |

## Coverage is part of the result (R16)

"Nothing found" is a pass only when the check also shows what it looked at. Every check and wrapper states its
coverage in its output, and a reader treats a result without it as unproven:
- **What it compared or classified, with counts** (board_diff's "Compared: 106 footprints, 402 copper items, ...";
  emc.md's routed nets per class and the nets that fell through to "slow"; partfields' "87 BOM parts, 87 with a
  datasheet link").
- **Every configured item that matched nothing**, as a warning, never a silent skip (a hot loop whose IC or net is not
  on the board is "NOT CHECKED", not omitted; a ground net with no copper empties every ground-based check).
- **Every default or fallback it used** (no config found: say so and which defaults; the starter config is labelled
  until a person reviews it) and **which project input files it read**, found by one convention (`projfiles.py`), so a
  wrapper and the project's own build cannot silently disagree.
- **Every attribute class it does not compare** (board_diff compares every footprint attribute and reports any other
  difference as "other content"; a diff that sees only geometry reported "0 unexpected" while three parts changed
  value and LCSC number).
Example (labelled): the starter review config's switch-node regex matched none of minipc-power's three converters'
switch nodes (named after a capacitor pad and after U6's L1/L2 pins), and the pack reported "loops 0 fast 0" with no
warning. The pack now derives switch nodes and hot loops from the netlist and lists what it derived and skipped first.

## Exemptions: name the item, never the category

When a known, accepted warning keeps showing up, exempt that item - never its whole type. Filtering every `silk_*`
item to hide one accepted warning (a connector outline that overhangs the board edge by design) hid three real silk
overlaps of the same type on the same board. Use `check.sh --accept accepted.json` (format in `drc_summary.py`): each
entry names the type, the item text that identifies it, and the reason; the summary lists every exempted item in an
"Accepted" section and flags entries that no longer match anything. The same rule applies to any script that
post-processes a report: a filter that drops a category is a bug.
