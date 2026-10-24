#!/usr/bin/env bash
# Is KiCad holding this project open?  kicad_open.sh PROJECT_DIR
# Exit 0 = safe to edit files on disk; exit 1 = open (lock files or a running editor). KiCad keeps its own in-memory copy:
# if you edit a file while it is open, the user's next save silently overwrites your edit (or yours clobbers theirs).
# Ask the user to save and close, then re-read the files, since they may have changed them.
P="${1:-.}"
locks=$(ls "$P"/*.lck "$P"/~*.lck "$P"/.~lock* 2>/dev/null)
# the editors, not kicad-cli or scripts that merely have "kicad" in their path
procs=$(pgrep -lf 'KiCad.app/Contents/MacOS/(kicad|pcbnew|eeschema)$|(^|/)(kicad|pcbnew|eeschema)(\.exe)?$' 2>/dev/null || true)
if [ -n "$locks" ]; then echo "lock files (kicad-cli can leave stale ones behind; if no editor is running, they are safe to delete):"; echo "$locks"; fi
if [ -n "$procs" ]; then echo "KiCad processes:"; echo "$procs"; fi
[ -z "$locks" ] && [ -z "$procs" ] && { echo "not open: safe to edit"; exit 0; }
exit 1
