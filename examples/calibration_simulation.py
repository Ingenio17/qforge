"""
14_single_gate_calibration.py

Description:
Demonstrates the automated calibration of single-qubit gates (X and H) using 
the GateEngine's built-in calibrate_gate method. This replaces manual loops 
over parameters with an optimized analytical-to-numerical sweep.
"""
import numpy as np
import os
from qforge.utils.terminal_plot import TerminalPlotter
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

def main():
    print("============================================================")
    print(" Example 14: Single Qubit Gate (X & H) Automated Calibration")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    # Initialize a Transmon qubit (truncated to 3 levels to observe leakage)
    q_eng.create_qubit("transmon", "Q1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
    
    # Extract qubit frequency (w01) for drive configuration
    qubit = q_eng.get_qubit("Q1")
    evals = qubit.eigensys(evals_count=2)[0]
    w01 = evals[1] - evals[0]
    
    drive_amp = 0.02 # GHz
    print(f"\n[CALIBRATION]: Finding optimal durations for Amp = {drive_amp} GHz...")

    # 1. Automated X-Gate Calibration
    # GateEngine.calibrate_gate internally calculates a tight sweep range 
    # around an analytical estimate and finds the peak duration.
    best_x_dur, x_metric = g_eng.calibrate_gate(
        q1_name="Q1", 
        gate_type="X", 
        parameter="duration", 
        amplitude=drive_amp
    )
    print(f"  -> Calibrated X-Pulse Duration: {best_x_dur:.2f} ns (Fidelity: {x_metric:.4f})")

    # 2. Automated H-Gate Calibration
    best_h_dur, h_metric = g_eng.calibrate_gate(
        q1_name="Q1", 
        gate_type="H", 
        parameter="duration", 
        amplitude=drive_amp
    )
    print(f"  -> Calibrated H-Pulse Duration: {best_h_dur:.2f} ns (Fidelity: {h_metric:.4f})")

    print(f"\n[EVOLUTION]: Simulating X-Gate dynamics with calibrated duration...")
    
    # Prepare the drive with optimal parameters for visualization
    drives = [{"target": 0, "type": "X", "amplitude": drive_amp, "frequency": w01, "phase": 0.0}]
    
    # Run high-resolution time-domain simulation
    res = g_eng.simulate_n_qubit_dynamics(
        ["Q1"], 
        "Calibrated_X", 
        best_x_dur, 
        [], # no couplings
        drives, 
        "0", # initial_state
        steps=50
    )
    
    times, p0, p1 = res["times"], res["populations"]["0"], res["populations"]["1"]
    p_leak = 1.0 - np.array(p0) - np.array(p1)
    
    print("\n   Time (ns) | P(|0>) | P(|1>) | P(|2>) (Leakage)")
    print("   ----------------------------------------------")
    for i in range(0, len(times), 10):
        print(f"   {times[i]:9.2f} |  {p0[i]:.3f} |  {p1[i]:.3f} |  {p_leak[i]:.6f}")
    print(f"   {times[-1]:9.2f} |  {p0[-1]:.3f} |  {p1[-1]:.3f} |  {p_leak[-1]:.6f}\n")
    
    # Terminal Visualization
    TerminalPlotter.plot_time_evolution(
        times=times,
        expectations=[p0, p1, p_leak],
        labels=['P(|0>)', 'P(|1>)', 'P(|2>) (Leakage)'],
        title=f"Automated Single Qubit X-Gate | Duration: {best_x_dur:.2f} ns"
    )

if __name__ == "__main__":
    main()