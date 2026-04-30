"""
12_CNOT_max_distance.py

Description:
Sweeps the EJ of a target transmon relative to a reference control transmon (EJ=15.0),
evaluating the drop-off in CNOT gate fidelity (measured as the P(|11>) yield) as the 
difference in EJ (Delta EJ) increases or decreases. Finally, plots Fidelity vs. Delta EJ.
"""
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

def main():
    print("============================================================")
    print(" Example 12: CNOT Gate Fidelity vs. Target EJ Detuning")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    ref_ej = 15.0
    print(f"\n[INIT]: Creating Reference Control Qubit Q_CTRL (EJ={ref_ej})...")
    q_eng.create_qubit("transmon", "Q_CTRL", {"EJ": ref_ej, "EC": 0.3, "truncated_dim": 4})
    
    # Sweep EJ from 12.0 to 18.0 (13 points gives 0.5 GHz steps)
    target_ejs = np.linspace(12.0, 18.0, 13) 
    
    delta_ejs = []
    fidelities = []
    
    for ej in target_ejs:
        targ_name = f"Q_TARG_{ej:.1f}"
        delta_ej = ej - ref_ej
        
        print("\n" + "-" * 60)
        print(f" TESTING TARGET: {targ_name} (EJ={ej:.1f}, Delta={delta_ej:.1f} GHz)")
        print("-" * 60)
        
        q_eng.create_qubit("transmon", targ_name, {"EJ": ej, "EC": 0.3, "truncated_dim": 4})
        couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.03}]
        
        print(f"[CALIBRATION]: Finding optimal CNOT gate duration...")
        best_duration, _ = g_eng.calibrate_gate(
            "Q_CTRL", targ_name, "CNOT", "tunable_coupler", 0.03, 
            parameter="duration", range_vals=np.linspace(20, 100, 20)
        )
        
        print(f"  -> Calibrated Duration: {best_duration:.1f} ns")
        print(f"[SIMULATION]: Running full dynamics with DRAG...")
        
        res = g_eng.simulate_n_qubit_dynamics(
            ["Q_CTRL", targ_name], "CNOT", best_duration, couplings, [], "10", 
            steps=100, use_drag=True
        )
        
        fidelity = res["populations"]["11"][-1]
        print(f"  -> Final P(|11>) Yield: {fidelity:.4f}")
        
        delta_ejs.append(delta_ej)
        fidelities.append(fidelity)
        
    # Plotting
    print("\n[PLOTTING]: Generating Fidelity vs. Delta EJ plot...")
    os.makedirs(os.path.join("outputs", "plots"), exist_ok=True)
    save_path = os.path.join("outputs", "plots", "12_CNOT_fidelity_vs_EJ_dropoff.png")
    
    plt.figure(figsize=(10, 6))
    plt.plot(delta_ejs, fidelities, marker='o', linestyle='-', color='#1565C0', linewidth=2, markersize=8)
    plt.axvline(0, color='gray', linestyle='--', alpha=0.7, label='Resonance (Delta=0)')
    plt.xlabel('Difference in EJ (Target - Control) [GHz]', fontsize=12)
    plt.ylabel('Operational CNOT Fidelity (P(|11>))', fontsize=12)
    plt.title('CNOT Gate Fidelity Drop-off vs. Qubit Detuning', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.ylim(0, 1.05)
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"\n[INFO]: Plot saved successfully to {save_path}\n")

if __name__ == "__main__":
    main()