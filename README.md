# QForge: Quantum Simulation Toolkit

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/qforge.svg)](https://badge.fury.io/py/qforge)

**QForge** is a comprehensive, terminal-based quantum simulation toolkit that bridges qubit physics to hardware design. Built for everyone from absolute beginners to seasoned quantum computing researchers.

## 🚀 Features

### ✅ Fully Implemented
- **Qubit Physics Modeling**: Transmon, Fluxonium, Flux, Zero-π with pre-configured parameters
- **Gate Physics Simulation**: Time-domain simulation of single-qubit gates (X, Y, Z, H) using QuTiP dynamics.
- **Terminal Plotting**: Visualize energy spectra and Rabi oscillations directly in your terminal.
- **Comprehensive Analysis**: Energy spectra, coherence times (T1, T2), parameter sweeps.
- **Realistic Noise Modeling**: Accurate coherence time estimates and relaxation dynamics.
- **Interactive CLI**: Beginner-friendly wizards with auto-completions and rich visualizations.
- **Comparison Engine**: Compare different qubit architectures side-by-side.

### 🚧 Coming Soon
- **Circuit Simulation**: Multi-qubit circuit simulation with Qiskit
- **Hardware Design**: Chip layout design with Qiskit Metal
- **Plugin Architecture**: Extensible system for custom qubits and components

## 📦 Installation

```bash
pip install qforge
```

### Development Installation

```bash
git clone https://github.com/Ingenio17/qforge.git
cd qforge
pip install -e ".[dev]"
```

## 🎯 Quick Start

### Interactive Mode (Recommended)

```bash
qforge --interactive
```

### 1. Create a Qubit

```bash
qforge qubit create transmon --name my_qubit --EJ 15 --EC 0.3
```

### 2. Analyze Spectrum
View energy levels directly in your terminal:
```bash
qforge qubit analyze --name my_qubit --plot
```

### 3. Simulate a Gate
Simulate a $\pi$-pulse (X gate) and view Rabi oscillations:
```bash
qforge gate simulate --qubit my_qubit --gate X --duration 40 --save
```

## 📚 Documentation

Full documentation is available at [qforge.readthedocs.io](https://qforge.readthedocs.io/).

- [Getting Started](docs/getting_started.rst)
- [Examples](examples/)

## 🎓 Examples

Check out the `examples/` directory for complete workflows:

- `gate_simulation.py`: End-to-end gate dynamics simulation.
- `transmon_workflow.py`: Complete transmon simulation and analysis.
- `fluxonium_workflow.py`: Complete fluxonium simulation and analysis.
- `comprehensive_comparison.py`: Advanced multi-qubit comparison with reports.

## 🏗️ Architecture

QForge is built on industry-standard quantum libraries:

- **[scqubits](https://scqubits.readthedocs.io/)**: Superconducting qubit physics
- **[QuTiP](https://qutip.org/)**: Quantum dynamics and gate simulation
- **[Qiskit](https://qiskit.org/)**: Circuit-level quantum computing
- **[Qiskit Metal](https://qiskit.org/metal/)**: Quantum hardware chip design

## 🤝 Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md).

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
