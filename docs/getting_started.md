# QForge Getting Started Guide

Welcome to QForge! This guide will help you get started with quantum simulation from qubit physics to hardware design.

## Installation

```bash
pip install qforge
```

Or for development:

```bash
git clone <repository-url>
cd qforge
pip install -e ".[dev]"
```

## Quick Start

### 1. Interactive Mode (Recommended for Beginners)

Launch the interactive wizard:

```bash
qforge --interactive
```

This provides a menu-driven interface with step-by-step guidance.

### 2. Command Line Interface

#### Creating a Qubit

Create a transmon qubit with custom parameters:

```bash
qforge qubit create --type transmon --name my_transmon --EJ 15 --EC 0.3
```

Output:
```
╭─────────────────────────────────────────────────────────╮
│           Qubit Created: my_transmon                    │
├──────────────────┬──────────────────────────────────────┤
│ Property         │ Value                                 │
├──────────────────┼──────────────────────────────────────┤
│ Type             │ Transmon                              │
│ Name             │ my_transmon                           │
│ EJ               │ 15.000 GHz                            │
│ EC               │ 0.300 GHz                             │
╰──────────────────┴──────────────────────────────────────╯
```

Or use presets:

```bash
qforge qubit create --type fluxonium --name my_fluxonium --preset high_coherence
```

#### Analyzing a Qubit

```bash
qforge qubit analyze my_transmon --coherence --plot
```

This computes:
- Energy spectrum
- Anharmonicity
- Coherence times (T1, T2)
- Generates plots (saved to `outputs/plots/`)

#### Comparing Qubits

Compare transmon vs fluxonium:

```bash
qforge compare qubits --qubits transmon,fluxonium --metrics all
```

Output:
```
╭──────────────────────────────────────────────────────────────────╮  
│                    Qubit Comparison                               │
├──────────────────┬────────────────┬─────────────────────────────┤
│ Metric           │ Transmon       │ Fluxonium                   │
├──────────────────┼────────────────┼─────────────────────────────┤
│ Frequency (ω₀₁)  │ 4.850 GHz      │ 0.750 GHz                   │
│ Anharmonicity (α)│ -220.0 MHz     │ -1200.0 MHz ✓               │
│ T1               │ 50.0 μs        │ 1000.0 μs ✓                 │
│ T2               │ 35.0 μs        │ 700.0 μs ✓                  │
╰──────────────────┴────────────────┴─────────────────────────────╯
```

### 3. Python API

Use QForge programmatically:

```python
from qforge.core.qubit_engine import QubitEngine

# Create engine
engine = QubitEngine()

# Create a transmon
params = {"EJ": 15.0, "EC": 0.3}
transmon = engine.create_qubit("transmon", "my_transmon", params)

# Compute properties
spectrum = engine.compute_spectrum(transmon, n_levels=5)
coherence = engine.estimate_coherence(transmon)

# Export for other tools
engine.export_to_qutip(transmon, "my_transmon.pkl")
engine.export_to_qiskit(transmon, "my_transmon.json")
```

## Supported Qubits

| Qubit Type | Key Parameters | Typical Frequency | Best For |
|------------|---------------|-------------------|----------|
| **Transmon** | EJ, EC | 4-5 GHz | Fast gates, easier control |
| **Fluxonium** | EJ, EC, EL | 0.1-1 GHz | Long coherence, reduced errors |
| **Flux** | EJ1, EJ2, EJ3, EC | 1-10 GHz | Flux-based control |
| **Zero-π** | EJ, EL, ECJ, EC | Variable | Noise protection |

## Workflow Stages

QForge supports end-to-end workflows:

1. **Qubit Physics** (`qforge qubit`) - Model superconducting qubits
2. **Gate Dynamics** (`qforge gate`) - Simulate quantum gates *[Coming soon]*
3. **Circuit Simulation** (`qforge circuit`) - Multi-qubit circuits *[Coming soon]*
4. **Hardware Design** (`qforge hardware`) - Chip layout *[Coming soon]*

## Examples

Check the `examples/` directory:

- `transmon_workflow.py` - Complete transmon analysis
- `transmon_vs_fluxonium.py` - Detailed comparison

Run them:

```bash
python examples/transmon_workflow.py
python examples/transmon_vs_fluxonium.py
```

## Next Steps

- Read the [Command Reference](command_reference.md) for all CLI commands
- Explore [Plugin Development](plugin_development.md) for custom qubits
- Join our community for support

## Tips

- Use `--help` on any command for details
- Tab completion works in interactive mode
- All plots save to `outputs/plots/`
- Export qubits to use with QuTiP, Qiskit, etc.

Happy simulating! 🚀
