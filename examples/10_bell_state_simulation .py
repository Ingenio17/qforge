"""
10_bell_state_simulation.py

Description:
Simulates a Two-Qubit bell state using a Flux-Tuned CZ gate,
and generates a time-evolution plot of the probabilities.

Terminal CLI Equivalents:
-------------------------
qforge qubit create --type transmon --name T1 --EJ 15.0 --EC 0.3
qforge qubit create --type transmon --name T2 --EJ 13.5 --EC 0.2
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
    print(" Example 10: Two Qubit Bell state creation with and without DRAG")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    q_eng.create_qubit("transmon", "T1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", "T2", {"EJ": 13.5, "EC": 0.2, "truncated_dim": 4})

    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.03}]

    # roughly: w1 - w2 + alpha2 = 5.70 - 4.44 + 0.30 = 1.56 GHz
    cz_detuning = 1.56 
    
    print(f"\n[CALIBRATION]: Finding optimal H gate duration for T1...")
    best_h_dur, _ = g_eng.calibrate_gate("T1", gate_type="H", parameter="duration")

    print(f"  -> Calibrated H Gate Duration: {best_h_dur:.1f} ns")

    print(f"\n[CALIBRATION]: Finding optimal CNOT gate duration...")
    # Pass the flux detuning to ensure the CZ gate is properly calibrated
    best_cnot_dur, max_p11 = g_eng.calibrate_gate(
        "T1", "T2", "CNOT", "tunable_coupler", 0.03, 
        parameter="duration", 
        range_vals=np.linspace(20, 100, 20),
        #detuning=cz_detuning
    )
    print(f"  -> Calibrated CNOT Gate Duration: {best_cnot_dur:.1f} ns")
    
    # Extract T1's exact anharmonic frequency for the targeted H drive
    evals_t1 = q_eng.get_qubit("T1").eigensys(evals_count=2)[0]
    w01_t1 = np.real(evals_t1[1] - evals_t1[0])

    print(f"\n[EVOLUTION]: Simulating Bell State Creation Sequence")
    print("Theory: Initializing the system in |00>.")
    print("1. Apply H gate on T1: creates superposition (|00> + |10>)/sqrt(2).")
    print("2. Apply CNOT (Control=T1, Target=T2): entangles into Bell state (|00> + |11>)/sqrt(2).")

    for drag_setting, drag_label in [(False, "without"), (True, "with")]:
        print("\n============================================================")
        print(f"{drag_label.upper()} DRAG SCHEME:")
        print("============================================================")
        
        # 1. Physical H Gate on T1
        h_drives = [{
            "target": 0, 
            "type": "H", 
            "amplitude": 0.025, 
            "frequency": w01_t1, 
            "phase": 0.0,
            "start_time": 0.0,
            "end_time": best_h_dur
        }]
        res_H = g_eng.simulate_n_qubit_dynamics(
            ["T1", "T2"], "H_Gate", best_h_dur, [], h_drives, "00", steps=50, use_drag=drag_setting
        )

        print(res_H["final_state"])
        
        # 2. CNOT Gate Sequence
        # Increased steps to 200 for clean Pi/2 plotting, added flux detuning
        res_CNOT = g_eng.simulate_n_qubit_dynamics(
            ["T1", "T2"], "CNOT", best_cnot_dur, couplings, [], res_H["final_state"], 
            steps=200, 
            #detuning=cz_detuning, 
            use_drag=drag_setting
        )
        
        # Stitch continuous time sequences together seamlessly
        times = np.concatenate((res_H["times"], res_H["times"][-1] + res_CNOT["times"][1:]))
        pops = {}
        for state in res_H["populations"]:
            pops[state] = np.concatenate((res_H["populations"][state], res_CNOT["populations"][state][1:]))
            
        p_00, p_01 = pops["00"], pops["01"]
        p_10, p_11 = pops["10"], pops["11"]
        
        # Text output
        print("\n   Time (ns) | P(|00>) | P(|01>) | P(|10>) | P(|11>) | P(Leakage)")
        print("   --------------------------------------------------------------")
        
        leakage_vals = []
        for i in range(len(times)):
            comp_prob = p_00[i] + p_01[i] + p_10[i] + p_11[i]
            comp_prob = min(comp_prob, 1.0) 
            leakage = 1.0 - comp_prob
            leakage_vals.append(leakage)
            
            if i % 20 == 0:
                print(f"   {times[i]:9.1f} |  {p_00[i]:.3f} |  {p_01[i]:.3f} |  {p_10[i]:.3f} |  {p_11[i]:.3f} |  {leakage:.3f}")
        
        comp_prob_last = min(p_00[-1] + p_01[-1] + p_10[-1] + p_11[-1], 1.0)
        leak_last = 1.0 - comp_prob_last
        print(f"   {times[-1]:9.1f} |  {p_00[-1]:.3f} |  {p_01[-1]:.3f} |  {p_10[-1]:.3f} |  {p_11[-1]:.3f} |  {leak_last:.3f}")
        
        # Terminal Plot
        TerminalPlotter.plot_time_evolution(
            times=times,
            expectations=[p_00, p_01, p_10, p_11, leakage_vals],
            labels=['P(|00>)', 'P(|01>) (Inter)', 'P(|10>) (Inter)', 'P(|11>)', 'Leakage'],
            title=f"Bell State Evolution {drag_label} DRAG",
            ylim=(0, 1.05)
        )
        
        # Save high-res plot to outputs/plots
        os.makedirs(os.path.join("qforge", "outputs", "plots"), exist_ok=True)
        save_path = os.path.join("qforge", "outputs", "plots", f"10_bell_state_{drag_label}_DRAG.png")
        
        plt.figure(figsize=(10, 6))
        plt.plot(times, p_00, label='P(|00>)', linewidth=2)
        plt.plot(times, p_01, label='P(|01>) (Inter)', linewidth=2)
        plt.plot(times, p_10, label='P(|10>) (Inter)', linewidth=2)
        plt.plot(times, p_11, label='P(|11>) (Bell)', linewidth=2)
        plt.plot(times, leakage_vals, label='Leakage', linestyle='--', linewidth=2)
        plt.xlabel('Time (ns)')
        plt.ylabel('Population')
        plt.title(f'Bell State Evolution {drag_label} DRAG scheme')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n[INFO]: High-resolution plot saved to {save_path}")

if __name__ == "__main__":
    main()