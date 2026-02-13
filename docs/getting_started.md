# QForge Getting Started Guide

Welcome to QForge! This guide will help you get started with quantum simulation from qubit physics to hardware design.

## Installation

```bash
pip install qforge
```

Or for development:

```bash
git clone https://github.com/Ingenio17/qforge.git
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
│ Property         │ Value                                │
├──────────────────┼──────────────────────────────────────┤
│ Type             │ Transmon                             │
│ Name             │ my_transmon                          │
│ EJ               │ 15.000 GHz                           │
│ EC               │ 0.300 GHz                            │
╰──────────────────┴──────────────────────────────────────╯
```

#### Analyzing and Plotting

Analyze the qubit's energy spectrum directly in the terminal:

```bash
qforge qubit analyze --name my_transmon --plot
```

This computes the spectrum and displays an ASCII plot of the energy levels (and saves high-res images).

#### Simulating Gates

Simulate quantum dynamics (e.g., a Pi-pulse X gate) to observe Rabi oscillations:

```bash
qforge gate simulate --qubit my_transmon --gate X --duration 40 --save
```

This will run a time-domain simulation using QuTiP and plot the population transfer in real-time in your terminal.

#### Comparing Qubits

Compare transmon vs fluxonium:

```bash
qforge compare qubits --qubits transmon,fluxonium --metrics all
```

### 3. Python API

Use QForge programmatically. See `examples/gate_simulation.py` for a complete script.

```python
from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.utils.terminal_plot import TerminalPlotter

# 1. Create Engine
qubit_engine = QubitEngine()

# 2. Create Qubit
params = {"EJ": 15.0, "EC": 0.3}
qubit = qubit_engine.create_qubit(
    qubit_type="transmon", 
    name="my_transmon", 
    params=params
)

# 3. Simulate Gate
gate_engine = GateEngine()
result = gate_engine.simulate_dynamics(
    qubit_name="my_transmon",
    gate_type="X",
    duration=40.0,
    noise_model="realistic"
)

# 4. Plot
TerminalPlotter.plot_time_evolution(
    result["times"], 
    result["expectations"], 
    result["labels"]
)
```

## Supported Qubits

<!-- DYNAMIC_TABLE: QUBITS -->
| Qubit Type | Key Parameters | Typical Frequency | Best For |
|------------|---------------|-------------------|----------|
| **Transmon** | EJ, EC | 4-5 GHz | Fast gates, easier control |
| **Fluxonium** | EJ, EC, EL | 0.1-1 GHz | Long coherence, reduced errors |
| **Flux** | EJ1, EJ2, EJ3, ECJ1, ECJ2, ECJ3, ECg1, ECg2 | 1-10 GHz | Flux-based control |
| **Zeropi** | EJ, EL, ECJ, EC | Variable | Noise protection |
<!-- END_DYNAMIC_TABLE -->

## Workflow Stages

QForge supports end-to-end workflows:

1. **Qubit Physics** (`qforge qubit`) - Model superconducting qubits (**Implemented**)
2. **Gate Dynamics** (`qforge gate`) - Simulate quantum gates (**Implemented**)
3. **Circuit Simulation** (`qforge circuit`) - Multi-qubit circuits *[Coming soon]*
4. **Hardware Design** (`qforge hardware`) - Chip layout *[Coming soon]*

## Examples

Check the `examples/` directory:

- `gate_simulation.py` - End-to-end gate dynamics and plotting
- `transmon_workflow.py` - Complete transmon analysis
- `comprehensive_comparison.py` - Advanced multi-qubit comparison with reports

## Next Steps

- Read the full documentation at `docs/`
- Explore [Plugin Development](plugin_development.md) for custom qubits
- Join our community for support

## Tips

- Use `--help` on any command for details
- Tab completion works in interactive mode
- All plots save to `outputs/plots/`
- Export qubits to use with QuTiP, Qiskit, etc.

Happy simulating! 🚀
