"""view.py arguments (it is the first thing an agent runs to learn them):   python3 tests/test_view_args.py
-h prints the usage with no analysis venv needed; a wrong argument count or an unknown layer is a usage error (exit 2),
not an IndexError; the board's own layer name ("Top Layer") selects that layer."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'tests'))
from test_pack_checks import PY, build  # noqa: E402


def view(*a, py=PY):
    return subprocess.run([py, os.path.join(HERE, 'view.py'), *a], capture_output=True, text=True)


def test_usage_and_errors():
    r = view('-h', py=sys.executable)
    assert r.returncode == 0 and 'usage: view.py' in r.stdout and 'board_json layer x0 y0 x1 y1 out' in r.stdout, r
    r = view('board.json', 'F.Cu')
    assert r.returncode == 2 and 'usage: view.py' in r.stderr and 'IndexError' not in r.stderr, r.stderr
    d = tempfile.mkdtemp(); build(d)
    bj = os.path.join(d, 'board.json')
    B = json.load(open(bj)); B['layer_names'] = {'F.Cu': 'Top Layer'}; json.dump(B, open(bj, 'w'))
    r = view(bj, 'Nope', '0', '0', '40', '30', os.path.join(d, 'x.png'))
    assert r.returncode == 2 and 'no copper layer Nope' in r.stderr, r.stderr
    out = os.path.join(d, 'top.png')
    r = view(bj, 'Top Layer', '0', '0', '40', '30', out, '5', '--nets', 'VDD')
    assert r.returncode == 0 and os.path.getsize(out) > 10000, r.stderr
    r = view(bj, 'F.Cu', '-5', '-5', '40', '30', out, '--nets', 'VDD', '5')       # negative window, grid after --nets
    assert r.returncode == 0, r.stderr


if __name__ == '__main__':
    test_usage_and_errors(); print('PASS')
