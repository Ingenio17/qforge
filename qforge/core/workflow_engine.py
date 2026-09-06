"""
workflow_engine.py

Provides the PhysicalWorkflowEngine for translating abstract quantum circuits
into physical microwave schedules on defined qubit topologies.
"""
import re
import numpy as np
import copy
from typing import List, Dict, Tuple, Any, Optional

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine

# Canonical bodies for the OpenQASM 2.0 standard-library gates ("qelib1.inc",
# included by virtually every real QASM 2.0 file) that are not already
# covered by QASMTranspiler's hand-written decompositions below. These are
# reproduced verbatim from the published qelib1.inc, so registering them
# does not introduce any new physical behavior - it only lets more gate
# mnemonics resolve into the same {x, h, rz, cx, cz, swap, cp} basis that
# QForge already simulates.
_QELIB1_EXTRA_GATES = r"""
gate cy a,b { sdg b; cx a,b; s b; }
gate ch a,b {
h b; sdg b;
cx a,b;
h b; t b;
cx a,b;
t b; h b; s b; x b; s a;
}
gate crz(lambda) a,b {
u1(lambda/2) b;
cx a,b;
u1(-lambda/2) b;
cx a,b;
}
gate cu1(lambda) a,b {
u1(lambda/2) a;
cx a,b;
u1(-lambda/2) b;
cx a,b;
u1(lambda/2) b;
}
gate cu3(theta,phi,lambda) c,t {
u1((lambda+phi)/2) c;
u1((lambda-phi)/2) t;
cx c,t;
u3(-theta/2,0,-(phi+lambda)/2) t;
cx c,t;
u3(theta/2,phi,0) t;
}
gate cswap a,b,c { cx c,b; ccx a,b,c; cx c,b; }
"""


class QASMTranspiler:
    """A parser and transpiler that converts OpenQASM 2.0 into a strict basis gate set."""

    # A single qubit reference such as "q[0]" or "anc_1[3]".
    INDEXED_QUBIT_PATTERN = re.compile(r"^([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]$")
    # A `gate name(params) qargs { body }` definition, anywhere in the source
    # (headers/bodies may legally span multiple lines).
    GATE_DEF_PATTERN = re.compile(r"gate\s+([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*([^{;]+)\{([^{}]*)\}")
    OPAQUE_DEF_PATTERN = re.compile(r"opaque\s+[^;]+;")
    # A single statement: NAME(params)? remainder
    STATEMENT_PATTERN = re.compile(r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*(.*)$")
    # "measure <qubit(s)> -> <clbit(s)>" - parsed separately for parse_logical()
    # only, since STATEMENT_PATTERN's "remainder" group can't cleanly hold the
    # "->" target and it is otherwise unused by the physical parse.
    MEASURE_STATEMENT_PATTERN = re.compile(r"^measure\s+(.+?)\s*->\s*(.+)$", re.IGNORECASE)

    # Statements that carry no meaning for a unitary/Hamiltonian simulation
    # (classical registers, mid-circuit measurement, timing barriers, and
    # classically-conditioned execution) are intentionally dropped rather
    # than approximated - see docs/qasm.rst.
    _IGNORED_KEYWORDS = {"openqasm", "include", "creg", "measure", "barrier", "reset", "if"}

    def __init__(self):
        # The strict basis gates allowed in the output
        self.basis_gates = {'x', 'h', 'rz', 'cx', 'cz', 'swap', 'cp'}
        self._reset_parse_state()

    def _reset_parse_state(self):
        """Clears all per-file state: the qubit register map and the custom-gate library."""
        self.qreg_offsets: Dict[str, int] = {}
        self.qreg_sizes: Dict[str, int] = {}
        self._next_qubit_offset = 0
        self.custom_gates: Dict[str, Dict[str, Any]] = {}
        self._warned_gates = set()
        # Preload the standard-library extras unconditionally: harmless if
        # unused, and lets files resolve cy/ch/crz/cu1/cu3/cswap correctly
        # even when their own `include "qelib1.inc";` line isn't present.
        self._register_gate_defs(_QELIB1_EXTRA_GATES)

    @staticmethod
    def _sanitize_identifier(name: str) -> str:
        """Renames identifiers that collide with Python keywords - 'lambda' is
        the standard OpenQASM parameter name for phase angles (u1, crz, cu1,
        cu3) and cannot be evaluated as a bare identifier via `eval`."""
        return "lambda_" if name == "lambda" else name

    def _parse_qubits(self, arg_string: str) -> List[int]:
        """Extracts indexed qubit references from a string like 'q[0], q[1]'.
        Kept for backward compatibility; prefer `_resolve_qubit_args`, which
        also understands multiple registers and whole-register broadcasts."""
        return [int(m.group(2)) for m in re.finditer(r"([A-Za-z_]\w*)\[(\d+)\]", arg_string)]

    def _parse_params(self, param_string: Optional[str], extra_vars: Optional[Dict[str, float]] = None) -> List[float]:
        """Safely evaluates mathematical expressions like 'pi/2' into floats.
        `extra_vars` supplies actual values for a custom gate's formal
        parameters (e.g. {'lambda_': 1.57}) while expanding its body."""
        if not param_string:
            return []

        safe_dict = {
            "pi": np.pi, "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos,
            "tan": np.tan, "exp": np.exp, "ln": np.log,
        }
        if extra_vars:
            safe_dict.update(extra_vars)

        params = []
        for p in param_string.split(","):
            expr = re.sub(r"\blambda\b", "lambda_", p.strip()).replace("^", "**")
            try:
                params.append(float(eval(expr, {"__builtins__": None}, safe_dict)))
            except Exception:
                params.append(0.0)
        return params

    # ------------------------------------------------------------------
    # Quantum register bookkeeping: multiple `qreg` declarations are mapped
    # into one contiguous physical index space, in declaration order, and
    # whole-register gate calls (e.g. "h q;") broadcast across their qubits.
    # ------------------------------------------------------------------

    def _handle_qreg(self, declaration: str):
        match = self.INDEXED_QUBIT_PATTERN.match(declaration.strip())
        if not match:
            return
        name, size = match.group(1), int(match.group(2))
        self.qreg_offsets[name] = self._next_qubit_offset
        self.qreg_sizes[name] = size
        self._next_qubit_offset += size

    def _global_index(self, reg_name: str, local_index: int) -> int:
        if reg_name not in self.qreg_offsets:
            raise ValueError(f"reference to undeclared quantum register '{reg_name}'.")
        if local_index >= self.qreg_sizes[reg_name]:
            raise ValueError(
                f"index {local_index} out of bounds for register '{reg_name}[{self.qreg_sizes[reg_name]}]'."
            )
        return self.qreg_offsets[reg_name] + local_index

    def _resolve_qubit_args(self, arg_string: str) -> List[List[int]]:
        """
        Resolves a gate's qubit-argument list into one or more concrete index
        lists. A bare register name (e.g. the 'q' in 'h q;') broadcasts the
        gate across every qubit of that register, per the OpenQASM 2.0
        register-broadcast rule; mixing broadcast and indexed arguments
        (e.g. 'cx q[0], r;') is also supported.
        """
        tokens = [t.strip() for t in arg_string.split(",") if t.strip()]
        resolved: List[Tuple[str, Any]] = []
        broadcast_len = None

        for tok in tokens:
            indexed = self.INDEXED_QUBIT_PATTERN.match(tok)
            if indexed:
                idx = self._global_index(indexed.group(1), int(indexed.group(2)))
                resolved.append(("single", idx))
                continue

            if tok not in self.qreg_sizes:
                raise ValueError(f"reference to undeclared quantum register '{tok}'.")
            size = self.qreg_sizes[tok]
            if broadcast_len is not None and size != broadcast_len:
                raise ValueError(
                    f"register size mismatch in broadcast gate call: '{tok}' has {size} qubits, expected {broadcast_len}."
                )
            broadcast_len = size
            resolved.append(("broadcast", [self._global_index(tok, i) for i in range(size)]))

        if broadcast_len is None:
            return [[val for _, val in resolved]]
        return [[val if kind == "single" else val[i] for kind, val in resolved] for i in range(broadcast_len)]

    # ------------------------------------------------------------------
    # Gate-definition parsing: both user-defined `gate { ... }` blocks found
    # in the source file and the bundled qelib1.inc extras above go through
    # this same registration/expansion machinery.
    # ------------------------------------------------------------------

    def _register_gate_defs(self, text: str) -> str:
        """Finds every `gate name(params) qargs { body }` block in `text`,
        records it in self.custom_gates, and returns `text` with those
        blocks removed so the remainder can be parsed as plain statements."""

        def _register(match: "re.Match") -> str:
            name = match.group(1).lower()
            param_names = [self._sanitize_identifier(p.strip())
                           for p in (match.group(2) or "").split(",") if p.strip()]
            qarg_names = [q.strip() for q in match.group(3).split(",") if q.strip()]

            body_text = " ".join(match.group(4).split())
            body_stmts = []
            for raw in body_text.split(";"):
                raw = raw.strip()
                if not raw:
                    continue
                sub_match = self.STATEMENT_PATTERN.match(raw)
                if not sub_match:
                    continue
                body_stmts.append((
                    sub_match.group(1).lower(),
                    sub_match.group(2) or "",
                    [q.strip() for q in sub_match.group(3).split(",") if q.strip()],
                ))

            self.custom_gates[name] = {"params": param_names, "qargs": qarg_names, "body": body_stmts}
            return ""

        return self.GATE_DEF_PATTERN.sub(_register, text)

    def _expand_custom_gate(self, gate_name: str, params: List[float], qubits: List[int]) -> List[Dict[str, Any]]:
        definition = self.custom_gates[gate_name]
        formal_params, formal_qargs = definition["params"], definition["qargs"]

        if len(qubits) != len(formal_qargs):
            print(f"Warning: Gate '{gate_name}' expects {len(formal_qargs)} qubit(s) "
                  f"but received {len(qubits)}; skipping.")
            return []

        param_map = dict(zip(formal_params, params))
        qarg_map = dict(zip(formal_qargs, qubits))

        instructions = []
        for sub_name, sub_param_str, sub_qarg_names in definition["body"]:
            sub_params = self._parse_params(sub_param_str, extra_vars=param_map)
            try:
                sub_qubits = [qarg_map[q] for q in sub_qarg_names]
            except KeyError as missing:
                print(f"Warning: Unknown qubit argument {missing} in body of gate '{gate_name}'; skipping sub-instruction.")
                continue
            instructions.extend(self._decompose(sub_name, sub_params, sub_qubits))
        return instructions

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

        # 7. Identity / delay gates carry no physical action
        if gate_name in ("id", "u0"):
            return []

        # 8. Anything defined via a `gate { ... }` block in the source file,
        # or via the bundled qelib1.inc extras registered in __init__.
        if gate_name in self.custom_gates:
            return self._expand_custom_gate(gate_name, params, qubits)

        # Ignore unrecognized commands (unknown gates) for the physics engine, warning once per name.
        if gate_name not in self._warned_gates:
            self._warned_gates.add(gate_name)
            print(f"Warning: Unrecognized gate '{gate_name}' has no known decomposition into the native basis; ignoring.")
        return []

    def parse_file(self, filepath: str) -> List[Dict[str, Any]]:
        with open(filepath, 'r') as f:
            return self.parse_string(f.read())

    @staticmethod
    def _strip_comments(text: str) -> str:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)  # block comments
        text = re.sub(r"//[^\n]*", "", text)                     # line comments
        return text

    def _process_statement(self, statement: str) -> List[Dict[str, Any]]:
        match = self.STATEMENT_PATTERN.match(statement)
        if not match:
            return []

        name, params_str, remainder = match.group(1), match.group(2), match.group(3).strip()
        name_lower = name.lower()

        if name_lower in self._IGNORED_KEYWORDS:
            return []
        if name_lower == "qreg":
            self._handle_qreg(remainder)
            return []
        if not remainder:
            return []

        params = self._parse_params(params_str)
        try:
            qubit_calls = self._resolve_qubit_args(remainder)
        except ValueError as err:
            print(f"Warning: {err} Skipping instruction '{statement}'.")
            return []

        instructions = []
        for qubits in qubit_calls:
            instructions.extend(self._decompose(name_lower, params, qubits))
        return instructions

    def parse_string(self, qasm_string: str) -> List[Dict[str, Any]]:
        """
        Parses an OpenQASM 2.0 source string into the transpiler's native
        instruction list. Handles multiple qregs (mapped to one contiguous
        physical index space), register broadcasts, statements/comments
        spanning multiple lines, several statements per line, and
        user-defined `gate { ... }` blocks in addition to the standard
        qelib1.inc library.
        """
        self._reset_parse_state()

        text = self._strip_comments(qasm_string)
        text = self._register_gate_defs(text)         # consume `gate ... { ... }` blocks
        text = self.OPAQUE_DEF_PATTERN.sub("", text)   # opaque declarations have no body to expand
        text = " ".join(text.split())                  # collapse newlines/indentation for statement splitting

        instructions = []
        for statement in text.split(";"):
            statement = statement.strip()
            if statement:
                instructions.extend(self._process_statement(statement))
        return instructions

    # ------------------------------------------------------------------
    # Display-only parse: gates exactly as written, never decomposed.
    #
    # parse_string()/_decompose() above exist to feed the physical
    # simulator, so they expand every gate down into {x, h, rz, cx, cz,
    # swap, cp} - a Toffoli becomes 15 instructions, not one. That is the
    # right thing to simulate, but the wrong thing to draw: a circuit
    # diagram should show the Toffoli a user actually wrote. parse_logical()
    # reuses the same register/broadcast bookkeeping and expression
    # evaluation as the physical parse, but stops short of _decompose(), so
    # composite gates (ccx, swap, cswap, any custom `gate {...}`) and
    # measurements survive as single logical operations. See
    # qforge.utils.circuit_diagram.draw_circuit for the renderer this feeds.
    # ------------------------------------------------------------------

    def parse_logical_file(self, filepath: str) -> Dict[str, Any]:
        with open(filepath, 'r') as f:
            return self.parse_logical(f.read())

    def parse_logical(self, qasm_string: str) -> Dict[str, Any]:
        """
        Returns {"num_qubits": int, "ops": [...]}, where each op is either
        {"name": <gate name as written>, "qubits": [int, ...], "params":
        [float, ...]} or {"name": "measure", "qubits": [int], "params": []}.
        """
        self._reset_parse_state()

        text = self._strip_comments(qasm_string)
        text = self._register_gate_defs(text)
        text = self.OPAQUE_DEF_PATTERN.sub("", text)
        text = " ".join(text.split())

        ops: List[Dict[str, Any]] = []
        for statement in text.split(";"):
            statement = statement.strip()
            if statement:
                ops.extend(self._process_statement_logical(statement))

        return {"num_qubits": self._next_qubit_offset, "ops": ops}

    def _process_statement_logical(self, statement: str) -> List[Dict[str, Any]]:
        measure_match = self.MEASURE_STATEMENT_PATTERN.match(statement)
        if measure_match:
            try:
                qubit_calls = self._resolve_qubit_args(measure_match.group(1).strip())
            except ValueError as err:
                print(f"Warning: {err} Skipping instruction '{statement}'.")
                return []
            return [{"name": "measure", "qubits": [qs[0]], "params": []} for qs in qubit_calls]

        match = self.STATEMENT_PATTERN.match(statement)
        if not match:
            return []

        name, params_str, remainder = match.group(1), match.group(2), match.group(3).strip()
        name_lower = name.lower()

        if name_lower in self._IGNORED_KEYWORDS:
            return []
        if name_lower == "qreg":
            self._handle_qreg(remainder)
            return []
        if not remainder:
            return []

        params = self._parse_params(params_str)
        try:
            qubit_calls = self._resolve_qubit_args(remainder)
        except ValueError as err:
            print(f"Warning: {err} Skipping instruction '{statement}'.")
            return []

        return [{"name": name_lower, "qubits": qubits, "params": params} for qubits in qubit_calls]


def print_logical_circuit_diagram(qasm_path: str, title: str = "Logical circuit") -> None:
    """
    Parses `qasm_path` purely for display (via QASMTranspiler.parse_logical,
    never the physical decomposition path) and prints an ASCII diagram of
    it. Defensive by design: a malformed or unusual QASM file should never
    be able to break an otherwise-working simulation just because its
    diagram couldn't be drawn, so any failure here is reported and
    swallowed rather than raised.
    """
    try:
        transpiler = QASMTranspiler()
        logical = transpiler.parse_logical_file(qasm_path)
        n_measure = sum(1 for op in logical["ops"] if op["name"] == "measure")
        n_gates = len(logical["ops"]) - n_measure
        summary = f"{title}: {logical['num_qubits']} qubit(s), {n_gates} gate(s)"
        if n_measure:
            summary += f", {n_measure} measurement(s)"
        print(summary)
        from qforge.utils.circuit_diagram import draw_circuit
        print(draw_circuit(logical["num_qubits"], logical["ops"]))
    except Exception as e:
        print(f"(Could not render circuit diagram: {e})")


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
        
        TODO: Future introduction of user customization of calibration bounds via ``**kwargs``
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

        print_logical_circuit_diagram(qasm_path)

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