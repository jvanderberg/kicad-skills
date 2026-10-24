# Source this to get KICAD_CLI, KICAD_PYTHON (KiCad's python, which has pcbnew) and PY (analysis python).
# Respects values already set in the environment.
if [ -z "${KICAD_CLI:-}" ]; then
  for c in /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli "$(command -v kicad-cli 2>/dev/null)" \
           "/c/Program Files/KiCad/10.0/bin/kicad-cli.exe" "/c/Program Files/KiCad/9.0/bin/kicad-cli.exe"; do
    [ -n "$c" ] && [ -x "$c" ] && KICAD_CLI="$c" && break
  done
fi
if [ -z "${KICAD_PYTHON:-}" ]; then
  for c in /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
           "/c/Program Files/KiCad/10.0/bin/python.exe" "/c/Program Files/KiCad/9.0/bin/python.exe" /usr/bin/python3; do
    [ -x "$c" ] && "$c" -c 'import pcbnew' 2>/dev/null && KICAD_PYTHON="$c" && break
  done
fi
if [ -z "${PY:-}" ] && [ -z "${KICAD_ENV_NO_PY:-}" ]; then
  _venv="${KICAD_SKILLS_VENV:-$HOME/.cache/kicad-skills/venv}"
  if [ ! -x "$_venv/bin/python" ]; then
    echo "creating analysis venv at $_venv (numpy scipy shapely matplotlib)" >&2
    python3 -m venv "$_venv" && "$_venv/bin/pip" -q install numpy scipy 'shapely>=2' matplotlib >&2
  fi
  PY="$_venv/bin/python"
fi
: "${KICAD_CLI:?kicad-cli not found; set KICAD_CLI}"; : "${KICAD_PYTHON:?no python with pcbnew found; set KICAD_PYTHON}"
export KICAD_CLI KICAD_PYTHON PY 2>/dev/null || export KICAD_CLI KICAD_PYTHON
