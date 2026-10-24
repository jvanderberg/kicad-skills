# Routing by hand, from a script

Route deliberately: every track is a list of coordinates you chose, written as data in the generator script. Do not
use an autorouter (KiCad's, Freerouting, or a home-made maze router) for anything but a throwaway experiment: it does
not know the board's layer plan, which returns must not be cut, which existing routes to reuse, or why a lane order
matters, and its output is hard to review. Hand routing from real coordinates is reliable and reviewable.

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

## 2. Draw as data

```python
# (layer, net, width, [points...]) - each consecutive pair becomes one segment
TRACKS = [
  ('F.Cu', 'I2C_SCL', 0.15, [(120.0, 60.0), (120.0, 80.0), (121.0, 81.0), (140.0, 81.0)]),
]
VIAS = [((140.0, 81.0), 'I2C_SCL', 0.45, 0.2)]
```
- Orthogonal runs with 45 degree corners (offset both coordinates by the same amount at a bend).
- Lanes on a fixed pitch (track width + clearance + margin, e.g. 0.5 mm for 0.15 mm tracks at 0.15 mm clearance).
- End exactly on pad centres or on another track's end/vertex - a 0.01 mm miss is an unconnected item.
- Width for the current (check with `power.py --net`), and generous where there is room.
- A via at every layer change, plus a ground via within about 1 mm when a fast signal changes reference planes.

## 3. Check clearance yourself before DRC

Build obstacles from `board.json` (pads, tracks, vias, other nets' zone fills) and buffer them by clearance + half the
new track width with **round caps** (shapely `cap_style=1`): KiCad's tracks have round ends, and a flat-cap check
approves positions DRC rejects. Then run `check.sh` - DRC is the authority - and fix every new clearance error and
unconnected item.

## 4. Look, and report what it crosses

Render the window (`render.py`, one or two layers) and look. Then report, for each new route: layer, length, what it
passes over/under, what plane it slots and what return path crosses that slot. For crossings of a plane layer, check
the alternate return (solid plane on the other inner layer, or a stitching via pair within about 1-2 mm of the cut).

## 5. Leave room for the human

The user may prefer to hand-tweak in KiCad. After they do, re-read the saved file (ask them to save and close first),
report exact coordinates of any overlaps or crossings in their edit, and fold their changes into the generator before
running it again - a regenerate that ignores a GUI edit silently reverts it.
