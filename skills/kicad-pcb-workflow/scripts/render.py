#!/usr/bin/env python3
"""Render part of a board to a PNG you can open with the Read tool and actually look at.

  render.py board.kicad_pcb out.png --layers F.Cu,F.Silkscreen,Edge.Cuts [--window x0,y0,x1,y1] [--px-per-mm 40]
  render.py board.kicad_pcb out.png --3d [--side top]           # whole-board 3D render (tall-part clearance, placement)

Why this exists: `kicad-cli pcb render --zoom/--pan` frames unpredictably, and a whole-board PNG is too coarse to see a
0.2 mm sliver. This exports an SVG with a board-sized page (--page-size-mode 2), rasterises it with rsvg-convert, and
crops by KiCad coordinates (mm, y down), so the window you ask for is the window you get.
Needs rsvg-convert (librsvg) for 2D. Removes any lock file its kicad-cli calls leave next to the board (kicad_locks.py).
Tip: render one or two layers at a time; a stack of every layer is unreadable because pours hide each other.
Boards without an Edge.Cuts outline (e.g. a vendor reference layout imported with `kicad-cli pcb import`): with
--window, a temporary copy gets an Edge.Cuts rectangle at the window and is rendered instead; without --window, the
whole page is rasterised uncropped (KiCad sizes it to the items, so its coordinates are not known).
For routing checks on a board with pours, use kicad-board-review's view.py (every net coloured and labelled):
a full-board copper render is one colour once a ground pour exists.
"""
import argparse, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_locks import cleanup_locks  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument('pcb'); ap.add_argument('out')
ap.add_argument('--layers', default='F.Cu,F.Silkscreen,F.Courtyard,Edge.Cuts')
ap.add_argument('--window'); ap.add_argument('--px-per-mm', type=float, default=40)
ap.add_argument('--3d', dest='three', action='store_true'); ap.add_argument('--side', default='top')
ap.add_argument('--kicad-cli', default=os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
a = ap.parse_args()
_locks = cleanup_locks(a.pcb); _locks.__enter__()       # every lock kicad-cli leaves next to the board goes at exit
import atexit; atexit.register(_locks.__exit__, None, None, None)

if a.three:
    subprocess.run([a.kicad_cli, 'pcb', 'render', '--side', a.side, '-w', '4000', '-h', '2500', '--background', 'opaque', '--quality', 'high',
                    '-o', a.out, a.pcb], check=True, capture_output=True)
    print(a.out); sys.exit(0)

t = open(a.pcb).read()
# board bbox from Edge.Cuts geometry (endpoints; arcs bulging past their endpoints are rare on outlines)
xs, ys = [], []
for m in re.finditer(r'\((gr_line|gr_rect|gr_arc|gr_circle|gr_poly|gr_curve)\b', t):
    i = m.start(); d = 0; j = i
    while True:
        d += (t[j] == '(') - (t[j] == ')'); j += 1
        if d == 0: break
    b = t[i:j]
    if '"Edge.Cuts"' not in b: continue
    for x, y in re.findall(r'\((?:start|end|mid|center|xy) ([-\d.]+) ([-\d.]+)\)', b): xs.append(float(x)); ys.append(float(y))
tmp = tempfile.mkdtemp(); svg = os.path.join(tmp, 'b.svg')
uncropped = False


def window_rect_sexpr(x0, y0, x1, y1):
    return ('\t(gr_rect\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.05)\n\t\t\t(type solid)\n\t\t)\n'
            '\t\t(fill no)\n\t\t(layer "Edge.Cuts")\n\t)\n') % (x0, y0, x1, y1)


if not xs:
    if a.window:
        wx0, wy0, wx1, wy1 = map(float, a.window.split(','))
        i = t.rstrip().rfind(')')
        a.pcb = os.path.join(tmp, 'outlined.kicad_pcb')
        open(a.pcb, 'w').write(t[:i] + window_rect_sexpr(wx0, wy0, wx1, wy1) + t[i:])
        xs, ys = [wx0, wx1], [wy0, wy1]
        print('no Edge.Cuts outline: rendering a copy with a temporary outline at the window')
    else:
        uncropped = True
        xs, ys = [0.0], [0.0]
        print('no Edge.Cuts outline and no --window: rendering the whole page uncropped (coordinates unknown)')
bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
subprocess.run([a.kicad_cli, 'pcb', 'export', 'svg', '--mode-single', '--page-size-mode', '2', '--exclude-drawing-sheet', '-l', a.layers, '-o', svg, a.pcb],
               check=True, capture_output=True)
# the SVG page is the board bbox (plus KiCad's small margin): read its real size in mm
head = open(svg).read(4000)
wmm = float(re.search(r'width="([\d.]+)mm"', head).group(1)); hmm = float(re.search(r'height="([\d.]+)mm"', head).group(1))
mx = (wmm - (bx1 - bx0)) / 2; my = (hmm - (by1 - by0)) / 2      # margin on each side
ox, oy = bx0 - mx, by0 - my                                       # KiCad coordinate of the page's top-left corner
x0, y0, x1, y1 = map(float, a.window.split(',')) if a.window and not uncropped else (ox, oy, ox + wmm, oy + hmm)
ppm = a.px_per_mm
if (x1 - x0) * ppm > 8000 or (y1 - y0) * ppm > 8000: ppm = 8000 / max(x1 - x0, y1 - y0)
full = os.path.join(tmp, 'full.png')
if not shutil.which('rsvg-convert'): sys.exit('rsvg-convert not found (brew install librsvg / apt install librsvg2-bin); the SVG is at ' + svg)
# rasterise only what is needed: scale the whole page, then crop in python to avoid giant intermediate images
subprocess.run(['rsvg-convert', '-b', 'white', '-w', str(int(wmm * ppm)), svg, '-o', full], check=True)
try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(full)
    im.crop((int((x0 - ox) * ppm), int((y0 - oy) * ppm), int((x1 - ox) * ppm), int((y1 - oy) * ppm))).save(a.out)
except ImportError:
    geo = '%dx%d+%d+%d' % ((x1 - x0) * ppm, (y1 - y0) * ppm, (x0 - ox) * ppm, (y0 - oy) * ppm)
    subprocess.run(['magick', full, '-crop', geo, '+repage', a.out], check=True)
print('%s  whole page, %.1f x %.1f mm at %.0f px/mm' % (a.out, wmm, hmm, ppm) if uncropped else
      '%s  window (%.1f, %.1f)-(%.1f, %.1f) mm at %.0f px/mm' % (a.out, x0, y0, x1, y1, ppm))
