#!/usr/bin/env python3
"""Run the kicad_sexpr tests without pytest:  python3 tests/run.py [name-filter]
(pytest works too:  python3 -m pytest tests)"""
import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers import Skip  # noqa: E402

flt = sys.argv[1] if len(sys.argv) > 1 else ''
passed = failed = skipped = 0
for fn in sorted(os.listdir(HERE)):
    if not (fn.startswith('test_') and fn.endswith('.py')):
        continue
    mod = importlib.import_module(fn[:-3])
    for name in [n for n in dir(mod) if n.startswith('test_')]:
        if flt and flt not in name and flt not in fn:
            continue
        t0 = time.time()
        try:
            getattr(mod, name)()
            passed += 1
            print('PASS %-55s %5.1fs' % ('%s::%s' % (fn, name), time.time() - t0), flush=True)
        except Skip as e:
            skipped += 1
            print('SKIP %-55s %s' % ('%s::%s' % (fn, name), e), flush=True)
        except Exception:
            failed += 1
            print('FAIL %s::%s' % (fn, name), flush=True)
            traceback.print_exc()
print('\n%d passed, %d failed, %d skipped' % (passed, failed, skipped))
sys.exit(1 if failed else 0)
