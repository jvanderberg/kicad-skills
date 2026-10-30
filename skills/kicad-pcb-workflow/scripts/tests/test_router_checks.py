"""router.py's via checks on a synthetic board.json (no KiCad; needs shapely, so under plain python3 the file reruns
itself under the analysis venv):   python3 tests/test_router_checks.py
Same-net copper is exempt from the clearance check only: a via on a neighbouring pad of its own net (FET source pins
side by side) passed every check and wicked solder out of that joint on a real board."""
import math, os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
PY = os.environ.get('PY') or os.path.expanduser('~/.cache/kicad-skills/venv/bin/python')
try:
    from shapely.geometry import Point
    import router
except ImportError as e:
    router = None; _why = str(e)

    def test_under_analysis_python():
        if not os.path.exists(PY):
            import pytest
            pytest.skip('shapely not importable (%s) and no analysis python at %s' % (_why, PY))
        r = subprocess.run([PY, os.path.abspath(__file__)], capture_output=True, text=True)
        assert r.returncode == 0 and 'FAIL' not in r.stdout, r.stdout + r.stderr[-2000:]


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def pad(num, net, x, y, w, h):
    return dict(num=num, net=net, x=x, y=y, layers=['F.Cu'], th=False, drill=0,
                poly=[[rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2), []]])


def board():
    # a PowerDI-like FET: three source pads in a row (same net), gate, and a big drain pad; an exposed-pad IC
    q = [pad(str(i + 1), 'SRC', 10 + 0.65 * i, 10, 0.4, 1.0) for i in range(3)] + [pad('4', 'G', 10 + 1.95, 10, 0.4, 1.0)]
    q += [pad('5', 'DRN', 11, 12.6, 2.6, 2.0)]
    u = [pad('21', 'GND', 30, 10, 3.0, 3.0), pad('1', 'SIG', 28, 8, 0.3, 0.8)]
    return dict(source='', layers=['F.Cu', 'B.Cu'], netclass={}, edge=[[rect(0, 0, 40, 25), []]], tracks=[], vias=[],
                footprints=[dict(ref='Q2', pads=q), dict(ref='U5', pads=u)])


def pads_hit(r, pt, size):
    c = Point(pt).buffer(size / 2)
    return sorted('%s.%s' % k for k, lst in r.pads.items() for p in lst if c.intersects(p['geom']))


def test_via_on_same_net_neighbour_pad_rejected():
    r = router.Router(board(), clearance=0.15)
    assert r.via((11.3, 10), 'SRC') is False                      # centre of Q2.3, the same net
    assert 'same-net pad Q2.3' in r.log[-1] and 'wicks solder' in r.log[-1], r.log
    assert r.via((11.3, 10), 'SRC', in_pad=('Q2', '3')) is True   # named on purpose: accepted


def test_via_near_keeps_off_every_pad():
    r = router.Router(board(), clearance=0.15)
    q = r.via_near('Q2', '2')                                     # middle source pad: same-net pads on both sides
    assert q is not None, r.log
    assert pads_hit(r, q, r.via_size + 0.0) == [], (q, pads_hit(r, q, r.via_size))
    q1 = r.via_near('Q2', '1')
    assert q1 is not None and pads_hit(r, q1, r.via_size) == []


def test_thermal_vias_need_in_pad():
    r = router.Router(board(), clearance=0.15)
    assert r.via_field('GND', 29, 9, 31, 11, pitch=1.0, size=0.45, drill=0.2) == 0     # all on U5.21: skipped
    n = r.via_field('GND', 29, 9, 31, 11, pitch=1.0, size=0.45, drill=0.2, in_pad=('U5', '21'))
    assert n == 9, r.log


def test_track_clearance_never_looser_than_drc():
    """two 45-degree tracks of different nets: 0.003 mm inside the clearance is a VIOLATION (a polygon tolerance once
    let it through and DRC caught it); exactly at the clearance is fine; the same holds against a round pad whose
    polygon was approximated inside the true pad (an old dump)"""
    clr, w = 0.15, 0.15
    s = math.sqrt(0.5)
    for gap, bad in ((clr - 0.003, True), (clr - 0.0005, True), (clr + 0.0002, False), (clr + 0.001, False)):
        r = router.Router(board(), clearance=clr)
        off = (w + gap)                                 # centre spacing perpendicular to the 45-degree run
        r.track('F.Cu', w, (2, 2), (8, 8), net='A')
        r.track('F.Cu', w, (2 + off * s, 2 - off * s), (8 + off * s, 8 - off * s), net='B')
        assert (r.violations == 1) == bad, (gap, r.log)
    # a round pad: boarddump writes the polygon outside the true circle (exact enough); an older dump inside it
    def ring(cx, cy, rad, n, outside):
        k = 1 / math.cos(math.pi / n) if outside else 1.0
        return [[cx + rad * k * math.cos(2 * math.pi * (i + 0.5) / n), cy + rad * k * math.sin(2 * math.pi * (i + 0.5) / n)]
                for i in range(n)]                      # a flat edge, not a vertex, faces the track
    for outside in (True, False):
        b = board()
        b['footprints'].append(dict(ref='TP1', pads=[dict(num='1', net='T', x=20, y=20, layers=['F.Cu'], th=False, drill=0,
                                                          poly=[[ring(20, 20, 0.5, 32, outside), []]])]))
        if outside:
            b['pad_poly'] = dict(error_mm=0.005, error_side='outside')
        # a vertical track whose edge is 0.002 mm inside the clearance from the true circle, passing between two
        # polygon vertices (where an inside polygon overstates the gap by the most)
        x = 20 + 0.5 + clr - 0.002 + w / 2
        r = router.Router(b, clearance=clr)
        r.track('F.Cu', w, (x, 18), (x, 22), net='A')
        assert r.violations == 1, (outside, r.log)


def test_repeated_pad_number_by_index():
    """a SOT-223's tab is a second pad "2": ('U4', '2', 1) names it in a track, as r.P('U4', '2', 1) does"""
    b = board()
    b['footprints'].append(dict(ref='U4', pads=[pad('1', 'VIN', 15, 20, 0.7, 1.5), pad('2', 'VOUT', 17.3, 20, 0.7, 1.5),
                                                pad('3', 'GND', 19.6, 20, 0.7, 1.5), pad('2', 'VOUT', 17.3, 14, 3.3, 1.5)]))
    r = router.Router(b, clearance=0.15)
    end = r.track('F.Cu', 1.0, ('U4', '2', 1), (17.3, 11.0))
    assert r.tracks[-1]['net'] == 'VOUT' and r.tracks[-1]['a'] == (17.3, 14.0) and end == (17.3, 11.0), r.tracks
    assert r.net('U4', '2', 1) == 'VOUT' and r.P('U4', '2', 1) == (17.3, 14.0)


def test_vias_and_tracks_keep_out_of_mounting_hardware():
    """a GND stitching field around an M3 hole (net-less NPTH, 3.2 mm drill): no via inside drill + 0.5 mm of it, as
    board_lint.py's UNDER HARDWARE would have it; hardware_nets / hardware_r follow board_lint's options"""
    def with_hole():
        b = board()
        b['footprints'].append(dict(ref='H1', fp='MountingHole_3.2mm_M3', pads=[dict(num='', net='', x=20, y=20, layers=[],
                                    th=False, drill=3.2, poly=[[rect(18.4, 18.4, 21.6, 21.6), []]])]))
        return b
    r = router.Router(with_hole(), clearance=0.15)
    assert r.hardware and r.hardware[0][3] == 3.7, r.hardware
    r.via_field('GND', 14, 14, 26, 26, pitch=1.0)
    assert r.vias and all(math.dist(v['at'], (20, 20)) - v['size'] / 2 >= 3.7 for v in r.vias), r.vias
    assert r.via((20, 23.8), 'GND') is False and 'mounting hole H1' in r.log[-1], r.log[-1]
    r.track('B.Cu', 0.2, (14, 23), (26, 23), net='SIG')                  # 3 mm from the centre on B.Cu: a violation
    r.track('In1.Cu', 0.2, (14, 22), (26, 22), net='SIG')                # inner layer: the hardware does not touch it
    assert r.violations == 1 and 'mounting hole H1' in r.log[-1], r.log
    assert router.Router(with_hole(), clearance=0.15, hardware_nets=['GND']).via((20, 23.8), 'GND')
    assert router.Router(with_hole(), clearance=0.15, hardware_r={'H1': 2.5}).via((20, 23.8), 'GND')


if router is None:
    for _k in [k for k in list(globals()) if k.startswith('test_') and k != 'test_under_analysis_python']:
        del globals()[_k]

if __name__ == '__main__':
    if router is None:
        print('SKIP: shapely not importable (%s); run with the analysis venv' % _why); sys.exit(0)
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e)[:2000])
    sys.exit(1 if fails else 0)
