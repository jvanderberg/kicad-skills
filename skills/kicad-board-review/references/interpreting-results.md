# Interpreting the analysis, and explaining it

Users ask follow-up questions in plain words. Answer with the measured number, the physics in one or two sentences,
what it means for their board, and what is not included. When you do not have a number, run the solver - do not guess.

## "This is the voltage drop?"

Yes - in the copper only. Each power run holds one pad at 0 V and draws the stated current from the load pads; the
result is the IR drop in pours, tracks and vias between them, plus the heat in that copper. Present it as the chain
the current actually follows (terminal -> fuse -> protection -> shunt -> each load) with one number per hop, point out
which hop dominates (usually the long rail fanning out to the loads), and add what is *not* included: fuse, FET, shunt,
PTC, connector contacts, the wires. Put the total in proportion (90 mV is 0.75 % of 12 V; the load's own wiring often
loses more).

## "We have a massive ground plane - what are its limits?"

A plane still has resistance (about 0.5 mOhm per square at 1 oz, 1 mOhm at 0.5 oz, regardless of the square's size).
It stays low because current spreads; its limits are thin inner copper, crowding where current enters and leaves (a
single connector pin), and holes/cuts. Report the ground run as offsets from a reference point (the MCU's ground pad):
the input terminals, the far loads, the regulators, and the logic. Explain the direction - return current makes the
board's ground sit slightly *above* the supply's minus terminal - and that what a part sees is its supply minus its own
local ground, so a shift shared by all logic changes nothing. The place it matters is between a driver and its
receiver on different grounds (data lines to the loads).

## "So the other parts see 0.1 V less?"

Separate the questions: logic regulators regulate relative to their own ground, so logic is unaffected; a load at the
end of a power path sees supply minus (+ side drops) minus (ground side rise). Add those up explicitly for the worst
load and scale to their supply voltage and load fraction.

## "Enough vias?"

Run `power.py --net <net> --source <ref:pad> --sink ...` and read the per-via currents. Report the count, the busiest
via's current, the barrel resistance (about 1.3 mOhm for 0.3 mm / 20 um / 1.6 mm), the drop across the array vs the
rest of the path, and the heat per via (I^2 R, milliwatts). The usual answer: the vias are not the limit; the pour is.
Uneven sharing (front row takes most) is normal.

## "Is this capacitor close enough?" / "How much inductance is that?"

Answer from `emc.md` "Decoupling": the path from the pin to its nearest capacitor along the copper (track, plane, vias)
and its inductance estimate. A track over a close plane is a microstrip: its loop inductance per mm is Z0 x sqrt(eps_eff)
/ c, about 0.2-0.4 nH/mm on an outer layer over a 0.1-0.2 mm prepreg - not the ~1 nH/mm of a wire in free space, which
overstates it several times and makes every move look worth doing. At the frequency that matters (the IC's edge rate or
switching harmonics), compare that inductance's impedance with the capacitor's own ESL (0.3-1 nH for 0402-0805) and say
which dominates. Before recommending a move, compute the new path the same way: if the number barely changes, the move
is not the fix.

## "Is the impedance right?"

The pack's Zdiff is a closed-form estimate from the measured width and gap; the gap to the nearest pour says whether
it is too high (a pour at its default clearance makes the pair partly coplanar). The authority is the fab's own
calculator for its stackup: run it with the as-built width, gap and pour gap (browser automation can drive it), and
quote its numbers.

## "Will it get hot?" / "Does the board need more stitching vias for heat?"

Answer from `thermal.md`, in this order. (1) The loss, per corner, and where it is: a battery path's FETs, fuse and
BATFET at the lowest cell voltage can out-heat every converter together. (2) The board average, P / (A (h_top + h_bottom)):
it depends only on the total loss, the board area and the cooling, so if it is already past a limit, no copper or via
change fixes it - the loss, the area, the enclosure or the airflow must change. (3) How far each hot part sits above that
average: that excess is what copper, pours and vias can reduce. (4) The what-if: ground stitching vias on a grid, solved
again. If it moves no hot part by more than a kelvin or two, stitching is not what limits the temperature (it is still an
EMC question); if it does, it is a cheap fix. A pour of a net that exists on no other layer cannot be stitched at all:
give the net copper on another layer, enlarge the pour, or lower the loss. Always quote the range over h (still air in a
closed box is the largest uncertainty), the ambient you assumed, and what the model leaves out (wires and cells carry
heat away; the box warms up), and compare the corner's duration with the board's time constant.

## "The pack found nothing" / "0 hot loops"

Read the "Coverage and warnings" section before any table. An empty table under a warning ("hot loop U3: NOT
CHECKED", "no ground copper on In2.Cu", "review_config.json is the STARTER") means the check did not run on that
item, not that it passed. Say so in the report, fix the config, and re-run. Derived items (switch nodes, hot loops) are
labelled; confirm each against the datasheet before relying on it.

## Hot loops: distance and current path

The hot-loop table has pad-to-pad geometry and a DC solve of the same loop. Explain both: the distance and plan area
say how big the loop is drawn; the solve says where the current actually goes. "One via carries 100 %" means the
capacitor's ground pad reaches the IC's ground pin only through that via and an inner layer, so the real loop includes
the board thickness and the via's inductance. The fix is a same-layer path (a short track or pour between the pads),
then re-run the pack to show the share drop.

## Grid artefacts and sanity checks

- One sink reporting an absurd drop (megavolts) while others are sane: a pad cell isolated by the grid alignment.
  Re-solve with a slightly different pitch (`h` 0.19 instead of 0.2). If the number becomes sane, it was the grid.
- A result that changed after an unrelated edit: the grid origin moved; compare at two pitches.
- Compare drops with a hand estimate (length / width squares x sheet resistance x current). A factor of 2 off is
  plausible (spreading); a factor of 10 means a modelling problem (wrong pad, wrong net name, a disconnected island).
- Results depend on the zone fills. The pack refills with KiCad; a board saved without a refill can have stale fills.

## Before / after comparisons

After a rework, rebuild the pack and tabulate every run's worst drop and copper loss before and after, plus the
ground return and plane slot counts. Call out anything that got worse even if it is small, with the reason (example:
a rework that lengthens a logic supply feed from 150 to 190 mOhm can still leave ample margin at the regulator - say
so, and record it as accepted).
