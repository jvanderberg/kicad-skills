#!/usr/bin/env bash
# Verify a KiCad project after a change: DRC (with zone refill and schematic parity) and ERC, both run on a COPY so
# the user's files are not rewritten, summarised and diffed against a baseline.
#   check.sh PROJECT_DIR OUT_DIR [--baseline BASELINE_OUT_DIR] [--save-fill]
# Run it on the unchanged project first to make the baseline (git stash is NOT how: copy HEAD with `git worktree` or
# `git archive HEAD | tar -x -C base/`). Then every run lists exactly what the change added.
# --save-fill copies the refilled board back over the project's board. Only do that when KiCad is closed, and say so.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$1" && pwd)"; OUT="$2"; shift 2; BASE=""; SAVE=0
while [ $# -gt 0 ]; do case "$1" in --baseline) BASE="$2"; shift;; --save-fill) SAVE=1;; esac; shift; done
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
KICAD_ENV_NO_PY=1 source "$HERE/kicad_env.sh"
PCB=$(ls "$PROJ"/*.kicad_pcb | head -1); NAME=$(basename "${PCB%.kicad_pcb}")
python3 "$HERE/sexp.py" check "$PROJ"/*.kicad_sch "$PCB" || echo "!! s-expression problems above: fix these first"
rsync -a --delete --exclude .git --exclude 'production*' --exclude '*-backups' --exclude '*.lck' "$PROJ/" "$OUT/proj/"
# refill twice: after zone edits the first refill can leave clearance errors that the second clears
for pass in 1 2; do
  "$KICAD_CLI" pcb drc --refill-zones --save-board --schematic-parity --severity-all --format json -o "$OUT/drc.json" "$OUT/proj/$NAME.kicad_pcb" > "$OUT/drc.log" 2>&1 || true
done
"$KICAD_CLI" sch erc --severity-all --format json -o "$OUT/erc.json" "$OUT/proj/$NAME.kicad_sch" > "$OUT/erc.log" 2>&1 || true
"$KICAD_CLI" sch export netlist --format kicadxml -o "$OUT/net.xml" "$OUT/proj/$NAME.kicad_sch" >/dev/null 2>&1 || true
for k in drc erc; do
  if [ -n "$BASE" ] && [ -f "$BASE/$k.json" ]; then python3 "$HERE/drc_summary.py" "$OUT/$k.json" --baseline "$BASE/$k.json" > "$OUT/$k.md"
  else python3 "$HERE/drc_summary.py" "$OUT/$k.json" > "$OUT/$k.md"; fi
  echo "== $k"; head -25 "$OUT/$k.md"
done
python3 - "$OUT/drc.json" <<'E'
import json, sys
d = json.load(open(sys.argv[1]))
print('unconnected items: %d   (must be 0 before you say "done")' % len(d.get('unconnected_items', [])))
print('schematic parity issues: %d' % len(d.get('schematic_parity', [])))
E
if [ "$SAVE" = 1 ]; then
  "$HERE/kicad_open.sh" "$PROJ" >/dev/null || { echo "KiCad is open: not copying the refilled board back"; exit 1; }
  cp "$OUT/proj/$NAME.kicad_pcb" "$PCB"; echo "refilled board copied back to $PCB"
fi
