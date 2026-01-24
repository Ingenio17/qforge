# QForge: Quantum Simulation Toolkit

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/qforge.svg)](https://badge.fury.io/py/qforge)
[![Build Status](https://github.com/Ingenio17/qforge/workflows/Upload%20Python%20Package/badge.svg)](https://github.com/Ingenio17/qforge/actions)

**QForge** is a comprehensive, terminal-based quantum simulation toolkit that bridges qubit physics to hardware design. Built for everyone from absolute beginners to seasoned quantum computing researchers.

## 🚀 Features

### ✅ Fully Implemented
- **Qubit Physics Modeling**: Transmon, Fluxonium, Flux, Zero-π with pre-configured parameters
- **Comprehensive Analysis**: Energy spectra, coherence times (T1, T2), parameter sweeps
- **Realistic Noise Modeling**: Accurate coherence time estimates with multiple decoherence channels
- **Side-by-Side Comparisons**: Compare different qubit architectures across multiple metrics
- **Interactive CLI**: Beginner-friendly wizards with rich terminal output
- **Python API**: Full programmatic access to qubit modeling functionality
- **Minimal Typing**: Concise, intuitive commands for qubit operations
- **Export Functionality**: Export to QuTiP, Qiskit formats

### 🚧 Coming Soon
- **Gate Physics**: Quantum gate dynamics simulation with QuTiP
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

### Interactive Mode (Recommended for Beginners)

```bash
qforge --interactive
```

### Create a Transmon Qubit

```bash
qforge qubit create transmon --name my_transmon --EJ 15 --EC 0.3
```



### Compare Qubit Architectures

```bash
qforge compare qubits --qubits transmon,fluxonium --metrics coherence,frequency
```

### Analyze Qubit Properties

```bash
qforge qubit analyze my_transmon --coherence --plot
```

## 📊 Example Output

```
╭─────────────────────────────────────────────────────────────╮
│           Transmon vs Fluxonium Comparison                  │
├─────────────────┬───────────────┬──────────────────────────┤
│ Metric          │ Transmon      │ Fluxonium                │
├─────────────────┼───────────────┼──────────────────────────┤
│ T1 (μs)         │ 50.2          │ 1200.5 ✓                 │
│ T2 (μs)         │ 35.8          │ 890.3 ✓                  │
│ Frequency (GHz) │ 4.85          │ 0.75                     │
│ Anharmonicity   │ -220 MHz      │ -1.2 GHz ✓               │
│ Gate Fidelity   │ 0.9989        │ 0.9995 ✓                 │
╰─────────────────┴───────────────┴──────────────────────────╯
```

## 🏗️ Architecture

QForge is built on industry-standard quantum libraries:

- **[scqubits](https://scqubits.readthedocs.io/)**: Superconducting qubit physics
- **[QuTiP](https://qutip.org/)**: Quantum dynamics and gate simulation
- **[Qiskit](https://qiskit.org/)**: Circuit-level quantum computing
- **[Qiskit Metal](https://qiskit.org/metal/)**: Quantum hardware chip design

## 📚 Documentation

- [Getting Started Guide](docs/getting_started.md)
- [Examples](examples/)

## 🎓 Examples

Check out the `examples/` directory for complete workflows:

- `transmon_workflow.py` - Complete transmon simulation and analysis
- `transmon_vs_fluxonium.py` - Detailed qubit comparison

## 🔌 Future Development

Planned features include:
- **Gate Simulation**: Custom gates and pulses with QuTiP
- **Circuit Building**: Multi-qubit circuits with Qiskit integration
- **Noise Models**: Advanced noise modeling for realistic simulations
- **Hardware Design**: Chip layout with Qiskit Metal
- **Plugin System**: Extensible architecture for custom components

Contributions welcome! See the [Contributing](#-contributing) section.

## 🤝 Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md) for guidelines on how to contribute to QForge.

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

Built on the excellent work of:
- The scqubits team
- The QuTiP community
- The Qiskit team at IBM
- The broader quantum computing community

## 📧 Contact

For questions and support, please open an issue on GitHub.
