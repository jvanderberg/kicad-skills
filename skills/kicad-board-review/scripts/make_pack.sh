#!/usr/bin/env bash
# Build a review pack for a KiCad project.
#   make_pack.sh PROJECT_DIR PACK_DIR [--no-power] [--inner-um 17.5,35]
# Steps: copy the board, refill its zones on the copy (never the original), export the netlist, dump geometry, digest the
# netlist, then run planes / emc / power (if PACK_DIR/review_config.json has power_runs) and write the markdown reports.
# Override tool paths with KICAD_CLI, KICAD_PYTHON and PY (a python with numpy, scipy, shapely>=2, matplotlib).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$1" && pwd)"; PACK="$2"; shift 2
POWER=1; INNER="17.5,35"
while [ $# -gt 0 ]; do case "$1" in --no-power) POWER=0;; --inner-um) INNER="$2"; shift;; esac; shift; done
mkdir -p "$PACK"; PACK="$(cd "$PACK" && pwd)"
source "$HERE/kicad_env.sh"
PCB=$(ls "$PROJ"/*.kicad_pcb | head -1); SCH="${PCB%.kicad_pcb}.kicad_sch"
[ -f "$SCH" ] || { echo "no root schematic next to $PCB"; exit 1; }
if ls "$PROJ"/*.lck "$PROJ"/~*.lck >/dev/null 2>&1; then echo "note: KiCad lock files present; the pack reads the files as saved on disk"; fi
# work on a copy of the whole project (schematics, project-local libraries and lib tables resolve via ${KIPRJMOD})
rsync -a --delete --exclude .git --exclude 'production*' --exclude '*-backups' --exclude '*.lck' "$PROJ/" "$PACK/proj/"
CPCB="$PACK/proj/$(basename "$PCB")"; CSCH="$PACK/proj/$(basename "$SCH")"
# DRC on the copy refills zones (island removal applied) and saves them, so the analysis sees what KiCad would plot
"$KICAD_CLI" pcb drc --refill-zones --save-board --schematic-parity --format json -o "$PACK/drc.json" "$CPCB" >/dev/null 2>&1 || true
"$KICAD_CLI" sch export netlist --format kicadxml -o "$PACK/net.xml" "$CSCH" >/dev/null
"$KICAD_CLI" sch erc --format json -o "$PACK/erc.json" "$CSCH" >/dev/null 2>&1 || true
"$KICAD_PYTHON" "$HERE/boarddump.py" "$CPCB" "$PACK"
"$PY" "$HERE/netdigest.py" "$PACK" "$(basename "${PCB%.kicad_pcb}")"
STARTER=0
[ -f "$PACK/review_config.json" ] || { cp "$HERE/../assets/review_config.example.json" "$PACK/review_config.json"; STARTER=1
  echo "wrote a starter review_config.json with PLACEHOLDER refs and nets: replace them with this board's, then re-run (power runs skipped this time)"; }
[ "$STARTER" = 1 ] && POWER=0
"$PY" "$HERE/planes.py" "$PACK"
"$PY" "$HERE/emc.py" "$PACK"
if [ "$POWER" = 1 ] && "$PY" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("power_runs") else 1)' "$PACK/review_config.json"; then
  for um in ${INNER//,/ }; do "$PY" "$HERE/power.py" "$PACK" --inner-um "$um" --tag "inner_${um}um"; done
fi
"$PY" "$HERE/report.py" "$PACK"
"$PY" "$HERE/drc_summary.py" "$PACK/drc.json" > "$PACK/drc.md" || true
echo "pack ready: $PACK (netlist.md board_overview.md power.md emc.md drc.md)"
