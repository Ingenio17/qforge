# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
-   **Optimal control** (`core/pulse_optimizer.py`): GRAPE, calibrated DRAG and Gaussian pulses on a multilevel qubit, with a lab-frame replay that makes no rotating-wave approximation.
-   **Randomized benchmarking** (`core/benchmarking.py`): pulse-level RB with T1/T2, and a leakage-aware analysis.
-   **Distance-3 surface code** (`SURFACE_9`, `execute_surface9_workflow`), error injection, state-vector memory rounds, and exact logical error rates for any code (`core/qec_benchmark.py`).
-   **`inject_errors`** on every error-correction workflow, and `data_axes` and `syndromes` in every result.
-   **Decoherence in N-qubit simulations and workflows**: `noise={qubit: {"T1": us, "T2": us}}`.
-   **Per-qubit drive amplitudes** in `PhysicalWorkflowEngine`, and `GateEngine.calibrate_half_pi`, which also measures and cancels the Stark phase of the pulse.
-   **Demo suite** in `examples/demo`, results in `demo_plots`.

### Performance
-   **Error correction**: gates act on the state array in place (`core/register_ops.py`) instead of being embedded as full-register operators, decoding no longer builds a density matrix, and pulse durations the encoded workflows never use are calibrated only on demand. A two-qubit Shor-encoded Bell circuit takes 0.5 s instead of 30 s; three logical Steane qubits are now practical.
-   **Size warnings** state what is really held in memory (ancillas are reclaimed) and appear only from 1 GB.
-   **Pulse simulation** (`core/pulse_solver.py`): evolution is split at pulse edges, pulses are evaluated in compiled code, idle stretches are exact. Typically 4 to 8 times faster, with the same results.
-   **Calibration** searches a rotation peak by climbing it, skips hopeless refinement points, and stores parametric CZ schedules on disk.
-   **Startup**: engines load on first use, so `QubitWeave --help` takes 0.6 s instead of 3 s. The session file is re-read only when it changes and written once per batch.

### Changed
-   Lab-frame evolution uses a 7th-order Runge-Kutta solver with tighter tolerances. Single-qubit durations calibrated with the old solver are recalibrated on first use.
-   The workflow calibrates only the gates a circuit uses.

### Fixed
-   **Phase errors were never detected in the Steane and Shor codes**: syndrome circuits were regrouped by gate type, so the Hadamards around an X-type check cancelled.
-   **Logical Hadamard**: on the Shor code H on every qubit is not a logical H, so an encoded Bell circuit produced |00> - |11> behind correct-looking populations. Shor now un-encodes, rotates and re-encodes; the surface code supports H (with a lattice relabelling) and CZ; Shor supports CZ.
-   **`ry(theta)` performed `ry(-theta)`**, and gate bodies with nested parentheses (`cu3`) dropped instructions.
-   **Solver error** of up to a few parts in a thousand of population per few hundred ns.
-   Parameter sweeps left a `_sweep_temp` qubit in the session, and `examples/10_bell_state_simulation.py` crashed on an unsupported plot label.
-   Debug output removed from the error-correction engine.
-   **Tunable-coupler CZ/CNOT on fluxonium and other strongly anharmonic pairs**: these were compiled with the transmon flux-tuning recipe, which is unphysical there and produced no entanglement. They now use a parametrically modulated coupler, calibrated on the full multilevel system.
-   **Virtual Z gates in the workflow engine**: `rz` (and `z`, `s`, `t`, ...) was dropped instead of shifting later pulse phases, and `h` omitted its virtual Z, so `h h` acted as a flip.
-   **Failed two-qubit calibrations** are now reported by the workflow instead of being simulated silently.

## [0.2.0] - 2026-02-13

### 🚀 New Features
-   **Expanded Qubit Library**: Added full support for **Fluxonium**, **Flux**, and **Zero-π** qubits alongside Transmons.
-   **Interactive Mode**: New `QubitWeave --interactive` command launches a guided wizard for creating qubits, simulating gates, and running workflows.
-   **Gate Dynamics**: Time-domain gate simulation (Rabi oscillations, pulses) backed by QuTiP.
-   **Comparison Engine**: Compare parameters and coherence times of multiple qubits side-by-side.
-   **Dynamic Configuration**: CLI options now load dynamically from `defaults.py`, enabling easier extension.

### 🛠️ Developer Tools & Automation
-   **Docs Sync**: New `QubitWeave dev sync` command automatically updates documentation tables from source code metadata.
-   **Agent Instructions**: Added `docs/AGENT_INSTRUCTIONS.md` to guide AI agents in adding new features.
-   **Citations**: New `QubitWeave citations` command outputs BibTeX entries for dependency libraries.

### ⚖️ Compliance
-   **Licensing**: Added `NOTICE` (Apache 2.0) and `ThirdPartyNotices.md` (BSD-3) for legal compliance.
-   **Acknowledgments**: Updated `README.md` with explicit credit to scqubits and QuTiP.
-   **Runtime Attribution**: Interactive mode now displays attribution at startup.

## [0.1.1] - 2026-01-24

### Added
- **Qubit Physics Modeling**: Full support for Transmon, Fluxonium, Flux, and Zero-π qubit architectures with pre-configured parameters
- **Comprehensive Analysis Tools**: Energy spectra calculations, coherence time analysis (T1, T2), and parameter sweep capabilities
- **Realistic Noise Modeling**: Accurate coherence time estimates incorporating multiple decoherence channels
- **Side-by-Side Comparisons**: Compare different qubit architectures across multiple metrics including coherence, frequency, and gate fidelity
- **Interactive CLI**: Beginner-friendly command-line interface with rich terminal output and interactive wizards
- **Python API**: Full programmatic access to qubit modeling functionality for advanced users
- **Export Functionality**: Export quantum systems to and QuTiP formats for integration with external tools
- **Examples**: Complete workflow examples for transmon simulation and qubit comparison
- **Documentation**: Getting started guide and comprehensive README

### Infrastructure
- Python package configuration with `pyproject.toml` supporting Python 3.9+
- Development dependencies for testing (pytest, pytest-cov), linting (ruff, black), and type checking (mypy)
- GitHub Actions workflow for automated PyPI publishing on releases
- Comprehensive test suite covering qubit engines, comparison tools, and scientific accuracy
- Optional hardware design support via `qiskit-metal` (installable separately)

### Dependencies
- Built on industry-standard quantum libraries: scqubits, QuTiP, Qiskit
- Rich terminal UI components using click, rich, and prompt-toolkit
- Scientific computing stack: numpy, scipy, matplotlib, pandas

[0.1.1]: https://github.com/Ingenio17/QubitWeave/releases/tag/v0.1.1
