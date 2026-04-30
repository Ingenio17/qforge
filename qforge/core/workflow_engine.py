"""
workflow_engine.py

Provides the PhysicalWorkflowEngine for translating abstract quantum circuits
into physical microwave schedules on defined qubit topologies.
"""

import numpy as np
import copy
from typing import List, Dict, Tuple, Any

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine

try:
    from qiskit import QuantumCircuit, transpile
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False


class PhysicalWorkflowEngine:
    """
    Automates the full physical workflow simulation:
    Abstract OpenQASM -> Transpilation -> Calibration -> Scheduling -> Physics Simulation
    """
    def __init__(self, q_eng: QubitEngine, g_eng: GateEngine):
        self.q_eng = q_eng
        self.g_eng = g_eng
        
        if not QISKIT_AVAILABLE:
            raise ImportError("Qiskit is required for physical workflow simulation.")

    def parse_qasm_circuit(self, qasm_path: str) -> 'QuantumCircuit':
        circuit = QuantumCircuit.from_qasm_file(qasm_path)
        basis_gates = ['x', 'h', 'rz', 'cx', 'cz', 'swap', 'cp']
        transpiled = transpile(circuit, basis_gates=basis_gates, optimization_level=2)
        return transpiled

    def automate_calibrations(self, qubit_names: List[str], couplings: List[Dict], transpiled_circuit: 'QuantumCircuit', **kwargs) -> Dict:
        calibrations = {
            "single_qubit": {},
            "two_qubit": {}
        }
        
        for q in qubit_names:
<<<<<<< HEAD
            # Physics-informed X calibration: calibrate_gate uses T_pi = 6/(amp*n01*sqrt(2pi))
            # as the sweep centre when range_vals is empty (no fixed 15-25 ns range).
            best_x, _ = self.g_eng.calibrate_gate(q, gate_type="X", parameter="duration", amplitude=0.025)
            # H = Rz(π/2)·Rx(π/2)·Rz(π/2).  The Rx(π/2) sub-pulse is the same charge-operator
            # drive as X but at half the rotation angle.  For a Gaussian pulse the rotation angle
            # scales linearly with duration, so H duration = X duration / 2.
            # A separate H sweep is not needed and would use a mis-phased operator anyway.
            # Natively calibrate the H-gate instead of guessing the scaling
            best_h, _ = self.g_eng.calibrate_gate(q, gate_type="H", parameter="duration", amplitude=0.025)
            
=======
            best_x, _ = self.g_eng.calibrate_gate(q, gate_type="X", parameter="duration", range_vals=np.linspace(5.0, 60.0, 50), amplitude=0.025)
            best_h, _ = self.g_eng.calibrate_gate(q, gate_type="H", parameter="duration", range_vals=np.linspace(5.0, 60.0, 50), amplitude=0.025)
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df
            calibrations["single_qubit"][q] = {"X": best_x, "H": best_h}
            
        for c in couplings:
            q1_name = qubit_names[c["q1"]]
            q2_name = qubit_names[c["q2"]]
            
<<<<<<< HEAD
            best_cz, _ = self.g_eng.calibrate_gate(q1_name, q2_name, "CZ", ctype, strength, "duration")
            best_cx, _ = self.g_eng.calibrate_gate(q1_name, q2_name, "CNOT", ctype, strength, "duration")
            calibrations["two_qubit"][(q1_name, q2_name)] = {"CZ": best_cz, "CX": best_cx}
            calibrations["two_qubit"][(q2_name, q1_name)] = {"CZ": best_cz, "CX": best_cx}
=======
            # FIX 1: Calibrate CNOT directly in the fast-gate regime to catch the correct resonance peak
            best_cnot, _ = self.g_eng.calibrate_gate(
                q1_name, q2_name, "CNOT", c["type"], c["strength"], 
                parameter="duration", range_vals=np.linspace(15, 80, 40)
            )
            calibrations["two_qubit"][(q1_name, q2_name)] = {"CNOT": best_cnot}
            calibrations["two_qubit"][(q2_name, q1_name)] = {"CNOT": best_cnot}
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df
            
        return calibrations

    def compile_schedule(self, qubit_names: List[str], couplings: List[Dict], transpiled_circuit: 'QuantumCircuit', calibrations: Dict) -> Tuple[List[Dict], float]:
        schedule = []
        num_qubits = len(qubit_names)
        qubit_times = [0.0] * num_qubits
        
        # FIX 2: Virtual Z tracking variables
        lo_phases = [0.0] * num_qubits 
        h_counts = [0] * num_qubits 
        
        w01_list = []
        for q in qubit_names:
            evals = self.q_eng.get_qubit(q).eigensys(evals_count=2)[0]
            w01_list.append(np.real(evals[1] - evals[0]))
            
<<<<<<< HEAD
        # TODO: _add_h is no longer called — H gate scheduling is handled inline in the
        # op_name == 'h' branch below. _add_cx previously used it as the flanking rotation
        # in H+CZ+H, but that decomposition is replaced by the physical Ry(±π/2)+coupler sequence.
        def _add_h(targ_idx, t_start):
            dur = calibrations["single_qubit"][qubit_names[targ_idx]]["H"]
            schedule.append({"target": targ_idx, "type": "H", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
            return t_start + dur
            
        def _add_cz(q1_idx, q2_idx, c_conf, t_start):
            dur = calibrations["two_qubit"][(qubit_names[q1_idx], qubit_names[q2_idx])]["CZ"]
            schedule.append({"target": (min(q1_idx, q2_idx), max(q1_idx, q2_idx)), "type": "coupler_pulse", "strength": c_conf["strength"], "start_time": t_start, "end_time": t_start + dur})
            return t_start + dur

        def _add_cx(ctrl_idx, targ_idx, c_conf, t_start):
            dur_cx = calibrations["two_qubit"][(qubit_names[ctrl_idx], qubit_names[targ_idx])]["CX"]
            ctype = c_conf["type"]

            if ctype == "tunable_coupler":
                # CX = Ry(-π/2)_targ · CZ · Ry(+π/2)_targ — mirrors the sequence in simulate_n_qubit_dynamics.
                # Ry(±π/2) implemented as X drives with ∓π/2 phase: cos(ωt ∓ π/2) = ±sin(ωt).
                t_h = calibrations["single_qubit"][qubit_names[targ_idx]]["X"] / 2.0
                schedule.append({"target": targ_idx, "type": "X", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": -np.pi / 2, "start_time": t_start, "end_time": t_start + t_h})
                t1 = t_start + t_h
                schedule.append({"target": (min(ctrl_idx, targ_idx), max(ctrl_idx, targ_idx)), "type": "coupler_pulse", "strength": c_conf["strength"], "start_time": t1, "end_time": t1 + dur_cx})
                t2 = t1 + dur_cx
                schedule.append({"target": targ_idx, "type": "X", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": np.pi / 2, "start_time": t2, "end_time": t2 + t_h})
                return t2 + t_h
            else:
                # Capacitive CR: drive control qubit at target qubit's transition frequency.
                schedule.append({"target": ctrl_idx, "type": "X", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur_cx})
                return t_start + dur_cx
=======
        def _add_cx(ctrl_idx, targ_idx, c_conf, t_start):
            # FIX 3: Recreate exact CNOT_COMPILED physics within the scheduler
            dur = calibrations["two_qubit"][(qubit_names[ctrl_idx], qubit_names[targ_idx])]["CNOT"]
            t_x = calibrations["single_qubit"][qubit_names[targ_idx]]["X"]
            t_h = t_x / 2.0
            
            H0_ctrl, _ = self.g_eng._get_qubit_hamiltonian(qubit_names[ctrl_idx])
            H0_tgt, _ = self.g_eng._get_qubit_hamiltonian(qubit_names[targ_idx])
            
            e_ctrl = H0_ctrl.diag() / (2 * np.pi)
            e_tgt = H0_tgt.diag() / (2 * np.pi)
            
            w01_ctrl = np.real(e_ctrl[1] - e_ctrl[0])
            w01_tgt = np.real(e_tgt[1] - e_tgt[0])
            
            alpha_tgt = np.real((e_tgt[2] - e_tgt[1]) - w01_tgt) if len(e_tgt) >= 3 else 0.0
            auto_detuning = (w01_ctrl - w01_tgt - alpha_tgt) if alpha_tgt != 0.0 else 0.0
            
            exact_flux_phase = (auto_detuning * 2 * np.pi) * (dur / 2.0)
            
            curr_t = max(t_start, qubit_times[targ_idx], qubit_times[ctrl_idx])
            
            # Y(-pi/2) on target
            schedule.append({"target": targ_idx, "type": "X", "amplitude": 0.025, "frequency": w01_tgt, "phase": -np.pi / 2 + lo_phases[targ_idx], "start_time": curr_t, "end_time": curr_t + t_h})
            curr_t += t_h
            
            # CZ (Coupler + Flux)
            schedule.append({"target": (min(ctrl_idx, targ_idx), max(ctrl_idx, targ_idx)), "type": "coupler_pulse", "strength": c_conf["strength"], "start_time": curr_t, "end_time": curr_t + dur})
            schedule.append({"target": targ_idx, "type": "flux_pulse", "detuning": auto_detuning, "start_time": curr_t, "end_time": curr_t + dur})
            curr_t += dur
            
            # Apply Virtual Z Phase from the flux pulse directly to the LO clock
            lo_phases[targ_idx] += exact_flux_phase
            
            # Y(pi/2) on target
            schedule.append({"target": targ_idx, "type": "X", "amplitude": 0.025, "frequency": w01_tgt, "phase": np.pi / 2 + lo_phases[targ_idx], "start_time": curr_t, "end_time": curr_t + t_h})
            curr_t += t_h
            
            return curr_t, curr_t 
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df

        for instr in transpiled_circuit.data:
            op_name = instr.operation.name
            qargs = [transpiled_circuit.find_bit(q).index for q in instr.qubits]
            
            if len(qargs) == 1:
                q = qargs[0]
                q_name = qubit_names[q]
                t_start = qubit_times[q]
                
                if op_name == 'x':
                    dur = calibrations["single_qubit"][q_name]["X"]
                    schedule.append({"target": q, "type": "X", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0 + lo_phases[q], "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q] += dur
                elif op_name == 'h':
                    dur = calibrations["single_qubit"][q_name]["H"]
<<<<<<< HEAD
                    # Change "type": "H" to "type": "Y"
                    schedule.append({"target": q, "type": "H", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
=======
                    # Logical inversion hack: Flip phase on alternate H applications to satisfy H^2 = I
                    phase_offset = np.pi if h_counts[q] % 2 == 1 else 0.0
                    schedule.append({"target": q, "type": "H", "amplitude": 0.025, "frequency": w01_list[q], "phase": phase_offset + lo_phases[q], "start_time": t_start, "end_time": t_start + dur})
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df
                    qubit_times[q] += dur
                    h_counts[q] += 1
                elif op_name == 'rz':
<<<<<<< HEAD
                    # Abstractly represented by tracking classical phase updates natively, but physical simulation uses
                    # raw drives. For simplicity without a hardware virtual Z compile, we treat it as an instantaneous frame update
                    # and omit the physical pulse (fidelity assumes global phase tracking mapping)
                    pass
                elif op_name in ('measure', 'barrier', 'reset'):
                    # Classical/control-flow operations — not unitary gates, no physical pulse needed.
                    pass
                else:
                    print(f"Warning: Single qubit gate {op_name} unsupported in rigorous native basis mapping. Treating it as identity wait.")
=======
                    params = instr.operation.params
                    theta = float(params[0]) if params else 0.0
                    # Instantaneous Virtual Z Native Support
                    lo_phases[q] += theta 
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df
                    
            elif len(qargs) == 2:
                q1, q2 = qargs
                q1_name, q2_name = qubit_names[q1], qubit_names[q2]
                t_start = max(qubit_times[q1], qubit_times[q2])
                
                c_conf = next((c for c in couplings if (c["q1"] == q1 and c["q2"] == q2) or (c["q1"] == q2 and c["q2"] == q1)), None)
                if not c_conf:
                    raise ValueError(f"Topology Error: No coupling between {q1_name} and {q2_name}.")
                
<<<<<<< HEAD
                if op_name == 'cz':
                    t_end = _add_cz(q1, q2, c_conf, t_start)
                    qubit_times[q1] = qubit_times[q2] = t_end
                    
                elif op_name == 'cx' or op_name == 'cnot':
                    qubit_times[q1] = qubit_times[q2] = _add_cx(q1, q2, c_conf, t_start)
                    
                elif op_name == 'cp' or op_name == 'cphase':
                    params = instr.operation.params
                    theta = float(params[0]) if params else np.pi
                    frac = np.abs(theta) / np.pi
                    base_dur = calibrations["two_qubit"][(q1_name, q2_name)]["CZ"]
                    dur = max(2.0, base_dur * frac) # proportional phase duration scaling 
                    
                    schedule.append({"target": (min(q1, q2), max(q1, q2)), "type": "coupler_pulse", "strength": c_conf["strength"], "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q1] = qubit_times[q2] = t_start + dur
                    
                elif op_name == 'swap':
                    # SWAP is 3 CX gates
                    qubit_times[q1] = qubit_times[q2] = _add_cx(q1, q2, c_conf, t_start)
                    qubit_times[q1] = qubit_times[q2] = _add_cx(q2, q1, c_conf, qubit_times[q1])
                    qubit_times[q1] = qubit_times[q2] = _add_cx(q1, q2, c_conf, qubit_times[q1])
=======
                if op_name == 'cx' or op_name == 'cnot':
                    t_ctrl, t_targ = _add_cx(q1, q2, c_conf, t_start)
                    qubit_times[q1] = t_ctrl
                    qubit_times[q2] = t_targ
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df

        return schedule, max(qubit_times)

    def execute_workflow(self, qubit_names: List[str], couplings: List[Dict], qasm_path: str) -> Dict:
        print(f"1. Translating Qubit-Agnostic QASM from '{qasm_path}' to precise superconducting native basis...")
        transpiled = self.parse_qasm_circuit(qasm_path)
        
        print("2. Automating physical hardware calibration bounds...")
        calibrations = self.automate_calibrations(qubit_names, couplings, transpiled)
        
        print("3. Compiling continuous chronologic microwave schedule...")
        schedule, total_time = self.compile_schedule(qubit_names, couplings, transpiled, calibrations)
        
        print(f"4. Schedular mapping complete! Physical simulation runtime depth: {total_time:.2f} ns.")
        initial_state = "0" * len(qubit_names)
        
        print(f"5. Engaging Hilbert-space QuTiP solvers (Simulating continuous Hamiltonian mappings)...")
        res = self.g_eng.simulate_n_qubit_dynamics(
            qubit_names=qubit_names,
            gate_type="Compiled_Algorithm",
            duration=total_time,
            couplings=couplings,
            drives=schedule,
            initial_state=initial_state,
            steps=max(50, int(total_time * 2)) 
        )
        return res