#!/usr/bin/env bash
# Verify a KiCad project after a change: DRC (with zone refill and schematic parity) and ERC, both run on a COPY so
# the user's files are not rewritten, summarised and diffed against a baseline.
#   check.sh PROJECT_DIR OUT_DIR [--baseline BASELINE_OUT_DIR] [--accept ACCEPTED.json] [--notes PIN_DECISIONS.json]
#            [--require-notes] [--save-fill]
# The project's own inputs are found by projfiles.py's convention when not given (drc-accept.json, pin-decisions.json
# next to the project or in docs/ up to the repository root), and the files used are printed, so this wrapper and the
# project's own build see the same notes and exemptions.
# Run it on the unchanged project first to make the baseline (git stash is NOT how: copy HEAD with `git worktree` or
# `git archive HEAD | tar -x -C base/`). Then every run lists exactly what the change added.
# --accept: specific known DRC items exempted by name with a reason (drc_summary.py); they are listed as Accepted.
# Never filter a whole violation type: that is how real problems of the same type get hidden.
# Also runs board_lint.py (no courtyard, missing 3D models, silk on part bodies: things DRC does not check),
# nc_audit.py (unused and strapped pins, written to OUT_DIR/nc.md for the record) and partfields.py (every BOM part
# has a datasheet link and a sourcing field, and every schematic field matches the board; exit 1 if not).
# --save-fill copies the refilled board back over the project's board. Only do that when KiCad is closed, and say so.
set -euo pipefail
# the project's board: the one named after its .kicad_pro, else the only .kicad_pcb; never "the first one ls prints"
pick_board() {
  local d="$1" pros n
  pros=$(ls "$d"/*.kicad_pro 2>/dev/null || true); n=$(printf '%s' "$pros" | grep -c . || true)
  if [ "$n" = 1 ] && [ -f "${pros%.kicad_pro}.kicad_pcb" ]; then echo "${pros%.kicad_pro}.kicad_pcb"; return; fi
  local boards; boards=$(ls "$d"/*.kicad_pcb 2>/dev/null || true); n=$(printf '%s' "$boards" | grep -c . || true)
  if [ "$n" = 1 ]; then echo "$boards"; return; fi
  echo "!! $d holds $n boards and no single .kicad_pro names one: $(echo $boards)" >&2; return 1
}
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$1" && pwd)"; OUT="$2"; shift 2; BASE=""; SAVE=0; ACCEPT=""; NOTES=""; REQ=""
abspath() { echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; }
while [ $# -gt 0 ]; do case "$1" in --baseline) BASE="$2"; shift;; --accept) ACCEPT="$(abspath "$2")"; shift;;
  --notes) NOTES="$(abspath "$2")"; shift;; --require-notes) REQ=--require-notes;; --save-fill) SAVE=1;;
  *) echo "unknown option $1"; exit 2;; esac; shift; done
[ -n "$ACCEPT" ] || ACCEPT=$(python3 "$HERE/projfiles.py" find "$PROJ" drc-accept.json) || ACCEPT=""
[ -n "$NOTES" ] || NOTES=$(python3 "$HERE/projfiles.py" find "$PROJ" pin-decisions.json) || NOTES=""
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
KICAD_ENV_NO_PY=1 source "$HERE/kicad_env.sh"
PCB=$(pick_board "$PROJ"); NAME=$(basename "${PCB%.kicad_pcb}")
python3 "$HERE/sexp.py" check "$PROJ"/*.kicad_sch "$PCB" || echo "!! s-expression problems above: fix these first"
rsync -a --delete --exclude .git --exclude 'production*' --exclude '*-backups' --exclude '*.lck' "$PROJ/" "$OUT/proj/"
# refill twice: after zone edits the first refill can leave clearance errors that the second clears
for pass in 1 2; do
  "$KICAD_CLI" pcb drc --refill-zones --save-board --schematic-parity --severity-all --format json -o "$OUT/drc.json" "$OUT/proj/$NAME.kicad_pcb" > "$OUT/drc.log" 2>&1 || true
done
"$KICAD_CLI" sch erc --severity-all --format json -o "$OUT/erc.json" "$OUT/proj/$NAME.kicad_sch" > "$OUT/erc.log" 2>&1 || true
"$KICAD_CLI" sch export netlist --format kicadxml -o "$OUT/net.xml" "$OUT/proj/$NAME.kicad_sch" >/dev/null 2>&1 || true
for k in drc erc; do
  args=()
  [ -n "$BASE" ] && [ -f "$BASE/$k.json" ] && args+=(--baseline "$BASE/$k.json")
  [ "$k" = drc ] && [ -n "$ACCEPT" ] && args+=(--accept "$ACCEPT")
  python3 "$HERE/drc_summary.py" "$OUT/$k.json" ${args[@]+"${args[@]}"} > "$OUT/$k.md"
  echo "== $k"; head -25 "$OUT/$k.md"
  awk 'NR > 25 && /^## Accepted/ {f = 1} f' "$OUT/$k.md"     # always show what was exempted
done
echo "== board_lint (what DRC does not check)"
"$KICAD_PYTHON" "$HERE/board_lint.py" "$OUT/proj/$NAME.kicad_pcb" 2>&1 | tee "$OUT/lint.txt" || true
echo "== no-connect / strap audit (every unused, NC-typed or strapped pin needs a datasheet decision)"
NCARGS=(--md "$OUT/nc.md"); [ -n "$NOTES" ] && NCARGS+=(--notes "$NOTES"); [ -n "$REQ" ] && NCARGS+=("$REQ")
NCRC=0; python3 "$HERE/nc_audit.py" "$OUT/net.xml" "${NCARGS[@]}" > /dev/null 2> "$OUT/nc.log" || NCRC=$?
cat "$OUT/nc.log"
if [ -f "$OUT/nc.md" ]; then echo "$(tail -1 "$OUT/nc.md") (table in $OUT/nc.md)"; else echo "!! nc_audit.py failed (exit $NCRC): no pin audit"; fi
echo "== part fields (Datasheet + sourcing on every BOM part, schematic <-> board parity of every field)"
PFRC=0; python3 "$HERE/partfields.py" check "$OUT/proj/$NAME.kicad_sch" "$OUT/proj/$NAME.kicad_pcb" > "$OUT/fields.txt" 2>&1 || PFRC=$?
grep -E '^(exemptions|[0-9]+ BOM parts|[0-9]+ problem)' "$OUT/fields.txt"; grep -E '^(PROBLEM|ACCEPTED)' "$OUT/fields.txt" | head -12; [ "$PFRC" = 0 ] || echo "!! part-field problems: full list in $OUT/fields.txt"
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
[ "$NCRC" = 0 ] || exit "$NCRC"
[ "$PFRC" = 0 ] || exit "$PFRC"
