# Roles of nets and parts derived from the netlist's structure (what is connected to what, and the IC pin functions),
# not from net names. The analysis scripts use it so that a switch node called Net-(C4-Pad2) or U6-L1 is still a
# switch node, and make_pack.sh uses it to write a starter review_config.json for this board instead of placeholders.
#   python topology.py PACK                      # print what was derived and why
#   python topology.py PACK --starter-config OUT # write a starter review_config.json (derived entries are labelled)
# Needs only PACK/netlist.json (netdigest.py). Every derivation carries a "why" so a reader can check it, and anything
# that could not be derived is listed under "underived" instead of being dropped.
import json, os, re, sys, collections

def natkey(s): return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]

def pin_fn(pf, pin):
    """'SW_19' -> 'SW', '~{CE}_9' -> 'CE' (imported symbols append the pin number; KiCad writes overbars as ~{})"""
    f = re.sub(r'_%s$' % re.escape(pin), '', pf or '')
    return re.sub(r'~\{([^}]*)\}', r'\1', f)

KIND_RX = [('inductor', r'^L\d'), ('transformer', r'^T\d'), ('capacitor', r'^C\d'), ('resistor', r'^R\d'),
           ('bead', r'^FB\d'), ('fuse', r'^F\d'), ('led', r'^LED\d'), ('diode', r'^D\d'), ('transistor', r'^Q\d'),
           ('connector', r'^(J|P|CN|X)\d'), ('testpoint', r'^TP\d'), ('ic', r'^(U|IC)\d')]
def kind(ref, comp=None):
    for k, rx in KIND_RX:
        if re.match(rx, ref): return k
    if comp and len(comp.get('pins', {})) > 3: return 'ic'
    return 'other'

# IC pin functions that drive an inductor (switch node). Used as corroboration and to name the pin; the structural
# test (an inductor terminal with no capacitor to ground and a semiconductor on it) does not depend on it.
SW_FN = re.compile(r'^(P?SW\w*|LX\w*|PH(ASE)?\w*|L\d|SW[A-D]?\d?)$', re.I)
GND_FN = re.compile(r'^(P|A|D|S)?GND\w*$|^VSS\w*$|^(E|THERMAL_?)?PAD$|^EP$', re.I)
PWR_FN = re.compile(r'^(P|A)?V?IN\w*$|^V?OUT\w*$|^P?V(DD|CC)\w*$|^V?SYS\w*$|^PMID$|^VBUS\w*$|^VAC$|^BAT\w*$|^VM$|^REGN$|^LDO\w*$', re.I)
ACTIVE = ('ic', 'transistor', 'diode')

class Topology:
    def __init__(self, nl, cfg=None):
        cfg = cfg or {}
        self.comps, self.nets = nl['components'], {n: [tuple(x) for x in v] for n, v in nl['nets'].items()}
        self.kind = {r: kind(r, c) for r, c in self.comps.items()}
        self.warnings, self.underived = [], []
        self.ground = self._ground(cfg.get('ground_nets'))
        self.switch_nodes = self._switch_nodes()
        self.switching_ics = self._switching_ics()

    def two_pin_other(self, ref, net):
        """for a two-pin part with one pin on net, the net of its other pin (None otherwise)"""
        ps = self.comps.get(ref, {}).get('pins', {})
        if len(ps) != 2: return None
        ns = [v[0] for v in ps.values()]
        if net not in ns: return None
        ns.remove(net); return ns[0]

    def caps_to_ground(self, net):
        return sorted({r for r, _, _, _ in self.nets.get(net, []) if self.kind[r] == 'capacitor' and self.two_pin_other(r, net) in self.ground}, key=natkey)

    def _ground(self, configured):
        found = collections.OrderedDict()
        for n, nodes in self.nets.items():
            why = []
            if re.match(r'^/?([APDS]?GND\w*|VSS|0V)$', n, re.I): why.append('name')
            g = ['%s.%s' % (r, p) for r, p, pf, _ in nodes if self.kind[r] == 'ic' and GND_FN.match(pin_fn(pf, p))]
            if g: why.append('IC ground pins %s' % ' '.join(g[:4]))
            if why: found[n] = '; '.join(why)
        if configured:
            missing = [n for n in configured if n not in self.nets]
            if missing: self.warnings.append('ground_nets %s not in the netlist (every ground-based check is empty for them)' % missing)
            extra = [n for n in found if n not in configured]
            if extra: self.warnings.append('nets that look like ground but are not in ground_nets: %s' % ', '.join('%s (%s)' % (n, found[n]) for n in extra))
            self.ground_why = {n: 'configured' for n in configured if n in self.nets}
            return [n for n in configured if n in self.nets]
        if not found:
            self.warnings.append('no ground net found by name or by IC ground pins: set ground_nets'); self.ground_why = {}; return []
        # several candidates (a protector's VSS is the cell's negative, not board ground): named ones win, else the one
        # with the most connections; the rest are reported, not silently merged or dropped
        named = [n for n in found if found[n].startswith('name')]
        pick = named or [max(found, key=lambda n: len(self.nets[n]))]
        rest = [n for n in found if n not in pick]
        if rest: self.warnings.append('ground-like nets NOT treated as ground: %s - add them to ground_nets if they are the same ground'
                                      % ', '.join('%s (%s)' % (n, found[n]) for n in rest))
        self.ground_why = {n: found[n] for n in pick}
        return pick

    def _switch_nodes(self):
        out = collections.OrderedDict()
        for r, k in sorted(self.kind.items(), key=lambda kv: natkey(kv[0])):
            if k not in ('inductor', 'transformer'): continue
            for p, (n, pf, pt) in sorted(self.comps[r]['pins'].items(), key=lambda kv: natkey(kv[0])):
                if n in self.ground or n.startswith('unconnected-'): continue
                nodes = self.nets.get(n, [])
                sw = ['%s.%s %s' % (rr, pp, pin_fn(f, pp)) for rr, pp, f, _ in nodes if self.kind[rr] == 'ic' and SW_FN.match(pin_fn(f, pp))]
                act = ['%s.%s' % (rr, pp) for rr, pp, _, _ in nodes if self.kind[rr] in ACTIVE]
                gc = self.caps_to_ground(n)
                why = None
                if sw: why = 'inductor %s.%s meets switch pin %s' % (r, p, ', '.join(sw[:3]))
                elif act and not gc: why = 'inductor %s.%s meets %s with no capacitor to ground' % (r, p, ', '.join(act[:3]))
                if why:
                    e = out.setdefault(n, dict(net=n, why=why, inductors=[], devices=sorted({x.split('.')[0] for x in act}, key=natkey)))
                    e['inductors'].append(r)
        return out

    def dc_side(self, inductors):
        """nets on the far side of these inductors from a switch node (the inductor's DC terminal)"""
        s = set()
        for r in inductors:
            for n, _, _ in self.comps[r]['pins'].values():
                if n not in self.switch_nodes and n not in self.ground: s.add(n)
        return s

    def _switching_ics(self):
        out = collections.OrderedDict()
        for n, e in self.switch_nodes.items():
            ics = [d for d in e['devices'] if self.kind[d] == 'ic']
            if not ics:
                self.underived.append('switch node %s has no IC on it (discrete switch %s): configure its hot loop by hand' % (n, ', '.join(e['devices'])))
            for ic in ics:
                o = out.setdefault(ic, dict(ic=ic, value=self.comps[ic]['value'], switch_nodes=[], inductors=set()))
                o['switch_nodes'].append(n); o['inductors'].update(e['inductors'])
        for ic, o in out.items():
            dc = self.dc_side(o['inductors'])
            o['inductors'] = sorted(o['inductors'], key=natkey)
            o['dc_side'] = sorted(dc, key=natkey)
            o['topology_hint'] = 'buck-boost (both inductor ends switch)' if not dc else 'buck or boost: inductor DC side on %s' % ', '.join(sorted(dc))
            cands = []
            for p, (n, pf, pt) in sorted(self.comps[ic]['pins'].items(), key=lambda kv: natkey(kv[0])):
                f = pin_fn(pf, p)
                if n in self.ground or n in self.switch_nodes or n in dc or n.startswith('unconnected-'): continue
                if not (pt.split('+')[0] in ('power_in', 'power_out') or PWR_FN.match(f)): continue
                caps = self.caps_to_ground(n)
                if not caps: continue
                c = next((x for x in cands if x['in_net'] == n), None)
                if c: c['pins'].append('%s %s' % (p, f)); continue
                cands.append(dict(ic=ic, in_net=n, gnd_net=self.ground[0] if self.ground else 'GND', pins=['%s %s' % (p, f)], caps=caps))
            for c in cands:
                c['label'] = '%s %s loop (derived: %s)' % (ic, '/'.join(sorted({x.split(' ', 1)[1] for x in c['pins']})), ', '.join(c['pins']))
            o['hot_loop_candidates'] = cands
            if not cands: self.underived.append('%s switches %s but no power pin of it has a capacitor to ground: configure its hot loop by hand' % (ic, ', '.join(o['switch_nodes'])))
        return out

    def summary(self):
        L = ['ground nets: %s' % (', '.join('%s (%s)' % (n, self.ground_why.get(n, '')) for n in self.ground) or 'NONE')]
        L.append('switch nodes (%d):' % len(self.switch_nodes))
        L += ['  %s: %s' % (n, e['why']) for n, e in self.switch_nodes.items()]
        L.append('switching ICs (%d):' % len(self.switching_ics))
        for ic, o in self.switching_ics.items():
            L.append('  %s %s: %s; hot-loop candidates: %s' % (ic, o['value'], o['topology_hint'], '; '.join('%s [%s] caps %s' % (c['in_net'], ', '.join(c['pins']), ' '.join(c['caps'][:6])) for c in o['hot_loop_candidates']) or 'none'))
        L += ['UNDERIVED: ' + u for u in self.underived] + ['WARNING: ' + w for w in self.warnings]
        return '\n'.join(L)

def esc(n): return re.escape(n)

def starter_config(t, nl):
    """a review_config.json for this board: derived entries are real, the rest are TODO markers (no placeholders)"""
    power = sorted({n for n, nodes in t.nets.items() if n not in t.ground and not n.startswith('unconnected-') and
                    (any(pt.split('+')[0] in ('power_in', 'power_out') for _, _, _, pt in nodes) or len(t.caps_to_ground(n)) >= 2)
                    and n not in t.switch_nodes}, key=natkey)
    loops = [dict(ic=c['ic'], in_net=c['in_net'], gnd_net=c['gnd_net'], label=c['label'])
             for o in t.switching_ics.values() for c in o['hot_loop_candidates']]
    return collections.OrderedDict([
        ('_comment', 'STARTER written by topology.py from this board\'s netlist. Derived: ground_nets (by name / IC ground pins), '
                     'the switch class (every net where an inductor meets a switch pin or an active part with no capacitor to ground), '
                     'hot_loops (every power pin of a switching IC with a capacitor to ground, except the inductor\'s DC side) and a power '
                     'class (nets with power pins or two or more capacitors to ground). Check each against the schematic and the datasheets, '
                     'delete what is not a hot loop, add classes for buses (usb/spi/i2c/clock/analog), then add power_runs with real currents '
                     '(none are written: currents are design inputs). Delete this "starter" key when done; the scripts warn while it is set.'),
        ('starter', True),
        ('ground_nets', t.ground),
        ('net_classes', ([dict(match='^(%s)$' % '|'.join(esc(n) for n in t.switch_nodes), **{'class': 'switch'})] if t.switch_nodes else []) +
                        ([dict(match='^(%s)$' % '|'.join(esc(n) for n in power), **{'class': 'power'})] if power else [])),
        ('fast_classes', ['usb', 'qspi', 'spi', 'clock', 'switch', 'swd', 'analog']),
        ('diff_pairs', []),
        ('rail_voltages', {}),
        ('hot_loops', loops),
        ('power_runs', []),
        ('_todo', ['classify buses and sensitive nets (feedback, current sense, CC, I2C) into classes; nets that fall through are "slow" and get no reference check',
                   'rail_voltages for rails whose name has no voltage'] + t.underived)])

def load(pack):
    pack = os.path.abspath(pack) + os.sep
    nl = json.load(open(pack + 'netlist.json'))
    cfg = json.load(open(pack + 'review_config.json')) if os.path.exists(pack + 'review_config.json') else {}
    return nl, cfg

if __name__ == '__main__':
    nl, cfg = load(sys.argv[1])
    if '--starter-config' in sys.argv:
        out = sys.argv[sys.argv.index('--starter-config') + 1]
        t = Topology(nl, {})
        json.dump(starter_config(t, nl), open(out, 'w'), indent=1)
        print(t.summary()); print('wrote starter config', out)
    else:
        print(Topology(nl, cfg).summary())
