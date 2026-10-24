# pcbnew python: what to trust it with (KiCad 10.0.x)

Use KiCad's bundled python (`kicad_env.sh` finds it; on macOS
`/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`). It has no numpy
extras worth relying on and no shapely/scipy: dump geometry to JSON with it and analyse in a normal venv
(`kicad-board-review/scripts/boarddump.py`). Its stderr is noisy (`assert "traits" failed in Get(): create wxApp before
calling this`) - harmless; filter it.

## Good uses

- Loading a board and reading geometry (pads with polygons, tracks, arcs, vias, zones and their **saved** fills,
  outline): `boarddump.py`.
- Creating a footprint from a library and placing it, or moving/rotating existing footprints - one stage, in its own
  process.

## Known failures and the workaround

| Symptom | Cause | Do this instead |
|---|---|---|
| Tracks change net after `LoadBoard` + `Save` | pcbnew re-derives track nets from the pads they touch | Delete or re-net obsolete copper as **text before** any pcbnew stage |
| Later calls fail: `'SwigPyObject' object is not iterable` | `b.Remove(item)` corrupts the session | Snapshot `list(b.GetTracks())` first and defer removals, or delete as text |
| Second `FootprintLoad` frees the first | SWIG registry breaks across several loads | Load, configure and add each footprint in one step; separate processes per stage |
| Many one-item `silk_overlap` warnings | Loaded footprints share the library file's uuids | `f = pcbnew.Cast_to_FOOTPRINT(pcbnew.FootprintLoad(dir, name).Duplicate(False))` |
| `'BOARD_ITEM' object has no attribute 'SetFPID'` | Missing cast | Same cast as above |
| Footprint has no library nickname, parity complains | `FootprintLoad` drops it | `f.SetFPID(pcbnew.LIB_ID("Lib", name))` |
| Many silk warnings after setting fields | `SetField` creates visible fields on F.SilkS; hiding via `GetFieldByName` does not stick | Write hidden `(property ...)` blocks as text |
| `PCB_VIA::GetWidth called without a layer argument` | KiCad 10 API change | `v.GetWidth(pcbnew.F_Cu)` |
| `GetBoardPolygonOutlines()` signature error | KiCad 10 API change | `eps = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(eps, True)` |
| Islands that KiCad would remove | `ZONE_FILLER(b).Fill(...)` skips island removal | Refill with `kicad-cli pcb drc --refill-zones --save-board` (twice after zone edits) |
| Whole file reformatted | Any `Save` | Accept it only in the footprint stage; do everything else as text |

Creating vias and tracks through the API works but is fragile across versions; text is simpler and exact
(`file-format.md` has the blocks).
