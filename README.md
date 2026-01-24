# QForge: Quantum Simulation Toolkit

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)

**QForge** is a comprehensive, terminal-based quantum simulation toolkit that bridges qubit physics to hardware design. Built for everyone from absolute beginners to seasoned quantum computing researchers.

## 🚀 Features

- **End-to-End Workflow**: Qubit modeling → Gate physics → Circuit simulation → Hardware design
- **Popular Qubits**: Transmon, Fluxonium, Flux, Zero-π with pre-configured parameters
- **Realistic Noise**: Accurate modeling of T1, T2, thermal noise, flux noise, and more
- **Easy Comparisons**: Side-by-side comparison of different qubit architectures
- **Interactive CLI**: Beginner-friendly wizards with rich terminal output
- **Minimal Typing**: Concise, intuitive commands
- **Extensible**: Plugin architecture for custom qubits and components

## 📦 Installation

```bash
pip install qforge
```

### Development Installation

```bash
git clone https://github.com/qforge/qforge.git
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

### Simulate a Gate

```bash
qforge gate simulate --qubit my_transmon --gate X --duration 20ns --noise realistic
```

### Build and Simulate a Circuit

```bash
qforge circuit build --qubits my_transmon --gates H,X,CNOT --shots 1000
```

### Design Hardware Layout

```bash
qforge hardware design --qubit my_transmon --layout grid --export my_chip.gds
```

### Compare Qubit Architectures

```bash
qforge compare --qubits transmon,fluxonium --metrics coherence,fidelity,frequency
```

### Run End-to-End Workflow

```bash
qforge workflow run --qubit-type transmon --interactive
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
- [Command Reference](docs/command_reference.md)
- [Plugin Development](docs/plugin_development.md)
- [Examples](examples/)

## 🎓 Examples

Check out the `examples/` directory for complete workflows:

- `transmon_workflow.py` - Complete transmon simulation
- `fluxonium_workflow.py` - Complete fluxonium simulation
- `transmon_vs_fluxonium.py` - Detailed comparison

## 🔌 Extensibility

QForge supports custom plugins for:
- Custom qubit types
- Custom gates and pulses
- Custom noise models
- Custom hardware components

See [Plugin Development Guide](docs/plugin_development.md) for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

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
