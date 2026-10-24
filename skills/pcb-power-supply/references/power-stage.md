# Power stage sizing

Symbols: Vin (use the stated case: min or max), Vout, Iout, fsw (switching frequency), L, dIL (inductor ripple, peak to
peak), eta (efficiency, 0.8-0.95; use the datasheet curve at your operating point), D (duty cycle), Ilim (the IC's
switch current limit: use its *minimum* for capability, *maximum* for component stress).

Always prefer the IC datasheet's "Detailed Design Procedure" where it exists: it encodes that part's limits (minimum
on/off time, compensation range, required output capacitance). Use these equations to understand and cross-check.
Source codes in brackets are in `sources.md`.

## Buck (step-down)  [TI SLVA477; TPS54560 datasheet]

```
D      = Vout / (Vin * eta)
dIL    = (Vin_max - Vout) * Vout / (Vin_max * fsw * L)          ripple is largest at maximum input
L      = (Vin_max - Vout) * Vout / (Vin_max * fsw * dIL)        choose dIL = 0.2-0.4 x Iout_max
I_peak = Iout_max + dIL / 2                                       inductor and high-side switch peak
Iout_max = Ilim_min - dIL / 2                                     what the IC can actually deliver
dVout  ~ dIL / (8 * fsw * Cout)  +  dIL * ESR                     capacitive + ESR ripple
Cin_rms = Iout * sqrt(D * (1 - D))                                maximum Iout / 2 at D = 0.5
Cin_min ~ Iout * D * (1 - D) / (fsw * dVin)                       for an allowed input ripple dVin
Cout_rms = Vout * (Vin - Vout) / (sqrt(12) * Vin * L * fsw)        output capacitor ripple current
```
- Inductor rating: **I_sat > Ilim_max** of the IC (a short or overload drives the inductor to the current limit;
  saturating it there makes the current spike). I_rms rating > Iout_max with thermal margin.
- Minimum on-time: at Vin_max, D x (1/fsw) must exceed the IC's minimum on-time, or it skips pulses (high ratios at
  high frequency, e.g. 24 V to 1 V at 2 MHz, fail this). This sets the highest usable switching frequency.
- If you read TI SLVA477's appendix, note its duty-cycle formula there is misprinted; the body's D = Vout/(Vin x eta)
  is the correct one.
- Output capacitance: within the IC's stable range after DC-bias derating; add for load steps:
  C >= dI_step^2 * L / (2 * Vout * dV_allowed) is a common estimate of the overshoot-limited minimum.

## Boost (step-up)  [TI SLVA372; SLVA061]

```
D        = 1 - Vin_min * eta / Vout
dIL      = Vin_min * D / (fsw * L)
L        = Vin_min * (Vout - Vin_min) / (dIL * fsw * Vout)        choose dIL ~ 0.2-0.4 x average inductor current
IL_avg   = Iout / (1 - D)                                          inductor (input) current is larger than Iout
I_sw_pk  = IL_avg + dIL / 2
Iout_max = (Ilim_min - dIL / 2) * (1 - D)                          what the IC can actually deliver
Cout_min = Iout * D / (fsw * dVout)
```
- The output current a boost can deliver falls fast as the ratio grows; check Iout_max at the lowest input.
- A plain boost has a DC path from input to output through the inductor and the rectifier: **no inherent short-circuit
  protection** and the output sits at Vin - Vf when disabled. Use a part with load disconnect if that matters.
- Output capacitor RMS current is high (pulsed output current); check its rating.
- Boosts have a right-half-plane zero, f_RHPZ = Vout x (1 - D)^2 / (2 pi x L x Iout) [SLVA061]: worst at the lowest
  input and highest load. The loop must cross over well below it (about a fifth is common practice), which is why
  boosts respond slowly and why the datasheet's inductance and output-capacitance ranges matter.

## Buck-boost (4-switch, non-inverting)  [TI SLVA535]

- Size for both modes. The worst inductor current is in boost mode at the lowest input:
  `IL_avg = Iout * Vout / (Vin_min * eta)`, `I_peak = IL_avg + dIL/2`.
- The worst ripple is usually at the highest input (buck mode). Compute both and choose L for the larger constraint,
  then I_sat > Ilim_max.
- Input capacitors see buck-mode pulsed current, output capacitors see boost-mode pulsed current: both need low-ESR
  ceramics at the pins.
- Example (hypothetical: 5-24 V in, 5 V / 3 A out, 1 MHz): in boost mode at 4.5 V in the inductor carries about 3.7 A
  average plus ripple. A controller with a 10 A+ current limit would need an inductor with I_sat above that - physically
  large - so choose a converter (or variant) whose current limit matches the load, and the inductor stays reasonable.

## SEPIC / inverting

Use the vendor's design tool; coupled inductors and coupling capacitors add RMS-current ratings to check.

## LDO  [TI SLVA079, SLYT202, SLYT187]

```
P_d   = (Vin_max - Vout) * Iout + Vin * Iq
Tj    = Ta + P_d * theta_JA                       theta_JA from the datasheet is for a JEDEC test board; yours will differ
Vin_min >= Vout + V_dropout(at Iout, hot)
```
- Dropout is specified at a current and temperature; use the worst case.
- PSRR falls with frequency; most LDOs reject little at a switcher's 1-2 MHz. It also collapses when the headroom
  (Vin - Vout) drops below about 1 V at heavy load: an LDO used as a post-filter needs headroom. Above the loop's
  bandwidth only the output capacitor and parasitics reject ripple. A ferrite + capacitor in front helps.
- Stability: modern CMOS LDOs are stable with small ceramics; older PMOS-pass types need an ESR window (roughly
  0.1-several Ohm) and can oscillate on ceramics alone - check the datasheet's stability chart.
- Accuracy: line + load regulation plus the root-sum-square of reference, amplifier, resistor and temperature terms.
- Quiescent current matters for battery products.
- Rule of thumb: above a few hundred mW of LDO loss, use a buck (or a buck followed by an LDO for noise).

## Feedback and enable dividers  [TI SLVA477, SLYT469, SLVA289; TPS54560 datasheet]

```
Vout = Vref * (1 + R_top / R_bot)
R_top = R_bot * (Vout / Vref - 1)
Accuracy ~ Vref tolerance + about 2 x resistor tolerance x (1 - Vref/Vout)   (worst case; 1 % resistors common)

EN rising threshold:   Vin_on  = V_EN_rise * (1 + R_top / R_bot)        (plus any EN pull-up current terms per datasheet)
Hysteresis (current-type): dV = I_hys * R_top                              e.g. 5 uA x 56 k = 0.28 V
EN pin at max input:   V_EN = Vin_max * R_bot / (R_top + R_bot)  <  EN abs max
```
- Keep the divider current at least ~100x the FB pin leakage; R_bot of 10-100 k is typical (follow the datasheet).
  Leakage error: V_FB = R_bot x (Vout - I_FB x R_top) / (R_top + R_bot).
- A feed-forward capacitor across R_top improves transient response on some parts, only where the datasheet says:
  C_ff = 1 / (2 pi x f_c) x sqrt((1/R_top) x (1/R_top + 1/R_bot)), with f_c the crossover without it [SLVA289].
- Current-type UVLO hysteresis gives R_top directly: R_top = (V_start - V_stop) / I_hys.
- Example: EN threshold 1.23 V, hysteresis 5 uA, R_top 56 k, R_bot 22 k: on at 1.23 x 78/22 = 4.36 V,
  hysteresis 0.28 V, EN at 28 V input = 7.9 V (abs max 20 V: fine).

## Losses and temperature (estimate)  [TI SLVA390, SLPA009, SPRA953]

```
Buck high-side conduction:  D * (Iout^2 + dIL^2/12) * Rds_on_HS
Buck low-side conduction:   (1 - D) * (Iout^2 + dIL^2/12) * Rds_on_LS
Switching:                  Vin * Iout * fsw * Q_sw / I_gate     (rough: 0.5 * Vin * Iout * (t_r + t_f) * fsw)
Gate drive:                 Q_g * V_drive * fsw
Dead time:                  V_sd * Iout * t_dead * fsw;   reverse recovery: Q_rr * Vin * fsw;   Coss: 0.5 * Q_oss * Vin * fsw
Inductor:                   I_rms^2 * DCR  (+ core loss at high ripple - from the vendor's calculator)
Async diode:                Vf * Iout * (1 - D)
```
Rds_on rises about 1.5x from 25 C to 125 C. Prefer the datasheet's efficiency curve at your Vin/Vout/fsw; the loss is
P_in - P_out = P_out * (1/eta - 1). Do not trust Tj = Ta + P x theta_JA for your board: theta_JA is measured on a
JEDEC test board through which most of the heat leaves, and the board alone changes it by tens of percent [SPRA953].
Use it only for a first estimate, give the part the copper and vias its datasheet layout shows, and confirm with a
measured case temperature (psi_JT relates top-of-package temperature to junction temperature).
