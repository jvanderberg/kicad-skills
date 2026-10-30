# Routing by hand, from a script

Route deliberately: every track is a list of coordinates you chose, written as data in a route plan that
`scripts/router.py` turns into KiCad copper. Do not
use an autorouter (KiCad's, Freerouting, or a home-made maze router) for anything but a throwaway experiment: it does
not know the board's layer plan, which returns must not be cut, which existing routes to reuse, or why a lane order
matters, and its output is hard to review. Hand routing from real coordinates is reliable and reviewable.

Route block by block, each from its brief, and check each block against its datasheet layout before starting the next
(`layout-stages.md`). The layer and channel plan (stage 0 there) comes before the first track.

## 1. Plan before drawing

- Decide the layer from the board's discipline (outer layers for signals if inner layers are planes) and the path
  from where the copper actually is: `region.py <pack> <layer> x0 y0 x1 y1` lists every pad, track, via and zone
  outline in a box with exact coordinates; `view.py` renders the same window with nets labelled and a grid.
- Look for existing routes first: escape routing left behind by a removed part, or parallel lanes already running
  where you need to go. `git log -p` / older board revisions show routes that were deleted.
- For a bus, decide the lane order at both ends and keep it the whole way (a group of tracks cannot swap order without
  crossing). Sketch it before writing coordinates.
- Note what the path crosses on the adjacent layers and which pours it will split; if it must cross a plane layer,
  pick the place where the least return current flows (e.g. beyond the input connectors, at the end of a pour), and
  say so in the report.

## 2. Draw as data, with router.py

```python
# plan.py - run with: $PY scripts/router.py check pack/board.json plan.py      (prints every check, writes nothing)
#                     $PY scripts/router.py apply proj.kicad_pcb pack/board.json plan.py
def build(r):
    r.track('F.Cu', 0.15, ('U1', '12'), (120.0, 80.0), (121.0, 81.0), ('J2', '3'))   # net taken from the pads
    r.via((140.0, 81.0), r.net('U1', '12'), 0.45, 0.2)          # checked before it is accepted; free at JLC on 4+ layers
    r.via_near('C5', '2')                     # closest legal spot beside a pad, with a short link track
    r.rect('GND', 'In1.Cu', 100.3, 100.3, 149.7, 139.7, name='GND_PLANE')
    r.keepout('F.Cu', [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], name='AGND_U3')     # no pour over an analog island
```
`board.json` is `kicad-board-review/scripts/boarddump.py` run on the unrouted board (or on the board as it is, with
`apply --append`). Pads are named, so routes follow placement changes; a track touching pads of two nets raises an
error. The board is regenerated from schematic + placement + plan, so the plan is the record of every route.
Helpers in the plan (a capacitor's via-and-stub, a fan-out pattern) take every net from the pads they serve
(`r.net(ref, pad)`), never a net name typed into the helper: a helper reused for parts on another rail then writes the
wrong net, and only the clearance check stands between that and a short (R17). An override keyed by reference
(another footprint, another via size for one part) lives where every instance is created, not in one helper (R13).
- Orthogonal runs with 45 degree corners (offset both coordinates by the same amount at a bend).
- Lanes on a fixed pitch (track width + clearance + margin, e.g. 0.5 mm for 0.15 mm tracks at 0.15 mm clearance).
- End exactly on pad centres or on another track's end/vertex - a 0.01 mm miss is an unconnected item.
- Width for the current (check with `power.py --net`), and generous where there is room.
- A via at every layer change, plus a ground via within about 1 mm when a fast signal changes reference planes.

## 3. Check clearance yourself before DRC

`router.py` checks each new via and track against existing and new copper before writing: copper clearance to other
nets (the larger of the two nets' net-class clearances, round track ends), the board edge, and **hole-to-hole distance
to every drilled hole, whatever its net**. The last one matters: a clearance check rightly skips same-net copper, but
holes must keep apart regardless of net, and a ground stitching pass that drops a via onto a hand-placed ground via is a
`hole_to_hole` DRC error at 0.000 mm. The same goes for pads: a via on or touching a pad of its own net passes DRC and the
clearance check, and the open barrel wicks solder out of that joint (on one board a via helper dropped a via into the
neighbouring source pad of a FET). The router rejects it unless the pad is named (`in_pad=('U5', '21')` on `via()` /
`via_field()` for thermal vias in an exposed pad, ordered filled or tented), and `board_lint.py` (in `check.sh`)
reports VIA IN PAD on any board, however the via got there. A same-net exemption belongs to the one rule it was made
for. It logs VIOLATION / REJECTED lines and exits 1 if there are any. It does not model
custom `.kicad_dru` rules (pass `clearance=` on that call and name the rule) or zone fills. Its clearance check is
never looser than DRC (exact distances; pad-outline approximation only ever counts against the gap: `checks.md`, R7).
**After every `apply`, read the log: any VIOLATION or REJECTED line is a failure** (R28) - the board was written, but
not the board the plan describes. When a router rule becomes stricter, re-run the whole plan and fix every newly
rejected item in one pass. Then run `check.sh` - DRC is the authority - and fix every new clearance error and
unconnected item.

## Generic habits that break datasheet rules

These look tidy and pass DRC, and each one has broken a specific datasheet rule on a real board:
- **A stitching via beside every ground pad, and one pour everywhere.** Parts whose datasheet asks for a separate
  analog/quiet ground joined to power ground at a single point (current-set, frequency-set, feedback, compensation and
  NTC resistors of chargers and converters) must not get plane vias, and the pour must be kept off them: route their
  grounds as a track to the specified point and add a keepout over the island (`r.keepout`).
- **Capacitor ground returns through the plane** when the datasheet shows them tied on the top layer to the IC's ground
  pins (input/output caps of a hot loop). Return on the same layer, then stitch.
- **Copper on adjacent layers under a switch node**, when the datasheet says no parallel layers under SW.
- **Feedback and compensation routing near the switch node or inductor**, or a slow signal routed through the reserved
  via site under an IC (allocate those sites in the layer plan first).

## Reference strips and stitching

A ground or plane strip added under a bus, or a pour between lanes, is checked where it acts right after the edit
(R30): it covers the layer-change vias and the whole track, stubs included (a strip that ends at the vias leaves the
stubs over the gap), and each pour piece it creates keeps two vias to its plane (a grid stitcher skips spots that
collide with tracks, so a piece under a bundle can end with one). `kicad-board-review/scripts/pour_check.py BOARD
--window x0,y0,x1,y1` reports both in seconds; add vias between the lanes or at spots chosen for that piece.

## 4. Look, and report what it crosses

Render the window (`render.py`, one or two layers) and look. Then report, for each new route: layer, length, what it
passes over/under, what plane it slots and what return path crosses that slot. For crossings of a plane layer, check
the alternate return (solid plane on the other inner layer, or a stitching via pair within about 1-2 mm of the cut).

## 5. Leave room for the human

The user may prefer to hand-tweak in KiCad. After they do, re-read the saved file (ask them to save and close first),
report exact coordinates of any overlaps or crossings in their edit, and fold their changes into the generator before
running it again - a regenerate that ignores a GUI edit silently reverts it.
