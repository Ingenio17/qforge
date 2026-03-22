"""
02_single_qubit_gates.py

Description:
Simulates a real microwave pulse applied to a qubit. We perform a parameter 
sweep (calibration) over the pulse duration to definitively find the pi-pulse 
time that maximizes the |1> state population, and plot the result.

Terminal CLI Equivalents:
-------------------------
qforge qubit create --type transmon --name Q1 --EJ 15.0 --EC 0.3
qforge gate simulate --qubit Q1 --gate X --duration 79.0 --save
"""
import numpy as np
import os
from qforge.utils.terminal_plot import TerminalPlotter
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

def main():
    print("============================================================")
    print(" Example 02: Single Qubit Gate (X) Calibration & Evolution")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    q_eng.create_qubit("transmon", "Q1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
    w01 = q_eng.get_qubit("Q1").eigensys(evals_count=2)[0][1] - q_eng.get_qubit("Q1").eigensys(evals_count=2)[0][0]
    
    drive_amp = 0.02 # GHz
    print(f"\n[CALIBRATION]: Finding optimal pi-pulse duration for Amp = {drive_amp} GHz...")
    
    # Run a sweep to calibrate duration to find the perfect pi-pulse
    best_duration = 0
    max_p1 = -1
    
    sweep_times = np.linspace(10, 200, 50)
    for duration in sweep_times:
        drives = [{"target": 0, "type": "X", "amplitude": drive_amp, "frequency": w01, "phase": 0.0}]
        res = g_eng.simulate_n_qubit_dynamics(["Q1"], "Custom_X", duration, [], drives, "0", steps=2)
        p1 = res["populations"]["1"][-1]
        
        if p1 > max_p1:
            max_p1 = p1
            best_duration = duration
            
    print(f"  -> Calibrated Pi-Pulse Duration: {best_duration:.1f} ns (Yielding P(|1>) = {max_p1:.4f})")
    print("  -> (Increase/Decrease drive amplitude and re-run calibration if target is unsatisfied)")
    
    print("\n[EVOLUTION]: Simulating the full time-domain trace using optimal parameters...")
    drives = [{"target": 0, "type": "X", "amplitude": drive_amp, "frequency": w01, "phase": 0.0}]
    res = g_eng.simulate_n_qubit_dynamics(["Q1"], "Custom_X", best_duration, [], drives, "0", steps=50)
    
    times, p0, p1 = res["times"], res["populations"]["0"], res["populations"]["1"]
    
    print("\n   Time (ns) | P(|0>) | P(|1>) | P(|2>) (Leakage)")
    print("   ----------------------------------------------")
    for i in range(0, len(times), 10):
        p_leak_val = max(0.0, 1.0 - p0[i] - p1[i])
        print(f"   {times[i]:9.1f} |  {p0[i]:.3f} |  {p1[i]:.3f} |  {p_leak_val:.6f}")
    
    p_leak_last = max(0.0, 1.0 - p0[-1] - p1[-1])
    print(f"   {times[-1]:9.1f} |  {p0[-1]:.3f} |  {p1[-1]:.3f} |  {p_leak_last:.6f}\n")
    
    # Terminal Plot
    p_leak = 1.0 - np.array(p0) - np.array(p1)
    TerminalPlotter.plot_time_evolution(
        times=times,
        expectations=[p0, p1, p_leak],
        labels=['P(|0>)', 'P(|1>)', 'P(|2>) (Leakage)'],
        title=f"Single Qubit X-Gate Evolution | Amp: {drive_amp} GHz | Calib. Duration: {best_duration:.1f} ns"
    )

if __name__ == "__main__":
    main()
