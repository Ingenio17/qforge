import re
import numpy as np
from typing import List, Dict, Any

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