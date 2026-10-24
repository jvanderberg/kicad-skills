# Rendering images you can actually inspect

A clean DRC says nothing about whether the result looks right. Render the area you changed, open the PNG with the Read
tool, and look for: tracks where they should not be, cuts in planes, slivers and isolated copper, labels over pads or
other labels, parts colliding with tall neighbours, text that is unreadable. Say what you checked.

## Copper and silk, by coordinates

```
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py board.kicad_pcb out.png --layers F.Cu,F.Silkscreen,Edge.Cuts --window x0,y0,x1,y1 [--px-per-mm 40]
```
KiCad coordinates are mm with y pointing down. It exports an SVG with a board-sized page (`--page-size-mode 2`),
rasterises with `rsvg-convert`, and crops. Render one or two layers at a time: an all-layer stack is unreadable because
pours hide each other. For "is this plane cut", render the plane layer alone.

## Specific nets, coloured and labelled

`kicad-board-review/scripts/view.py board.json LAYER x0 y0 x1 y1 out.png [grid_mm] [--nets A,B]` draws one layer from
the `board.json` dump with every net coloured and labelled and a coordinate grid - the best way to see which net is
which and to read coordinates for the next edit.

## 3D (placement, tall parts)

`render.py board.kicad_pcb out.png --3d` (top view), or directly:
`kicad-cli pcb render --side top --perspective --rotate '-50,0,20' --zoom 6 -w 1600 -h 1100 -o p.png board.kicad_pcb`.
`--zoom/--pan` frame unpredictably; render the whole board large and crop instead if needed.

## Schematic pages and footprints

- `kicad-cli sch export pdf -o sch.pdf top.kicad_sch`, then `pdftoppm -r 200 -f N -l N -png sch.pdf page` and crop.
  Look for overlapping labels ("GNDGNDGND"), references on symbol bodies, rotated values, notes that grew over symbols.
- `kicad-cli fp export svg --fp NAME --layers F.Cu,F.SilkS,F.Fab,F.CrtYd -o outdir Lib.pretty` then
  `rsvg-convert -z 15 -b white outdir/NAME.svg -o fp.png`, next to the datasheet's land pattern rendered with
  `pdftoppm`, to compare pad sizes and positions.

## Hygiene

kicad-cli leaves `~board.kicad_pcb.lck` beside the file after renders; `render.py` removes it if it created it. Very
large PNGs trip PIL's decompression-bomb check; crop with `magick` or lower the resolution.
