"""
Default configurations and presets for QForge.
"""

# Qubit parameter presets
QUBIT_PRESETS = {
    "transmon": {
        "typical": {
            "EJ": 15.0,  # GHz
            "EC": 0.3,   # GHz
            "ng": 0.0,   # Offset charge
            "ncut": 30,  # Charge basis cutoff
        },
        "high_coherence": {
            "EJ": 20.0,
            "EC": 0.25,
            "ng": 0.0,
            "ncut": 30,
        },
        "fast_gates": {
            "EJ": 12.0,
            "EC": 0.4,
            "ng": 0.0,
            "ncut": 30,
        },
    },
    "fluxonium": {
        "typical": {
            "EJ": 8.9,   # GHz
            "EC": 2.5,   # GHz
            "EL": 0.5,   # GHz
            "flux": 0.5, # Φ₀
            "cutoff": 110,
        },
        "high_coherence": {
            "EJ": 10.0,
            "EC": 2.0,
            "EL": 0.4,
            "flux": 0.5,
            "cutoff": 110,
        },
        "fast_gates": {
            "EJ": 7.0,
            "EC": 3.0,
            "EL": 0.6,
            "flux": 0.5,
            "cutoff": 110,
        },
    },
    "flux": {
        "typical": {
            "EJ1": 10.0,
            "EJ2": 10.0,
            "EJ3": 10.0,
            "ECJ1": 1.0,
            "ECJ2": 1.0,
            "ECJ3": 1.0,
            "ECg1": 50.0,
            "ECg2": 50.0,
            "flux": 0.5,
        },
    },
    "zeropi": {
        "typical": {
            "EJ": 10.0,
            "EL": 0.1,
            "ECJ": 20.0,
            "EC": 0.04,
            "ng": 0.0,
            "flux": 0.0,
            "grid": (-6.0, 6.0, 100),
        },
    },
}

# Noise parameters (typical values)
NOISE_DEFAULTS = {
    "transmon": {
        "T1_dielectric": 50.0,  # μs
        "T1_capacitive": 100.0,
        "T2_echo": 70.0,
        "t_meas": 0.3,  # μs
        "temperature": 0.015,  # K
    },
    "fluxonium": {
        "T1_dielectric": 1000.0,
        "T1_inductive": 500.0,
        "T2_echo": 800.0,
        "t_meas": 0.5,
        "temperature": 0.015,
    },
}

# Gate parameters
GATE_DEFAULTS = {
    "X": {"duration": 20, "shape": "gaussian"},  # ns
    "Y": {"duration": 20, "shape": "gaussian"},
    "Z": {"duration": 0, "shape": "instant"},  # Virtual Z
    "H": {"duration": 40, "shape": "gaussian"},
    "CNOT": {"duration": 200, "shape": "optimized"},
}

# Circuit simulation defaults
CIRCUIT_DEFAULTS = {
    "backend": "qasm_simulator",
    "shots": 1024,
    "optimization_level": 2,
}

# Hardware design defaults
HARDWARE_DEFAULTS = {
    "chip_size": {"x": 10, "y": 10},  # mm
    "substrate": "silicon",
    "qubit_spacing": 2.0,  # mm
}

# Output directories
OUTPUT_DIRS = {
    "qubits": "outputs/qubits",
    "gates": "outputs/gates",
    "circuits": "outputs/circuits",
    "hardware": "outputs/hardware",
    "comparisons": "outputs/comparisons",
    "plots": "outputs/plots",
}
