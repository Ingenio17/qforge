"""
workflow_engine.py

Provides the PhysicalWorkflowEngine for translating abstract quantum circuits
into physical microwave schedules on defined qubit topologies.
"""
import re
import numpy as np
import copy
from typing import List, Dict, Tuple, Any

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine

class QASMTranspiler:
    """A parser and transpiler that converts OpenQASM 2.0 into a strict basis gate set."""
    
    GATE_PATTERN = re.compile(r"([a-z0-9]+)(?:\(([^)]+)\))?\s+([^;]+);")
    QUBIT_PATTERN = re.compile(r"([a-z]+)\[(\d+)\]")

    def __init__(self):
        # The strict basis gates allowed in the output
        self.basis_gates = {'x', 'h', 'rz', 'cx', 'cz', 'swap', 'cp'}

    def _parse_qubits(self, arg_string: str) -> List[int]:
        """Extracts qubit indices from a string like 'q[0], q[1]'."""
        return [int(match.group(2)) for match in self.QUBIT_PATTERN.finditer(arg_string)]

    def _parse_params(self, param_string: str) -> List[float]:
        """Safely evaluates mathematical expressions like 'pi/2' into floats."""
        if not param_string: return []
        
        safe_dict = {"pi": np.pi, "sqrt": np.sqrt}
        params = []
        for p in param_string.split(","):
            try:
                params.append(eval(p.strip(), {"__builtins__": None}, safe_dict))
            except Exception:
                params.append(0.0)
        return params

    def _decompose(self, gate_name: str, params: List[float], qubits: List[int]) -> List[Dict[str, Any]]:
        """
        Recursively maps any gate into the strict basis set.
        """
        gate_name = gate_name.lower()
        
        # 1. BASE CASE: The gate is already in our basis set
        if gate_name in self.basis_gates:
            inst = {
                "type": gate_name.upper(),
                "target": qubits[0] if len(qubits) == 1 else tuple(qubits)
            }
            if params:
                inst["theta"] = params[0] # RZ and CP take 1 parameter
            return [inst]

        # 2. ALIASES
        if gate_name == "cnot":
            return self._decompose("cx", params, qubits)
        if gate_name in ["p", "u1"]:
            return self._decompose("rz", params, qubits)

        # 3. PAULI & CLIFFORD DECOMPOSITIONS
        if gate_name == "z":
            return self._decompose("rz", [np.pi], qubits)
        if gate_name == "y":
            # Y = S X Sdg  ->  RZ(pi/2) X RZ(-pi/2)
            return (self._decompose("rz", [np.pi/2], qubits) +
                    self._decompose("x", [], qubits) +
                    self._decompose("rz", [-np.pi/2], qubits))
        if gate_name == "s":
            return self._decompose("rz", [np.pi/2], qubits)
        if gate_name == "sdg":
            return self._decompose("rz", [-np.pi/2], qubits)
        if gate_name == "t":
            return self._decompose("rz", [np.pi/4], qubits)
        if gate_name == "tdg":
            return self._decompose("rz", [-np.pi/4], qubits)

        # 4. CONTINUOUS ROTATION DECOMPOSITIONS
        if gate_name == "rx":
            # RX(theta) = H RZ(theta) H
            return (self._decompose("h", [], qubits) +
                    self._decompose("rz", params, qubits) +
                    self._decompose("h", [], qubits))
        
        if gate_name == "ry":
            # RY(theta) = RZ(pi/2) H RZ(theta) H RZ(-pi/2)
            return (self._decompose("rz", [np.pi/2], qubits) +
                    self._decompose("h", [], qubits) +
                    self._decompose("rz", params, qubits) +
                    self._decompose("h", [], qubits) +
                    self._decompose("rz", [-np.pi/2], qubits))

        # 5. UNIVERSAL SINGLE-QUBIT DECOMPOSITIONS
        if gate_name == "u2":
            phi, lam = params[0], params[1]
            return (self._decompose("rz", [lam - np.pi/2], qubits) +
                    self._decompose("rx", [np.pi/2], qubits) +
                    self._decompose("rz", [phi + np.pi/2], qubits))

        if gate_name in ["u3", "u"]:
            theta, phi, lam = params[0], params[1], params[2]
            return (self._decompose("rz", [lam], qubits) +
                    self._decompose("rx", [np.pi/2], qubits) +
                    self._decompose("rz", [theta], qubits) +
                    self._decompose("rx", [-np.pi/2], qubits) +
                    self._decompose("rz", [phi], qubits))

        # 6. TOFFOLI (CCX) DECOMPOSITION (Standard 6-CNOT breakdown)
        if gate_name == "ccx":
            c1, c2, t = qubits[0], qubits[1], qubits[2]
            return (
                self._decompose("h", [], [t]) +
                self._decompose("cx", [], [c2, t]) +
                self._decompose("tdg", [], [t]) +
                self._decompose("cx", [], [c1, t]) +
                self._decompose("t", [], [t]) +
                self._decompose("cx", [], [c2, t]) +
                self._decompose("tdg", [], [t]) +
                self._decompose("cx", [], [c1, t]) +
                self._decompose("t", [], [t]) +
                self._decompose("h", [], [t]) +
                self._decompose("t", [], [c2]) +
                self._decompose("cx", [], [c1, c2]) +
                self._decompose("t", [], [c1]) +
                self._decompose("tdg", [], [c2]) +
                self._decompose("cx", [], [c1, c2])
            )

        # Ignore unrecognized commands (like measurements/barriers) for the physics engine
        return []

    def parse_file(self, filepath: str) -> List[Dict[str, Any]]:
        with open(filepath, 'r') as f:
            return self.parse_string(f.read())

    def parse_string(self, qasm_string: str) -> List[Dict[str, Any]]:
        instructions = []
        qasm_string = re.sub(r"//.*", "", qasm_string) # Strip comments
        
        for line in qasm_string.splitlines():
            line = line.strip()
            if not line or line.startswith(("OPENQASM", "include", "creg", "qreg", "measure", "barrier")):
                continue
                
            match = self.GATE_PATTERN.match(line)
            if match:
                gate_name = match.group(1)
                params = self._parse_params(match.group(2))
                qubits = self._parse_qubits(match.group(3))

                # Recursively expand the gate and append to the main instruction list
                instructions.extend(self._decompose(gate_name, params, qubits))

        return instructions


class PhysicalWorkflowEngine:
    """
    Automates the full physical workflow simulation:
    Abstract OpenQASM -> Transpilation -> Calibration -> Scheduling -> Physics Simulation
    """
    def __init__(self, q_eng: QubitEngine, g_eng: GateEngine):
        self.q_eng = q_eng
        self.g_eng = g_eng

    def parse_qasm_circuit(self, qasm_path: str) -> List[Dict[str, Any]]:
        """
        Parses an OpenQASM file and transpiles it to a precise native basis
        using the standalone QASMTranspiler.
        """
        transpiler = QASMTranspiler()
        transpiled = transpiler.parse_file(qasm_path)
        return transpiled

    def automate_calibrations(self, qubit_names: List[str], couplings: List[Dict], transpiled_circuit: List[Dict[str, Any]], **kwargs) -> Dict:
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
            # Physics-informed X calibration
            best_x, _ = self.g_eng.calibrate_gate(q, gate_type="X", parameter="duration", amplitude=0.025)
            # Natively calibrate the H-gate
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

    def compile_schedule(self, qubit_names: List[str], couplings: List[Dict], transpiled_circuit: List[Dict[str, Any]], calibrations: Dict) -> Tuple[List[Dict], float]:
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
                # Physically a tunable-coupler CNOT is compiled as H(target) -> CZ -> H(target).
                # The CZ leg only reaches the |11>-|02> avoided crossing if the target qubit is
                # flux-detuned into resonance for the duration of the coupler pulse - this must
                # mirror the same flux_pulse + Stark-shift-corrected closing pulse that
                # GateEngine.simulate_n_qubit_dynamics uses internally when it calibrates dur_cx
                # (see the CNOT/tunable_coupler auto-compile block), otherwise the calibrated
                # duration corresponds to a gate that is never actually executed here.
                t_h = calibrations["single_qubit"][qubit_names[targ_idx]]["X"] / 2.0
                detuning = self.g_eng._calculate_resonant_flux(qubit_names[ctrl_idx], qubit_names[targ_idx])
                stark_shift_phase = self.g_eng._calculate_stark_shift(detuning, dur_cx)

                schedule.append({"target": targ_idx, "type": "X", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": -np.pi / 2, "start_time": t_start, "end_time": t_start + t_h})
                t1 = t_start + t_h
                schedule.append({"target": (min(ctrl_idx, targ_idx), max(ctrl_idx, targ_idx)), "type": "coupler_pulse", "strength": c_conf["strength"], "start_time": t1, "end_time": t1 + dur_cx})
                schedule.append({"target": targ_idx, "type": "flux_pulse", "detuning": detuning, "start_time": t1, "end_time": t1 + dur_cx})
                t2 = t1 + dur_cx
                schedule.append({"target": targ_idx, "type": "X", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": np.pi / 2 + stark_shift_phase, "start_time": t2, "end_time": t2 + t_h})
                return t2 + t_h
            else:
                schedule.append({"target": ctrl_idx, "type": "X", "amplitude": 0.025, "frequency": w01_list[targ_idx], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur_cx})
                return t_start + dur_cx

        # Parse operations iteratively from our native dictionary list
        for instr in transpiled_circuit:
            op_name = instr["type"].lower()
            target = instr["target"]
            
            # Single Qubit Gates
            if isinstance(target, int):
                q = target
                q_name = qubit_names[q]
                t_start = qubit_times[q]
                
                if op_name == 'x':
                    dur = calibrations["single_qubit"][q_name]["X"]
                    schedule.append({"target": q, "type": "X", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q] += dur
                elif op_name == 'h':
                    dur = calibrations["single_qubit"][q_name]["H"]
                    schedule.append({"target": q, "type": "H", "amplitude": 0.025, "frequency": w01_list[q], "phase": 0.0, "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q] += dur
                elif op_name == 'rz':
                    # Abstract instantaneous frame update
                    pass
                else:
                    print(f"Warning: Single qubit gate {op_name} unsupported in rigorous native basis mapping. Treating it as identity wait.")
                    
            # Two Qubit Gates
            elif isinstance(target, tuple) and len(target) == 2:
                q1, q2 = target
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
                    theta = float(instr.get("theta", np.pi))
                    frac = np.abs(theta) / np.pi
                    base_dur = calibrations["two_qubit"][(q1_name, q2_name)]["CZ"]
                    dur = max(2.0, base_dur * frac) # proportional phase duration scaling 
                    
                    schedule.append({"target": (min(q1, q2), max(q1, q2)), "type": "coupler_pulse", "strength": c_conf["strength"], "start_time": t_start, "end_time": t_start + dur})
                    qubit_times[q1] = qubit_times[q2] = t_start + dur
                    
                elif op_name == 'swap':
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