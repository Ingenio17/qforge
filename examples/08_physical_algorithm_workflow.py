"""
08_physical_algorithm_workflow.py

Description:
Implementation of the full Physical Algorithm Simulation Workflow. 
This script compiles a hardware-agnostic Shor's Algorithm (Period Finding) 
down to a chronologically scheduled sequence of physical microwave drives 
and tunable coupler flux pulses on an instantiated superconducting topology.

Topology: 
4 Transmons connected via Tunable Couplers
Q0 -- Q1 -- Q2 -- Q3
  \---------/ (Fast IQFT routing coupler to simulate full connectivity temporarily)

Terminal CLI Equivalents:
-------------------------
(This specialized continuous multi-qubit physical algorithmic simulation 
 is accessed directly via the Python API GateEngine)
"""
import numpy as np
import fractions
import time
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.utils.terminal_plot import TerminalPlotter

def main():
    print("============================================================")
    print(" Example 08: Physical Algorithm Simulation Workflow (Shor's)")
    print("============================================================")
    print("\n[STEP 1 & 2]: Instantiating Physical Hardware Topology")
    
    # 1. Hardware Instantiation
    q_eng = QubitEngine()
    g_eng = GateEngine()
    
    # 4 identical transmons
    w01_list = []
    print("  -> Initializing 4 Transmons (Truncated to 2 levels to prevent memory explosion)")
    for i in range(4):
        q_eng.create_qubit("transmon", f"Q{i}", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 2})
        evals = q_eng.get_qubit(f"Q{i}").eigensys(evals_count=2)[0]
        w01_list.append(evals[1] - evals[0])
        
    print("  -> Defining Hardware Topology Engine (Capacitive base, 0 drive default)")
    couplings = [
        {"q1": 0, "q2": 1, "type": "capacitive", "strength": 0.0},
        {"q1": 1, "q2": 2, "type": "capacitive", "strength": 0.0},
        {"q1": 2, "q2": 3, "type": "capacitive", "strength": 0.0},
        {"q1": 0, "q2": 2, "type": "capacitive", "strength": 0.0} # Routing edge for IQFT SWAP
    ]
    
    print("\n[STEP 3 & 4]: Algorithm Analysis & Pulse Schedule Compilation")
    print("  -> Deconstructing idealized Shor's unitary circuit (4 qubits: N=15, a=11).")
    print("  -> Translating abstract matrices into overlapping time-dependent physical drives.")
    
    print("  -> Executing native gate calibration against physical Transmon properties...")
    best_x_dur, x_metric = g_eng.calibrate_gate("Q0", gate_type="X", parameter="duration", range_vals=np.linspace(15.0, 25.0, 10), amplitude=0.025)
    best_h_dur, h_metric = g_eng.calibrate_gate("Q0", gate_type="H", parameter="duration", range_vals=np.linspace(5.0, 15.0, 10), amplitude=0.025)
    
    print(f"     [Calibrated] X-Gate (Pi-Pulse): {best_x_dur:.2f} ns (Fidelity: {x_metric:.4f})")
    print(f"     [Calibrated] H-Gate (Pi/2-Pulse): {best_h_dur:.2f} ns (Fidelity: {h_metric:.4f})")
    
    print("  -> Executing two-qubit entangling gate calibration (CZ) on tunable coupler...")
    best_cz_dur, cz_metric = g_eng.calibrate_gate("Q0", "Q1", "CZ", "tunable_coupler", 0.05, "duration", np.linspace(20, 60, 10))
    print(f"     [Calibrated] CZ-Gate: {best_cz_dur:.2f} ns (Phase Metric: {cz_metric:.4f})")

    schedule = []
    t = 0.0
    
    def add_x(q, t_start):
        dur = best_x_dur
        schedule.append({"target": q, "type": "X", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
        return t_start + dur

    def add_h(q, t_start):
        dur = best_h_dur 
        schedule.append({"target": q, "type": "H", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
        return t_start + dur

    def add_cz(q1, q2, t_start):
        dur = best_cz_dur
        schedule.append({"target": (min(q1, q2), max(q1, q2)), "type": "coupler_pulse", "strength": 0.05, "start_time": t_start, "end_time": t_start + dur})
        return t_start + dur
        
    def add_cnot(ctrl, targ, t_start):
        t1 = add_h(targ, t_start)
        t2 = add_cz(ctrl, targ, t1)
        return add_h(targ, t2)
        
    def add_swap(q1, q2, t_start):
        t1 = add_cnot(q1, q2, t_start)
        t2 = add_cnot(q2, q1, t1)
        return add_cnot(q1, q2, t2)
        
    def add_cphase(q1, q2, phase, t_start):
        # Scale duration physically proportional to target phase stringency
        frac = np.abs(phase) / np.pi
        dur = max(2.0, best_cz_dur * frac) # min dur to prevent fast numerical spikes
        schedule.append({"target": (min(q1, q2), max(q1, q2)), "type": "coupler_pulse", "strength": 0.05, "start_time": t_start, "end_time": t_start + dur})
        return t_start + dur

    # Compile the Shor's circuit sequentially
    # Init target to |1> and Phase register to |+>
    t_end_init = max(add_x(3, t), add_h(0, t), add_h(1, t), add_h(2, t))
    t = t_end_init
    
    # Unitary Modular Exponentiation (U = X controlled by Q2)
    t = add_cnot(2, 3, t)
    
    # IQFT Sequence
    t = add_swap(0, 2, t)
    
    # Q0 CPHASE
    t1 = add_h(0, t)
    t2 = add_cphase(0, 1, -np.pi/2, t1)
    t = add_cphase(0, 2, -np.pi/4, t2)
    
    # Q1 CPHASE
    t3 = add_h(1, t)
    t = add_cphase(1, 2, -np.pi/2, t3)
    
    # Q2
    t = add_h(2, t)
    
    total_time = t
    print(f"  -> Total physical compilation runtime: {total_time:.1f} ns")
    print(f"  -> Total scheduled microwave drives and flux pulses: {len(schedule)}")
    
    print("\n[STEP 5]: Full Physical System Evolution")
    print(f"  -> Invoking continuous Lindblad/Schrodinger solver over {total_time:.1f} ns.")
    print("  -> Computing true Hilbert-space dynamics (This may take several seconds)...")
    
    start_sim = time.time()
    # Execute full physics simulation
    res = g_eng.simulate_n_qubit_dynamics(
        qubit_names=["Q0", "Q1", "Q2", "Q3"], 
        gate_type="Compiled_Algorithm", 
        duration=total_time,
        couplings=couplings, 
        drives=schedule, 
        initial_state="0000", 
        steps=int(total_time * 2) # high res 0.5ns/step
    )
    sim_dur = time.time() - start_sim
    print(f"  -> Simulation complete in {sim_dur:.2f} seconds!")
    
    print("\n[STEP 6]: Result Decoding & Classical Post Processing (Shor's)")
    final_pops = res["populations"]
    
    # Find dominant probabilities
    print("\n   [Measurement Output]")
    success = False
    max_p = 0.0
    for prob_idx in range(16):
        bin_str = format(prob_idx, '04b')
        if bin_str in final_pops:
            p = final_pops[bin_str][-1]
            if p > max_p: max_p = p
            
            if p > 0.05:
                phase_bin = bin_str[:3]
                target_bin = bin_str[3]
                phase_val = int(phase_bin, 2)
                measured_phase_decimal = phase_val / 8.0
                
                print(f"   Detected Peak: State |{bin_str}>  (Prob: {p*100:5.1f}%)")
                print(f"      -> Target Register: |{target_bin}>")
                print(f"      -> Phase Register:  |{phase_bin}> (Decimal: {phase_val})")
                print(f"      -> Measured Phase:  {phase_val}/8 = {measured_phase_decimal}")
                
                if measured_phase_decimal == 0.0:
                    print("      -> Phase is 0. Trivial period, algorithm must repeat.")
                else:
                    frac = fractions.Fraction(measured_phase_decimal).limit_denominator(15)
                    print(f"      -> Continued Fraction limit_denominator(15) -> {frac.numerator}/{frac.denominator}")
                    print(f"      -> Calculated Period (r) = {frac.denominator}. Expected Period = 2.")
                    if frac.denominator == 2:
                        success = True
    
    if success:
         print("\n   >>> PHYSICAL SIMULATION SUCCESS! The correct algorithmic period was recovered from compiled pulses. <<<")

    print("\n[STEP 7]: Visual Analysis")
    times = res["times"]
    
    # Grab the top 4 states to plot continuously
    sorted_pops = sorted([(k, v[-1]) for k,v in final_pops.items()], key=lambda x: -x[1])
    top_4_keys = [k for k, v in sorted_pops[:4]]
    plot_expectations = [final_pops[k] for k in top_4_keys]
    labels = [f"P(|{k}>)" for k in top_4_keys]
    
    TerminalPlotter.plot_time_evolution(
        times=times,
        expectations=plot_expectations,
        labels=labels,
        title="Physical Shor's Algorithm Runtime Dynamics"
    )

if __name__ == "__main__":
    main()
    
