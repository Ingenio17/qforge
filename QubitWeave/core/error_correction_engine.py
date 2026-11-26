"""
error_correction_engine.py

Provides the ErrorCorrectionEngine with active mid-circuit measurement,
real-time feed-forward correction, and dynamic physical qubit allocation
for stabilizer error-correcting codes.

The engine is written generically in terms of a `StabilizerCode`
specification (see stabilizer_codes.py): stabilizer generators, a
syndrome -> correction lookup table, and transversal logical-operator
support. The engine itself never hard-codes a specific code's generator
count, qubit count, or syndrome table -- it reads all of that from the
`StabilizerCode` it is given. This means a new CSS stabilizer code can be
added by writing a new `StabilizerCode` instance in stabilizer_codes.py; no
changes to this file are required, as long as the new code's generators are
CSS-type (pure X or pure Z, never mixed on one generator).

Two codes are implemented today:
  - the 3-qubit bit-flip repetition code (`stabilizer_codes.REPETITION_3`),
    run by `execute_3q_repetition_workflow()` for backward compatibility.
    Its physical behaviour -- encoding, transversal gates, syndrome
    extraction, feed-forward correction, and decoding -- is numerically
    unchanged from the original hard-coded implementation.
  - the 9-qubit Shor code (`stabilizer_codes.SHOR_9`), run by
    `execute_shor9_workflow()`.
Both are just call sites for the generic `execute_stabilizer_workflow()`.

Architecture
------------
Each *logical* qubit L is encoded into `code.num_data + code.num_ancilla`
*physical* qubits. For the default 3-qubit repetition code that is 5 qubits:
    D0 = L_D0   (data)
    D1 = L_D1   (data)
    D2 = L_D2   (data)
    A0 = L_A0   (ancilla – parity check D0⊕D1)
    A1 = L_A1   (ancilla – parity check D1⊕D2)
For the 9-qubit Shor code that is 17 qubits (9 data + 8 ancilla) -- see
stabilizer_codes.py for the block structure and generator layout.

Physical qubits in each block are clones of the original logical qubit
(same scqubits type and parameters), matching the "same name → same type"
convention used throughout QubitWeave.

Scalability note: gates, syndrome extraction, and encoding are all
simulated on small per-generator/per-qubit(-pair) subsystems (see below),
so no single dense operator ever spans a whole code block. The overall
STATE VECTOR, however, always spans every physical qubit in the workflow at
once (this engine has no other state representation), so its size is
2**(total physical qubits) regardless of how gates are simulated. One Shor-
encoded logical qubit (17 physical qubits, 2**17 states) is small; several
Shor-encoded logical qubits in the same workflow (34+ physical qubits) can
exceed available memory when built as a dense state vector -- this is a
pre-existing limit of the engine's dense global-state-vector
representation (the repetition code hits the same wall, just at a much
higher logical-qubit count thanks to its 5-qubit-per-block footprint), not
specific to the stabilizer-formalism machinery itself.

Workflow per execute_stabilizer_workflow() call
------------------------------------------------
1. Parse the logical QASM circuit (QASMTranspiler → list of dicts).
2. Register all physical qubits in QubitEngine (clone of the logical qubit).
3. Build the full physical coupling list from the code's stabilizer
   generators (capacitive, used for syndrome-extraction CNOT drives).
4. Calibrate single-qubit X and two-qubit CNOT pulse durations once.
5. Initialize the physical register to |00...0> and then run
   `code.encoding_circuit` against each logical block's data qubits to
   prepare the actual codeword |0>_L. This is not a no-op in general (only
   for the repetition code, whose |0>_L already equals |000>) -- see
   `_encode_logical_zero`.
6. For every logical instruction, apply a *transversal* physical drive
   schedule built from the code's declared logical-operator support
   (`code.logical_x_qubits`/`code.logical_x_pauli` for X; every data qubit
   for H; corresponding data-qubit pairs across two logical blocks for
   CX/CZ), simulating one qubit (or qubit pair) at a time so the simulated
   Hilbert space never has to span an entire large code block at once.
7. Run a syndrome extraction + measurement + correction cycle, GENERATOR BY
   GENERATOR (never as one combined operation across the whole block):
      - For each generator, simulate ONLY its own participating data
        qubits + its own ancilla as a small subsystem:
          * Z-type: CNOT(data -> ancilla) per data qubit.
          * X-type: H(ancilla), CNOT(ancilla -> data) per data qubit,
            H(ancilla) -- so a direct Z-basis ancilla readout yields the
            stabilizer eigenvalue either way.
      - Measure that ONE ancilla, collapse the wavefunction, record its bit.
      Because a valid code's generators always mutually commute, measuring
      them one at a time gives EXACTLY the same joint outcome distribution
      and post-measurement state as measuring them all jointly -- this
      generator-by-generator processing is required to keep every
      simulated subsystem's dimension bounded by the code's largest
      generator weight (up to 7 qubits for Shor) rather than its total
      qubit count (17 for Shor), which the dense-matrix simulation backend
      cannot handle directly.
      Once every generator has been measured, look up the full syndrome in
      `code.syndrome_to_correction` (a LIST of corrections -- more than one
      can apply simultaneously, e.g. an X and a Z correction together for
      Shor) and apply each feed-forward Pauli correction, then reset every
      ancilla found in |1⟩ back to |0⟩ via X.
8. Decode the final physical state via a joint projective measurement in
   the logical-Z basis, built from `code.logical_z_qubits`/
   `code.logical_z_pauli` (see `_decode_logical_state` for why this is
   required in general rather than a simpler population/majority-vote
   reading, and why it is nonetheless numerically identical to the old
   majority-vote decode for the repetition code).

Syndrome table (default: 3-qubit repetition code)
--------------------------------------------------
A0 detects D0⊕D1;  A1 detects D1⊕D2.
    (A0=0, A1=0) → no error
    (A0=1, A1=0) → error on D0  → correct with X on D0
    (A0=1, A1=1) → error on D1  → correct with X on D1
    (A0=0, A1=1) → error on D2  → correct with X on D2

See stabilizer_codes.py for the 9-qubit Shor code's syndrome table and the
derivation of its (non-obvious) logical X/Z operators.
"""

import itertools
import numpy as np
import qutip as qt
from scipy.linalg import expm as scipy_expm
from typing import List, Dict, Tuple, Any, Optional

from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.register_ops import (
    apply_cx,
    apply_cz,
    apply_hadamard,
    apply_matrix,
    apply_pauli,
    apply_rz,
)
from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine, QASMTranspiler, print_logical_circuit_diagram
from QubitWeave.core.stabilizer_codes import (
    StabilizerCode,
    StabilizerGenerator,
    EncodingStep,
    REPETITION_3,
    SHOR_9,
    STEANE_7,
    SURFACE_9,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tensor_op_at(op: qt.Qobj, idx: int, dims: List[int]) -> qt.Qobj:
    """
    Embed a single-site operator `op` at position `idx` in an N-site
    tensor product space with local dimensions `dims`.
    All other sites get identity operators of the correct local dimension.
    """
    ops = [qt.qeye(d) for d in dims]
    ops[idx] = op
    return qt.tensor(ops)


def _sigmax_dim(d: int) -> qt.Qobj:
    """
    Pauli-X on the computational subspace of a d-dimensional system.

    Leakage levels are left untouched.  The previous implementation filled
    the rest of the matrix with zeroes, which made a correction non-unitary
    and silently discarded population in |2>, |3>, ... .  A logical recovery
    operation must never make leakage disappear.
    """
    if d < 2:
        raise ValueError("A computational qubit needs at least two levels.")

    mat = np.eye(d, dtype=complex)
    mat[0, 1] = 1.0
    mat[1, 0] = 1.0
    mat[0, 0] = 0.0
    mat[1, 1] = 0.0
    return qt.Qobj(mat)


def _sigmaz_dim(d: int) -> qt.Qobj:
    """
    Pauli-Z on the computational subspace of a d-dimensional system.

    Leakage levels (|2>, |3>, ...) are left untouched, mirroring the
    leakage-preserving convention used by `_sigmax_dim`. Not needed by the
    3-qubit repetition code (a bit-flip code only ever needs X corrections),
    but required for phase-flip corrections in future CSS codes such as
    Steane/Shor.
    """
    if d < 2:
        raise ValueError("A computational qubit needs at least two levels.")

    mat = np.eye(d, dtype=complex)
    mat[1, 1] = -1.0
    return qt.Qobj(mat)


def _pauli_dim(pauli_type: str, d: int) -> qt.Qobj:
    """Leakage-preserving Pauli correction operator, dispatched by type."""
    if pauli_type == "X":
        return _sigmax_dim(d)
    if pauli_type == "Z":
        return _sigmaz_dim(d)
    raise ValueError(f"Unsupported correction Pauli type: {pauli_type!r}")


def _proj0_dim(d: int) -> qt.Qobj:
    """Projector onto |0> in a d-dimensional local space."""
    mat = np.zeros((d, d), dtype=complex)
    mat[0, 0] = 1.0
    return qt.Qobj(mat)


def _proj1_dim(d: int) -> qt.Qobj:
    """Projector onto |1> in a d-dimensional local space."""
    mat = np.zeros((d, d), dtype=complex)
    mat[1, 1] = 1.0
    return qt.Qobj(mat)


def _build_ideal_cz_operator(dims: List[int], idx_a: int, idx_b: int) -> qt.Qobj:
    """
    Ideal CZ unitary acting on a pair of qubits in an N-qubit register:
    applies a -1 phase to the |1>|1> computational amplitude and leaves
    every other computational and leakage amplitude untouched (diagonal,
    unitary, leakage-preserving — mirrors GateEngine._build_ideal_cx_operator).

    Every qubit outside {idx_a, idx_b} is iterated over its full local
    dimension (not restricted to {0,1}): a spectator qubit sitting in a
    leakage level must not block the CZ phase from being applied to
    idx_a/idx_b, and must not itself be touched by this gate.
    """
    import itertools

    total_dim = int(np.prod(dims))
    U = np.eye(total_dim, dtype=complex)

    full_dim_ranges = [range(d) for d in dims]

    for levels in itertools.product(*full_dim_ranges):
        if levels[idx_a] == 1 and levels[idx_b] == 1:
            idx = np.ravel_multi_index(levels, dims)
            U[idx, idx] = -1.0

    op = qt.Qobj(U)
    op.dims = [list(dims), list(dims)]
    return op


# Drives that are ideal gates rather than simulated pulses.
_IDEAL_DRIVES = frozenset({"ICX", "ICZ", "X", "H", "Z", "RZ"})


def _as_array(state: qt.Qobj, dims: List[int]) -> np.ndarray:
    """A ket as a fresh array with one axis per qubit, safe to modify in place."""
    return np.array(state.full().reshape(dims), dtype=complex)


def _as_ket(array: np.ndarray, dims: List[int]) -> qt.Qobj:
    """The inverse of `_as_array`."""
    ket = qt.Qobj(np.ascontiguousarray(array).reshape(-1, 1), copy=False)
    ket.dims = [list(dims), [1] * len(dims)]
    return ket


def _apply_pauli_to_ket(state: qt.Qobj, pauli: str, idx: int, dims: List[int]) -> qt.Qobj:
    """A leakage-preserving Pauli on one qubit of a register ket."""
    if state.type != "ket":
        op = _tensor_op_at(_pauli_dim(pauli, dims[idx]), idx, dims)
        return op * state * op.dag()
    array = _as_array(state, dims)
    apply_pauli(array, idx, pauli)
    return _as_ket(array, dims)


def _drive_target(drive: Dict[str, Any]) -> int:
    target = drive.get("target")
    return int(target[0]) if isinstance(target, (tuple, list)) else int(target)


def _apply_ideal_drives(array: np.ndarray, drives: List[Dict], axes: List[int]) -> None:
    """
    Run ideal gates on a register array in place, in schedule order.

    Drives use local indices; `axes` maps them to the register. Order matters: an
    X-type syndrome is H(ancilla), CNOTs, H(ancilla), and grouping gates by type would
    cancel the two Hadamards and leave phase errors undetected.
    """
    for drive in drives:
        kind = drive["type"]
        if kind == "ICX":
            apply_cx(array, axes[int(drive["control"])], axes[int(drive["target"])])
        elif kind == "ICZ":
            apply_cz(array, axes[int(drive["control"])], axes[int(drive["target"])])
        elif kind == "H":
            apply_hadamard(array, axes[_drive_target(drive)])
        elif kind == "RZ":
            apply_rz(
                array,
                axes[_drive_target(drive)],
                float(drive["theta"]),
                drive.get("pauli_type", "Z"),
            )
        else:
            apply_pauli(array, axes[_drive_target(drive)], kind)


def _encoding_drives(code: StabilizerCode) -> List[Dict]:
    """A code's encoding circuit as ideal drives on local data-qubit indices."""
    return [
        {"type": "H", "target": step.target}
        if step.gate == "H"
        else {"type": "ICX", "control": step.control, "target": step.target}
        for step in code.encoding_circuit
    ]


def _logical_parities(
    state: qt.Qobj, dims: List[int], groups: List[List[int]], pauli: str
) -> np.ndarray:
    """
    Joint distribution of several Pauli-string measurements on a register ket.

    Returns an array with one binary axis per group: index 0 is the +1 outcome of that
    group's string. X strings are turned into Z strings by Hadamards, after which each
    outcome is the parity of the group's bits, so only probabilities are ever stored.
    Leakage levels count as +1, matching `_pauli_dim`.
    """
    array = _as_array(state, dims)
    if pauli == "X":
        for axis in (a for group in groups for a in group):
            apply_hadamard(array, axis)
    probabilities = np.abs(array) ** 2
    del array

    used = [a for group in groups for a in group]
    spectators = tuple(a for a in range(len(dims)) if a not in used)
    probabilities = probabilities.sum(axis=spectators)
    order = sorted(used)
    probabilities = np.transpose(probabilities, [order.index(a) for a in used])

    # Fold each group's axes into one parity axis, rotating finished axes to the back.
    for group in groups:
        for position in range(len(group)):
            odd = probabilities[1]
            even = probabilities[0] + probabilities[2:].sum(axis=0)
            if position == 0:
                parity = np.stack([even, odd], axis=-1)
            else:
                parity = np.stack(
                    [even[..., 0] + odd[..., 1], even[..., 1] + odd[..., 0]], axis=-1
                )
            probabilities = parity
    return probabilities


# A workflow is worth warning about once its state vector alone reaches this many bytes.
LARGE_STATE_BYTES = 2**30


def estimate_state_size(
    code: StabilizerCode, num_logical: int, truncated_dim: int = 2
) -> Tuple[int, int]:
    """
    Size of the state vector an encoded workflow holds: (amplitudes, bytes).

    Only the repetition code keeps its ancillas, and leakage levels, for the whole run.
    Every other code runs on computational levels and drops each ancilla as soon as it
    is measured, so at most one is ever present whatever the number of syndrome rounds.

    Args:
        truncated_dim: Levels kept per data qubit. Matters for the repetition code only.
    """
    if code is REPETITION_3:
        block = truncated_dim**code.num_data * 2**code.num_ancilla
        amplitudes = block**num_logical
    else:
        amplitudes = 2 ** (code.num_data * num_logical + 1)
    return amplitudes, amplitudes * np.dtype(complex).itemsize


class _LazyDurations(dict):
    """
    Pulse durations calibrated the first time one is asked for.

    Every gate an encoded circuit plays today is an ideal logical operation, so the
    durations go unused and a calibration sweep up front (minutes, for a fluxonium) buys
    nothing. A physical gate path that needs one gets it calibrated here.
    """

    def __init__(self, calibrate):
        super().__init__()
        self._calibrate = calibrate

    def __missing__(self, name: str) -> float:
        self[name] = self._calibrate(name)
        return self[name]


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class ErrorCorrectionEngine:
    """
    Stabilizer error-correction engine with active, mid-circuit error
    correction, generic over any CSS `StabilizerCode` (see
    stabilizer_codes.py). Defaults to the 3-qubit repetition code.

    Physical qubits for each logical qubit are created as clones of the
    original logical qubit (same type + parameters), ensuring they are
    properly registered in QubitEngine before any simulation begins.
    """

    def __init__(self, qubit_engine: QubitEngine, gate_engine: GateEngine):
        self.qubit_engine   = qubit_engine
        self.gate_engine    = gate_engine
        self.workflow_engine = PhysicalWorkflowEngine(qubit_engine, gate_engine)
        self._last_syndromes: Dict[str, Tuple[int, ...]] = {}

    # ------------------------------------------------------------------
    # 1. Mapping helpers
    # ------------------------------------------------------------------

    def generate_stabilizer_mapping(
        self,
        logical_names: List[str],
        code: StabilizerCode,
    ) -> Dict[str, Dict[str, List[str]]]:
        """
        Return a mapping dict::

            { logical_name: {"data": [D0..D(n-1)], "ancilla": [A0..A(m-1)]} }

        where n = code.num_data and m = code.num_ancilla.
        """
        mapping = {}
        for l_name in logical_names:
            mapping[l_name] = {
                "data":    [f"{l_name}_D{i}" for i in range(code.num_data)],
                "ancilla": [f"{l_name}_A{j}" for j in range(code.num_ancilla)],
            }
        return mapping

    def generate_3q_repetition_mapping(
        self,
        logical_names: List[str],
    ) -> Dict[str, Dict[str, List[str]]]:
        """
        Backward-compatible alias: mapping for the 3-qubit repetition code.

        Return a mapping dict::

            { logical_name: {"data": [D0, D1, D2], "ancilla": [A0, A1]} }
        """
        return self.generate_stabilizer_mapping(logical_names, REPETITION_3)

    def _get_flat_physical_names(
        self,
        logical_names: List[str],
        mapping: Dict,
    ) -> List[str]:
        """
        Ordered flat list: for each logical qubit, data qubits first, then
        ancillas.  This ordering is what simulate_n_qubit_dynamics sees.
        """
        names = []
        for l_name in logical_names:
            names.extend(mapping[l_name]["data"])
            names.extend(mapping[l_name]["ancilla"])
        return names

    # ------------------------------------------------------------------
    # 2. Physical qubit registration
    # ------------------------------------------------------------------


    def _build_physical_couplings(
        self,
        logical_names,
        mapping,
        code: StabilizerCode,
        physical_names,
        physical_index,
        coupling_type,
        coupling_strength,
    )-> List[Dict[str, Any]]:
        """
        Build capacitive couplings needed for syndrome extraction CNOTs.

        Derived generically from `code.generators`: every (data_qubit,
        ancilla) pair that appears together in a stabilizer generator needs
        a coupling. For the default 3-qubit repetition code this reproduces
        exactly:
            D0 — A0   (parity D0 ⊕ D1, first CNOT)
            D1 — A0   (parity D0 ⊕ D1, second CNOT)
            D1 — A1   (parity D1 ⊕ D2, first CNOT)
            D2 — A1   (parity D1 ⊕ D2, second CNOT)

        Note: a data qubit may couple to *multiple* ancillas (e.g. D1 above)
        which is fine — we sequence the CNOTs in time so only one coupling
        is active per step.
        """
        couplings = []
        seen = set()

        def _add(qa, qb):
            ia = physical_index[qa]
            ib = physical_index[qb]
            key = (min(ia, ib), max(ia, ib))
            if key not in seen:
                seen.add(key)
                couplings.append({
                    "q1":      min(ia, ib),
                    "q2":      max(ia, ib),
                    "type":    coupling_type,
                    "strength": coupling_strength,
                })

        for l_name in logical_names:
            d = mapping[l_name]["data"]
            a = mapping[l_name]["ancilla"]
            for gen in code.generators:
                anc_name = a[gen.ancilla]
                for dq in gen.data_qubits:
                    _add(d[dq], anc_name)

        return couplings

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 4. Calibration (run once, cached by GateEngine)
    # ------------------------------------------------------------------

    def _calibrate(
        self,
        logical_names: List[str],
        mapping: Dict,
        physical_names: List[str],
        syndrome_couplings: List[Dict],
        coupling_type: str,
        coupling_strength: float,
        calibrate_cnot: bool = False,
    ) -> Dict:
        """
        X durations, exploiting the fact that every physical qubit
        in a logical block is a perfect clone of its parent.

        Strategy
        --------
        Single-qubit X
            Calibrated on demand, once per unique (qubit_type, params)
            fingerprint: see `_LazyDurations`.

        CNOT syndrome pairs
            Retained for callers that explicitly request calibration.  Normal
            EC execution uses ideal logical CX instructions for syndrome
            extraction and therefore does not need a physical CNOT duration.
        """
        calibrations: Dict[str, Any] = {"x_dur": {}, "x_amp": {}, "cnot_dur": {}}
        x_results: Dict[tuple, float] = {}

        def calibrate_x(p_name: str) -> float:
            q_data = self.qubit_engine._qubits[p_name]
            fp = (q_data["type"], tuple(sorted(q_data["params"].items())))
            if fp not in x_results:
                print(f"[EC]   Calibrating X for type '{q_data['type']}' "
                      f"(representative: {p_name})...")
                x_results[fp], _ = self.gate_engine.calibrate_gate(
                    p_name, gate_type="X", parameter="duration", amplitude=0.025
                )
            return x_results[fp]

        calibrations["x_dur"] = _LazyDurations(calibrate_x)
        # Amplitude of the X pi pulse. H uses half of it for the same duration.
        calibrations["x_amp"] = {
            p_name: 0.025
            for l_name in logical_names
            for p_name in mapping[l_name]["data"] + mapping[l_name]["ancilla"]
        }

        if not calibrate_cnot:
            return calibrations

        # ── CNOT syndrome-pair calibration ─────────────────────────── #
        print("[EC] Calibrating CNOT syndrome links "
              "(one calibration per unique coupling fingerprint)...")

        # fingerprint -> (best_dur, best_metric)
        cnot_results: Dict[tuple, Tuple[float, float]] = {}

        for coup in syndrome_couplings:
            q1n = physical_names[coup["q1"]]
            q2n = physical_names[coup["q2"]]

            key_fwd = (q1n, q2n)
            key_rev = (q2n, q1n)

            if key_fwd in calibrations["cnot_dur"]:
                continue   # already done (symmetric duplicate)

            qd1 = self.qubit_engine._qubits[q1n]
            qd2 = self.qubit_engine._qubits[q2n]
            fp  = (
                qd1["type"], tuple(sorted(qd1["params"].items())),
                qd2["type"], tuple(sorted(qd2["params"].items())),
                coupling_type, float(coupling_strength),
            )

            if fp not in cnot_results:
                # First pair of this fingerprint — run the calibration sweep
                print(f"[EC]   Calibrating CNOT '{coupling_type}' "
                      f"(representative: {q1n}-{q2n})...")
                dur, metric = self.gate_engine.calibrate_gate(
                    q1n, q2n,
                    gate_type="CNOT",
                    coupling_type=coupling_type,
                    coupling_strength=coupling_strength,
                    parameter="duration",
                )
                cnot_results[fp] = (dur, metric)
            else:
                # Clone pair — reuse the representative result directly.
                dur, metric = cnot_results[fp]
                print(f"[EC]   {q1n}-{q2n}: clone → calibration reused "
                      f"(dur={dur:.4f}, metric={metric:.4f})")

            calibrations["cnot_dur"][key_fwd] = dur
            calibrations["cnot_dur"][key_rev] = dur

        return calibrations

    # ------------------------------------------------------------------
    # 2b. Alias injection — keep physical qubits alive across load_session
    # ------------------------------------------------------------------

    def _register_physical_qubits(
        self,
        logical_names: List[str],
        mapping: Dict,
    ) -> None:
        """
        Register all physical qubit clones into QubitEngine using create_qubit().

        Each logical qubit L is expanded to
        (code.num_data + code.num_ancilla) physical qubits, e.g. for the
        default 3-qubit repetition code:
            L_D0, L_D1, L_D2  — data qubits (same type/params as L)
            L_A0, L_A1        — ancilla qubits (truncated_dim=2, otherwise same)

        create_qubit() saves to the session JSON, so the qubits survive every
        load_session() call made internally by GateEngine.  They are cleaned up
        at the end of the workflow by _cleanup_physical_qubits().

        Qubits that already exist (e.g. on a re-run) are skipped safely.
        """
        existing = set(self.qubit_engine._qubits.keys())
        total_registered = 0

        # One session write for the whole block rather than one per qubit.
        with self.qubit_engine.deferred_save():
            for l_name in logical_names:
                # Find the source logical qubit record
                src = self.qubit_engine._qubits.get(l_name)
                if src is None:
                    raise ValueError(
                        f"Logical qubit '{l_name}' not registered in QubitEngine. "
                        f"Create it first with qubit_engine.create_qubit(...)."
                    )

                q_type   = src["type"]
                q_params = src["params"].copy()
                anc_params = {**q_params, "truncated_dim": 2}
                anc_set = set(mapping[l_name]["ancilla"])

                for p_name in mapping[l_name]["data"] + mapping[l_name]["ancilla"]:
                    total_registered += 1
                    if p_name in existing:
                        continue
                    params = anc_params if p_name in anc_set else q_params
                    self.qubit_engine.create_qubit(q_type, p_name, params)
                    existing.add(p_name)

        print(
            f"[EC] Physical qubits registered: "
            f"{total_registered} qubits for "
            f"{len(logical_names)} logical qubit(s)."
        )

    def _cleanup_physical_qubits(
        self,
        logical_names: List[str],
        mapping: Dict,
    ) -> None:
        """
        Delete all physical qubit clones (data + ancilla) from QubitEngine
        at the end of a workflow run.

        This is the ONLY place physical qubits are deleted.  It runs exactly
        once, inside the finally-block of execute_stabilizer_workflow()
        (which execute_3q_repetition_workflow() delegates to), so it always
        fires even if the workflow crashes mid-run.

        delete_qubit() removes from _qubits AND from the session JSON, so the
        qubit list is clean for the next normal operation.
        """
        with self.qubit_engine.deferred_save():
            for l_name in logical_names:
                for p_name in mapping[l_name]["data"] + mapping[l_name]["ancilla"]:
                    try:
                        self.qubit_engine.delete_qubit(p_name)
                    except Exception:
                        pass   # already gone — that's fine


    # ------------------------------------------------------------------
    # 2c. Fast unitary helpers
    # ------------------------------------------------------------------

    def _build_H0_rad(self, qubit_name: str) -> qt.Qobj:
        """Return bare qubit H0 in rad/ns (diagonal Qobj in energy eigenbasis)."""
        # _get_qubit_hamiltonian returns H in GHz; convert to rad/ns (*2π)
        H0, _ = self.gate_engine._get_qubit_hamiltonian(qubit_name)
        return H0 * (2 * np.pi)

    def _apply_unitary_to_subsystem(
        self,
        U_sub: qt.Qobj,
        sub_global_idxs: List[int],
        full_state: qt.Qobj,
        full_dims: List[int],
    ) -> qt.Qobj:
        """
        Embed a unitary U_sub acting on `sub_global_idxs` into the full
        Hilbert space and apply it to full_state WITHOUT partial trace.
        All entanglement across the full register is preserved.

        U_sub.dims must be [[d0,...],[d0,...]] for the subsystem qubits.
        """
        dims = list(full_dims)
        matrix = U_sub.full()

        if full_state.type == "ket":
            array = full_state.full().reshape(dims)
            return _as_ket(apply_matrix(array, matrix, sub_global_idxs), dims)

        rho = full_state.full().reshape(dims + dims)
        rho = apply_matrix(rho, matrix, sub_global_idxs)
        columns = [len(dims) + i for i in sub_global_idxs]
        rho = apply_matrix(rho, matrix.conj(), columns)
        total = int(np.prod(dims))
        new_state = qt.Qobj(np.ascontiguousarray(rho).reshape(total, total), copy=False)
        new_state.dims = [dims, list(dims)]
        return new_state

    # ------------------------------------------------------------------
    # 5. Subsystem simulation helper
    # ------------------------------------------------------------------

    def _simulate_subsystem(
        self,
        sub_names: List[str],
        sub_drives: List[Dict],
        duration: float,
        sub_couplings: List[Dict],
        full_state: qt.Qobj,
        full_names: List[str],
        full_dims: List[int],
        gate_label: str,
    ) -> qt.Qobj:
        """
        Apply a gate on a SUBSET of the full register via a fast unitary
        path (matrix exponential of the time-averaged Hamiltonian) and embed
        the result back with _apply_unitary_to_subsystem, which preserves
        all inter-qubit entanglement across the full register.

        This replaces the old mesolve path, which was ~1000× slower because:
          - mesolve stores every intermediate time-step state in memory
          - steps = max(200, int(duration*50)) = 2000+ per gate
          - QuTiP's ODE integrator resolves GHz-frequency carriers unnecessarily
            when all we need is the net rotation angle (the unitary)

        For ECE syndrome extraction and logical gates, the drives are
        resonant microwave pulses. In the rotating frame the effective
        Hamiltonian is time-INDEPENDENT (after RWA), so the unitary is
        simply U = exp(-i H_eff T). We build H_eff analytically from the
        qubit eigenvalues and drive amplitudes, then exponentiate once.

        sub_drives must use LOCAL indices (0..len(sub_names)-1).
        """
        sub_global_idxs = [full_names.index(n) for n in sub_names]
        sub_dims        = [full_dims[i] for i in sub_global_idxs]
        N_sub           = len(sub_names)

        # Ideal gates act on the state directly: no operator is ever built.
        if full_state.type == "ket" and all(d.get("type") in _IDEAL_DRIVES for d in sub_drives):
            array = _as_array(full_state, full_dims)
            _apply_ideal_drives(array, sub_drives, sub_global_idxs)
            return _as_ket(array, full_dims)

        # Ideal operations in schedule order (see _apply_ideal_drives).
        ideal_ops: List[qt.Qobj] = []
        has_only_ideal = True
        x_drives = []  # (local_idx, amplitude, phase) for microwave drives

        for drv in sub_drives:
            drv_type = drv.get("type", "")

            if drv_type == "ICX":
                ideal_ops.append(
                    self.gate_engine._build_ideal_cx_operator(
                        sub_dims, int(drv["control"]), int(drv["target"])
                    )
                )
            elif drv_type == "ICZ":
                ideal_ops.append(
                    _build_ideal_cz_operator(sub_dims, int(drv["control"]), int(drv["target"]))
                )
            elif drv_type in ("X", "H", "Z"):
                target_val = drv.get("target")
                if isinstance(target_val, (tuple, list)):
                    target_idx = int(target_val[0])
                else:
                    target_idx = int(target_val)
                ideal_ops.append(
                    self.gate_engine._build_ideal_single_qubit_operator(
                        sub_dims, target_idx, drv_type
                    )
                )
            elif drv_type == "RZ":
                target_val = drv.get("target")
                if isinstance(target_val, (tuple, list)):
                    target_idx = int(target_val[0])
                else:
                    target_idx = int(target_val)
                ideal_ops.append(
                    self.gate_engine._build_ideal_rz_operator(
                        sub_dims, target_idx, float(drv["theta"]), drv.get("pauli_type", "Z")
                    )
                )
            elif drv_type in ("microwave",):
                has_only_ideal = False
                x_drives.append(
                    (
                        int(drv["target"])
                        if not isinstance(drv["target"], (tuple, list))
                        else drv["target"][0],
                        float(drv.get("amplitude", 0.025)),
                        float(drv.get("phase", 0.0)),
                    )
                )
            else:
                has_only_ideal = False

        #
        # Fast path:
        # if the subsystem only contains ideal gates, skip Hamiltonian construction.
        #
        if has_only_ideal:
            U_sub = qt.qeye(int(np.prod(sub_dims)))
            U_sub.dims = [list(sub_dims), list(sub_dims)]

            for U_step in ideal_ops:
                U_sub = U_step * U_sub

            return self._apply_unitary_to_subsystem(
                U_sub,
                sub_global_idxs,
                full_state,
                full_dims,
            )

        # ── Build H_eff in the rotating frame (RWA, time-independent) ─────
        # Start with the static qubit Hamiltonian sum (dressed eigenvalues)
        H_eff = qt.Qobj(
            np.zeros((int(np.prod(sub_dims)), int(np.prod(sub_dims))), dtype=complex)
        )
        H_eff.dims = [list(sub_dims), list(sub_dims)]

        # 1. Bare qubit terms (diagonal in the computational basis)
        for local_i, q_name in enumerate(sub_names):
            H0_full, _ = self.gate_engine._get_qubit_hamiltonian(q_name)
            # H0_full is in GHz; embed at local position, convert to rad/ns
            H0_q = qt.Qobj(np.diag(np.real(H0_full.diag())))
            H0_q.dims = [[sub_dims[local_i]], [sub_dims[local_i]]]
            ops = [qt.qeye(sub_dims[j]) for j in range(N_sub)]
            ops[local_i] = H0_q
            H_eff = H_eff + (2 * np.pi) * qt.tensor(ops)

        # 2. Static coupling terms  g*(a†b + ab†)
        for coup in sub_couplings:
            ia, ib = coup["q1"], coup["q2"]
            g      = float(coup.get("strength", 0.010)) * 2 * np.pi  # rad/ns
            da, db = sub_dims[ia], sub_dims[ib]

            # Lowering operators in the local d-dim space
            a_op = qt.destroy(da)
            b_op = qt.destroy(db)

            ops_ab = [qt.qeye(sub_dims[j]) for j in range(N_sub)]
            ops_ba = [qt.qeye(sub_dims[j]) for j in range(N_sub)]

            a_op_full = [qt.qeye(sub_dims[j]) for j in range(N_sub)]
            b_op_full = [qt.qeye(sub_dims[j]) for j in range(N_sub)]
            a_op_full[ia] = a_op
            b_op_full[ib] = b_op

            A = qt.tensor(a_op_full)
            B = qt.tensor(b_op_full)
            H_eff = H_eff + g * (A.dag() * B + A * B.dag())

        # 3. Drive terms: in the rotating frame the carrier oscillation
        #    cancels, leaving a static Rabi term Omega/2 * sigma_x (or
        #    rotated by phase).  For a coupler_pulse we treat it as a
        #    time-averaged ISWAP-like transmon coupling that applies a
        #    controlled phase (CZ), which we model as the CZ unitary directly.


        # Add rotating-frame microwave drives  Omega/2 * (e^{i*phi}|0><1| + h.c.)
        for (local_i, amp, phase) in x_drives:
            d = sub_dims[local_i]
            # Pi-pulse condition: amp * duration = pi  =>  Omega = pi/duration
            # We use amplitude as the Rabi frequency in GHz (units match calibration)
            Omega = amp * 2 * np.pi  # rad/ns
            # sigma_x-like 0<->1 operator
            sx = np.zeros((d, d), dtype=complex)
            sx[0, 1] = np.exp(-1j * phase)
            sx[1, 0] = np.exp( 1j * phase)
            sx_q = qt.Qobj(sx)
            sx_q.dims = [[d], [d]]
            ops_drv = [qt.qeye(sub_dims[j]) for j in range(N_sub)]
            ops_drv[local_i] = sx_q
            H_eff = H_eff + (Omega / 2.0) * qt.tensor(ops_drv)

        # ── Compute unitary  U = exp(-i H_eff * duration) ─────────────────
        # For coupler_pulse drives we build a direct CZ unitary in the
        # {|00>, |01>, |10>, |11>} subspace instead of driving via H_eff,
        # because the CZ comes from the 11<->20 avoided crossing — not a
        # simple XY coupling. We accumulate partial unitaries sequentially.

        # Start with exp(-i H_eff * duration) for the bare+microwave part
        H_mat  = H_eff.full()
        # Subtract diagonal mean to improve numerical conditioning
        diag_mean = np.mean(np.diag(H_mat).real)
        H_mat -= diag_mean * np.eye(H_mat.shape[0])
        U_mat  = scipy_expm(-1j * H_mat * duration)
        U_sub  = qt.Qobj(U_mat)
        U_sub.dims = [list(sub_dims), list(sub_dims)]

        # Ideal gates scheduled alongside the microwave drives act after them.
        for U_step in ideal_ops:
            U_sub = U_step * U_sub

        U_sub.dims = [list(sub_dims), list(sub_dims)]

        # ── Apply unitary to full state (no ptrace — entanglement preserved) ─
        return self._apply_unitary_to_subsystem(
            U_sub, sub_global_idxs, full_state, full_dims
        )

    # ------------------------------------------------------------------
    # 5b. Logical-zero encoding
    # ------------------------------------------------------------------

    def _encode_logical_zero(
        self,
        l_name: str,
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        full_dims: List[int],
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Prepare logical |0>_L for one logical block by running
        `code.encoding_circuit` against its data qubits (which start in
        |00...0>). Every step is an ideal H or CNOT, applied in place to the
        register's state (see register_ops).
        """
        array = _as_array(current_state, full_dims)
        axes = [physical_names.index(name) for name in mapping[l_name]["data"]]
        _apply_ideal_drives(array, _encoding_drives(code), axes)
        return _as_ket(array, full_dims)

    # ------------------------------------------------------------------
    # 6. Transversal logical gate → per-block subsystem simulations
    # ------------------------------------------------------------------

    def _transversal_drives(
        self,
        instruction: Dict[str, Any],
        logical_names: List[str],
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        full_dims: List[int],
        calibrations: Dict,
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Apply a logical instruction transversally, one physical qubit (or
        qubit pair) at a time -- never the whole logical block in a single
        combined subsystem. This keeps every simulated Hilbert space small
        (bounded by 1-2 qubits) regardless of the code's total qubit count,
        which is required for the 9-qubit Shor code (18 data qubits
        involved in a two-block CX) to be tractable with this engine's
        dense-matrix backend; it gives IDENTICAL results to a combined
        simulation for the repetition code, since gates on disjoint qubits
        always commute and `_apply_unitary_to_subsystem` embeds each one
        via a pure unitary (no partial trace), so entanglement across the
        full register -- including between different logical qubits -- is
        preserved exactly whether the gates are grouped into one call or
        applied via several sequential calls.

        Single-qubit gates:
            X   -- applied to the data qubits in `code.logical_x_qubits`,
                   using Pauli `code.logical_x_pauli` (X for the repetition
                   code; Z for the Shor code, whose logical X-bar is
                   physically a Z string -- see stabilizer_codes.py).
            H   -- applied to every data qubit, or by the code's own method
                   if that is not a logical H (`code.logical_hadamard`).
            RZ  -- virtual, no physical drive.

        Two-qubit gates (CX/CNOT/CZ between two logical blocks):
            Applied to corresponding data-qubit pairs across the two
            blocks, one pair per data-qubit index: (D0_L1,D0_L2),
            (D1_L1,D1_L2), ... -- the general fact that transversal CNOT
            implements logical CNOT for any CSS code.

        Returns the updated full quantum state.
        """
        gate   = instruction["type"].upper()
        target = instruction["target"]

        # ---- single-qubit transversal gates --------------------------------
        if isinstance(target, int):
            l_name = logical_names[target]
            data   = mapping[l_name]["data"]    # [D0..D(n-1)]

            if gate == "X":
                # Transversal logical X touches exactly the data qubits (and
                # Pauli type) the code declares as its logical-X support
                # (code.logical_x_qubits / code.logical_x_pauli). For the
                # repetition code that is physical X on every data qubit,
                # reproducing the previous hard-coded behaviour exactly. For
                # the Shor code it is physical Z on one representative qubit
                # per block (see stabilizer_codes.py for the derivation).
                for local_idx in code.logical_x_qubits:
                    p = data[local_idx]
                    current_state = self._simulate_subsystem(
                        sub_names=[p],
                        sub_drives=[{"type": code.logical_x_pauli, "target": 0}],
                        duration=0.0,
                        sub_couplings=[],
                        full_state=current_state,
                        full_names=physical_names,
                        full_dims=full_dims,
                        gate_label=f"EC_{gate}",
                    )

            elif gate == "H" and code.logical_hadamard != "transversal":
                current_state = self._non_transversal_hadamard(
                    l_name, mapping, code, physical_names, full_dims, current_state
                )

            elif gate == "H":
                for p in data:
                    current_state = self._simulate_subsystem(
                        sub_names=[p],
                        sub_drives=[{"type": "H", "target": 0}],
                        duration=0.0,
                        sub_couplings=[],
                        full_state=current_state,
                        full_names=physical_names,
                        full_dims=full_dims,
                        gate_label="EC_H",
                    )

            elif gate == "RZ":
                # Logical Z-axis rotation: applied transversally, with no
                # physical drive duration (virtual-Z -- real hardware
                # implements this by shifting the phase reference of
                # subsequent pulses rather than emitting one of its own,
                # which is equivalent to applying the ideal rotation
                # instantaneously here), to the code's declared logical-Z
                # support (code.logical_z_qubits), rotating each physical
                # qubit about the axis given by code.logical_z_pauli --
                # the same axis whose pi-rotation special case is exactly
                # the code's logical Z (see the "X" branch above, which
                # mirrors this using code.logical_x_qubits/pauli). NOTE:
                # this reproduces logical Z/S/Sdg exactly for every code
                # here (repetition, Shor, Steane), and reproduces logical
                # T/Tdg for the repetition code (whose codewords are
                # themselves computational-basis states) -- but for the
                # Steane code, a bare transversal T/Tdg (theta = +/- pi/4)
                # is only an approximation: the Steane code has no exact
                # transversal T gate (a well-known limitation, distinct
                # from this engine's previous bug of applying no rotation
                # at all), so circuits reaching this branch with a
                # non-Clifford theta on a Steane block accumulate a small
                # amount of leakage out of the code space that the
                # subsequent syndrome/correction pass cannot fully undo.
                theta = float(instruction.get("theta", 0.0))
                for local_idx in code.logical_z_qubits:
                    p = data[local_idx]
                    current_state = self._simulate_subsystem(
                        sub_names=[p],
                        sub_drives=[{
                            "type": "RZ",
                            "target": 0,
                            "theta": theta,
                            "pauli_type": code.logical_z_pauli,
                        }],
                        duration=0.0,
                        sub_couplings=[],
                        full_state=current_state,
                        full_names=physical_names,
                        full_dims=full_dims,
                        gate_label="EC_RZ",
                    )

            else:
                print(f"[EC] Warning: gate '{gate}' not natively supported; skipping.")

        # ---- two-qubit transversal gates -----------------------------------
        elif isinstance(target, tuple) and len(target) == 2:
            l1_idx, l2_idx = target
            l1    = logical_names[l1_idx]
            l2    = logical_names[l2_idx]
            data1 = mapping[l1]["data"]
            data2 = mapping[l2]["data"]

            if gate == "CZ" and code.logical_hadamard != "transversal":
                # Qubit-by-qubit CZ needs the X and Z checks to share supports.
                # Without that, CZ = H(target) CX H(target).
                for step in (
                    {"type": "H", "target": l2_idx},
                    {"type": "CX", "target": (l1_idx, l2_idx)},
                    {"type": "H", "target": l2_idx},
                ):
                    current_state = self._transversal_drives(
                        step, logical_names, mapping, code,
                        physical_names, full_dims, calibrations, current_state,
                    )
            elif gate in ("CX", "CNOT", "CZ"):
                # CZ must use the ideal CZ operator, not CX/CNOT — they are
                # different gates and were previously conflated here,
                # silently executing a logical CZ as a CNOT.
                drive_type = "ICZ" if gate == "CZ" else "ICX"
                for p1, p2 in zip(data1, data2):
                    dur = calibrations["cnot_dur"].get(
                        (p1, p2), calibrations["cnot_dur"].get((p2, p1), 100.0)
                    )
                    current_state = self._simulate_subsystem(
                        sub_names=[p1, p2],
                        sub_drives=[{"type": drive_type, "control": 0, "target": 1}],
                        duration=dur,
                        sub_couplings=[],
                        full_state=current_state,
                        full_names=physical_names,
                        full_dims=full_dims,
                        gate_label=f"EC_{gate}",
                    )
            else:
                print(f"[EC] Warning: two-qubit gate '{gate}' not natively supported; skipping.")

        return current_state

    # ------------------------------------------------------------------
    # 6. Syndrome extraction drive schedule
    # ------------------------------------------------------------------

    def _non_transversal_hadamard(
        self,
        l_name: str,
        mapping: Dict,
        code: StabilizerCode,
        names: List[str],
        dims: List[int],
        state: qt.Qobj,
    ) -> qt.Qobj:
        """Logical H for codes on which H on every qubit is not one."""
        array = _as_array(state, dims)
        axes = [names.index(name) for name in mapping[l_name]["data"]]

        if code.logical_hadamard == "relabel":
            for axis in axes:
                apply_hadamard(array, axis)
            order = list(range(array.ndim))
            for old, new in enumerate(code.hadamard_relabelling):
                order[axes[new]] = axes[old]
            return _as_ket(np.transpose(array, order), dims)

        steps = _encoding_drives(code)
        # Every encoding gate is its own inverse, so the inverse circuit is the reverse.
        _apply_ideal_drives(array, steps[::-1], axes)
        apply_hadamard(array, axes[0])
        _apply_ideal_drives(array, steps, axes)
        return _as_ket(array, dims)

    @staticmethod
    def _inject_errors(
        errors: Optional[List[Tuple[str, int, str]]],
        mapping: Dict,
        names: List[str],
        dims: List[int],
        state: qt.Qobj,
    ) -> qt.Qobj:
        """Apply (logical name, data-qubit index, "X" | "Y" | "Z") errors to a register."""
        for l_name, local_dq, pauli in errors or []:
            idx = names.index(mapping[l_name]["data"][local_dq])
            print(f"    [EC] Injecting {pauli} error on {names[idx]}")
            for factor in ("Z", "X") if pauli == "Y" else (pauli,):
                state = _apply_pauli_to_ket(state, factor, idx, dims)
        return state

    def _generator_extraction_drives(self, gen: StabilizerGenerator) -> List[Dict]:
        """
        Build the LOCAL extraction-drive schedule for ONE stabilizer
        generator. The subsystem this schedule is meant to run on must be
        ordered as [gen.data_qubits in order, ancilla] -- i.e. local index k
        for the k-th listed data qubit, and local index len(gen.data_qubits)
        for the ancilla.

          - Z-type: CNOT(data -> ancilla) for every data qubit in the
            generator, sequenced in time. A direct Z-basis ancilla readout
            afterwards gives the Z-stabilizer eigenvalue.
          - X-type: H(ancilla), then CNOT(ancilla -> data) for every data
            qubit in the generator, then H(ancilla) — the standard
            X-stabilizer measurement circuit, so a Z-basis ancilla readout
            still gives the correct eigenvalue. Not exercised by the
            3-qubit repetition code (Z-type only), but required by the
            9-qubit Shor code's outer (phase-flip) generators.

        For the repetition code's two generators this reproduces exactly
        the previous fixed sequence:
            CNOT(D0 -> A0)   parity D0 xor D1
            CNOT(D1 -> A0)
            CNOT(D1 -> A1)   parity D1 xor D2
            CNOT(D2 -> A1)
        """
        n = len(gen.data_qubits)
        anc_local = n
        drives: List[Dict] = []

        if gen.basis == "Z":
            for local_dq in range(n):
                drives.append({"type": "ICX", "control": local_dq, "target": anc_local})
        elif gen.basis == "X":
            drives.append({"type": "H", "target": anc_local})
            for local_dq in range(n):
                drives.append({"type": "ICX", "control": anc_local, "target": local_dq})
            drives.append({"type": "H", "target": anc_local})

        return drives

    # ------------------------------------------------------------------
    # 7. Syndrome measurement (projective, with correction)
    # ------------------------------------------------------------------

    def _measure_and_collapse_ancilla(
        self,
        state: qt.Qobj,
        anc_idx: int,
        dims: List[int],
        label: str,
    ) -> Tuple[qt.Qobj, int]:
        """
        Projectively measure ONE physical ancilla qubit in the Z
        (computational) basis, collapse the FULL state onto the observed
        outcome, and return (collapsed_state, bit).

        Ancillas are measured one at a time (rather than jointly, as a
        single combined 2**num_ancilla-outcome projector) purely for
        tractability with codes that have many generators (8 for the Shor
        code): all of a valid code's stabilizer generators mutually
        commute by construction, so sequential single-ancilla measurement
        gives EXACTLY the same joint outcome distribution and
        post-measurement state as a joint measurement — this is the
        standard equivalence between sequential and joint measurement of
        commuting observables, not an approximation.
        """
        ket = state.type == "ket"
        if ket:
            array = state.full().reshape(dims)
            p0, p1 = (
                float(np.sum(np.abs(np.take(array, level, axis=anc_idx)) ** 2)) for level in (0, 1)
            )
        else:
            d_anc = dims[anc_idx]
            proj0 = _tensor_op_at(_proj0_dim(d_anc), anc_idx, dims)
            proj1 = _tensor_op_at(_proj1_dim(d_anc), anc_idx, dims)
            p0 = float(np.real((proj0 * state).tr()))
            p1 = float(np.real((proj1 * state).tr()))

        total = p0 + p1
        if total < 1e-12:
            print(f"    [EC] Warning: total probability ~0 measuring {label}. State may be corrupted.")
            return state, 0

        p0n  = p0 / total
        bit  = int(np.random.choice([0, 1], p=[p0n, 1.0 - p0n]))
        prob = (1.0 - p0n) if bit == 1 else p0n
        scale = 1.0 / np.sqrt(prob) if prob > 1e-12 else 1.0

        if ket:
            kept = [slice(None)] * len(dims)
            kept[anc_idx] = bit
            reduced = np.zeros_like(array)
            reduced[tuple(kept)] = array[tuple(kept)] * scale
            collapsed = _as_ket(reduced, dims)
        else:
            collapsed = (proj1 if bit == 1 else proj0) * state * scale

        print(f"      [EC] {label}  bit={bit}  p={prob:.4f}")
        return collapsed, bit

    # ------------------------------------------------------------------
    # 7b. Shor-code-specific: measure AND reclaim an ancilla's dimension
    # ------------------------------------------------------------------
    #
    # Used ONLY by the Shor-code execution path below (execute_shor9_workflow
    # / _run_shor9_workflow / _run_shor9_syndrome_block). The repetition
    # code's execution path (_run_ec_workflow / _run_syndrome_block /
    # _measure_and_collapse_ancilla above) is untouched by this and behaves
    # exactly as before.
    #
    # The generic engine keeps one dense state vector spanning every
    # physical qubit for the whole workflow, including every ancilla,
    # forever. That is fine for the repetition code (2 ancillas, a factor
    # of 4), but the Shor code's 8 ancillas per logical block make it
    # prohibitive as soon as more than one Shor-encoded logical qubit is in
    # the same workflow: e.g. a 2-logical-qubit Bell-state circuit needs
    # 2*17=34 physical qubits, i.e. a 2**34-dimensional dense state vector
    # (hundreds of GB), even though only 2*9=18 of those qubits (the data
    # qubits) ever carry information that outlives a single syndrome round.
    #
    # The fix implemented here: after a projective measurement, the
    # measured qubit is -- by construction -- in a definite product-state
    # factor, unentangled with the rest of the register (this is exactly
    # what "collapse" means). That means its dimension can be removed from
    # the tracked Hilbert space entirely, with zero information loss and
    # zero approximation, by reshaping the state array by the current
    # per-qubit dimensions and slicing out the measured qubit's axis at its
    # observed value, instead of just collapsing-and-keeping it (as
    # `_measure_and_collapse_ancilla` above does) or partial-tracing it out
    # (which would be equally exact but would turn a compact ket into a
    # dense d*d density matrix -- quadratically worse, not better).
    # `_run_shor9_syndrome_block` tensors a fresh |0> ancilla in only for
    # the duration of its own generator's extraction + measurement, then
    # immediately drops it here, so at most ONE ancilla is ever "live" at a
    # time, regardless of how many logical qubits or syndrome rounds the
    # workflow has -- bounding the live dimension by (total data qubits) +
    # 1 ancilla instead of (total data qubits) + (every ancilla ever used).

    # ------------------------------------------------------------------
    # 8. Final state decoding
    # ------------------------------------------------------------------

    def _decode_logical_state(
        self,
        state: qt.Qobj,
        logical_names: List[str],
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        physical_index,
        dims: List[int],
    ) -> Dict[str, float]:
        """
        Decode the logical value of each logical block via a JOINT
        projective measurement in the logical-Z basis, built from the
        code's declared `logical_z_qubits`/`logical_z_pauli` (Z0Z1Z2 for
        the repetition code, X0X1X2 for the Shor code — see
        stabilizer_codes.py).

        This is required for physical correctness in general: it is NOT
        equivalent to reading raw data-qubit populations and majority-
        voting, which is all the repetition code needed because its
        codewords |000> and |111> ARE themselves computational-basis
        states. That coincidence does not hold for the Shor code — |0>_L
        and |1>_L touch the exact same computational-basis strings with the
        exact same probabilities and differ only in relative phase, which a
        bit-population reading of the diagonal cannot see at all. A genuine
        logical-Z operator expectation-value measurement is the only
        general way to decode a stabilizer-encoded state.

        For the repetition code this reduces to EXACTLY the previous
        population/majority-vote decode once the state has been corrected
        back into the codespace (the case that always applies here, since
        decode always follows a mandatory final syndrome-correction pass):
        Z0, Z1, Z2 all act identically on the repetition code's codespace
        (they differ only by stabilizer elements), so <Z0 Z1 Z2> on a state
        confined to {|000>, |111>} gives exactly P(|000>) - P(|111>), the
        same split majority-vote-over-the-diagonal already computed.

        Handles both ket states and density matrices, and preserves
        correlations/entanglement between multiple logical qubits (e.g. a
        logical Bell state still decodes to {'00': 0.5, '11': 0.5}, not
        independent per-qubit marginals).
        """
        if state.type == "ket":
            z_axes = [
                [physical_index[mapping[name]["data"][dq]] for dq in code.logical_z_qubits]
                for name in logical_names
            ]
            joint = _logical_parities(state, dims, z_axes, code.logical_z_pauli)
            return {
                "".join(map(str, bits)): float(joint[bits])
                for bits in itertools.product((0, 1), repeat=len(logical_names))
                if joint[bits] > 1e-8
            }

        rho = state

        # Build each logical block's Z-bar operator, embedded in the full
        # physical register (identity on every other qubit).
        z_bar_ops: List[qt.Qobj] = []
        for l_name in logical_names:
            data_names = mapping[l_name]["data"]
            op_list = [qt.qeye(d) for d in dims]
            for local_dq in code.logical_z_qubits:
                idx = physical_index[data_names[local_dq]]
                op_list[idx] = _pauli_dim(code.logical_z_pauli, dims[idx])
            z_bar_ops.append(qt.tensor(op_list))

        identity_full = qt.tensor([qt.qeye(d) for d in dims])

        logical_pops: Dict[str, float] = {}
        for bits in itertools.product([0, 1], repeat=len(logical_names)):
            projector = identity_full
            for z_bar, bit in zip(z_bar_ops, bits):
                sign = 1.0 if bit == 0 else -1.0
                projector = projector * (identity_full + sign * z_bar) / 2.0
            prob = float(np.real((rho * projector).tr()))
            if prob > 1e-8:
                bitstring = "".join(str(b) for b in bits)
                logical_pops[bitstring] = logical_pops.get(bitstring, 0.0) + prob

        return logical_pops

    # ------------------------------------------------------------------
    # 9. Main entry point
    # ------------------------------------------------------------------

    def execute_3q_repetition_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> Dict:
        """
        Backward-compatible entry point for the 3-qubit repetition code.

        Thin wrapper around `execute_stabilizer_workflow(code=REPETITION_3)`;
        parameters and behaviour are unchanged from before the stabilizer
        formalism refactor.

        Parameters
        ----------
        logical_names : list of str
            Names of the logical qubits (must exist in QubitEngine).
            Each is expanded to 5 physical qubits (D0, D1, D2, A0, A1) in
            memory only — they are NEVER written to the session JSON file.
        qasm_path : str
            Path to an OpenQASM 2.0 file for the logical circuit.
        coupling_type : str
            Coupling type for syndrome-extraction CNOTs (default: "capacitive").
        coupling_strength : float
            Coupling strength in GHz (default: 0.010).
        ec_every_n_gates : int
            Run a syndrome cycle after every N gates (default: 1).
            Set to 0 to skip all mid-circuit syndromes and run only a single
            final syndrome pass.  Use 0 for circuits with H gates / superpositions,
            because Z-stabiliser measurement collapses X-basis states mid-circuit.
        inject_errors : list of (str, int, str), optional
            Pauli errors applied just before the final syndrome pass, each as
            (logical qubit name, local data-qubit index, "X" | "Y" | "Z").
        """
        return self.execute_stabilizer_workflow(
            logical_names=logical_names,
            qasm_path=qasm_path,
            code=REPETITION_3,
            coupling_type=coupling_type,
            coupling_strength=coupling_strength,
            ec_every_n_gates=ec_every_n_gates,
            inject_errors=inject_errors,
        )

    def execute_shor9_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> Dict:
        """
        Entry point for the 9-qubit Shor code.

        Runs a dedicated, ancilla-reclaiming execution path (see
        `_run_shor9_workflow` / `_run_shor9_syndrome_block` /
        `_reclaiming_syndrome_block`) instead of the generic
        `execute_stabilizer_workflow`: the generic path keeps one dense
        state vector spanning EVERY physical qubit -- data AND ancilla --
        for the whole workflow, which is fine for the repetition code (2
        ancillas) but is only 2 logical qubits away from needing hundreds
        of GB for the Shor code (8 ancillas per block). This path instead
        reclaims each ancilla's dimension immediately after it is measured
        (exact, not an approximation -- see `_reclaiming_syndrome_block`),
        so the live simulated Hilbert space is bounded by the total number
        of DATA qubits plus at most one "borrowed" ancilla at a time,
        regardless of how many logical qubits or syndrome rounds the
        workflow has. See stabilizer_codes.SHOR_9 for the code's generator
        layout and the derivation of its logical X/Z operators.

        Parameters
        ----------
        logical_names : list of str
            Names of the logical qubits (must exist in QubitEngine).
            Each is expanded to 17 physical qubits (9 data + 8 ancilla) in
            memory only — they are NEVER written to the session JSON file.
        qasm_path : str
            Path to an OpenQASM 2.0 file for the logical circuit.
        coupling_type : str
            Coupling type for syndrome-extraction CNOTs (default: "capacitive").
        coupling_strength : float
            Coupling strength in GHz (default: 0.010).
        ec_every_n_gates : int
            Run a syndrome cycle after every N gates (default: 1).
            Set to 0 to skip all mid-circuit syndromes and run only a single
            final syndrome pass.  Use 0 for circuits with H gates / superpositions,
            because Z-stabiliser measurement collapses X-basis states mid-circuit.
        inject_errors : list of (str, int, str), optional
            Pauli errors applied just before the final syndrome pass, each as
            (logical qubit name, local data-qubit index, "X" | "Y" | "Z").
        """
        code = SHOR_9

        print(f"[EC] 1. Parsing logical QASM from '{qasm_path}'...")
        transpiler      = QASMTranspiler()
        logical_circuit = transpiler.parse_file(qasm_path)
        print(f"[EC]    {len(logical_circuit)} logical instructions parsed.")

        print_logical_circuit_diagram(qasm_path, title="[EC] Logical circuit (error correction hidden)")

        print(f"[EC] 2. Generating physical qubit mapping for '{code.name}'...")
        mapping        = self.generate_stabilizer_mapping(logical_names, code)
        physical_names = self._get_flat_physical_names(logical_names, mapping)
        print(
            f"[EC]    Logical qubits : {logical_names}\n"
            f"[EC]    Physical qubits: {physical_names}"
        )

        self._register_physical_qubits(logical_names, mapping)

        try:
            self._run_shor9_workflow(
                logical_names     = logical_names,
                logical_circuit   = logical_circuit,
                mapping           = mapping,
                code              = code,
                physical_names    = physical_names,
                coupling_type     = coupling_type,
                coupling_strength = coupling_strength,
                ec_every_n_gates  = ec_every_n_gates,
                inject_errors=inject_errors,
            )
            result = self._last_ec_result
        finally:
            self._cleanup_physical_qubits(logical_names, mapping)

        return result

    # ------------------------------------------------------------------
    # 9d. Shor-code-specific inner workflow (ancilla-reclaiming)
    # ------------------------------------------------------------------

    def _run_shor9_workflow(
        self,
        logical_names: List[str],
        logical_circuit: List[Dict],
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        coupling_type: str,
        coupling_strength: float,
        ec_every_n_gates: int,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> None:
        """
        Shor-code counterpart of `_run_ec_workflow`, differing in how the
        simulated state is kept small:

        Ancilla reclaim: `active_names`/`active_dims` are the qubits
        CURRENTLY present in `current_state` (initially just the data
        qubits of every logical block), grown by one ancilla right before
        its own generator is extracted and shrunk back down the instant
        that ancilla is measured (`_run_shor9_syndrome_block`). Encoding
        and transversal gates only ever touch data qubits, so
        `_encode_logical_zero` / `_transversal_drives` / `_decode_logical_state`
        are reused completely unmodified.

        Simulated dimension: every qubit's dimension in `active_dims` is
        capped at 2 (the computational subspace {|0>,|1>} only), regardless
        of its registered `truncated_dim` (which may be larger, e.g. 4, to
        model leakage in general physical-pulse simulations elsewhere in
        QubitWeave). This is exact here, not an approximation: every gate this
        workflow ever applies -- transversal X/H, syndrome CNOTs, and
        feed-forward Pauli corrections -- goes through the IDEAL gate path
        (`_build_ideal_single_qubit_operator` / `_build_ideal_cx_operator` /
        `_pauli_dim`), which is built directly from whatever `dims` it is
        given and provably acts as identity outside the qubit indices it
        touches; combined with an initial state of |0> everywhere, no
        leakage level is ever populated at any point in this workflow, so
        there is nothing for a truncated_dim=2 simulation to lose. It is
        also necessary: with each qubit's full registered truncated_dim
        (e.g. 4), two Shor-encoded logical qubits alone would need
        4**18 ~ 6.9*10**10 states just for the data qubits, no matter how
        efficiently ancillas are reclaimed.
        """
        print("[EC] 3. Calibrating pulses (results cached for re-use)...")
        calibrations = self._calibrate(
            logical_names,
            mapping,
            physical_names,
            syndrome_couplings=[],
            coupling_type=coupling_type,
            coupling_strength=coupling_strength,
            calibrate_cnot=False,
        )

        # ── Active state: data qubits of every logical block, initially |00...0> ──
        active_names = []
        for l_name in logical_names:
            active_names.extend(mapping[l_name]["data"])
        # Simulated dimension is capped at 2 per qubit (computational subspace
        # only), NOT the qubit's full registered truncated_dim -- see the
        # "Simulated dimension" note in this method's docstring for why this
        # is exact (not an approximation) for this specific workflow, and
        # necessary: with the registered qubits' full truncated_dim (e.g. 4),
        # 2 Shor-encoded logical qubits alone need 4**18 ~ 6.9*10**10 states
        # for the data qubits, regardless of how well ancillas are reclaimed.
        active_dims = [
            min(2, self.qubit_engine.get_qubit(name).truncated_dim)
            for name in active_names
        ]
        print(f"[EC] 4. Initialising physical state to |00...0> ({len(active_names)} data qubits)...")
        current_state = qt.tensor([qt.basis(d, 0) for d in active_dims])
        current_state.dims = [list(active_dims), [1] * len(active_dims)]

        print(f"[EC]    Encoding |0>_L for {len(logical_names)} logical qubit(s)...")
        for l_name in logical_names:
            current_state = self._encode_logical_zero(
                l_name, mapping, code, active_names, active_dims, current_state,
            )

        # ── Execute logical circuit, gate by gate ──────────────────────
        print(f"\n[EC] 5. Executing logical circuit ({len(logical_circuit)} gates)...\n")
        gate_counter = 0

        for step_idx, instruction in enumerate(logical_circuit):
            gate_label = instruction.get("type", "?")
            target     = instruction.get("target", "?")
            print(f"  [Gate {step_idx:03d}] {gate_label}  target={target}")

            if isinstance(target, tuple) and len(target) == 2:
                # Two-qubit gates need Shor-specific handling: see
                # _shor9_transversal_two_qubit_gate for why a plain
                # transversal CNOT does not implement logical CNOT in the
                # circuit's intended direction for this code.
                current_state = self._shor9_transversal_two_qubit_gate(
                    instruction, logical_names, mapping, code,
                    active_names, active_dims, calibrations,
                    current_state,
                )
            else:
                current_state = self._transversal_drives(
                    instruction, logical_names, mapping, code,
                    active_names, active_dims, calibrations,
                    current_state,
                )

            gate_counter += 1

            if ec_every_n_gates > 0 and gate_counter % ec_every_n_gates == 0:
                print(f"  [EC cycle after gate {step_idx}]")
                for l_name in logical_names:
                    current_state = self._run_shor9_syndrome_block(
                        l_name, mapping, code, active_names, active_dims, current_state,
                    )

        current_state = self._inject_errors(
            inject_errors, mapping, active_names, active_dims, current_state
        )

        # ── Final syndrome pass (always runs) ──────────────────────────
        print("  [EC final syndrome pass]")
        for l_name in logical_names:
            current_state = self._run_shor9_syndrome_block(
                l_name, mapping, code, active_names, active_dims, current_state,
            )

        # By now every ancilla has been reclaimed, so active_names/active_dims
        # are exactly the data qubits again, in the same order as at the top.
        active_index = {name: idx for idx, name in enumerate(active_names)}

        print("\n[EC] 6. Circuit complete. Decoding final logical populations...")
        logical_pops = self._decode_logical_state(
            current_state, logical_names, mapping, code, active_names, active_index, active_dims
        )

        print("[EC] Logical state populations:")
        if not logical_pops:
            print("    [EC] WARNING: no logical populations decoded.")
        for bitstring, pop in sorted(logical_pops.items(), key=lambda x: -x[1]):
            bar = "█" * int(pop * 20) + "░" * (20 - int(pop * 20))
            print(f"    |{bitstring}>_L  {bar}  {pop * 100:5.2f}%")

        self._last_ec_result = {
            "logical_populations":  logical_pops,
            "final_physical_state": current_state,
            "data_axes":            {
                name: [active_names.index(d) for d in mapping[name]["data"]] for name in logical_names
            },
            "syndromes":            dict(self._last_syndromes),
        }

    def _run_shor9_syndrome_block(
        self,
        l_name: str,
        mapping: Dict,
        code: StabilizerCode,
        active_names: List[str],
        active_dims: List[int],
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Shor-code counterpart of `_run_syndrome_block`: runs one full
        syndrome-extraction + measurement + correction cycle for one
        logical block, generator by generator, but tensors each
        generator's ancilla in fresh right before it is needed and
        reclaims (removes) its dimension immediately after measuring it
        (`_reclaiming_syndrome_block`), instead of registering all 8
        ancillas in the state up front and keeping them forever. `active_names`
        and `active_dims` are mutated IN PLACE to track whatever is
        currently tensored into `current_state`; both are back to exactly
        the data qubits (in their original order) by the time this method
        returns.
        """
        return self._reclaiming_syndrome_block(
            l_name, mapping, code, active_names, active_dims, current_state
        )

    def _reclaiming_syndrome_block(
        self,
        l_name: str,
        mapping: Dict,
        code: StabilizerCode,
        active_names: List[str],
        active_dims: List[int],
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Syndrome extraction, measurement and correction for one logical block, shared
        by every code whose ancillas are reclaimed as soon as they are measured.

        Each generator's ancilla is added in |0> as the LEADING axis of the state, its
        CNOTs are applied, and it is projected. With the ancilla leading, the two
        outcomes are the two contiguous halves of the array, so collapsing and removing
        it is taking one half: exact, and free of copies.
        """
        print(f"    Syndrome extraction for logical block: {l_name}")

        data_axes = [active_names.index(name) for name in mapping[l_name]["data"]]
        anc_names = mapping[l_name]["ancilla"]
        syndrome_bits: List[int] = [0] * code.num_ancilla

        state = current_state.full().reshape(active_dims)
        for gen in code.generators:
            extended = np.zeros((2, *active_dims), dtype=complex)
            extended[0] = state
            axes = [data_axes[dq] + 1 for dq in gen.data_qubits] + [0]
            _apply_ideal_drives(extended, self._generator_extraction_drives(gen), axes)

            label = f"{l_name}:{anc_names[gen.ancilla]}"
            p0, p1 = (float(np.vdot(half, half).real) for half in extended)
            bit, prob = self._draw_outcome(p0, p1, label)
            state = extended[bit]
            norm = np.sqrt(p1 if bit else p0)
            if norm > 1e-12:
                state = state / norm
            print(f"      [EC] {label}  bit={bit}  p={prob:.4f}")
            syndrome_bits[gen.ancilla] = bit

        syndrome = tuple(syndrome_bits)
        self._last_syndromes[l_name] = syndrome
        print(f"    [EC] {l_name}  syndrome {syndrome}")

        # Feed-forward corrections. No ancilla reset is needed: a reclaimed ancilla is
        # gone, and the next round starts from a fresh |0>.
        corrections = code.syndrome_to_correction.get(syndrome, [])
        if corrections:
            state = np.array(state)
        for local_dq, pauli_type in corrections:
            print(f"    [EC] Applying {pauli_type} correction to {active_names[data_axes[local_dq]]}")
            apply_pauli(state, data_axes[local_dq], pauli_type)

        return _as_ket(state, active_dims)

    @staticmethod
    def _draw_outcome(p0: float, p1: float, label: str) -> Tuple[int, float]:
        """Sample a Z measurement. Returns (bit, its probability given no leakage)."""
        total = p0 + p1
        if total < 1e-12:
            print(f"    [EC] Warning: total probability ~0 measuring {label}. State may be corrupted.")
            return 0, 0.0
        p0n = p0 / total
        bit = int(np.random.choice([0, 1], p=[p0n, 1.0 - p0n]))
        return bit, (1.0 - p0n) if bit == 1 else p0n

    def _shor9_transversal_two_qubit_gate(
        self,
        instruction: Dict[str, Any],
        logical_names: List[str],
        mapping: Dict,
        code: StabilizerCode,
        active_names: List[str],
        active_dims: List[int],
        calibrations: Dict,
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Shor-code-specific transversal two-qubit gate handler for
        CX/CNOT/CZ, used ONLY by the Shor execution path
        (`_run_shor9_workflow`). Does not touch, and is not used by, the
        repetition code's `_transversal_drives`.

        Why this exists: for a CSS code whose logical X-bar is built from
        PHYSICAL X's and Z-bar from physical Z's (the repetition code:
        code.logical_x_pauli == "X"), a transversal CNOT (physical CNOT_i
        from control-block qubit i to target-block qubit i, for every i)
        implements logical CNOT in that SAME direction. The Shor code's
        logical operators are swapped (code.logical_x_pauli == "Z": X-bar
        is a Z-type string, Z-bar an X-type string -- see
        stabilizer_codes.py for the derivation), and conjugating X-bar/
        Z-bar through a transversal CNOT for a code with this swapped
        convention shows it instead implements logical CNOT with the
        physical control and target blocks' roles REVERSED. This was
        verified three independent ways (stabilizer conjugation algebra,
        a block-parity amplitude derivation, and direct enumeration of the
        transversal CNOT's action on all four computational-basis logical
        inputs |0>_L|0>_L .. |1>_L|1>_L), all agreeing exactly.

        The fix: apply the transversal CNOT with the PHYSICAL control and
        target blocks swapped relative to the circuit's logical control and
        target -- i.e. physical control = the circuit's target block's
        qubits, physical target = the circuit's control block's qubits.
        That reproduces the circuit's intended logical CNOT(l1 -> l2)
        exactly.

        A transversal physical CZ does not implement logical CZ here (it is diagonal in
        the physical Z basis, the logical Z basis is the physical X one), so CZ is
        compiled to H(target) CX H(target).
        """
        gate = instruction["type"].upper()
        l1_idx, l2_idx = instruction["target"]
        l1 = logical_names[l1_idx]
        l2 = logical_names[l2_idx]
        data1 = mapping[l1]["data"]   # circuit's control block
        data2 = mapping[l2]["data"]   # circuit's target block

        if gate == "CZ":
            # CZ = H(target) CX H(target)
            current_state = self._non_transversal_hadamard(
                l2, mapping, code, active_names, active_dims, current_state
            )
            current_state = self._shor9_transversal_two_qubit_gate(
                {**instruction, "type": "CX"}, logical_names, mapping, code,
                active_names, active_dims, calibrations, current_state,
            )
            return self._non_transversal_hadamard(
                l2, mapping, code, active_names, active_dims, current_state
            )

        if gate not in ("CX", "CNOT"):
            print(f"[EC] Warning: two-qubit gate '{gate}' not natively supported for the Shor code; skipping.")
            return current_state

        for phys_control, phys_target in zip(data2, data1):
            dur = calibrations["cnot_dur"].get(
                (phys_control, phys_target), calibrations["cnot_dur"].get((phys_target, phys_control), 100.0)
            )
            current_state = self._simulate_subsystem(
                sub_names=[phys_control, phys_target],
                sub_drives=[{"type": "ICX", "control": 0, "target": 1}],
                duration=dur,
                sub_couplings=[],
                full_state=current_state,
                full_names=active_names,
                full_dims=active_dims,
                gate_label=f"EC_{gate}_shor",
            )

        return current_state

    # ------------------------------------------------------------------
    # 9e. Steane-code-specific entry point and inner workflow
    # ------------------------------------------------------------------
    #
    # Structurally a near-twin of the Shor-code path above (same
    # ancilla-reclaiming, dimension-capped strategy, for the same
    # tractability reasons -- see _run_shor9_workflow's docstring), but
    # written as its own independent set of methods rather than sharing
    # code with the Shor-specific ones, so that nothing here can ever
    # affect the Shor code's behaviour (and vice versa).
    #
    # Unlike Shor, the Steane code needs NO special-cased two-qubit gate
    # handling: it uses the "obvious" CSS convention (logical X-bar =
    # transversal X, logical Z-bar = transversal Z -- see stabilizer_codes.py),
    # for which transversal CNOT and CZ implement logical CNOT/CZ directly,
    # with no direction reversal or basis mismatch (verified by direct
    # state-vector simulation before this was written). So the gate-
    # execution loop below calls the fully generic `_transversal_drives`
    # for every gate type, single- or two-qubit alike.

    def execute_steane7_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> Dict:
        """
        Entry point for the 7-qubit Steane code.

        Runs a dedicated, ancilla-reclaiming execution path (see
        `_run_steane7_workflow` / `_run_steane7_syndrome_block`), for the
        same reason `execute_shor9_workflow` does: the generic
        `execute_stabilizer_workflow` keeps one dense state vector
        spanning every physical qubit -- data AND ancilla -- for the whole
        workflow, which becomes intractable well before this code's 13
        qubits per logical block (7 data + 6 ancilla) are used more than
        once or twice in the same workflow. This path instead reclaims
        each ancilla's dimension immediately after it is measured (exact,
        not an approximation -- see `_reclaiming_syndrome_block`) and
        simulates every qubit at its computational dimension (2) rather
        than its full registered `truncated_dim`, which is also exact here
        since every gate in this workflow is an ideal/logical Clifford
        operation that never populates a leakage level (see
        `_run_steane7_workflow`'s docstring for the full justification).
        See stabilizer_codes.STEANE_7 for the code's generator layout and
        the Hamming-code syndrome decoding it uses.

        Parameters
        ----------
        logical_names : list of str
            Names of the logical qubits (must exist in QubitEngine).
            Each is expanded to 13 physical qubits (7 data + 6 ancilla) in
            memory only — they are NEVER written to the session JSON file.
        qasm_path : str
            Path to an OpenQASM 2.0 file for the logical circuit.
        coupling_type : str
            Coupling type for syndrome-extraction CNOTs (default: "capacitive").
        coupling_strength : float
            Coupling strength in GHz (default: 0.010).
        ec_every_n_gates : int
            Run a syndrome cycle after every N gates (default: 1).
            Set to 0 to skip all mid-circuit syndromes and run only a single
            final syndrome pass.  Use 0 for circuits with H gates / superpositions,
            because stabiliser measurement collapses non-eigenstate superpositions
            mid-circuit.
        inject_errors : list of (str, int, str), optional
            Pauli errors applied just before the final syndrome pass, each as
            (logical qubit name, local data-qubit index, "X" | "Y" | "Z").
        """
        code = STEANE_7

        print(f"[EC] 1. Parsing logical QASM from '{qasm_path}'...")
        transpiler      = QASMTranspiler()
        logical_circuit = transpiler.parse_file(qasm_path)
        print(f"[EC]    {len(logical_circuit)} logical instructions parsed.")

        print_logical_circuit_diagram(qasm_path, title="[EC] Logical circuit (error correction hidden)")

        print(f"[EC] 2. Generating physical qubit mapping for '{code.name}'...")
        mapping        = self.generate_stabilizer_mapping(logical_names, code)
        physical_names = self._get_flat_physical_names(logical_names, mapping)
        print(
            f"[EC]    Logical qubits : {logical_names}\n"
            f"[EC]    Physical qubits: {physical_names}"
        )

        self._register_physical_qubits(logical_names, mapping)

        try:
            self._run_steane7_workflow(
                logical_names     = logical_names,
                logical_circuit   = logical_circuit,
                mapping           = mapping,
                code              = code,
                physical_names    = physical_names,
                coupling_type     = coupling_type,
                coupling_strength = coupling_strength,
                ec_every_n_gates  = ec_every_n_gates,
                inject_errors=inject_errors,
            )
            result = self._last_ec_result
        finally:
            self._cleanup_physical_qubits(logical_names, mapping)

        return result

    def execute_surface9_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> Dict:
        """
        Entry point for the distance-3 rotated surface code (9 data + 8 ancilla).

        Runs the same ancilla-reclaiming path as `execute_steane7_workflow`, which is
        generic over CSS codes with standard logical operators.

        Parameters are those of `execute_steane7_workflow`, plus:

        inject_errors : list of (str, int, str), optional
            Pauli errors applied just before the final syndrome pass, each as
            (logical qubit name, local data-qubit index, "X" | "Y" | "Z").

        Returns
        -------
        dict
            "logical_populations", "final_physical_state" and "syndromes" (the last
            measured syndrome of each logical block, Z plaquettes first).
        """
        code = SURFACE_9
        logical_circuit = QASMTranspiler().parse_file(qasm_path)
        print_logical_circuit_diagram(qasm_path, title="[EC] Logical circuit (error correction hidden)")
        mapping        = self.generate_stabilizer_mapping(logical_names, code)
        physical_names = self._get_flat_physical_names(logical_names, mapping)
        self._register_physical_qubits(logical_names, mapping)
        try:
            self._run_steane7_workflow(
                logical_names     = logical_names,
                logical_circuit   = logical_circuit,
                mapping           = mapping,
                code              = code,
                physical_names    = physical_names,
                coupling_type     = coupling_type,
                coupling_strength = coupling_strength,
                ec_every_n_gates  = ec_every_n_gates,
                inject_errors     = inject_errors,
            )
            return self._last_ec_result
        finally:
            self._cleanup_physical_qubits(logical_names, mapping)

    def simulate_memory_rounds(
        self,
        logical_name: str,
        code: StabilizerCode,
        error_patterns: List[List[Tuple[int, str]]],
    ) -> List[Dict[str, Any]]:
        """
        Run one full error-correction round per error pattern on an encoded qubit.

        Each round prepares the logical state with Bloch vector (1,1,1)/sqrt(3). It is an
        eigenstate of no logical Pauli, so any logical error drops its fidelity to 1/3,
        where |+i> for instance would hide a logical Y. The round then applies the pattern, extracts and measures every stabilizer on the state
        vector, applies the looked-up correction, and compares with the start.

        Parameters
        ----------
        logical_name : str
            A registered qubit, whose clones form the code block. Temporary physical
            qubits are removed afterwards.
        code : StabilizerCode
            Any CSS code with an encoding circuit (the Shor code included).
        error_patterns : list of list of (int, str)
            One entry per round: (data-qubit index, "X" | "Y" | "Z") errors.

        Returns
        -------
        list of dict
            "syndrome" (tuple of bits) and "fidelity" to the state before the errors.
        """
        mapping = self.generate_stabilizer_mapping([logical_name], code)
        self._register_physical_qubits([logical_name], mapping)
        try:
            data = mapping[logical_name]["data"]
            dims = [2] * code.num_data
            state = qt.tensor([qt.basis(2, 0)] * code.num_data)
            state = self._encode_logical_zero(logical_name, mapping, code, list(data), dims, state)
            flipped = state
            for idx in code.logical_x_qubits:
                flipped = _apply_pauli_to_ket(flipped, code.logical_x_pauli, idx, dims)
            polar = np.arccos(1 / np.sqrt(3))
            start = (
                np.cos(polar / 2) * state + np.exp(1j * np.pi / 4) * np.sin(polar / 2) * flipped
            ).unit()

            rounds = []
            for pattern in error_patterns:
                noisy = start
                for idx, pauli in pattern:
                    for factor in ("Z", "X") if pauli == "Y" else (pauli,):
                        noisy = _apply_pauli_to_ket(noisy, factor, idx, dims)
                after = self._run_steane7_syndrome_block(
                    logical_name, mapping, code, list(data), list(dims), noisy
                )
                overlap = complex(np.vdot(start.full(), after.full()))
                rounds.append(
                    {
                        "syndrome": self._last_syndromes[logical_name],
                        "fidelity": float(abs(overlap) ** 2),
                    }
                )
            return rounds
        finally:
            self._cleanup_physical_qubits([logical_name], mapping)

    def _run_steane7_workflow(
        self,
        logical_names: List[str],
        logical_circuit: List[Dict],
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        coupling_type: str,
        coupling_strength: float,
        ec_every_n_gates: int,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> None:
        """
        Steane-code counterpart of `_run_shor9_workflow`.

        Ancilla reclaim: `active_names`/`active_dims` are the qubits
        CURRENTLY present in `current_state` (initially just the data
        qubits of every logical block), grown by one ancilla right before
        its own generator is extracted and shrunk back down the instant
        that ancilla is measured (`_run_steane7_syndrome_block`).

        Simulated dimension: every qubit's dimension in `active_dims` is
        capped at 2 (the computational subspace {|0>,|1>} only), regardless
        of its registered `truncated_dim`. This is exact here, not an
        approximation: every gate this workflow ever applies -- transversal
        X/H/CX/CZ, syndrome CNOTs, and feed-forward Pauli corrections --
        goes through the IDEAL gate path (`_build_ideal_single_qubit_operator`
        / `_build_ideal_cx_operator` / `_pauli_dim`), built directly from
        whatever `dims` it is given and provably acting as identity outside
        the qubit indices it touches; combined with an initial state of |0>
        everywhere, no leakage level is ever populated at any point in this
        workflow, so there is nothing for a truncated_dim=2 simulation to
        lose. It is also necessary for tractability: with each qubit's full
        registered truncated_dim (commonly > 2 for scqubits transmon
        models), even a single Steane-encoded logical qubit's 7 data qubits
        could need an unnecessarily large state vector.

        Because Steane's logical operators use the standard CSS convention
        (see stabilizer_codes.STEANE_7), transversal gates -- single- and
        two-qubit alike -- are all handled by the fully generic
        `_transversal_drives`, unlike the Shor path which needs a
        dedicated two-qubit handler.
        """
        print("[EC] 3. Calibrating pulses (results cached for re-use)...")
        calibrations = self._calibrate(
            logical_names,
            mapping,
            physical_names,
            syndrome_couplings=[],
            coupling_type=coupling_type,
            coupling_strength=coupling_strength,
            calibrate_cnot=False,
        )

        # ── Active state: data qubits of every logical block, initially |00...0> ──
        active_names = []
        for l_name in logical_names:
            active_names.extend(mapping[l_name]["data"])
        active_dims = [
            min(2, self.qubit_engine.get_qubit(name).truncated_dim)
            for name in active_names
        ]
        print(f"[EC] 4. Initialising physical state to |00...0> ({len(active_names)} data qubits)...")
        current_state = qt.tensor([qt.basis(d, 0) for d in active_dims])
        current_state.dims = [list(active_dims), [1] * len(active_dims)]

        print(f"[EC]    Encoding |0>_L for {len(logical_names)} logical qubit(s)...")
        for l_name in logical_names:
            current_state = self._encode_logical_zero(
                l_name, mapping, code, active_names, active_dims, current_state,
            )

        # ── Execute logical circuit, gate by gate ──────────────────────
        print(f"\n[EC] 5. Executing logical circuit ({len(logical_circuit)} gates)...\n")
        gate_counter = 0

        for step_idx, instruction in enumerate(logical_circuit):
            gate_label = instruction.get("type", "?")
            target     = instruction.get("target", "?")
            print(f"  [Gate {step_idx:03d}] {gate_label}  target={target}")

            current_state = self._transversal_drives(
                instruction, logical_names, mapping, code,
                active_names, active_dims, calibrations,
                current_state,
            )

            gate_counter += 1

            if ec_every_n_gates > 0 and gate_counter % ec_every_n_gates == 0:
                print(f"  [EC cycle after gate {step_idx}]")
                for l_name in logical_names:
                    current_state = self._run_steane7_syndrome_block(
                        l_name, mapping, code, active_names, active_dims, current_state,
                    )

        current_state = self._inject_errors(
            inject_errors, mapping, active_names, active_dims, current_state
        )

        # ── Final syndrome pass (always runs) ──────────────────────────
        print("  [EC final syndrome pass]")
        for l_name in logical_names:
            current_state = self._run_steane7_syndrome_block(
                l_name, mapping, code, active_names, active_dims, current_state,
            )

        # By now every ancilla has been reclaimed, so active_names/active_dims
        # are exactly the data qubits again, in the same order as at the top.
        active_index = {name: idx for idx, name in enumerate(active_names)}

        print("\n[EC] 6. Circuit complete. Decoding final logical populations...")
        logical_pops = self._decode_logical_state(
            current_state, logical_names, mapping, code, active_names, active_index, active_dims
        )

        print("[EC] Logical state populations:")
        if not logical_pops:
            print("    [EC] WARNING: no logical populations decoded.")
        for bitstring, pop in sorted(logical_pops.items(), key=lambda x: -x[1]):
            bar = "█" * int(pop * 20) + "░" * (20 - int(pop * 20))
            print(f"    |{bitstring}>_L  {bar}  {pop * 100:5.2f}%")

        self._last_ec_result = {
            "logical_populations":  logical_pops,
            "final_physical_state": current_state,
            "data_axes":            {
                name: [active_names.index(d) for d in mapping[name]["data"]] for name in logical_names
            },
            "syndromes":            dict(self._last_syndromes),
        }

    def _run_steane7_syndrome_block(
        self,
        l_name: str,
        mapping: Dict,
        code: StabilizerCode,
        active_names: List[str],
        active_dims: List[int],
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Steane-code counterpart of `_run_shor9_syndrome_block`: runs one
        full syndrome-extraction + measurement + correction cycle for one
        logical block, generator by generator, tensoring each generator's
        ancilla in fresh right before it is needed and reclaiming (removing)
        its dimension immediately after measuring it
        (`_reclaiming_syndrome_block`). `active_names` and `active_dims`
        are mutated IN PLACE to track whatever is currently tensored into
        `current_state`; both are back to exactly the data qubits (in their
        original order) by the time this method returns.
        """
        return self._reclaiming_syndrome_block(
            l_name, mapping, code, active_names, active_dims, current_state
        )

    def execute_stabilizer_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        code: StabilizerCode = REPETITION_3,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> Dict:
        """
        Full stabilizer-code EC workflow, generic over any CSS
        `StabilizerCode` (see stabilizer_codes.py). Defaults to the 3-qubit
        repetition code.

        Parameters
        ----------
        logical_names : list of str
            Names of the logical qubits (must exist in QubitEngine).
            Each is expanded to (code.num_data + code.num_ancilla) physical
            qubits in memory only — they are NEVER written to the session
            JSON file.
        qasm_path : str
            Path to an OpenQASM 2.0 file for the logical circuit.
        code : StabilizerCode
            The stabilizer code specification to encode against (default:
            the 3-qubit repetition code).
        coupling_type : str
            Coupling type for syndrome-extraction CNOTs (default: "capacitive").
        coupling_strength : float
            Coupling strength in GHz (default: 0.010).
        ec_every_n_gates : int
            Run a syndrome cycle after every N gates (default: 1).
            Set to 0 to skip all mid-circuit syndromes and run only a single
            final syndrome pass.  Use 0 for circuits with H gates / superpositions,
            because Z-stabiliser measurement collapses X-basis states mid-circuit.
        inject_errors : list of (str, int, str), optional
            Pauli errors applied just before the final syndrome pass, each as
            (logical qubit name, local data-qubit index, "X" | "Y" | "Z").
        """

        # ── Step 1: Parse logical QASM ─────────────────────────────────
        print(f"[EC] 1. Parsing logical QASM from '{qasm_path}'...")
        transpiler      = QASMTranspiler()
        logical_circuit = transpiler.parse_file(qasm_path)
        print(f"[EC]    {len(logical_circuit)} logical instructions parsed.")

        print_logical_circuit_diagram(qasm_path, title="[EC] Logical circuit (error correction hidden)")

        # ── Step 2: Map & inject physical qubits (alias-only, no disk write) ─
        print(f"[EC] 2. Generating physical qubit mapping for '{code.name}'...")
        mapping        = self.generate_stabilizer_mapping(logical_names, code)
        physical_names = self._get_flat_physical_names(logical_names, mapping)
        print(
            f"[EC]    Logical qubits : {logical_names}\n"
            f"[EC]    Physical qubits: {physical_names}"
        )

        # Register physical qubits into QubitEngine using create_qubit(),
        # which saves them to the session JSON so they survive every
        # load_session() call GateEngine makes internally.
        # _cleanup_physical_qubits() in the finally block deletes them all.
        self._register_physical_qubits(logical_names, mapping)

        try:
            self._run_ec_workflow(
                logical_names    = logical_names,
                logical_circuit  = logical_circuit,
                mapping          = mapping,
                code             = code,
                physical_names   = physical_names,
                coupling_type    = coupling_type,
                coupling_strength = coupling_strength,
                ec_every_n_gates  = ec_every_n_gates,
                inject_errors=inject_errors,
            )
            result = self._last_ec_result
        finally:
            # Always runs — deletes all physical data/ancilla qubits from
            # QubitEngine and the session JSON so they never appear in the
            # normal qubit list after the workflow completes.
            self._cleanup_physical_qubits(logical_names, mapping)

        return result

    # ------------------------------------------------------------------
    # 9b. Inner workflow (runs with aliases active)
    # ------------------------------------------------------------------

    def _run_ec_workflow(
        self,
        logical_names: List[str],
        logical_circuit: List[Dict],
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        coupling_type: str,
        coupling_strength: float,
        ec_every_n_gates: int,
        inject_errors: Optional[List[Tuple[str, int, str]]] = None,
    ) -> None:
        # ── Step 3: Collect local dims ─────────────────────────────────
        dims = [
            self.qubit_engine.get_qubit(name).truncated_dim
            for name in physical_names
        ]

        physical_index = {
            name: idx
            for idx, name in enumerate(physical_names)
        }
        print(f"[EC]    Local dims: {dims}")

        # ── Step 4: Build coupling topology ────────────────────────────
        print("[EC] 3. Building syndrome-extraction coupling topology...")
        syndrome_couplings = self._build_physical_couplings(
            logical_names,
            mapping,
            code,
            physical_names,
            physical_index,
            coupling_type,
            coupling_strength,
        )
        print(f"[EC]    {len(syndrome_couplings)} coupling links defined.")

        # ── Step 5: Calibrate pulses ────────────────────────────────────
        print("[EC] 4. Calibrating pulses (results cached for re-use)...")
        calibrations = self._calibrate(
            logical_names,
            mapping,
            physical_names,
            syndrome_couplings,
            coupling_type,
            coupling_strength,
            calibrate_cnot=False,
        )

        # ── Step 6: Initial state |00...0> ─────────────────────────────
        print("[EC] 5. Initialising physical state to |00...0>...")
        ground_states = [qt.basis(d, 0) for d in dims]
        current_state = qt.tensor(ground_states)
        current_state.dims = [list(dims), [1] * len(dims)]

        # ── Step 6b: Encode |0>_L for every logical block ───────────────
        # |00...0> is only itself the codeword |0>_L for codes where the
        # logical zero happens to coincide with a computational basis state
        # (true of the repetition code, NOT true in general -- e.g. the
        # Shor code's |0>_L is a genuine multi-term superposition). Running
        # code.encoding_circuit turns the physical |00...0> state into the
        # actual |0>_L codeword; for the repetition code this is a
        # mathematical no-op (verified in stabilizer_codes.py).
        if code.encoding_circuit:
            print(f"[EC]    Encoding |0>_L for {len(logical_names)} logical qubit(s)...")
            for l_name in logical_names:
                current_state = self._encode_logical_zero(
                    l_name, mapping, code, physical_names, dims, current_state,
                )

        # ── Step 7: Execute logical circuit, gate by gate ──────────────
        print(f"\n[EC] 6. Executing logical circuit ({len(logical_circuit)} gates)...\n")
        gate_counter = 0

        for step_idx, instruction in enumerate(logical_circuit):
            gate_label = instruction.get("type", "?")
            target     = instruction.get("target", "?")
            print(f"  [Gate {step_idx:03d}] {gate_label}  target={target}")

            # 7a. Transversal logical gate
            current_state = self._transversal_drives(
                instruction, logical_names, mapping, code,
                physical_names, dims, calibrations,
                current_state,
            )

            gate_counter += 1

            # 7b. Mid-circuit syndrome extraction
            # ec_every_n_gates=0 => skip all mid-circuit syndromes
            if ec_every_n_gates > 0 and gate_counter % ec_every_n_gates == 0:
                print(f"  [EC cycle after gate {step_idx}]")
                for l_name in logical_names:
                    current_state = self._run_syndrome_block(
                        l_name, mapping, code, physical_names, physical_index, dims,
                        calibrations, coupling_strength, coupling_type,
                        current_state,
                    )

        current_state = self._inject_errors(
            inject_errors, mapping, physical_names, dims, current_state
        )

        # ── Step 8: Final syndrome pass (always runs) ──────────────────
        print("  [EC final syndrome pass]")
        for l_name in logical_names:
            current_state = self._run_syndrome_block(
                l_name, mapping, code, physical_names, physical_index, dims,
                calibrations, coupling_strength, coupling_type,
                current_state,
            )

        # ── Step 9: Decode ─────────────────────────────────────────────
        print("\n[EC] 7. Circuit complete. Decoding final logical populations...")
        logical_pops = self._decode_logical_state(
            current_state, logical_names, mapping, code, physical_names, physical_index, dims
        )

        print("[EC] Logical state populations (majority-vote decoded):")
        if not logical_pops:
            print("    [EC] WARNING: no logical populations decoded (all diagonal entries < 1e-8).")
            print(f"    [EC] Full state type={current_state.type}, dims={current_state.dims}")
        for bitstring, pop in sorted(logical_pops.items(), key=lambda x: -x[1]):
            bar = "█" * int(pop * 20) + "░" * (20 - int(pop * 20))
            print(f"    |{bitstring}>_L  {bar}  {pop * 100:5.2f}%")

        self._last_ec_result = {
            "logical_populations":  logical_pops,
            "final_physical_state": current_state,
            "data_axes":            {
                name: [physical_names.index(d) for d in mapping[name]["data"]] for name in logical_names
            },
            "syndromes":            dict(self._last_syndromes),
        }

    # ------------------------------------------------------------------
    # 9c. Helper: run one syndrome block (simulation + measurement)
    # ------------------------------------------------------------------

    def _run_syndrome_block(
        self,
        l_name: str,
        mapping: Dict,
        code: StabilizerCode,
        physical_names: List[str],
        physical_index,
        dims: List[int],
        calibrations: Dict,
        coupling_strength: float,
        coupling_type: str,
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Run one full syndrome-extraction + measurement + correction cycle
        for one logical block, GENERATOR BY GENERATOR.

        Each stabilizer generator is extracted and measured using ONLY the
        small subsystem of qubits it actually touches (its own data qubits
        + its own ancilla) rather than the whole logical block at once.
        This keeps every simulated subsystem's Hilbert-space dimension
        bounded by the code's largest generator WEIGHT (2-3 qubits for the
        repetition code, up to 7 for a Shor-code X-generator) instead of
        the code's total qubit count (5 for the repetition code, but 17 for
        Shor) — required for the 9-qubit Shor code to be tractable at all
        with this engine's dense-matrix simulation backend. Because all of
        a valid code's generators mutually commute, this generator-by-
        generator processing gives EXACTLY the same joint syndrome
        distribution and post-measurement state as extracting/measuring
        everything jointly (see _measure_and_collapse_ancilla).
        """
        print(f"    Syndrome extraction for logical block: {l_name}")

        data_names = mapping[l_name]["data"]
        anc_names  = mapping[l_name]["ancilla"]

        syndrome_bits: List[int] = [0] * code.num_ancilla

        for gen in code.generators:
            anc_name        = anc_names[gen.ancilla]
            gen_data_names  = [data_names[dq] for dq in gen.data_qubits]
            sub_names       = gen_data_names + [anc_name]

            drives = self._generator_extraction_drives(gen)
            current_state = self._simulate_subsystem(
                sub_names      = sub_names,
                sub_drives     = drives,
                sub_couplings  = [],
                duration       = 0.0,
                full_state     = current_state,
                full_names     = physical_names,
                full_dims      = dims,
                gate_label     = "EC_Syndrome",
            )

            anc_idx = physical_index[anc_name]
            current_state, bit = self._measure_and_collapse_ancilla(
                current_state, anc_idx, dims, f"{l_name}:{anc_name}",
            )
            syndrome_bits[gen.ancilla] = bit

        syndrome = tuple(syndrome_bits)
        self._last_syndromes[l_name] = syndrome
        print(f"    [EC] {l_name}  syndrome {syndrome}")

        # Feed-forward correction(s), looked up from the code's syndrome table.
        data_idxs   = [physical_index[n] for n in data_names]
        corrections = code.syndrome_to_correction.get(syndrome, [])
        for local_dq, pauli_type in corrections:
            target_idx = data_idxs[local_dq]
            label = physical_names[target_idx]
            print(f"    [EC] Applying {pauli_type} correction to {label}")
            current_state = _apply_pauli_to_ket(current_state, pauli_type, target_idx, dims)

        # Reset every ancilla found in |1> back to |0>.
        for anc_name, bit in zip(anc_names, syndrome_bits):
            if bit == 1:
                anc_idx = physical_index[anc_name]
                current_state = _apply_pauli_to_ket(current_state, "X", anc_idx, dims)

        return current_state
