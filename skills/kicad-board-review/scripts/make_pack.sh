#!/usr/bin/env bash
# Build a review pack for a KiCad project.
#   make_pack.sh PROJECT_DIR PACK_DIR [--no-power] [--inner-um 17.5,35]
# Steps: copy the board, refill its zones on the copy (never the original), export the netlist, dump geometry, digest the
# netlist, then run planes / emc / power (if PACK_DIR/review_config.json has power_runs) / thermal and write the reports.
# Override tool paths with KICAD_CLI, KICAD_PYTHON and PY (a python with numpy, scipy, shapely>=2, matplotlib).
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
PROJ="$(cd "$1" && pwd)"; PACK="$2"; shift 2
POWER=1; INNER="17.5,35"
while [ $# -gt 0 ]; do case "$1" in --no-power) POWER=0;; --inner-um) INNER="$2"; shift;; esac; shift; done
mkdir -p "$PACK"; PACK="$(cd "$PACK" && pwd)"
source "$HERE/kicad_env.sh"
PCB=$(pick_board "$PROJ"); SCH="${PCB%.kicad_pcb}.kicad_sch"
[ -f "$SCH" ] || { echo "no root schematic next to $PCB"; exit 1; }
if ls "$PROJ"/*.lck "$PROJ"/~*.lck >/dev/null 2>&1; then echo "note: KiCad lock files present; the pack reads the files as saved on disk"; fi
# work on a copy of the whole project (schematics, project-local libraries and lib tables resolve via ${KIPRJMOD})
rsync -a --delete --exclude .git --exclude 'production*' --exclude '*-backups' --exclude '*.lck' "$PROJ/" "$PACK/proj/"
CPCB="$PACK/proj/$(basename "$PCB")"; CSCH="$PACK/proj/$(basename "$SCH")"
# DRC on the copy refills zones (island removal applied) and saves them, so the analysis sees what KiCad would plot
rm -f "$PACK/drc.json"
"$KICAD_CLI" pcb drc --refill-zones --save-board --schematic-parity --format json -o "$PACK/drc.json" "$CPCB" > "$PACK/drc.log" 2>&1 || true
[ -s "$PACK/drc.json" ] || { echo "!! kicad-cli DRC failed (see $PACK/drc.log): zones were NOT refilled, the analysis below reads the fills as saved"; }
"$KICAD_CLI" sch export netlist --format kicadxml -o "$PACK/net.xml" "$CSCH" >/dev/null
"$KICAD_CLI" sch erc --format json -o "$PACK/erc.json" "$CSCH" >/dev/null 2>&1 || echo "!! kicad-cli ERC failed: no erc.json"
"$KICAD_PYTHON" "$HERE/boarddump.py" "$CPCB" "$PACK"
# review config: the pack's own, else the project's (one discovery convention: projfiles.py), else a starter derived
# from this board's netlist (topology.py) - never placeholder refs that silently match nothing
STARTER=0
if [ ! -f "$PACK/review_config.json" ]; then
  if FOUND=$(python3 "$HERE/projfiles.py" find "$PROJ" review_config.json 2>"$PACK/.cfgmsg"); then
    cp "$FOUND" "$PACK/review_config.json"; echo "$FOUND" > "$PACK/.config_source"    # relative inputs (path_budget files) resolve next to it
  fi
  cat "$PACK/.cfgmsg"; rm -f "$PACK/.cfgmsg"
fi
"$PY" "$HERE/netdigest.py" "$PACK" "$(basename "${PCB%.kicad_pcb}")"
if [ ! -f "$PACK/review_config.json" ]; then
  "$PY" "$HERE/topology.py" "$PACK" --starter-config "$PACK/review_config.json"; STARTER=1
  echo "wrote a STARTER review_config.json derived from this board (switch nodes, hot loops, ground, power nets): check it, add bus classes and power_runs, delete \"starter\", re-run (power runs skipped this time)"
  "$PY" "$HERE/netdigest.py" "$PACK" "$(basename "${PCB%.kicad_pcb}")" >/dev/null
else
  "$PY" "$HERE/topology.py" "$PACK" | sed 's/^/topology: /'
fi
[ "$STARTER" = 1 ] && POWER=0
"$PY" "$HERE/planes.py" "$PACK"
"$PY" "$HERE/emc.py" "$PACK"
if [ "$POWER" = 1 ] && "$PY" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("power_runs") else 1)' "$PACK/review_config.json"; then
  for um in ${INNER//,/ }; do "$PY" "$HERE/power.py" "$PACK" --inner-um "$um" --tag "inner_${um}um"; done
fi
# heat: always runs - with no "thermal" config it still lists every candidate heat source as UNKNOWN, measures the
# thermal vias and the stitching, and says that no temperature was computed
"$PY" "$HERE/thermal.py" "$PACK" || echo "!! thermal.py failed: no thermal.md"
"$PY" "$HERE/report.py" "$PACK"
"$PY" "$HERE/drc_summary.py" "$PACK/drc.json" > "$PACK/drc.md" || true
echo "pack ready: $PACK (netlist.md board_overview.md power.md emc.md thermal.md drc.md) - read the 'Coverage and warnings' section of power.md, emc.md and thermal.md first"
