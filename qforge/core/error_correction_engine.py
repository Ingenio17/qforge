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
convention used throughout qforge.

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
from typing import List, Dict, Tuple, Any

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.core.workflow_engine import PhysicalWorkflowEngine, QASMTranspiler, print_logical_circuit_diagram
from qforge.core.stabilizer_codes import (
    StabilizerCode,
    StabilizerGenerator,
    EncodingStep,
    REPETITION_3,
    SHOR_9,
    STEANE_7,
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
        Calibrate X durations, exploiting the fact that every physical qubit
        in a logical block is a perfect clone of its parent.

        Strategy
        --------
        Single-qubit X
            Calibrate once per unique (qubit_type, params) fingerprint.
            Reuse the representative result directly.  The EC simulator does
            not call ``calibrate_gate`` for every clone, so it must not rely on
            GateEngine's private cache-key format.

        CNOT syndrome pairs
            Retained for callers that explicitly request calibration.  Normal
            EC execution uses ideal logical CX instructions for syndrome
            extraction and therefore does not need a physical CNOT duration.
        """
        # x_amp stores the amplitude used for the X-pi calibration.
        # H uses amp_h = x_amp / 2 with the same duration (t_h = t_x).
        calibrations: Dict[str, Any] = {"x_dur": {}, "x_amp": {}, "cnot_dur": {}}

        # ── Single-qubit X ─────────────────────────────────────────── #
        print("[EC] Calibrating X pulses (one calibration per unique qubit type)...")

        # fingerprint -> (best_dur, best_metric)
        x_results: Dict[tuple, Tuple[float, float]] = {}

        for l_name in logical_names:
            for p_name in mapping[l_name]["data"] + mapping[l_name]["ancilla"]:
                q_data = self.qubit_engine._qubits[p_name]
                fp     = (q_data["type"], tuple(sorted(q_data["params"].items())))

                if fp not in x_results:
                    # First qubit of this type — run the calibration sweep
                    print(f"[EC]   Calibrating X for type '{q_data['type']}' "
                          f"(representative: {p_name})...")
                    dur, metric = self.gate_engine.calibrate_gate(
                        p_name, gate_type="X", parameter="duration", amplitude=0.025
                    )
                    x_results[fp] = (dur, metric)
                else:
                    # Clone — reuse the representative result directly.
                    dur, metric = x_results[fp]
                    print(f"[EC]   {p_name}: clone → calibration reused "
                          f"(dur={dur:.4f}, metric={metric:.4f})")

                calibrations["x_dur"][p_name] = dur
                calibrations["x_amp"][p_name] = 0.025  # amplitude used for pi-pulse calibration

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
        deleted = []
        for l_name in logical_names:
            for p_name in mapping[l_name]["data"] + mapping[l_name]["ancilla"]:
                try:
                    self.qubit_engine.delete_qubit(p_name)
                    deleted.append(p_name)
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
        N = len(full_dims)
        remain_idxs = [i for i in range(N) if i not in set(sub_global_idxs)]

        if remain_idxs:
            I_remain = qt.tensor([qt.qeye(full_dims[i]) for i in remain_idxs])
            U_combined = qt.tensor(U_sub, I_remain)
            all_ordered = sub_global_idxs + remain_idxs
            combined_dims = [full_dims[i] for i in all_ordered]
            U_combined.dims = [list(combined_dims), list(combined_dims)]
            perm = [all_ordered.index(i) for i in range(N)]
            U_full = U_combined.permute(perm)
        else:
            U_full = U_sub

        U_full.dims = [list(full_dims), list(full_dims)]

        if full_state.type == "ket":
            new_state = U_full * full_state
            new_state.dims = [list(full_dims), [1] * N]
        else:
            rho = full_state if full_state.type == "oper" else qt.ket2dm(full_state)
            rho.dims = [list(full_dims), list(full_dims)]
            new_state = U_full * rho * U_full.dag()
            new_state.dims = [list(full_dims), list(full_dims)]

        #DEBUG PRINT

        print(
            "State change:",
            (new_state - full_state).norm()
        )

        #DEBUG END
        
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

        ideal_cx_pairs = []  # (local_ctrl, local_targ) for ideal CX drives
        ideal_cz_pairs = []  # (local_a, local_b) for ideal CZ drives
        ideal_single_qubit_ops = []  # (gate_name, local_idx) for ideal X/H drives
        ideal_rz_ops = []  # (local_idx, theta, pauli_type) for ideal RZ drives
        has_only_ideal = True
        x_drives = []  # (local_idx, amplitude, phase) for microwave drives

        for drv in sub_drives:
            drv_type = drv.get("type", "")

            if drv_type == "ICX":
                ideal_cx_pairs.append(
                    (
                        int(drv["control"]),
                        int(drv["target"]),
                    )
                )
            elif drv_type == "ICZ":
                ideal_cz_pairs.append(
                    (
                        int(drv["control"]),
                        int(drv["target"]),
                    )
                )
            elif drv_type in ("X", "H", "Z"):
                target_val = drv.get("target")
                if isinstance(target_val, (tuple, list)):
                    target_idx = int(target_val[0])
                else:
                    target_idx = int(target_val)
                ideal_single_qubit_ops.append((drv_type, target_idx))
            elif drv_type == "RZ":
                target_val = drv.get("target")
                if isinstance(target_val, (tuple, list)):
                    target_idx = int(target_val[0])
                else:
                    target_idx = int(target_val)
                ideal_rz_ops.append(
                    (target_idx, float(drv["theta"]), drv.get("pauli_type", "Z"))
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

            for drv_type, target_idx in ideal_single_qubit_ops:
                U_step = self.gate_engine._build_ideal_single_qubit_operator(
                    sub_dims,
                    target_idx,
                    drv_type,
                )
                U_sub = U_step * U_sub

            for target_idx, theta, pauli_type in ideal_rz_ops:
                U_step = self.gate_engine._build_ideal_rz_operator(
                    sub_dims,
                    target_idx,
                    theta,
                    pauli_type,
                )
                U_sub = U_step * U_sub

            for control_idx, target_idx in ideal_cx_pairs:
                U_step = self.gate_engine._build_ideal_cx_operator(
                    sub_dims,
                    control_idx,
                    target_idx,
                )
                U_sub = U_step * U_sub

            for idx_a, idx_b in ideal_cz_pairs:
                U_step = _build_ideal_cz_operator(
                    sub_dims,
                    idx_a,
                    idx_b,
                )
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

        # DEBUG
        print(
            "Hamiltonian unitary deviation from identity:",
            np.linalg.norm(U_sub.full() - np.eye(U_sub.shape[0]))
        )
        # END DEBUG

        # Apply coupler-pulse CZ unitaries on top, one pair at a time
        #
        # Apply ideal CX operators.
        #

        for control_idx, target_idx in ideal_cx_pairs:

            U_icx = self.gate_engine._build_ideal_cx_operator(
                sub_dims,
                control_idx,
                target_idx,
            )

            U_sub = U_icx * U_sub

        for idx_a, idx_b in ideal_cz_pairs:

            U_icz = _build_ideal_cz_operator(
                sub_dims,
                idx_a,
                idx_b,
            )

            U_sub = U_icz * U_sub


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
        |00...0>), one gate at a time.

        Every step is a single-qubit H or a 2-qubit ideal CNOT, so each is
        simulated as its own small subsystem — consistent with the rest of
        this engine's "never simulate a whole large code block as one
        subsystem" approach, and required for the 9-qubit Shor code's
        11-gate encoding circuit to be tractable.
        """
        data = mapping[l_name]["data"]

        for step in code.encoding_circuit:
            if step.gate == "H":
                p = data[step.target]
                current_state = self._simulate_subsystem(
                    sub_names=[p],
                    sub_drives=[{"type": "H", "target": 0}],
                    duration=0.0,
                    sub_couplings=[],
                    full_state=current_state,
                    full_names=physical_names,
                    full_dims=full_dims,
                    gate_label="EC_Encode",
                )
            else:  # "ICX"
                p_ctrl = data[step.control]
                p_targ = data[step.target]
                current_state = self._simulate_subsystem(
                    sub_names=[p_ctrl, p_targ],
                    sub_drives=[{"type": "ICX", "control": 0, "target": 1}],
                    duration=0.0,
                    sub_couplings=[],
                    full_state=current_state,
                    full_names=physical_names,
                    full_dims=full_dims,
                    gate_label="EC_Encode",
                )

        return current_state

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
            H   -- applied to every data qubit (unchanged from the
                   repetition code's original transversal-H behaviour).
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

        def _make_single_qubit_drive(
            phys_name: str, pauli_type: str, phase: float = 0.0, amplitude: float = 0.025,
        ) -> Tuple[Dict, float]:
            dur       = calibrations["x_dur"][phys_name]
            qubit_obj = self.qubit_engine.get_qubit(phys_name)
            evals     = qubit_obj.eigensys(evals_count=2)[0]
            w01       = float(evals[1] - evals[0])
            drive = {
                "target":     0,
                "type":       pauli_type,
                "amplitude":  amplitude,
                "frequency":  w01,
                "phase":      phase,
                "start_time": 0.0,
                "end_time":   dur,
            }
            return drive, dur

        def _make_h_drive(phys_name: str) -> Tuple[Dict, float]:
            # H gate uses the SAME duration as X (t_h = t_x) but half the
            # amplitude.  Using t_x/2 is wrong: Gaussian area is nonlinear
            # in T, so halving T does not halve the rotation angle.
            amp_pi = calibrations["x_amp"].get(phys_name, 0.025)
            return _make_single_qubit_drive(
                phys_name, "H", phase=-np.pi / 2, amplitude=amp_pi / 2.0
            )

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
                    drv, dur = _make_single_qubit_drive(p, code.logical_x_pauli)
                    current_state = self._simulate_subsystem(
                        sub_names=[p],
                        sub_drives=[drv],
                        duration=dur,
                        sub_couplings=[],
                        full_state=current_state,
                        full_names=physical_names,
                        full_dims=full_dims,
                        gate_label=f"EC_{gate}",
                    )

            elif gate == "H":
                for p in data:
                    drv, dur = _make_h_drive(p)
                    current_state = self._simulate_subsystem(
                        sub_names=[p],
                        sub_drives=[drv],
                        duration=dur,
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

            if gate in ("CX", "CNOT", "CZ"):
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
        d_anc = dims[anc_idx]
        proj0 = _tensor_op_at(_proj0_dim(d_anc), anc_idx, dims)
        proj1 = _tensor_op_at(_proj1_dim(d_anc), anc_idx, dims)

        # QuTiP's inner product can return either a 1x1 Qobj or a plain
        # complex scalar depending on version — extract a real float safely
        # in either case.
        def _qobj_to_real(val) -> float:
            if isinstance(val, qt.Qobj):
                arr = val.full().flatten()
                return float(np.real(arr[0]))
            return float(np.real(val))

        if state.type == "ket":
            p0 = _qobj_to_real(state.dag() * proj0 * state)
            p1 = _qobj_to_real(state.dag() * proj1 * state)
        else:
            p0 = float(np.real((proj0 * state).tr()))
            p1 = float(np.real((proj1 * state).tr()))

        total = p0 + p1
        if total < 1e-12:
            print(f"    [EC] Warning: total probability ~0 measuring {label}. State may be corrupted.")
            return state, 0

        p0n  = p0 / total
        bit  = int(np.random.choice([0, 1], p=[p0n, 1.0 - p0n]))
        proj = proj1 if bit == 1 else proj0
        prob = (1.0 - p0n) if bit == 1 else p0n

        collapsed = proj * state
        if prob > 1e-12:
            collapsed = collapsed / np.sqrt(prob)

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

    def _measure_and_reclaim_ancilla(
        self,
        state: qt.Qobj,
        dims: List[int],
        idx: int,
        label: str,
    ) -> Tuple[qt.Qobj, int]:
        """
        Projectively measure the ancilla at local position `idx` (within
        the CURRENT tensor structure `dims`, a ket) in the Z basis, and
        return a NEW, SMALLER ket with that qubit's axis removed entirely
        (rather than collapsed-and-kept). See the section comment above for
        why this is exact, not an approximation.
        """
        arr = state.full().reshape(dims)
        p0 = float(np.sum(np.abs(np.take(arr, 0, axis=idx)) ** 2))
        p1 = float(np.sum(np.abs(np.take(arr, 1, axis=idx)) ** 2))
        total = p0 + p1

        if total < 1e-12:
            print(f"    [EC] Warning: total probability ~0 measuring {label}. State may be corrupted.")
            bit, prob = 0, 0.0
        else:
            p0n  = p0 / total
            bit  = int(np.random.choice([0, 1], p=[p0n, 1.0 - p0n]))
            prob = (1.0 - p0n) if bit == 1 else p0n

        sliced = np.take(arr, bit, axis=idx)
        norm = np.linalg.norm(sliced)
        if norm > 1e-12:
            sliced = sliced / norm

        remaining_dims = [d for i, d in enumerate(dims) if i != idx]
        new_total = int(np.prod(remaining_dims)) if remaining_dims else 1
        new_ket = qt.Qobj(sliced.reshape(new_total, 1))
        new_ket.dims = [remaining_dims, [1] * len(remaining_dims)]

        print(f"      [EC] {label}  bit={bit}  p={prob:.4f}")
        return new_ket, bit

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
            rho = qt.ket2dm(state)
        else:
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
        """
        return self.execute_stabilizer_workflow(
            logical_names=logical_names,
            qasm_path=qasm_path,
            code=REPETITION_3,
            coupling_type=coupling_type,
            coupling_strength=coupling_strength,
            ec_every_n_gates=ec_every_n_gates,
        )

    def execute_shor9_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
    ) -> Dict:
        """
        Entry point for the 9-qubit Shor code.

        Runs a dedicated, ancilla-reclaiming execution path (see
        `_run_shor9_workflow` / `_run_shor9_syndrome_block` /
        `_measure_and_reclaim_ancilla`) instead of the generic
        `execute_stabilizer_workflow`: the generic path keeps one dense
        state vector spanning EVERY physical qubit -- data AND ancilla --
        for the whole workflow, which is fine for the repetition code (2
        ancillas) but is only 2 logical qubits away from needing hundreds
        of GB for the Shor code (8 ancillas per block). This path instead
        reclaims each ancilla's dimension immediately after it is measured
        (exact, not an approximation -- see `_measure_and_reclaim_ancilla`),
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
        qforge). This is exact here, not an approximation: every gate this
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
        (`_measure_and_reclaim_ancilla`), instead of registering all 8
        ancillas in the state up front and keeping them forever. `active_names`
        and `active_dims` are mutated IN PLACE to track whatever is
        currently tensored into `current_state`; both are back to exactly
        the data qubits (in their original order) by the time this method
        returns.
        """
        print(f"    Syndrome extraction for logical block: {l_name}")

        data_names = mapping[l_name]["data"]
        anc_names  = mapping[l_name]["ancilla"]
        syndrome_bits: List[int] = [0] * code.num_ancilla

        for gen in code.generators:
            anc_name = anc_names[gen.ancilla]
            # Capped at 2 for the same reason active_dims is in
            # _run_shor9_workflow: exact (not approximate) for this
            # ideal-gate-only workflow, and necessary for tractability.
            d_anc = min(2, self.qubit_engine.get_qubit(anc_name).truncated_dim)

            # Tensor a fresh |0> ancilla onto the END of the active state.
            current_state = qt.tensor(current_state, qt.basis(d_anc, 0))
            active_names.append(anc_name)
            active_dims.append(d_anc)
            current_state.dims = [list(active_dims), [1] * len(active_dims)]

            gen_data_names = [data_names[dq] for dq in gen.data_qubits]
            sub_names      = gen_data_names + [anc_name]
            drives         = self._generator_extraction_drives(gen)
            current_state = self._simulate_subsystem(
                sub_names      = sub_names,
                sub_drives     = drives,
                sub_couplings  = [],
                duration       = 0.0,
                full_state     = current_state,
                full_names     = active_names,
                full_dims      = active_dims,
                gate_label     = "EC_Syndrome",
            )

            anc_idx = active_names.index(anc_name)
            current_state, bit = self._measure_and_reclaim_ancilla(
                current_state, active_dims, anc_idx, f"{l_name}:{anc_name}",
            )
            syndrome_bits[gen.ancilla] = bit

            # The ancilla's dimension is gone from current_state now — drop
            # its bookkeeping entries too so active_names/active_dims stay
            # in sync with what's actually tensored into current_state.
            del active_names[anc_idx]
            del active_dims[anc_idx]

        syndrome = tuple(syndrome_bits)
        print(f"    [EC] {l_name}  syndrome {syndrome}")

        # Feed-forward correction(s), looked up from the code's syndrome table.
        # No ancilla reset is needed here (unlike _run_syndrome_block): a
        # reclaimed ancilla has already been removed from the state, so
        # there is nothing left to reset -- the next syndrome round tensors
        # in a brand new |0> ancilla instead.
        active_index = {name: idx for idx, name in enumerate(active_names)}
        data_idxs    = [active_index[n] for n in data_names]
        corrections  = code.syndrome_to_correction.get(syndrome, [])
        for local_dq, pauli_type in corrections:
            target_idx = data_idxs[local_dq]
            label = active_names[target_idx]
            print(f"    [EC] Applying {pauli_type} correction to {label}")
            P_op   = _pauli_dim(pauli_type, active_dims[target_idx])
            P_full = _tensor_op_at(P_op, target_idx, active_dims)
            current_state = P_full * current_state

        return current_state

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

        CZ has no such simple fix and is not supported here: a transversal
        physical CZ is diagonal in the PHYSICAL Z basis, but the Shor
        code's logical Z-basis corresponds to the PHYSICAL X eigenbasis
        (since Z-bar is X-type), so a transversal physical CZ is diagonal
        in the wrong basis to implement logical CZ for this code at all --
        unlike CNOT, swapping control/target does not fix this (CZ is
        symmetric under that swap). A warning is printed and the gate is
        skipped rather than silently returning a wrong answer.
        """
        gate = instruction["type"].upper()
        l1_idx, l2_idx = instruction["target"]
        l1 = logical_names[l1_idx]
        l2 = logical_names[l2_idx]
        data1 = mapping[l1]["data"]   # circuit's control block
        data2 = mapping[l2]["data"]   # circuit's target block

        if gate == "CZ":
            print(
                "[EC] Warning: logical CZ is not supported for the Shor "
                "code (a transversal physical CZ does not implement it -- "
                "see _shor9_transversal_two_qubit_gate); skipping."
            )
            return current_state

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
        not an approximation -- see `_measure_and_reclaim_ancilla`) and
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
            )
            result = self._last_ec_result
        finally:
            self._cleanup_physical_qubits(logical_names, mapping)

        return result

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
        (`_measure_and_reclaim_ancilla`). `active_names` and `active_dims`
        are mutated IN PLACE to track whatever is currently tensored into
        `current_state`; both are back to exactly the data qubits (in their
        original order) by the time this method returns.
        """
        print(f"    Syndrome extraction for logical block: {l_name}")

        data_names = mapping[l_name]["data"]
        anc_names  = mapping[l_name]["ancilla"]
        syndrome_bits: List[int] = [0] * code.num_ancilla

        for gen in code.generators:
            anc_name = anc_names[gen.ancilla]
            d_anc = min(2, self.qubit_engine.get_qubit(anc_name).truncated_dim)

            # Tensor a fresh |0> ancilla onto the END of the active state.
            current_state = qt.tensor(current_state, qt.basis(d_anc, 0))
            active_names.append(anc_name)
            active_dims.append(d_anc)
            current_state.dims = [list(active_dims), [1] * len(active_dims)]

            gen_data_names = [data_names[dq] for dq in gen.data_qubits]
            sub_names      = gen_data_names + [anc_name]
            drives         = self._generator_extraction_drives(gen)
            current_state = self._simulate_subsystem(
                sub_names      = sub_names,
                sub_drives     = drives,
                sub_couplings  = [],
                duration       = 0.0,
                full_state     = current_state,
                full_names     = active_names,
                full_dims      = active_dims,
                gate_label     = "EC_Syndrome",
            )

            anc_idx = active_names.index(anc_name)
            current_state, bit = self._measure_and_reclaim_ancilla(
                current_state, active_dims, anc_idx, f"{l_name}:{anc_name}",
            )
            syndrome_bits[gen.ancilla] = bit

            del active_names[anc_idx]
            del active_dims[anc_idx]

        syndrome = tuple(syndrome_bits)
        print(f"    [EC] {l_name}  syndrome {syndrome}")

        # Feed-forward correction(s), looked up from the code's syndrome table.
        active_index = {name: idx for idx, name in enumerate(active_names)}
        data_idxs    = [active_index[n] for n in data_names]
        corrections  = code.syndrome_to_correction.get(syndrome, [])
        for local_dq, pauli_type in corrections:
            target_idx = data_idxs[local_dq]
            label = active_names[target_idx]
            print(f"    [EC] Applying {pauli_type} correction to {label}")
            P_op   = _pauli_dim(pauli_type, active_dims[target_idx])
            P_full = _tensor_op_at(P_op, target_idx, active_dims)
            current_state = P_full * current_state

        return current_state

    def execute_stabilizer_workflow(
        self,
        logical_names: List[str],
        qasm_path: str,
        code: StabilizerCode = REPETITION_3,
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
        ec_every_n_gates: int = 0,
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

            #DEBUG PRINT
            print("\nNorm:", current_state.norm())
            print(current_state)

            #DEBUG END

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
        print(f"    [EC] {l_name}  syndrome {syndrome}")

        # Feed-forward correction(s), looked up from the code's syndrome table.
        data_idxs   = [physical_index[n] for n in data_names]
        corrections = code.syndrome_to_correction.get(syndrome, [])
        for local_dq, pauli_type in corrections:
            target_idx = data_idxs[local_dq]
            label = physical_names[target_idx]
            print(f"    [EC] Applying {pauli_type} correction to {label}")
            P_op   = _pauli_dim(pauli_type, dims[target_idx])
            P_full = _tensor_op_at(P_op, target_idx, dims)
            current_state = P_full * current_state

        # Reset every ancilla found in |1> back to |0>.
        for anc_name, bit in zip(anc_names, syndrome_bits):
            if bit == 1:
                anc_idx = physical_index[anc_name]
                X_op   = _sigmax_dim(dims[anc_idx])
                X_full = _tensor_op_at(X_op, anc_idx, dims)
                current_state = X_full * current_state

        return current_state

