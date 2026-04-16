"""
11_deutsch.py

Description:
Simulates the two-qubit Deutsch Algorithm using physical microwave drives and a tunable
coupler. We test a "balanced" oracle (CNOT gate) and verify that the algorithm
deterministically evolves the data qubit to |1>.

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
    print(" Example 11: Deutsch Algorithm (Balanced vs. Constant Oracle)")
    print("============================================================")
    
    q_eng = QubitEngine()
    g_eng = GateEngine()

    q_eng.create_qubit("transmon", "T1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", "T2", {"EJ": 13.5, "EC": 0.2, "truncated_dim": 4})

    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.03}]

    print(f"\n[CALIBRATION]: Finding optimal H gate durations...")
    best_h_dur_t1, _ = g_eng.calibrate_gate("T1", gate_type="H", parameter="duration")
    best_h_dur_t2, _ = g_eng.calibrate_gate("T2", gate_type="H", parameter="duration")
    
    print(f"  -> Calibrated H Gate Duration (T1): {best_h_dur_t1:.1f} ns")
    print(f"  -> Calibrated H Gate Duration (T2): {best_h_dur_t2:.1f} ns")

    print(f"\n[CALIBRATION]: Finding optimal CNOT gate duration (Balanced Oracle)...")
    best_cnot_dur, max_p11 = g_eng.calibrate_gate(
        "T1", "T2", "CNOT", "tunable_coupler", 0.03, 
        parameter="duration", 
        range_vals=np.linspace(0, 80, 80)
    )
    print(f"  -> Calibrated CNOT Gate Duration: {best_cnot_dur:.1f} ns")
    
    # Extract exact anharmonic frequencies for targeted H drives
    evals_t1 = q_eng.get_qubit("T1").eigensys(evals_count=2)[0]
    w01_t1 = np.real(evals_t1[1] - evals_t1[0])
    
    evals_t2 = q_eng.get_qubit("T2").eigensys(evals_count=2)[0]
    w01_t2 = np.real(evals_t2[1] - evals_t2[0])

    for oracle_type, oracle_gate in [("Balanced", "CNOT"), ("Constant", "Identity")]:
        print("\n============================================================")
        print(f" Running Deutsch Algorithm with a {oracle_type} Oracle")
        print("============================================================")

        if oracle_type == "Balanced":
            print(f"\n[EVOLUTION]: Simulating Deutsch Algorithm Sequence ({oracle_type})")
            print("Theory: Initializing the system in |01>.")
            print("1. Apply H on both qubits: creates superposition |+>|->.")
            print("2. Apply Oracle (Balanced = CNOT): flips phase of |1>|->, entangling into |->|->.")
            print("3. Apply H on both qubits: interferes to |1>|1>.")
            print("Result: T1 measuring as |1> proves the function is balanced!")
        else: # Constant
            print(f"\n[EVOLUTION]: Simulating Deutsch Algorithm Sequence ({oracle_type})")
            print("Theory: Initializing the system in |01>.")
            print("1. Apply H on both qubits: creates superposition |+>|->.")
            print("2. Apply Oracle (Constant = Identity): state remains |+>|->.")
            print("3. Apply H on both qubits: interferes to |0>|1>.")
            print("Result: T1 measuring as |0> proves the function is constant!")

        # Step 1: Initial H Gates
        h_drives_1 = [
            {"target": 0, "type": "H", "amplitude": 0.025, "frequency": w01_t1, "phase": 0.0, "start_time": 0.0, "end_time": best_h_dur_t1},
            {"target": 1, "type": "H", "amplitude": 0.025, "frequency": w01_t2, "phase": 0.0, "start_time": 0.0, "end_time": best_h_dur_t2}
        ]
        dur_1 = max(best_h_dur_t1, best_h_dur_t2)
        
        res_step1 = g_eng.simulate_n_qubit_dynamics(
            ["T1", "T2"], "H_Gates", dur_1, [], h_drives_1, "01", steps=50, use_drag=True
        )
        
        # Step 2: Oracle
        if oracle_type == "Balanced":
            res_step2 = g_eng.simulate_n_qubit_dynamics(
                ["T1", "T2"], "CNOT", best_cnot_dur, couplings, [], res_step1["final_state"], steps=150, use_drag=True
            )
        else: # Constant
            # Simulate free evolution (Identity) for the same duration as the CNOT gate
            res_step2 = g_eng.simulate_n_qubit_dynamics(
                ["T1", "T2"], "Identity", best_cnot_dur, [], [], res_step1["final_state"], steps=150, use_drag=True
            )
        
        # Step 3: Final H Gates
        h_drives_3 = [
            {"target": 0, "type": "H", "amplitude": 0.025, "frequency": w01_t1, "phase": np.pi, "start_time": 0.0, "end_time": best_h_dur_t1},
            {"target": 1, "type": "H", "amplitude": 0.025, "frequency": w01_t2, "phase": np.pi, "start_time": 0.0, "end_time": best_h_dur_t2}
        ]
        
        res_step3 = g_eng.simulate_n_qubit_dynamics(
            ["T1", "T2"], "H_Gates", dur_1, [], h_drives_3, res_step2["final_state"], steps=50, use_drag=True
        )

        # Stitch continuous time sequences together seamlessly
        t_offset_1 = res_step1["times"][-1]
        t_offset_2 = t_offset_1 + res_step2["times"][-1]
        
        times = np.concatenate((
            res_step1["times"], 
            t_offset_1 + res_step2["times"][1:],
            t_offset_2 + res_step3["times"][1:]
        ))
        
        pops = {}
        for state in res_step1["populations"]:
            pops[state] = np.concatenate((
                res_step1["populations"][state], 
                res_step2["populations"][state][1:],
                res_step3["populations"][state][1:]
            ))
            
        p_00, p_01 = pops.get("00", np.zeros_like(times)), pops.get("01", np.zeros_like(times))
        p_10, p_11 = pops.get("10", np.zeros_like(times)), pops.get("11", np.zeros_like(times))
        
        # Text output
        print("\n   Time (ns) | P(|00>) | P(|01>) | P(|10>) | P(|11>) | P(Leakage)")
        print("   --------------------------------------------------------------")
        
        leakage_vals = []
        for i in range(len(times)):
            comp_prob = p_00[i] + p_01[i] + p_10[i] + p_11[i]
            comp_prob = min(comp_prob, 1.0) 
            leakage = 1.0 - comp_prob
            leakage_vals.append(leakage)
            
            if i % 25 == 0:
                print(f"   {times[i]:9.1f} |  {p_00[i]:.3f} |  {p_01[i]:.3f} |  {p_10[i]:.3f} |  {p_11[i]:.3f} |  {leakage:.3f}")
        
        comp_prob_last = min(p_00[-1] + p_01[-1] + p_10[-1] + p_11[-1], 1.0)
        leak_last = 1.0 - comp_prob_last
        print(f"   {times[-1]:9.1f} |  {p_00[-1]:.3f} |  {p_01[-1]:.3f} |  {p_10[-1]:.3f} |  {p_11[-1]:.3f} |  {leak_last:.3f}")
        
        # Terminal Plot
        plot_labels = ['P(|01>)', 'P(|11>)', 'Leakage']
        if oracle_type == "Balanced":
            plot_labels = ['P(|01>) (Init)', 'P(|11>) (Final)', 'Leakage']
        else:
            plot_labels = ['P(|01>) (Final)', 'P(|11>)', 'Leakage']

        TerminalPlotter.plot_time_evolution(
            times=times,
            expectations=[p_01, p_11, leakage_vals],
            labels=plot_labels,
            title=f"Deutsch Algorithm Evolution ({oracle_type} Oracle)",
            ylim=(0, 1.05)
        )
        
        # Save high-res plot to outputs/plots
        os.makedirs(os.path.join("qforge", "outputs", "plots"), exist_ok=True)
        save_path = os.path.join("qforge", "outputs", "plots", f"11_deutsch_algorithm_{oracle_type.lower()}.png")
        
        plt.figure(figsize=(10, 6))
        plt.plot(times, p_00, label='P(|00>)', linewidth=2, alpha=0.6)
        if oracle_type == "Balanced":
            plt.plot(times, p_01, label='P(|01>) (Init)', linewidth=2)
            plt.plot(times, p_11, label='P(|11>) (Balanced Target)', linewidth=2)
        else:
            plt.plot(times, p_01, label='P(|01>) (Constant Target)', linewidth=2)
            plt.plot(times, p_11, label='P(|11>)', linewidth=2, alpha=0.6)
        plt.plot(times, p_10, label='P(|10>)', linewidth=2, alpha=0.6)
        plt.plot(times, leakage_vals, label='Leakage', linestyle='--', linewidth=2)
        
        # Add phase markers
        plt.axvline(x=t_offset_1, color='gray', linestyle=':', label=f'H -> {oracle_gate}')
        plt.axvline(x=t_offset_2, color='gray', linestyle='-.', label=f'{oracle_gate} -> H')
        
        plt.xlabel('Time (ns)')
        plt.ylabel('Population')
        plt.title(f'Deutsch Algorithm ({oracle_type} Oracle) Evolution')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"\n[INFO]: High-resolution plot saved to {save_path}")

if __name__ == "__main__":
    main()