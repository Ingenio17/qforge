"""
03_two_qubit_gates.py

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
from qforge.utils.terminal_plot import TerminalPlotter
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

def main():
    print("============================================================")
    print(" Example 03: Two Qubit CNOT Gate Time Evolution")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    q_eng.create_qubit("transmon", "T1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
    q_eng.create_qubit("transmon", "T2", {"EJ": 14.5, "EC": 0.3, "truncated_dim": 3})
    
    # We use a tunable coupler to mediate the CNOT entanglement
    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.03}]
    
    print(f"\n[CALIBRATION]: Finding optimal CNOT gate duration...")
    best_duration = 0
    max_p11 = -1
    
    sweep_times = np.linspace(20, 100, 20)
    for duration in sweep_times:
        res = g_eng.simulate_n_qubit_dynamics(["T1", "T2"], "CNOT", duration, couplings, initial_state="10", steps=2)
        p11 = res["populations"]["11"][-1]
        
        if p11 > max_p11:
            max_p11 = p11
            best_duration = duration
            
    print(f"  -> Calibrated Gate Duration: {best_duration:.1f} ns (Yielding P(|11>) = {max_p11:.4f})")
    
    print(f"\n[EVOLUTION]: Simulating CNOT Gate Dynamics over {best_duration:.1f}ns")
    print("Theory: Initializing the system in |10>. A perfect CNOT (Control=Q0, Target=Q1)")
    print("will flip the target, evolving the state from |10> to |11> over time.")
    print("Note: In physical multi-level systems, probabilities may not sum to 1 due to leakage into |2>.")
    
    res = g_eng.simulate_n_qubit_dynamics(["T1", "T2"], "CNOT", best_duration, couplings, initial_state="10", steps=50)
    
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
        expectations=[p_00, p_01, p_10, p_11, leakage_vals],
        labels=['P(|00>)', 'P(|01>)', 'P(|10>) (Initial)', 'P(|11>) (Target)', 'P(Leakage)'],
        title="Two-Qubit CNOT Gate Evolution (Control=T1, Target=T2)"
    )

if __name__ == "__main__":
    main()
