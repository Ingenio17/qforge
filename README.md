# qforge: Quantum Simulation Toolkit

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/qforge.svg)](https://badge.fury.io/py/qforge)

**A terminal-native quantum simulation toolkit — from qubit physics to gate-level hardware design.**
 
qforge lets you model superconducting qubits, simulate quantum gate dynamics, and analyze multi-qubit couplings — all from your terminal or Python scripts, no GUI required.
 
Whether you're designing a transmon-based processor, sweeping Josephson junction parameters, or benchmarking CNOT fidelity across coupling topologies, qforge gives you the physics simulation layer you need — fast

---

## ✨ What You Can Do
 
- **Model superconducting qubits** — Transmon, Fluxonium, Flux, and ZeroPi circuits with physical parameters (EJ, EC, flux, etc.)
- **Compute energy spectra** — Visualize energy levels, wavefunctions, and matrix elements directly in the terminal
- **Simulate gate dynamics** — Single- and two-qubit gates (X, Y, Z, H, CNOT, CZ) with realistic noise models including T1 coherence
- **Sweep parameters** — Explore how EJ/EC ratios affect frequency, anharmonicity, and coherence time
- **Benchmark gate fidelity** — Calculate average gate fidelity and run state/process tomography
- **Compare coupling topologies** — Capacitive, inductive/ZZ, and tunable coupler models side-by-side
- **Export to your stack** — Push Hamiltonians to QuTiP or noise parameters to Qiskit for downstream circuit simulation

---
 
## 🚀 Quickstart
 
### Install
 
```bash
pip install qforge
```
 
Or install from source:
 
```bash
git clone https://github.com/Ingenio17/qforge.git
cd qforge
pip install -e .
```
 
### Try the interactive wizard
 
The easiest way to get started — no scripting needed:
 
```bash
qforge --interactive
```
 
This walks you through creating a qubit, analyzing its spectrum, and simulating a gate interactively.
 
### Or use the CLI directly
 
```bash
# 1. Create a transmon qubit
qforge qubit create transmon --name my_qubit --EJ 15 --EC 0.3
 
# 2. Plot its energy spectrum
qforge qubit analyze --name my_qubit --plot
 
# 3. Simulate an X (pi-pulse) gate
qforge gate simulate --qubit my_qubit --gate X --duration 40
```
 
---

## 📖 Documentation
 
Full documentation including API reference and worked examples:
👉 **[qforge.readthedocs.io](https://qforge.readthedocs.io/en/latest/)**
 
---
 
## 🐍 Python API
 
For scripting and research workflows, qforge exposes clean Python engines:
 
```python
from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.utils.terminal_plot import TerminalPlotter
 
# Create and characterize a transmon
qubit_engine = QubitEngine()
qubit = qubit_engine.create_qubit(
    qubit_type="transmon",
    name="q1",
    params={"EJ": 15.0, "EC": 0.3}
)
 
# Compute and visualize energy spectrum
spectrum = qubit_engine.compute_spectrum(qubit, n_levels=5, subtract_ground=True)
TerminalPlotter.plot_spectrum(spectrum, title="Energy Spectrum")
 
# Simulate an X gate with realistic noise
gate_engine = GateEngine()
result = gate_engine.simulate_dynamics(
    qubit_name="q1",
    gate_type="X",
    duration=40.0,      # nanoseconds
    noise_model="realistic",
    steps=100
)
 
# Visualize Rabi oscillation in the terminal
TerminalPlotter.plot_time_evolution(
    times=result["times"],
    expectations=result["expectations"],
    labels=result["labels"],
    title="Rabi Oscillation (X Gate)"
)
```
 
---
 
## 🔗 Multi-Qubit Couplings
 
qforge models three physical coupling regimes used in real superconducting hardware:
 
| Coupling Type | Hamiltonian | Best For |
|---|---|---|
| **Capacitive** | $g(a^\dagger b + ab^\dagger)$ | Fixed-frequency transmons, Cross-Resonance / CNOT gates |
| **Inductive / ZZ** | $g\hat{n}_1\hat{n}_2$ | Dispersive interactions, native CZ / CPHASE evolution |
| **Tunable Coupler** | $g_\text{max} f(t)(a^\dagger b + ab^\dagger)$ | iSWAP, adiabatic CZ, flux-pulsed gates |
 
You can compare coupling schemes directly:
 
```python
results = gate_engine.compare_couplings(q1="q1", q2="q2", gate="CNOT")
```
 
---
 
## 📦 Core API at a Glance
 
### `QubitEngine`
| Method | Description |
|---|---|
| `create_qubit(type, name, params)` | Instantiate a qubit with physical parameters |
| `compute_spectrum(qubit, n_levels)` | Get energy eigenvalues |
| `estimate_coherence(qubit, temperature)` | Estimate T1/T2 coherence times |
| `parameter_sweep(type, param, range, ...)` | Sweep EJ/EC/flux and observe property changes |
| `visualize_enhanced(qubit, plot_types)` | Generate spectrum, wavefunction, potential plots |
| `save_qubit / load_qubit` | Persist qubit configs to/from JSON |
| `export_to_qiskit / export_to_qutip` | Hand off to downstream frameworks |
 
### `GateEngine`
| Method | Description |
|---|---|
| `simulate_dynamics(qubit, gate, duration)` | Single-qubit gate simulation with optional noise |
| `simulate_two_qubit_dynamics(...)` | Two-qubit dynamics under a chosen coupling |
| `calculate_gate_fidelity(...)` | Average gate fidelity via full propagator |
| `calibrate_gate(...)` | Sweep gate parameters to maximize fidelity |
| `compare_couplings(q1, q2, gate)` | Benchmark capacitive vs. ZZ vs. tunable coupling |
| `perform_state_tomography(state, target)` | Fidelity and trace distance analysis |
 
---
 
## 🧑‍💻 Who Is This For?
 
qforge is built for:
 
- **Quantum hardware researchers** designing and characterizing superconducting qubit circuits
- **Graduate students** exploring qubit physics and gate-level simulation
- **Quantum software engineers** who need a fast physics layer before running full circuit simulations in Qiskit or Cirq
- **Anyone who wants a scriptable, terminal-first alternative to heavy GUI simulation environments**
---

## 🏗️ Architecture

qforge is built on industry-standard quantum libraries:

- **[scqubits](https://scqubits.readthedocs.io/)**: Superconducting qubit physics
- **[QuTiP](https://qutip.org/)**: Quantum dynamics and gate simulation
- **[Qiskit Metal](https://qiskit.org/metal/)**: Quantum hardware chip design

## 🤝 Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md).

## Acknowledgments

qforge relies on the following open-source projects:

*   **[scqubits](https://scqubits.readthedocs.io/)**: Setup and simulation of superconducting qubits.
    *   Copyright (c) 2019 and later, Jens Koch and Peter Groszkowski. Licensed under BSD 3-Clause.
*   **[QuTiP](https://qutip.org/)**: Quantum Toolbox in Python for dynamics.
    *   Copyright (c) 2011-2022 QuTiP developers. Licensed under BSD 3-Clause.
*   **[Qiskit Metal](https://qiskit.org/metal/)**: Hardware design.
    *   Copyright Qiskit Metal Development Team. Licensed under Apache 2.0.

Please see `NOTICE` and `ThirdPartyNotices.md` for full license details.

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
