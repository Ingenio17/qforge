"""
11_pairwise_CNOT_simulation.py

Description:
Simulates pairwise Two-Qubit CNOT gates among 3 qubits via tunable coupling.
Compares the CNOT fidelity and leakage across different pairs, 
leveraging DRAG pulsing to minimize leakage.
(Now powered by GateEngine's implicit auto-flux compiler!)
"""
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from qforge.utils.terminal_plot import TerminalPlotter
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

def main():
    print("============================================================")
    print(" Example 11: Pairwise CNOT Gate Simulation for 3 Qubits")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    print("\n[INIT]: Creating Qubits Q0 (EJ=15.0), Q1 (EJ=14.5), Q2 (EJ=13.5)...")
    q_eng.create_qubit("transmon", "Q0", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", "Q1", {"EJ": 14.5, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", "Q2", {"EJ": 13.5, "EC": 0.3, "truncated_dim": 4})
    
    pairs = [("Q0", "Q1"), ("Q1", "Q2"), ("Q0", "Q2")]
    
    for ctrl, targ in pairs:
        print("\n" + "=" * 60)
        print(f" PAIRWISE SIMULATION: Control={ctrl} -> Target={targ}")
        print("=" * 60)
        
        couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.03}]
        
        print(f"\n[CALIBRATION]: Finding optimal CNOT gate duration for {ctrl}->{targ}...")
        # Look how clean this is! No detuning passed, the GateEngine handles it automatically.
        best_duration, max_p11 = g_eng.calibrate_gate(
            ctrl, targ, "CNOT", "tunable_coupler", 0.03, 
            parameter="duration", range_vals=np.linspace(20, 100, 20)
        )
                
        print(f"  -> Calibrated Gate Duration: {best_duration:.1f} ns (Yielding P(|11>) = {max_p11:.4f})")
        print(f"\n[EVOLUTION]: Simulating CNOT Gate Dynamics over {best_duration:.1f}ns with DRAG")
        
        res = g_eng.simulate_n_qubit_dynamics(
            [ctrl, targ], "CNOT", best_duration, couplings, [], "10", 
            steps=200, use_drag=True
        )
        
        times = res["times"]
        p_00, p_01 = res["populations"]["00"], res["populations"]["01"]
        p_10, p_11 = res["populations"]["10"], res["populations"]["11"]
        
        print("\n   Time (ns) | P(|00>) | P(|01>) | P(|10>) | P(|11>) | P(Leakage)")
        print("   --------------------------------------------------------------")
        
        leakage_vals = []
        for i in range(len(times)):
            comp_prob = min(p_00[i] + p_01[i] + p_10[i] + p_11[i], 1.0) 
            leakage = 1.0 - comp_prob
            leakage_vals.append(leakage)
            
            if i % 40 == 0 or i == len(times) - 1:
                print(f"   {times[i]:9.1f} |  {p_00[i]:.3f} |  {p_01[i]:.3f} |  {p_10[i]:.3f} |  {p_11[i]:.3f} |  {leakage:.3f}")
        
        TerminalPlotter.plot_time_evolution(
            times=times,
            expectations=[p_10, p_11, leakage_vals],
            labels=['P(|10>) (Init)', 'P(|11>) (Target)', 'Leakage'],
            title=f"CNOT {ctrl}->{targ} Evolution (with DRAG)",
            ylim=(0, 1.05)
        )
        
        os.makedirs(os.path.join("outputs", "plots"), exist_ok=True)
        save_path = os.path.join("outputs", "plots", f"11_CNOT_{ctrl}_{targ}_DRAG.png")
        
        plt.figure(figsize=(10, 6))
        plt.plot(times, p_10, label='P(|10>) (Init)', linewidth=2)
        plt.plot(times, p_11, label='P(|11>) (Target)', linewidth=2)
        plt.plot(times, leakage_vals, label='Leakage', linestyle='--', linewidth=2)
        plt.xlabel('Time (ns)')
        plt.ylabel('Population')
        plt.title(f'CNOT Gate Evolution {ctrl}->{targ} (DRAG)')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n[INFO]: High-resolution plot saved to {save_path}\n")

if __name__ == "__main__":
    main()