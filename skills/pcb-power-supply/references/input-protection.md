# Input protection for DC-powered boards

Walk the input under: normal operation, reversed polarity, hot-plugging the real cable, a surge on the line, an
output short, and (for several inputs) one source present while others are absent. Sources in `sources.md`.

## Reverse polarity

| Option | Loss | Notes |
|---|---|---|
| Series Schottky diode | Vf x I (0.3-0.5 V) | Simplest; fine at low current |
| P-channel FET in the supply line (gate to ground through a resistor, gate clamped with a zener to its Vgs max) | I^2 x R_DS(on) | Low loss; **does not block reverse current**: if the input drops, hold-up capacitors discharge back out of the input [TI SLVAE57B] |
| Ideal-diode controller + N-channel FET | I^2 x R_DS(on) | Low loss *and* blocks reverse current quickly; also OR-s several sources; needs layout care and a FET rated for the surge |

Check the FET's V_DS and V_GS ratings against the maximum input plus surge, and that downstream parts survive the
moment before protection acts. A unidirectional TVS placed *before* the reverse-polarity element conducts forward
when the input is reversed - acceptable only if the source or a fuse limits that current.

## Surge and TVS selection

- Standoff voltage (V_RWM) above the highest normal input; **clamping voltage at the surge current** below the absolute
  maximum of everything on that rail. The clamp is typically well above the standoff (often around 1.5x; read the part's
  table - this ratio is practice, not a rule).
- Peak pulse power / I_pp for the expected surge; a small-signal zener is not a surge clamp.
- Place the TVS at the connector with a short, wide path to ground.

## Hot-plugging and input overshoot

A ceramic input capacitor plus the inductance of the supply cable forms a lightly damped LC: plugging in a live
supply can ring the input well above its nominal voltage (an undamped LC step overshoots towards twice the step).
More capacitance does not fix this; **damping does** [TI SLUAAL8]: an aluminium electrolytic or polymer bulk capacitor
with appropriate ESR, or an RC snubber across the input (e.g. a few ohms in series with a few uF, resistor rated for the
pulse), plus a TVS. Check the result against the regulator's VIN absolute maximum.

## Inrush

Charging capacitance from a stiff source draws I = C dV/dt - large enough to trip upstream protection or droop a shared
rail (a 100 uF load switched onto a 3.3 V rail can pull several amps and drop the rail [TI SLVA670A]). Use the
converter's soft start, a load switch with controlled slew, a hot-swap/eFuse controller, or an NTC/resistor for
small supplies.

## Fusing and current limits

- Fuse the input for the wiring and connector rating; time-lag vs fast per the inrush.
- Resettable PTCs: hold current derates with temperature (rate for the enclosure temperature); the maximum interrupt
  current must exceed what the source can deliver into a short.
- Every output that leaves the board on a cable gets its own protection rated for that wire.
- Boost converters have a DC path from input to output through the inductor and rectifier, so a shorted output is not
  protected by the converter itself unless the part has a load-disconnect switch (standard practice; check the
  datasheet).

## UVLO and multiple sources

- Set the enable/UVLO threshold above the voltage where the converter can regulate and below the lowest real input
  after all upstream drops (fuse, reverse-protection, OR-ing, copper). Hysteresis from the datasheet equation
  (current-type hysteresis: R_top = (V_start - V_stop) / I_hys) [TPS54560 datasheet].
- Check the enable pin's absolute maximum at the highest input.
- Several inputs into one rail: OR them deliberately (ideal diodes or Schottkys) or state "one source only"; work out
  the worst case where the lowest source alone must start everything.

## Mains

Do not put mains on a hobby board. Use a certified external adapter or a certified enclosed AC/DC module, and treat
its DC output as the board's input.
