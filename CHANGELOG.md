# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-01-24

### Added
- **Qubit Physics Modeling**: Full support for Transmon, Fluxonium, Flux, and Zero-π qubit architectures with pre-configured parameters
- **Comprehensive Analysis Tools**: Energy spectra calculations, coherence time analysis (T1, T2), and parameter sweep capabilities
- **Realistic Noise Modeling**: Accurate coherence time estimates incorporating multiple decoherence channels
- **Side-by-Side Comparisons**: Compare different qubit architectures across multiple metrics including coherence, frequency, and gate fidelity
- **Interactive CLI**: Beginner-friendly command-line interface with rich terminal output and interactive wizards
- **Python API**: Full programmatic access to qubit modeling functionality for advanced users
- **Export Functionality**: Export quantum systems to QuTiP and Qiskit formats for integration with external tools
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

[0.1.0]: https://github.com/Ingenio17/qforge/releases/tag/v0.1.0
