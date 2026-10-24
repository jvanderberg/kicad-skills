# What the analysis pack cannot see

- **DC only.** No AC impedance, no field solving, no resonance. Crosstalk uses the 1/(1+(D/h)^2) rule of thumb; Z0 is
  closed-form microstrip over the nearest copper layer (stripline overstated).
- **Copper at 20 C**, no plating build-up on outer layers, 20 um via plating, solder in plated holes ignored. Hot
  copper is about 0.39 % per C worse.
- **Components are not in the model.** Fuses, FETs, shunts, PTCs, connector contacts and wires add their own drops.
- **Zone fills are KiCad's saved fills** after the pack's refill of a copy. If the user's file was saved without a
  refill, the user's board can differ until they refill.
- **Grid artefacts.** A pad cell isolated by grid alignment reports an absurd drop; re-run at another pitch.
- **Hotspot limits** are IPC-2221 isolated-trace figures, pessimistic for planes.
- **Net classes come from regexes** in `review_config.json`. A net that falls through to "slow" is not checked for
  reference continuity. Classify anything long, exposed or near noisy copper.
- **Load currents are inputs**, not measurements: use connector/fuse ratings for power paths and datasheet peaks for
  radios and MCUs, and say which.
- **Hot-loop distances** are pad centre to pad centre; subtract half pad widths before calling a capacitor far away.
- **Crossings are not parallel runs**; a high crosstalk figure on a short overlap is usually an artefact.
- **No thermal model.** Copper loss in watts is reported; temperature rise needs judgment (area, airflow, neighbours).
