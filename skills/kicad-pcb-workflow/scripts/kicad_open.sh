#!/usr/bin/env bash
# Is KiCad holding this project open?  kicad_open.sh PROJECT_DIR [--clean]
# Exit 0 = safe to edit files on disk (closed, or only stale lock files: --clean deletes them); 1 = an editor holds the
# folder (or kicad-cli is busy in it); 2 = cannot tell (ask the user). KiCad keeps its own in-memory copy: if you edit a
# file while it is open, the user's next save silently overwrites your edit (or yours clobbers theirs). Ask the user to
# save and close, then re-read the files, since they may have changed them.
# A lock file alone is not "open": kicad-cli leaves them behind. The decision is kicad_locks.py's (one owner).
exec python3 "$(cd "$(dirname "$0")" && pwd)/kicad_locks.py" status "${1:-.}" "${@:2}"
