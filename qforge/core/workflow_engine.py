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
            raise ImportError("Qiskit is required for physical workflow simulation (translating QASM to precise basis). Please install qiskit.")

    def parse_qasm_circuit(self, qasm_path: str) -> 'QuantumCircuit':
        """
        Parses an OpenQASM file and transpiles it to a precise native basis.
        """
        circuit = QuantumCircuit.from_qasm_file(qasm_path)
        # Precise native superconducting basis for optimal calibration mapping
        basis_gates = ['x', 'h', 'rz', 'cx', 'cz', 'swap', 'cp']
        
        transpiled = transpile(circuit, basis_gates=basis_gates, optimization_level=2)
        return transpiled

    def automate_calibrations(self, qubit_names: List[str], couplings: List[Dict], transpiled_circuit: 'QuantumCircuit', **kwargs) -> Dict:
        """
        Dynamically calibrate physical pulses for abstract gates needed.
        Currently highly automated.
        
        TODO: Future introduction of user customization of calibration bounds via **kwargs
        """
        calibrations = {
            "single_qubit": {},
            "two_qubit": {}
        }
        
        # We auto-calibrate the prime single-qubit primitives for all involved qubits
        for q in qubit_names:
            # Physics-informed X calibration: calibrate_gate uses T_pi = 6/(amp*n01*sqrt(2pi))
            # as the sweep centre when range_vals is empty (no fixed 15-25 ns range).
            best_x, _ = self.g_eng.calibrate_gate(q, gate_type="X", parameter="duration", amplitude=0.025)
            # H = Rz(π/2)·Rx(π/2)·Rz(π/2).  The Rx(π/2) sub-pulse is the same charge-operator
            # drive as X but at half the rotation angle.  For a Gaussian pulse the rotation angle
            # scales linearly with duration, so H duration = X duration / 2.
            # A separate H sweep is not needed and would use a mis-phased operator anyway.
            # Natively calibrate the H-gate instead of guessing the scaling
            best_h, _ = self.g_eng.calibrate_gate(q, gate_type="H", parameter="duration", amplitude=0.025)
            
            calibrations["single_qubit"][q] = {"X": best_x, "H": best_h}
            
        # We auto-calibrate CZ on all defined couplings
        for c in couplings:
            q1_idx = c["q1"]
            q2_idx = c["q2"]
            q1_name = qubit_names[q1_idx]
            q2_name = qubit_names[q2_idx]
            ctype = c["type"]
            strength = c["strength"]
            
            best_cz, _ = self.g_eng.calibrate_gate(q1_name, q2_name, "CZ", ctype, strength, "duration")
            best_cx, _ = self.g_eng.calibrate_gate(q1_name, q2_name, "CNOT", ctype, strength, "duration")
            calibrations["two_qubit"][(q1_name, q2_name)] = {"CZ": best_cz, "CX": best_cx}
            calibrations["two_qubit"][(q2_name, q1_name)] = {"CZ": best_cz, "CX": best_cx}
            
        return calibrations

    def compile_schedule(self, qubit_names: List[str], couplings: List[Dict], transpiled_circuit: 'QuantumCircuit', calibrations: Dict) -> Tuple[List[Dict], float]:
        """
        Builds a chronological microwave drive schedule mapping precise gates to compiled pulses and timings.
        """
        schedule = []
        num_qubits = len(qubit_names)
        qubit_times = [0.0] * num_qubits
        
        # Fetch transition frequencies w01 from QubitEngine for parameterization
        w01_list = []
        for q in qubit_names:
            evals = self.q_eng.get_qubit(q).eigensys(evals_count=2)[0]
            w01_list.append(evals[1] - evals[0])
            
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

        # Parse operations iteratively, extending sequential times 
        for instr in transpiled_circuit.data:
            op_name = instr.operation.name
            
            # Map qiskit qubits to integers locally
            qargs = [transpiled_circuit.find_bit(q).index for q in instr.qubits]
            
            if len(qargs) == 1:
                q = qargs[0]
                q_name = qubit_names[q]
                t_start = qubit_times[q]
                
                if op_name == 'x':
                    dur = calibrations["single_qubit"][q_name]["X"]
                    schedule.append({"target": q, "type": "X", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q] += dur
                elif op_name == 'h':
                    dur = calibrations["single_qubit"][q_name]["H"]
                    # Change "type": "H" to "type": "Y"
                    schedule.append({"target": q, "type": "H", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q] += dur
                elif op_name == 'rz':
                    # Abstractly represented by tracking classical phase updates natively, but physical simulation uses
                    # raw drives. For simplicity without a hardware virtual Z compile, we treat it as an instantaneous frame update
                    # and omit the physical pulse (fidelity assumes global phase tracking mapping)
                    pass
                elif op_name in ('measure', 'barrier', 'reset'):
                    # Classical/control-flow operations — not unitary gates, no physical pulse needed.
                    pass
                else:
                    print(f"Warning: Single qubit gate {op_name} unsupported in rigorous native basis mapping. Treating it as identity wait.")
                    
            elif len(qargs) == 2:
                q1, q2 = qargs
                q1_name, q2_name = qubit_names[q1], qubit_names[q2]
                
                t_start = max(qubit_times[q1], qubit_times[q2])
                
                c_conf = None
                for c in couplings:
                    if (c["q1"] == q1 and c["q2"] == q2) or (c["q1"] == q2 and c["q2"] == q1):
                        c_conf = c
                        break
                
                if not c_conf:
                    raise ValueError(f"Topology Error: No coupling defined between physically adjacent logic operations on {q1_name} and {q2_name}.")
                
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

        return schedule, max(qubit_times)

    def execute_workflow(self, qubit_names: List[str], couplings: List[Dict], qasm_path: str) -> Dict:
        """
        Bundles compiling and simulating into a single execution step, returning the full dynamics payload.
        """
        print(f"1. Translating Qubit-Agnostic QASM from '{qasm_path}' to precise superconducting native basis...")
        transpiled = self.parse_qasm_circuit(qasm_path)
        
        print("2. Automating physical hardware calibration bounds...")
        calibrations = self.automate_calibrations(qubit_names, couplings, transpiled)
        
        print("3. Compiling continuous chronologic microwave schedule...")
        schedule, total_time = self.compile_schedule(qubit_names, couplings, transpiled, calibrations)
        
        print(f"4. Schedular mapping complete! Physical simulation runtime depth: {total_time:.2f} ns.")
        # Evolve using GatEngine
        initial_state = "0" * len(qubit_names)
        
        print(f"5. Engaging Hilbert-space QuTiP solvers (Simulating continuous Hamiltonian mappings)...")
        res = self.g_eng.simulate_n_qubit_dynamics(
            qubit_names=qubit_names,
            gate_type="Compiled_Algorithm",
            duration=total_time,
            couplings=couplings,
            drives=schedule,
            initial_state=initial_state,
            steps=max(10, int(total_time * 2)) 
        )
        return res
