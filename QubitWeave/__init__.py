"""
QubitWeave: Quantum Simulation Toolkit

End-to-end quantum simulation from qubit physics to hardware design.
"""

__version__ = "0.2.0"
__author__ = "Saumya Shah"

# Engines are imported on first access (PEP 562): QuTiP and scqubits take seconds to
# load, and `import QubitWeave` or the command line may not need them.
_LAZY = {
    "QubitEngine": "QubitWeave.core.qubit_engine",
    "GateEngine": "QubitWeave.core.gate_engine",
    "CircuitEngine": "QubitWeave.core.circuit_engine",
    "HardwareEngine": "QubitWeave.core.hardware_engine",
    "Comparator": "QubitWeave.comparison.comparator",
}
_SUBPACKAGES = ("cli", "comparison", "config", "core", "plugins", "utils")


def __getattr__(name):
    import importlib

    if name in _LAZY:
        value = getattr(importlib.import_module(_LAZY[name]), name)
        globals()[name] = value
        return value
    if name in _SUBPACKAGES:
        return importlib.import_module(f"QubitWeave.{name}")
    raise AttributeError(f"module 'QubitWeave' has no attribute {name!r}")


def __dir__():
    return sorted({*globals(), *_LAZY, *_SUBPACKAGES})


__all__ = [
    "QubitEngine",
    "GateEngine",
    "CircuitEngine",
    "HardwareEngine",
    "Comparator",
]
