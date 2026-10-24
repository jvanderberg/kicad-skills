# Choosing the power-stage components

What the datasheet numbers mean and where the usual rules of thumb go wrong. Source codes in brackets are listed in
`sources.md`.

## Inductors

- **I_sat is not comparable between vendors.** It is the current at which inductance has dropped by a vendor-chosen
  amount - anywhere from 10 % to 50 % [Coilcraft Doc361, Vishay IHLP]. Read the definition, and if it is a 30 % drop,
  your converter's ripple and current-limit behaviour at that point is already degraded. Choose I_sat above the IC's
  *maximum* peak current limit (not the load current) so an overload or short does not saturate the inductor.
- **I_rms (or I_dc) is a heating rating**: the current for a stated temperature rise (often 40 C; 15 C for some chip
  inductors) in still air. Your loss is I_rms^2 x DCR plus core loss; check the temperature rise against your ambient.
- **Saturation behaviour depends on the core** [TI SLUP124]: gapped ferrite holds inductance then drops abruptly at
  saturation; powder-iron / composite (molded) cores roll off gradually - they can lose a large fraction of
  inductance well before their quoted I_sat - and have higher core loss at high ripple and frequency. Molded composite
  inductors are forgiving in overload; ferrite parts need real margin.
- **Core loss** grows with ripple amplitude and frequency; use the vendor's loss calculator for your operating point
  when ripple is large (boost and buck-boost designs, high fsw).
- **Shielded** (molded or shielded drum) for anything near sensitive circuitry or the board edge; unshielded drum
  cores radiate.
- **Chip/multilayer "inductors" in 0603/0805** are for filters and very low-current rails, not for a switcher's power
  stage - check I_sat and DCR before accepting one.

## Ceramic capacitors (MLCC)

- **Capacitance falls with applied DC voltage** (X5R/X7R class II dielectrics). The loss depends on case size and the
  specific part, not just the voltage rating: a larger case at the same rating usually holds more. A *higher voltage
  rating in the same case can lose more capacitance*, not less [ROHM 62AN089E]. Examples from the sources: about 20 %
  loss at 63 % of rating for one Murata type; 3 x 47 uF 10 V parts giving about 87 uF at 5 V (38 % lost)
  [TPS54560 datasheet]. **Always read the part's DC-bias curve** (vendor tools: Murata SimSurfing, TDK, Samsung, KEMET
  K-SIM) and design with the derated value.
- The common "rate the capacitor at 1.5-2x the working voltage" rule is a reasonable reliability margin but has no
  single manufacturer source; it does not by itself guarantee the capacitance you need.
- Temperature: X5R is specified to 85 C, X7R to 125 C (both +/-15 % over range); Y5V/Z5U lose most of their value -
  avoid in power stages.
- Ceramics have very low ESR; that is good for ripple but means the input LC formed with cable inductance is barely
  damped (see input-protection.md).
- **Input ripple current**: buck input capacitors carry I_rms = Iout x sqrt(D (1 - D)), up to Iout/2 - check the
  rating and spread it over several parts. Size the input ceramics for under about 75 mVpp ripple; bulk electrolytics
  do not reduce input ripple and are there for damping and hold-up [TI SLTA055].

## Bulk capacitors

Polymer (aluminium polymer, POSCAP) or electrolytic bulk at the input damps the input LC and supplies hold-up; it
needs adequate ESR for damping and a ripple-current rating. Electrolytic life roughly halves per 10 C rise: keep them
away from hot parts. Rate voltage with margin over the maximum input including transients.

## FETs and diodes (external switches, rectifiers, protection)

- R_DS(on) is specified at a gate voltage and 25 C; at 100-125 C it is roughly 1.4-1.6x higher. Use the gate drive
  you actually have.
- Switching losses scale with Vin x Iout x fsw x (charge to switch) [TI SLPA009A]; gate-drive loss is Qg x Vdrv x fsw.
- SOA matters for anything that operates in its linear region (hot-swap, inrush limiting, load switches with slow
  turn-on): check the SOA curve at your pulse length and case temperature.
- Schottky rectifiers (asynchronous converters): forward drop sets the loss (Vf x Iout x (1 - D)); reverse leakage
  rises steeply with temperature.

## Resistors

- Feedback dividers: 1 % is normal; 0.1 % only where the output accuracy budget needs it. Keep the divider current
  at least ~100x the FB pin leakage [TI SLVA477]; very high values (MOhm) pick up noise and leakage.
- Power rating at 50 % or less of rated; check pulse ratings for resistors that see surges (snubbers, inrush).
- Current-sense shunts: use the manufacturer's land pattern, Kelvin sense connections, and check tempco and power.

## Picking real parts

Translate each calculated requirement into a specification (value, voltage, current, ESR/DCR, case, temperature),
then find a stocked part that meets it with the **pcb-part-selection** skill. When a design tool (WEBENCH etc.) gives
specific MPNs, treat them as the specification to match, not as the parts you must buy.
