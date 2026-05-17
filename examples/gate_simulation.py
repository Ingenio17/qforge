"""
Gate Simulation Example
=======================

This example demonstrates how to use the qforge API to:
1. Create a Transmon qubit.
2. Analyze its energy spectrum.
3. Simulate a quantum gate (X-gate / Pi-pulse).
4. Visualize the dynamics directly in the terminal.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.utils.terminal_plot import TerminalPlotter
import numpy as np

def run_simulation():
    print("\n=== qforge Gate Simulation Example ===\n")

    # 1. Initialize Engines
    qubit_engine = QubitEngine()


    # 2. Create a Transmon Qubit
    print("-> Creating Transmon...")
    qubit = qubit_engine.create_qubit(
        qubit_type="transmon",
        name="example_qubit",
        params={"EJ": 15.0, "EC": 0.3}
    )

    # 3. Compute and Plot Spectrum
    print("-> Computing Spectrum...")
    spectrum = qubit_engine.compute_spectrum(qubit, n_levels=5, subtract_ground=True)
    TerminalPlotter.plot_spectrum(spectrum, title="Energy Spectrum (Relative)")

    # 4. Simulate X Gate (Pi Pulse)
    print("\n-> Simulating X Gate (Pi-pulse)...")
    gate_engine = GateEngine()
    # For a Pi pulse, duration usually depends on drive amplitude. 
    # qforge auto-calibrates amplitude based on duration for standard gates.
    duration = 40.0 # ns
    
    result = gate_engine.simulate_dynamics(
        qubit_name="example_qubit",
        gate_type="X",
        duration=duration,
        noise_model="realistic", # Uses internal T1 coherence estimates
        steps=100
    )

    # 5. Visualize Dynamics
    print("-> Plotting Dynamics...")
    TerminalPlotter.plot_time_evolution(
        times=result["times"],
        expectations=result["expectations"],
        labels=result["labels"],
        title="Rabi Oscillation (X Gate)"
    )
    
    print("\n=== Simulation Complete ===")

if __name__ == "__main__":
    run_simulation()
