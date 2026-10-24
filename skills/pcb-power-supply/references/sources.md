# Sources

Manufacturer application notes and datasheets behind the PSU references. Search the document number on the vendor's
site (ti.com/lit/an/<number>/<number>.pdf for TI notes). Page references are to the PDF.

| Code | Document | Used for |
|---|---|---|
| TI SLVA477 | Basic Calculation of a Buck Converter's Power Stage | Buck duty cycle, ripple, inductor, peak current, output capacitance, divider current (Eq 1 is correct; an appendix copy of the duty-cycle equation is misprinted) |
| TI SLVA372 | Basic Calculation of a Boost Converter's Power Stage | Boost duty, maximum output current from the switch limit, peak current, output capacitance |
| TI SLVA061 | Understanding Boost Power Stages | Right-half-plane zero: f_RHPZ = Vout (1 - D)^2 / (2 pi L Iout) |
| TI SLVA535 | Basic Calculations of a 4-Switch Buck-Boost Power Stage | Sizing for both modes; peak current in boost mode at minimum input |
| TI SLVA390 | Calculating Efficiency (PMP - DC/DC controllers) | Conduction losses, inductor DCR loss |
| TI SLPA009 | Power Loss Calculation With Common Source Inductance Consideration for Synchronous Buck Converters | Switching, gate, dead-time, reverse-recovery and Coss losses |
| TI SLVA289 | Optimizing Transient Response of Internally Compensated DC-DC Converters with Feed-Forward Capacitor | Feed-forward capacitor value |
| TI SLYT469 | Methods of output-voltage adjustment for DC/DC converters | Feedback leakage error |
| TPS54560 datasheet (SLVSBN0) | Detailed design procedure example | Input/output capacitor RMS current, minimum on-time limit on fsw, UVLO hysteresis resistor, MLCC derating example |
| TI SLVA079 | Understanding the Terms and Definitions of LDO Voltage Regulators | Dropout, dissipation, accuracy budget |
| TI SLYT202 | LDO PSRR measurement simplified | PSRR vs headroom and frequency |
| TI SLYT187 | ESR, stability, and the LDO regulator | ESR stability window of older LDOs |
| TI SLVA115 | Measuring the bode plot / transient response | Ringing on a load step as a phase-margin indicator |
| TI SNVA021 (AN-1149) | Layout Guidelines for Switching Power Supplies | Hot loops, placement, grounding |
| TI SLYT614 | Five steps to a great PCB layout for a step-down converter | Placement order, AGND/PGND |
| TI SLVA773 | Layout guidelines | Grounding, via counts (note the conflicting per-via current rules) |
| TI SNVA489 | Input filter design for switching regulators | Filter resonance placement and damping |
| TI SLTA055 | Input and output capacitor selection | Input ripple target, role of bulk capacitors |
| TI SLUAAL8 | Hot-plug / input overvoltage transients | Damping instead of more capacitance; RC snubber |
| TI SLVA670 | Managing inrush current | I = C dV/dt and its effect on a shared rail |
| TI SLVAE57 | Basics of power switches / reverse current blocking | P-FET reverse protection does not block reverse current |
| TI SPRA953 | Semiconductor and IC Package Thermal Metrics | Why theta-JA is not your board's number; psi-JT / psi-JB |
| TI SLUP124 | Magnetics design (Dixon) | Ferrite vs powder-core saturation and loss |
| ROHM 62AN089E | MLCC DC-bias characteristics | Higher voltage rating in the same case can lose more capacitance |
| Coilcraft Doc361, Vishay IHLP datasheets | Inductor current ratings | Definitions of I_sat (10-50 % drop) and I_rms (temperature rise) |
| ADI/Linear AN88 | Ceramic input capacitors can cause overvoltage transients | Hot-plug ringing (summary only; the PDF could not be retrieved) |

Practice, not from a single source above (marked as such where used): P-FET gate zener clamp, TVS clamp-to-standoff
ratio of roughly 1.5x, boost converters lacking inherent short-circuit protection, keeping loop crossover well below the
RHP-zero frequency (one fifth is a common rule).
