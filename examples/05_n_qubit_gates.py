"""
05_n_qubit_gates.py

Description:
Showcases qforge's Generalized N-Qubit physical mapping.
1) A strong static capacitive coupling demonstrating visual excitation hopping.
2) An active simulation of a calibrated X-drive applied globally to all 4 qubits.

Terminal CLI Equivalents:
-------------------------
qforge qubit create --type transmon --name Q0 --EJ 15.0 --EC 0.3
(Note: Continuous multi-qubit physical simulation is powerfully accessed directly via 
 the Python API GateEngine, whereas `qforge gate simulate` is tuned for single qubits).
"""
import numpy as np
import os
from qforge.utils.terminal_plot import TerminalPlotter
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

def main():
    print("============================================================")
    print(" Example 05: Generalized N-Qubit Topology and Global Drive")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    # Identical transmon chain for resonant energy exchange
    for i in range(4):
        q_eng.create_qubit("transmon", f"Q{i}", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 2})
        
    print("\n[STEP 1]: Demonstrating Extreme Excitation Hopping (Strong Coupling)")
    print("Theory: Initializing the chain directly in |1000>. Because this is a *Closed* ")
    print("isolated quantum system, the energy cannot decay. It hops from Q0 -> Q3, ")
    print("reflects off the boundary, and oscillates back. This is why probability ")
    print("appears to continuously oscillate rather than smoothly decreasing to zero!")
    
    couplings = []
    for i in range(3):
         # Strong capacitive coupling
        couplings.append({"q1": i, "q2": i+1, "type": "capacitive", "strength": 0.05})
        
    res_hop = g_eng.simulate_n_qubit_dynamics(
        qubit_names=["Q0", "Q1", "Q2", "Q3"], gate_type="Free_Evolution", duration=100.0,
        couplings=couplings, drives=[], initial_state="1000", steps=100
    )
    
    times_hop = res_hop["times"]
    p_1000, p_0100 = res_hop["populations"]["1000"], res_hop["populations"]["0100"]
    p_0010, p_0001 = res_hop["populations"]["0010"], res_hop["populations"]["0001"]
    
    # Output the textual data
    print("\n   Time (ns) | P(|1000>) | P(|0100>) | P(|0010>) | P(|0001>)")
    print("   --------------------------------------------------------")
    for i in range(0, len(times_hop), 20):
        print(f"   {times_hop[i]:9.1f} |    {p_1000[i]:.3f} |    {p_0100[i]:.3f} |    {p_0010[i]:.3f} |    {p_0001[i]:.3f}")
    print(f"   {times_hop[-1]:9.1f} |    {p_1000[-1]:.3f} |    {p_0100[-1]:.3f} |    {p_0010[-1]:.3f} |    {p_0001[-1]:.3f}\n")
    
    # Terminal Plot for spin hopping
    TerminalPlotter.plot_time_evolution(
        times=times_hop,
        expectations=[p_1000, p_0100, p_0010, p_0001],
        labels=['P(|1000>) Phase 0', 'P(|0100>) Phase 1', 'P(|0010>) Phase 2', 'P(|0001>) Phase 3'],
        title="N-Qubit Capacitive Spin Hopping (Closed System Oscillations)"
    )

    print("\n[STEP 2]: Global Multi-Qubit Drive Simulation (Calibrating X-Gate first)")
    w01 = q_eng.get_qubit("Q0").eigensys(evals_count=2)[0][1] - q_eng.get_qubit("Q0").eigensys(evals_count=2)[0][0]
    
    # Calibrate Pi pulse duration on a single qubit
    drive_amp = 0.02
    best_duration = 0
    max_p1 = -1
    for duration in np.linspace(10, 200, 50):
        drives = [{"target": 0, "type": "X", "amplitude": drive_amp, "frequency": w01, "phase": 0.0}]
        res = g_eng.simulate_n_qubit_dynamics(["Q0"], "Custom_X", duration, [], drives, "0", steps=2)
        p1 = res["populations"]["1"][-1]
        if p1 > max_p1:
            max_p1 = p1
            best_duration = duration
            
    print(f"  -> Calibrated Pi-Pulse: Duration={best_duration:.1f}ns, Yield P(|1>)={max_p1:.4f}")
    
    print("\nApplying perfectly tuned calibrated pulse to Q0 and Q2 simultaneously...")
    global_drives = [
        {"target": 0, "type": "X", "amplitude": drive_amp, "frequency": w01, "phase": 0.0},
        {"target": 2, "type": "X", "amplitude": drive_amp, "frequency": w01, "phase": 0.0}
    ]
    
    # Evaluate global drive
    res_drive = g_eng.simulate_n_qubit_dynamics(
        qubit_names=["Q0", "Q1", "Q2", "Q3"], gate_type="Custom_X", duration=best_duration,
        couplings=[], drives=global_drives, initial_state="0000", steps=50
    )
    
    times_dr = res_drive["times"]
    pd_0000 = res_drive["populations"]["0000"]
    pd_1000 = res_drive["populations"]["1000"]
    pd_0010 = res_drive["populations"]["0010"]
    pd_1010 = res_drive["populations"]["1010"]
    
    # Output the textual data
    print("\n   Time (ns) | P(|0000>) | P(|1000>) | P(|0010>) | P(|1010>)")
    print("   --------------------------------------------------------")
    for i in range(0, len(times_dr), 10):
        print(f"   {times_dr[i]:9.1f} |    {pd_0000[i]:.3f} |    {pd_1000[i]:.3f} |    {pd_0010[i]:.3f} |    {pd_1010[i]:.3f}")
    print(f"   {times_dr[-1]:9.1f} |    {pd_0000[-1]:.3f} |    {pd_1000[-1]:.3f} |    {pd_0010[-1]:.3f} |    {pd_1010[-1]:.3f}\n")
    
    # Terminal Plot for global drive
    TerminalPlotter.plot_time_evolution(
        times=times_dr,
        expectations=[pd_0000, pd_1000, pd_0010, pd_1010],
        labels=['P(|0000>)', 'P(|1000>)', 'P(|0010>)', 'P(|1010>) (Target)'],
        title="Simultaneous Calibrated Global X-drive Evolution (Q0 & Q2)"
    )

if __name__ == "__main__":
    main()
