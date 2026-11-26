# QubitWeave demo

Twelve demonstrations, one folder each: plots as PNG, tables as CSV, Markdown and PNG, and
`checks.csv` listing every comparison with an independent calculation. `SUMMARY.md` has
the pass counts and run times of the last full run.

Run from the repository root, in the environment QubitWeave is installed in (`qforge_env`):

```bash
python examples/demo/run_all.py            # all of them
python examples/demo/run_all.py 2 3 10     # a quick subset
python examples/demo/demo_03_kerr_cats.py  # one
```

Demos run in a scratch directory and never touch the qubits in your own session.

| # | Demo | What it shows | Checked against |
|---|---|---|---|
| 1 | [Sign-flipping qubit](01_sign_flipping_qubit/anharmonicity_sign_flip.png) | A custom three-junction netlist whose anharmonicity goes from −465 to +705 MHz with flux, plus a design map | scqubits' separate `FluxQubit` class, level by level |
| 2 | [Vacuum Rabi splitting](02_vacuum_rabi/vacuum_rabi_splitting.png) | Circuit QED from a two-mode netlist: 295 MHz anticrossing and the dispersive readout shift, no coupling strength given | Transmon-oscillator model built from the capacitance matrix, nothing fitted |
| 3 | [Kerr cats](03_kerr_cats/wigner_cats.png) | A custom Kerr resonator turning a coherent state into 4-, 3- and 2-legged Schrödinger cats, with photon loss | Perturbation theory for K, ideal Kerr cats |
| 4 | [Parametric CZ](04_parametric_chevron/chevron_and_cz.png) | Chevron, CZ and continuous controlled phases for six pairings of preset and custom qubits | Analytic Rabi formula, independent QuTiP integration |
| 5 | [Optimal control](05_optimal_control/grape_vs_drag.png) | GRAPE pulses against DRAG and Gaussian on a five-level transmon | Lab-frame replay without RWA, QuTiP `sesolve` |
| 6 | [Randomized benchmarking](06_randomized_benchmarking/randomized_benchmarking.png) | RB of simulated pulses with T1/T2, including leakage-aware RB where the standard protocol fails | Exact average error of the same channels |
| 7 | [Light cone](07_light_cone/light_cone_and_localization.png) | A 7-transmon chain (2,187 states) as an analog simulator: ballistic spreading, then localization by disorder | Tight-binding theory, Bessel-function light cone |
| 8 | [Heterogeneous GHZ](08_ghz_heterogeneous/ghz_state.png) | GHZ state across a netlist fluxonium, a transmon and a preset fluxonium, with parity fringes, a Mermin test and T1/T2 | Frequency-tripled fringes, quantum bound M = 4 |
| 9 | [H₂ by VQE](09_vqe_h2/h2_dissociation.png) | Gaussian integrals to microwave pulses: the dissociation curve of hydrogen, with shot noise and decoherence | Literature energies and full configuration interaction |
| 10 | [Surface code](10_surface_code/surface_code.png) | Distance-3 surface code correcting all 27 single-qubit errors, compared with Steane, Shor and repetition | Exact enumeration of 262,144 Pauli patterns vs state-vector Monte Carlo |
| 11 | [Bell state, every method](11_bell_state/bell_state_all_methods.png) | Transmon Q1 + fluxonium Q2: pulse-level evolution to a Bell state, then the same circuit in all four error-correcting codes, clean and with every correctable single-qubit error | Bell fidelity from all three correlations, stabilizers, exhaustive error injection |
| 12 | [Toffoli](12_toffoli/toffoli_evolution.png) | A Toffoli on a transmon, a fluxonium and a netlist flux qubit: evolution from \|110⟩ and \|100⟩, and the full 8 x 8 gate | Ideal Toffoli with phases, superposed control |

## What is and is not modelled

- Demos 1, 2, 4, 5, 7 and 12 are closed-system: no T1 or T2. Their errors are coherent errors.
- Demo 3 includes photon loss, 6 includes T1/T2 throughout, 8 and 9 show both with and without.
- Tunable couplers are an effective time-dependent coupling `g(t) n1 n2`, not a third circuit.
- Demo 11 has no T1/T2 in its pulse run, and its encoded gates are ideal logical operations. Shor's logical H is exact but not fault tolerant.
- Demo 10 is the code-capacity setting: errors on data qubits, perfect gates and measurement.
  Real break-even rates are much lower.
- T1 and T2 values are QubitWeave's defaults, not measurements of a device.
