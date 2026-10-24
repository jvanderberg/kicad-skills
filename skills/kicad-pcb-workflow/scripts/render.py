#!/usr/bin/env python3
"""Render part of a board to a PNG you can open with the Read tool and actually look at.

  render.py board.kicad_pcb out.png --layers F.Cu,F.Silkscreen,Edge.Cuts [--window x0,y0,x1,y1] [--px-per-mm 40]
  render.py board.kicad_pcb out.png --3d [--side top]           # whole-board 3D render (tall-part clearance, placement)

Why this exists: `kicad-cli pcb render --zoom/--pan` frames unpredictably, and a whole-board PNG is too coarse to see a
0.2 mm sliver. This exports an SVG with a board-sized page (--page-size-mode 2), rasterises it with rsvg-convert, and
crops by KiCad coordinates (mm, y down), so the window you ask for is the window you get.
Needs rsvg-convert (librsvg) for 2D. Removes the stale lock file kicad-cli leaves next to the board.
Tip: render one or two layers at a time; a stack of every layer is unreadable because pours hide each other.
"""
import argparse, os, re, shutil, subprocess, sys, tempfile
ap = argparse.ArgumentParser()
ap.add_argument('pcb'); ap.add_argument('out')
ap.add_argument('--layers', default='F.Cu,F.Silkscreen,F.Courtyard,Edge.Cuts')
ap.add_argument('--window'); ap.add_argument('--px-per-mm', type=float, default=40)
ap.add_argument('--3d', dest='three', action='store_true'); ap.add_argument('--side', default='top')
ap.add_argument('--kicad-cli', default=os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
a = ap.parse_args()
lock = os.path.join(os.path.dirname(os.path.abspath(a.pcb)), '~' + os.path.basename(a.pcb) + '.lck')
had_lock = os.path.exists(lock)

def cleanup():
    if not had_lock and os.path.exists(lock): os.remove(lock)

if a.three:
    subprocess.run([a.kicad_cli, 'pcb', 'render', '--side', a.side, '-w', '4000', '-h', '2500', '--background', 'opaque', '--quality', 'high',
                    '-o', a.out, a.pcb], check=True, capture_output=True)
    cleanup(); print(a.out); sys.exit(0)

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
if not xs: sys.exit('no Edge.Cuts outline found')
bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
tmp = tempfile.mkdtemp(); svg = os.path.join(tmp, 'b.svg')
subprocess.run([a.kicad_cli, 'pcb', 'export', 'svg', '--mode-single', '--page-size-mode', '2', '--exclude-drawing-sheet', '-l', a.layers, '-o', svg, a.pcb],
               check=True, capture_output=True)
cleanup()
# the SVG page is the board bbox (plus KiCad's small margin): read its real size in mm
head = open(svg).read(4000)
wmm = float(re.search(r'width="([\d.]+)mm"', head).group(1)); hmm = float(re.search(r'height="([\d.]+)mm"', head).group(1))
mx = (wmm - (bx1 - bx0)) / 2; my = (hmm - (by1 - by0)) / 2      # margin on each side
ox, oy = bx0 - mx, by0 - my                                       # KiCad coordinate of the page's top-left corner
x0, y0, x1, y1 = map(float, a.window.split(',')) if a.window else (ox, oy, ox + wmm, oy + hmm)
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
print('%s  window (%.1f, %.1f)-(%.1f, %.1f) mm at %.0f px/mm' % (a.out, x0, y0, x1, y1, ppm))
