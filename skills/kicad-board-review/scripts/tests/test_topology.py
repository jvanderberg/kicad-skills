"""Topology derivations on synthetic netlists that differ from any one board:  python3 tests/test_topology.py
(no KiCad, no venv needed). Each case is a shape the name-pattern config used to miss or misclassify."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from topology import Topology, starter_config


def nl(parts, nets):
    """parts: {ref: value}; nets: {net: [(ref, pin, pinfunction, pintype), ...]}"""
    comps = {r: dict(ref=r, value=v, fp='', pins={}) for r, v in parts.items()}
    for n, nodes in nets.items():
        for r, p, pf, pt in nodes:
            comps[r]['pins'][p] = [n, pf, pt]
    return dict(components=comps, nets={n: [list(x) for x in v] for n, v in nets.items()})


# a synchronous buck whose switch node KiCad named after the inductor pad, and whose IC calls its pin "PH"
BUCK = nl({'U1': 'TPS54302', 'L1': '10uH', 'C1': '10uF', 'C2': '22uF', 'C3': '100nF', 'R1': '100k', 'R2': '22k'}, {
    'VIN': [('U1', '3', 'VIN_3', 'power_in'), ('C1', '1', '', 'passive')],
    'Net-(L1-Pad1)': [('U1', '2', 'PH_2', 'power_out'), ('L1', '1', '1', 'passive'), ('C3', '2', '', 'passive')],
    'Net-(U1-BOOT)': [('U1', '1', 'BOOT_1', 'passive'), ('C3', '1', '', 'passive')],
    '+5V': [('L1', '2', '2', 'passive'), ('C2', '1', '', 'passive'), ('R1', '1', '', 'passive')],
    'Net-(U1-FB)': [('U1', '5', 'FB_5', 'input'), ('R1', '2', '', 'passive'), ('R2', '1', '', 'passive')],
    'PGND': [('U1', '4', 'GND_4', 'power_in'), ('C1', '2', '', 'passive'), ('C2', '2', '', 'passive'), ('R2', '2', '', 'passive')],
})

# an asynchronous buck: switch pin named "OUT" (no SW-like name at all) and a catch diode; plus an LC input filter
ASYNC = nl({'U1': 'LM2596', 'L1': '33uH', 'L2': '1uH', 'D1': 'SS34', 'C1': '100uF', 'C2': '220uF', 'C3': '10uF'}, {
    'VRAW': [('L2', '1', '1', 'passive'), ('C3', '1', '', 'passive')],
    'VIN_F': [('L2', '2', '2', 'passive'), ('U1', '1', 'VIN_1', 'power_in'), ('C1', '1', '', 'passive')],
    'Net-(D1-K)': [('U1', '2', 'OUT_2', 'output'), ('D1', '1', 'K', 'passive'), ('L1', '1', '1', 'passive')],
    'VOUT': [('L1', '2', '2', 'passive'), ('C2', '1', '', 'passive'), ('U1', '4', 'FB_4', 'input')],
    'GND': [('U1', '3', 'GND_3', 'power_in'), ('D1', '2', 'A', 'passive'), ('C1', '2', '', 'passive'), ('C2', '2', '', 'passive'),
            ('C3', '2', '', 'passive')],
})

# a controller with external FETs: the switch node joins two FETs and the inductor, no IC pin on it
DISCRETE = nl({'U1': 'LM5146', 'Q1': 'CSD18', 'Q2': 'CSD18', 'L1': '4.7uH', 'C1': '10uF', 'C2': '47uF'}, {
    'VIN': [('Q1', '1', 'D', 'passive'), ('C1', '1', '', 'passive'), ('U1', '1', 'VIN_1', 'power_in')],
    'Net-(Q1-S)': [('Q1', '2', 'S', 'passive'), ('Q2', '1', 'D', 'passive'), ('L1', '1', '1', 'passive')],
    'VOUT': [('L1', '2', '2', 'passive'), ('C2', '1', '', 'passive')],
    'GND': [('Q2', '2', 'S', 'passive'), ('C1', '2', '', 'passive'), ('C2', '2', '', 'passive'), ('U1', '2', 'PGND_2', 'power_in')],
})


def test_buck_switch_node_named_after_inductor_pad():
    t = Topology(BUCK)
    assert t.ground == ['PGND'], t.ground                       # ground found from the IC's GND pin, not the name GND
    assert list(t.switch_nodes) == ['Net-(L1-Pad1)'], t.switch_nodes
    o = t.switching_ics['U1']
    assert o['dc_side'] == ['+5V']
    assert [c['in_net'] for c in o['hot_loop_candidates']] == ['VIN']   # buck: input loop, not the output side


def test_async_buck_and_input_filter():
    t = Topology(ASYNC)
    assert list(t.switch_nodes) == ['Net-(D1-K)'], t.switch_nodes    # found by structure (no SW-like pin name)
    assert 'no capacitor to ground' in t.switch_nodes['Net-(D1-K)']['why']
    assert 'VRAW' not in t.switch_nodes and 'VIN_F' not in t.switch_nodes   # LC filter: caps on both sides
    assert [c['in_net'] for c in t.switching_ics['U1']['hot_loop_candidates']] == ['VIN_F']


def test_discrete_switch_is_reported_not_dropped():
    t = Topology(DISCRETE)
    assert 'Net-(Q1-S)' in t.switch_nodes
    assert not t.switching_ics
    assert any('no IC on it' in u for u in t.underived), t.underived


def test_configured_ground_missing_is_a_warning():
    t = Topology(BUCK, {'ground_nets': ['GND']})
    assert any('not in the netlist' in w for w in t.warnings), t.warnings
    assert any('look like ground' in w for w in t.warnings), t.warnings


def test_starter_config_has_no_placeholders():
    t = Topology(BUCK)
    c = starter_config(t, BUCK)
    assert c['starter'] is True and c['power_runs'] == []
    assert c['hot_loops'] == [dict(ic='U1', in_net='VIN', gnd_net='PGND', label=c['hot_loops'][0]['label'])]
    import re
    sw = [r for r in c['net_classes'] if r['class'] == 'switch'][0]
    assert re.search(sw['match'], 'Net-(L1-Pad1)') and not re.search(sw['match'], 'VIN')


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_'):
            try:
                f(); print('PASS', k)
            except Exception as e:
                fails += 1; print('FAIL', k, repr(e))
    sys.exit(1 if fails else 0)
