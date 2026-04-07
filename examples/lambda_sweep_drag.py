"""
lambda_sweep_drag.py

Description:
Simulates a fast X-gate on a Transmon qubit and sweeps the DRAG coefficient (lambda) 
from 0.0 to 1.0. Outputs the final population size of the ket(1) state and leakage to ket(2) 
for each lambda, recording the most optimal value to suppress leakage.
"""
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

def main():
    print("============================================================")
    print(" DRAG Coefficient (Lambda) Sweep for Multiple Gates (X, H, Y)")
    print("============================================================")
    
    # Initialize simulation engines
    q_eng = QubitEngine()
    g_eng = GateEngine()

    # Create a default Transmon qubit
    q_eng.create_qubit("transmon", "Q_sweep", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
    
    # A fast gate duration is calibrated to make DRAG correction highly necessary 
    # to prevent leakage out of the computational subspace into |2>.
    drive_amp = 0.06
    
    def run_sweep(lambdas_array, current_gate, duration):
        best_lam = 0.0
        max_metric = -1.0
        
        print("\n  Lambda | Metric  | Leakage P(|2>)")
        print("-----------------------------------")
        
        for lam in lambdas_array:
            res = g_eng.simulate_dynamics(
                qubit_name="Q_sweep",
                gate_type=current_gate,
                duration=duration,
                noise_model="none",
                steps=100,
                drag_lambda=lam,
                use_drag=True
            )
            
            # Extract final expectation values
            p0 = res["expectations"][0][-1]
            p1 = res["expectations"][1][-1]
            p2 = res["expectations"][2][-1] if len(res["expectations"]) > 2 else 0.0
            
            # Determine success metric based on gate type
            if current_gate in ["X", "Y"]:
                metric = p1
            elif current_gate == "H":
                metric = 1.0 - abs(p1 - 0.5) * 2.0
            else:
                metric = p1
            
            print(f"   {lam:.4f}  |  {metric:.4f} |  {p2:.4f}")
            
            # Record optimal lambda
            if metric > max_metric:
                max_metric = metric
                best_lam = lam
                
        return best_lam, max_metric

    gates = ["X", "H", "Y"]
    
    for gate in gates:
        print(f"\n============================================================")
        print(f" Calibrating {gate}-gate for fast drive (Amp = {drive_amp} GHz)")
        print(f"============================================================")
        
        calib_duration, _ = g_eng.calibrate_gate(
            "Q_sweep", gate_type=gate, parameter="duration", 
            amplitude=drive_amp, use_drag=False
        )
        print(f"-> Calibrated fast {gate}-gate duration: {calib_duration:.2f} ns")
        
        print(f"\n Running DRAG sweep for {gate}-gate (Duration: {calib_duration:.2f} ns)")
        
        # 1. Coarse Sweep
        print("\n--- Coarse Sweep ---")
        coarse_lambdas = np.linspace(0.0, 2.0, 30)
        best_lambda, max_metric = run_sweep(coarse_lambdas, gate, calib_duration)
        print(f"\n-> Coarse optimal DRAG lambda for {gate}: {best_lambda:.4f} (Metric = {max_metric:.4f})")
        
        # 2. High-Precision Fine Sweep
        print("\n--- Fine Sweep ---")
        step = coarse_lambdas[1] - coarse_lambdas[0]
        fine_bounds = (max(coarse_lambdas[0], best_lambda - step), 
                       min(coarse_lambdas[-1], best_lambda + step))
        fine_lambdas = np.linspace(fine_bounds[0], fine_bounds[1], 21)
        
        fine_best_lambda, fine_max_metric = run_sweep(fine_lambdas, gate, calib_duration)
        
        print(f"\n-> Final optimal DRAG lambda recorded for {gate}: {fine_best_lambda:.4f} (Metric = {fine_max_metric:.4f})")
        
        # 3. Simulate and plot
        print(f"\n-> Generating comparison plots for {gate}-gate...")
        
        res_no_drag = g_eng.simulate_dynamics(
            qubit_name="Q_sweep", gate_type=gate, duration=calib_duration,
            noise_model="none", steps=100, use_drag=False
        )
        
        res_with_drag = g_eng.simulate_dynamics(
            qubit_name="Q_sweep", gate_type=gate, duration=calib_duration,
            noise_model="none", steps=100, drag_lambda=fine_best_lambda, use_drag=True
        )
        
        times = res_no_drag["times"]
        p1_no = res_no_drag["expectations"][1]
        p2_no = res_no_drag["expectations"][2] if len(res_no_drag["expectations"]) > 2 else np.zeros_like(times)
        
        p1_with = res_with_drag["expectations"][1]
        p2_with = res_with_drag["expectations"][2] if len(res_with_drag["expectations"]) > 2 else np.zeros_like(times)
        
        os.makedirs(os.path.join("qforge","outputs", "plots"), exist_ok=True)
        save_path = os.path.join("qforge","outputs", "plots", f"lambda_sweep_{gate}_drag_comparison.png")
        
        plt.figure(figsize=(10, 6))
        plt.plot(times, p1_no, 'r--', label='P(|1>) Without DRAG', linewidth=2)
        plt.plot(times, p2_no, 'r:', label='Leakage P(|2>) Without DRAG', linewidth=2)
        
        plt.plot(times, p1_with, 'b-', label=f'P(|1>) With DRAG (λ={fine_best_lambda:.3f})', linewidth=2)
        plt.plot(times, p2_with, 'b-', alpha=0.5, label='Leakage P(|2>) With DRAG', linewidth=2)
        
        plt.xlabel('Time (ns)')
        plt.ylabel('Population')
        plt.title(f'{gate}-Gate Evolution: DRAG vs No DRAG (Duration: {calib_duration:.1f} ns)')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"-> Plot saved to {save_path}\n")

if __name__ == "__main__":
    main()