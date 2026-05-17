"""
Complete Transmon Workflow Example

This example demonstrates the full workflow for a transmon qubit:
1. Create qubit with physical parameters
2. Analyze energy spectrum
3. Estimate coherence times
4. Export for use in other tools
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
    print("qforge Example: Transmon Workflow")
    print("=" * 60)
    
    # Initialize engine
    engine = QubitEngine()
    
    # Step 1: Create a transmon qubit
    print("\n1. Creating transmon qubit...")
    params = {
        "EJ": 15.0,  # Josephson energy (GHz)
        "EC": 0.3,   # Charging energy (GHz)
        "ng": 0.0,   # Offset charge
        "ncut": 30,  # Charge basis cutoff
    }
    
    transmon = engine.create_qubit(
        qubit_type="transmon",
        name="my_transmon",
        params=params
    )
    print("✓ Transmon created successfully!")
    print(f"   EJ = {params['EJ']} GHz, EC = {params['EC']} GHz")
    
    # Step 2: Compute energy spectrum
    print("\n2. Computing energy spectrum...")
    spectrum = engine.compute_spectrum(transmon, n_levels=5)
    
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
    coherence = engine.estimate_coherence(transmon, temperature=0.015)
    
    for param, data in coherence.items():
        print(f"   {param}: {data['value']:.2f} μs ({data['limit']})")
    
    # Step 4: Simulate Gate Dynamics
    print("\n4. Simulating Gate Dynamics (Pi-pulse)...")
    gate_engine = GateEngine()
    result = gate_engine.simulate_dynamics(
        qubit_name="my_transmon",
        gate_type="X",
        duration=40.0,
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
    engine.save_qubit(transmon, "outputs/qubits/my_transmon.json")
    print("   ✓ Saved to outputs/qubits/my_transmon.json")
    
    # Step 6: Export for QuTiP (for external use)
    print("\n6. Exporting for QuTiP...")
    engine.export_to_qutip(transmon, "outputs/qubits/my_transmon_qutip.pkl")
    print("   ✓ Exported to outputs/qubits/my_transmon_qutip.pkl")
    
    # Step 7: Export for Qiskit (for circuit simulations)
    print("\n7. Exporting for Qiskit...")
    engine.export_to_qiskit(transmon, "outputs/qubits/my_transmon_qiskit.json")
    print("   ✓ Exported to outputs/qubits/my_transmon_qiskit.json")
    
    print("\n" + "=" * 60)
    print("Workflow completed successfully!")
    print("=" * 60)
    print("\nNext steps:")
    print("  - Use QuTiP export for gate-level simulations")
    print("  - Use Qiskit export for circuit-level simulations")
    print("  - Design hardware layout with Qiskit Metal")
    print("\nRun this workflow from CLI:")
    print("  qforge qubit create transmon --name my_transmon --EJ 15 --EC 0.3")
    print("  qforge qubit analyze my_transmon --coherence")
    print("  qforge qubit export my_transmon --format qutip -o output.pkl")


if __name__ == "__main__":
    main()
