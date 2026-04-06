"""
09_CNOT_drag_scheme_simulation.py

Description:
Simulates a Two-Qubit CNOT gate via cross-resonance or tunable coupling, 
and generates a time-evolution plot of the probabilities.

Terminal CLI Equivalents:
-------------------------
qforge qubit create --type transmon --name T1 --EJ 15.0 --EC 0.3
qforge qubit create --type transmon --name T2 --EJ 14.5 --EC 0.3
(Note: Continuous multi-qubit physical simulation is powerfully accessed directly via 
 the Python API `GateEngine`, whereas `qforge gate simulate` is tuned for single qubits).
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
    print(" Example 09: Two Qubit CNOT Gate Time Evolution with and without DRAG")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    q_eng.create_qubit("transmon", "T1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", "T2", {"EJ": 13.5, "EC": 0.3, "truncated_dim": 4})
    
    # We use a tunable coupler to mediate the CNOT entanglement
    couplings = [{"q1": 0, "q2": 1, "type": "capacitive", "strength": 0.03}]
    
    print(f"\n[CALIBRATION]: Finding optimal CNOT gate duration...")
    best_duration, max_p11 = g_eng.calibrate_gate(
        "T1", "T2", "CNOT", "capacitive", 0.03, parameter="duration", range_vals=np.linspace(20, 100, 20)
    )
            
    print(f"  -> Calibrated Gate Duration: {best_duration:.1f} ns (Yielding P(|11>) = {max_p11:.4f})")
    
    print(f"\n[EVOLUTION]: Simulating CNOT Gate Dynamics over {best_duration:.1f}ns")
    print("Theory: Initializing the system in |10>. A perfect CNOT (Control=Q0, Target=Q1)")
    print("will flip the target, evolving the state from |10> to |11> over time.")
    print("Note: In physical multi-level systems, probabilities may not sum to 1 due to leakage into |2>.")

    for drag_setting, drag_label in [(False, "without"), (True, "with")]:
        print("\n============================================================")
        print(f"{drag_label.upper()} DRAG SCHEME:")
        print("============================================================")

        res = g_eng.simulate_n_qubit_dynamics(["T1", "T2"], "CNOT", best_duration, couplings, [], "10", steps=50, use_drag=drag_setting)
        
        times = res["times"]
        p_00, p_01 = res["populations"]["00"], res["populations"]["01"]
        p_10, p_11 = res["populations"]["10"], res["populations"]["11"]
        
        # Text output
        print("\n   Time (ns) | P(|00>) | P(|01>) | P(|10>) | P(|11>) | P(Leakage)")
        print("   --------------------------------------------------------------")
        
        leakage_vals = []
        for i in range(len(times)):
            comp_prob = p_00[i] + p_01[i] + p_10[i] + p_11[i]
            # Use abs to prevent floating point epsilons pushing sum slightly over 1
            comp_prob = min(comp_prob, 1.0) 
            leakage = 1.0 - comp_prob
            leakage_vals.append(leakage)
            
            if i % 10 == 0:
                print(f"   {times[i]:9.1f} |  {p_00[i]:.3f} |  {p_01[i]:.3f} |  {p_10[i]:.3f} |  {p_11[i]:.3f} |  {leakage:.3f}")
        
        comp_prob_last = min(p_00[-1] + p_01[-1] + p_10[-1] + p_11[-1], 1.0)
        leak_last = 1.0 - comp_prob_last
        print(f"   {times[-1]:9.1f} |  {p_00[-1]:.3f} |  {p_01[-1]:.3f} |  {p_10[-1]:.3f} |  {p_11[-1]:.3f} |  {leak_last:.3f}")
        
        # Terminal Plot
        TerminalPlotter.plot_time_evolution(
            times=times,
            expectations=[p_10, p_11, leakage_vals],
            labels=['P(|10>) (Init)', 'P(|11>) (Target)', 'Leakage'],
            title=f"CNOT Gate Evolution (T1->T2) {drag_label} DRAG scheme",
            ylim=(0, 1.05)
        )
        
        # Save high-res plot to outputs/plots
        os.makedirs(os.path.join("qforge", "outputs", "plots"), exist_ok=True)
        save_path = os.path.join("qforge", "outputs", "plots", f"09_CNOT_gates_{drag_label}_DRAG.png")
        
        plt.figure(figsize=(10, 6))
        plt.plot(times, p_10, label='P(|10>) (Init)', linewidth=2)
        plt.plot(times, p_11, label='P(|11>) (Target)', linewidth=2)
        plt.plot(times, leakage_vals, label='Leakage', linestyle='--', linewidth=2)
        plt.xlabel('Time (ns)')
        plt.ylabel('Population')
        plt.title(f'CNOT Gate Evolution (T1->T2) {drag_label.title()} DRAG')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n[INFO]: High-resolution plot saved to {save_path}")


if __name__ == "__main__":
    main()
