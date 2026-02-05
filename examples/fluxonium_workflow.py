"""
Complete Fluxonium Workflow Example

This example demonstrates the full workflow for a fluxonium qubit:
1. Create qubit with physical parameters
2. Analyze energy spectrum (showing high anharmonicity)
3. Estimate coherence times (showing long T1)
4. Simulate Gate Dynamics
5. Export for use in other tools
"""

import sys
import os
# Enable UTF-8 console for beautiful Unicode output
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from qforge.utils.console import enable_unicode_console
enable_unicode_console()

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.utils.terminal_plot import TerminalPlotter


def main():
    print("=" * 60)
    print("QForge Example: Fluxonium Workflow")
    print("=" * 60)
    
    # Initialize engine
    engine = QubitEngine()
    
    # Step 1: Create a fluxonium qubit
    print("\n1. Creating fluxonium qubit...")
    # Heavy fluxonium parameters (sweet spot)
    params = {
        "EJ": 8.9,   # Josephson energy (GHz)
        "EC": 2.5,   # Charging energy (GHz)
        "EL": 0.5,   # Inductive energy (GHz)
        "flux": 0.5, # Magnetic flux (frustation point)
        "cutoff": 110 # Charge basis cutoff
    }
    
    fluxonium = engine.create_qubit(
        qubit_type="fluxonium",
        name="my_fluxonium",
        params=params
    )
    print("✓ Fluxonium created successfully!")
    print(f"   EJ={params['EJ']}, EC={params['EC']}, EL={params['EL']}, Φ={params['flux']}")
    
    # Step 2: Compute energy spectrum
    print("\n2. Computing energy spectrum...")
    spectrum = engine.compute_spectrum(fluxonium, n_levels=5)
    
    print("   Energy Levels:")
    for i, energy in enumerate(spectrum):
        print(f"   |{i}⟩: {energy:.4f} GHz")
    
    # Calculate derived properties
    omega_01 = spectrum[1] - spectrum[0]
    omega_12 = spectrum[2] - spectrum[1]
    anharmonicity = omega_12 - omega_01
    
    print(f"\n   Qubit Frequency (ω₀₁): {omega_01:.4f} GHz")
    print(f"   Anharmonicity (α): {anharmonicity*1000:.1f} MHz")
    
    # Step 3: Estimate coherence times
    print("\n3. Estimating coherence times...")
    # Fluxonium usually has higher T1/T2 due to lower frequency and noise protection
    coherence = engine.estimate_coherence(fluxonium, temperature=0.015)
    
    for param, data in coherence.items():
        print(f"   {param}: {data['value']:.2f} μs ({data['limit']})")
    
    # Step 4: Simulate Gate Dynamics
    print("\n4. Simulating Gate Dynamics (X gate)...")
    gate_engine = GateEngine()
    
    # Simulate an X gate (Pi-pulse)
    # Note: Fluxonium gates can be slower or faster depending on drive coupling
    duration = 50.0 
    
    result = gate_engine.simulate_dynamics(
        qubit_name="my_fluxonium",
        gate_type="X",
        duration=duration,
        noise_model="realistic"
    )
    
    print("   ✓ Simulation complete. Plotting dynamics:")
    TerminalPlotter.plot_time_evolution(
        result["times"], 
        result["expectations"], 
        result["labels"]
    )

    # Step 5: Save qubit
    print("\n5. Saving qubit...")
    engine.save_qubit(fluxonium, "outputs/qubits/my_fluxonium.json")
    print("   ✓ Saved to outputs/qubits/my_fluxonium.json")
    
    # Step 6: Export
    print("\n6. Exporting...")
    engine.export_to_qutip(fluxonium, "outputs/qubits/my_fluxonium_qutip.pkl")
    print("   ✓ Exported to outputs/qubits/my_fluxonium_qutip.pkl")
    
    print("\n" + "=" * 60)
    print("Workflow completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
