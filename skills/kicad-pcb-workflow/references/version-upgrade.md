# Converting a project from KiCad 9 to 10

1. Commit first. Export the KiCad 9 netlist with the KiCad 9 CLI before upgrading (keep the old app around:
   `/Applications/KiCad 9.x/...`).
2. Upgrade every file with the CLI:
   ```
   for f in *.kicad_sch; do kicad-cli sch upgrade "$f"; done
   kicad-cli pcb upgrade board.kicad_pcb
   for l in *.kicad_sym; do kicad-cli sym upgrade "$l"; done
   for l in *.pretty; do kicad-cli fp upgrade "$l"; done
   ```
   A legacy/non-KiCad `.pretty` fails with "Output path must be specified to convert legacy and non-KiCad libraries".
3. Verify electrically: export the KiCad 10 netlist and compare nets, pins and components with the KiCad 9 one.
   KiCad 10 writes the netlist multi-line - collapse whitespace before parsing, or a naive parser finds "no nets".
4. Parity: KiCad 10 compares footprint fields with the schematic; `Datasheet "~"` on the board vs `""` in the
   schematic shows as `footprint_symbol_field_mismatch`. Fix with a text replace on the board.
5. Libraries: parts that lived in the user's KiCad 9 global or PCM libraries (EasyEDA, PCM_JLCPCB, ...) are missing in
   KiCad 10's global tables. Copy the used symbols/footprints/3D models into project libraries under the same
   nicknames with `${KIPRJMOD}` paths, so no reference changes and the project opens anywhere: copy the file, then
   `scripts/libtable.py add PROJECT_DIR sym|fp NICKNAME COPIED_PATH`.
6. `lib_symbol_mismatch` from arc midpoints that differ between the schematic's embedded copy and the library: copy the
   embedded symbol back into the library and `sym upgrade --force`.
7. kicad-cli does not touch `.kicad_pro`; KiCad 10 rewrites it on first open and the first ERC adds new default
   settings. Tell the user to expect that diff.
8. Run the full check (`check.sh`) and record the result as the new baseline.
