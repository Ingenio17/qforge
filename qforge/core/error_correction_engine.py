"""
error_correction_engine.py

Provides the ErrorCorrectionEngine with active mid-circuit measurement,
real-time feed-forward correction, and dynamic physical qubit allocation
for a 3-qubit repetition code.

Architecture
------------
Each *logical* qubit L is encoded into 5 *physical* qubits:
    D0 = L_D0   (data)
    D1 = L_D1   (data)
    D2 = L_D2   (data)
    A0 = L_A0   (ancilla – parity check D0⊕D1)
    A1 = L_A1   (ancilla – parity check D1⊕D2)

Physical qubits in each block are clones of the original logical qubit
(same scqubits type and parameters), matching the "same name → same type"
convention used throughout qforge.

Workflow per execute_3q_repetition_workflow() call
--------------------------------------------------
1. Parse the logical QASM circuit (QASMTranspiler → list of dicts).
2. Register all physical qubits in QubitEngine (clone of the logical qubit).
3. Build the full physical coupling list (capacitive, used for CNOT drives).
4. Calibrate single-qubit X and two-qubit CNOT pulse durations once.
5. For every logical instruction:
   a. Map the logical gate to a *transversal* physical drive schedule
      (apply the gate to every data qubit in the logical block).
   b. Physically simulate the drives from the current quantum state.
   c. Run a syndrome extraction cycle:
      - Build CNOT drives: D0→A0, D1→A0, D1→A1, D2→A1.
      - Physically simulate the syndrome CNOTs.
      - Measure (project) each ancilla pair, collapse the wavefunction.
      - Apply feed-forward X corrections to the indicated data qubit.
      - Reset ancillas back to |0⟩ via X if they were found in |1⟩.
6. Decode the final physical state by majority-vote on data qubits.

Syndrome table (standard 3-qubit repetition code)
--------------------------------------------------
A0 detects D0⊕D1;  A1 detects D1⊕D2.
    (A0=0, A1=0) → no error
    (A0=1, A1=0) → error on D0  → correct with X on D0
    (A0=1, A1=1) → error on D1  → correct with X on D1
    (A0=0, A1=1) → error on D2  → correct with X on D2
"""

import numpy as np
import qutip as qt
from scipy.linalg import expm as scipy_expm
from typing import List, Dict, Tuple, Any

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.core.workflow_engine import PhysicalWorkflowEngine, QASMTranspiler


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


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class ErrorCorrectionEngine:
    """
    3-qubit repetition code engine with active, mid-circuit error correction.

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

    def generate_3q_repetition_mapping(
        self,
        logical_names: List[str],
    ) -> Dict[str, Dict[str, List[str]]]:
        """
        Return a mapping dict:
            { logical_name: {"data": [D0, D1, D2], "ancilla": [A0, A1]} }
        """
        mapping = {}
        for l_name in logical_names:
            mapping[l_name] = {
                "data":    [f"{l_name}_D0", f"{l_name}_D1", f"{l_name}_D2"],
                "ancilla": [f"{l_name}_A0", f"{l_name}_A1"],
            }
        return mapping

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
        physical_names,
        physical_index,
        coupling_type,
        coupling_strength,
    )-> List[Dict[str, Any]]:
        """
        Build capacitive couplings needed for syndrome extraction CNOTs.

        For each logical block we need:
            D0 — A0   (parity D0 ⊕ D1, first CNOT)
            D1 — A0   (parity D0 ⊕ D1, second CNOT)
            D1 — A1   (parity D1 ⊕ D2, first CNOT)
            D2 — A1   (parity D1 ⊕ D2, second CNOT)

        Note: D1 couples to *both* ancillas which is fine — we sequence the
        CNOTs in time so only one coupling is active per step.
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
            _add(d[0], a[0])   # D0-A0
            _add(d[1], a[0])   # D1-A0
            _add(d[1], a[1])   # D1-A1
            _add(d[2], a[1])   # D2-A1

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

        Each logical qubit L is expanded to 5 physical qubits:
            L_D0, L_D1, L_D2  — data qubits (same type/params as L)
            L_A0, L_A1        — ancilla qubits (truncated_dim=2, otherwise same)

        create_qubit() saves to the session JSON, so the qubits survive every
        load_session() call made internally by GateEngine.  They are cleaned up
        at the end of the workflow by _cleanup_physical_qubits().

        Qubits that already exist (e.g. on a re-run) are skipped safely.
        """
        existing = set(self.qubit_engine._qubits.keys())

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

            for p_name in mapping[l_name]["data"] + mapping[l_name]["ancilla"]:
                if p_name in existing:
                    continue
                params = (
                    anc_params
                    if p_name.endswith(("_A0", "_A1"))
                    else q_params
                )
                self.qubit_engine.create_qubit(q_type, p_name, params)
                existing.add(p_name)

        print(
            f"[EC] Physical qubits registered: "
            f"{5 * len(logical_names)} qubits for "
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
        once, inside the finally-block of execute_3q_repetition_workflow(),
        so it always fires even if the workflow crashes mid-run.

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
        ideal_single_qubit_ops = []  # (gate_name, local_idx) for ideal X/H drives
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
            elif drv_type in ("X", "H"):
                target_val = drv.get("target")
                if isinstance(target_val, (tuple, list)):
                    target_idx = int(target_val[0])
                else:
                    target_idx = int(target_val)
                ideal_single_qubit_ops.append((drv_type, target_idx))
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

            for control_idx, target_idx in ideal_cx_pairs:
                U_step = self.gate_engine._build_ideal_cx_operator(
                    sub_dims,
                    control_idx,
                    target_idx,
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


        U_sub.dims = [list(sub_dims), list(sub_dims)]

        # ── Apply unitary to full state (no ptrace — entanglement preserved) ─
        return self._apply_unitary_to_subsystem(
            U_sub, sub_global_idxs, full_state, full_dims
        )


    # ------------------------------------------------------------------
    # 6. Transversal logical gate → per-block subsystem simulations
    # ------------------------------------------------------------------

    def _transversal_drives(
        self,
        instruction: Dict[str, Any],
        logical_names: List[str],
        mapping: Dict,
        physical_names: List[str],
        full_dims: List[int],
        calibrations: Dict,
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """
        Apply a logical instruction transversally by simulating each
        involved logical block as a SMALL subsystem.

        Single-qubit gates  (H, X, RZ):
            Simulate only the 3 data qubits of the target logical block
            (subsystem dim [d,d,d], total ≤ 64 states).

        Two-qubit gates (CNOT/CZ between two logical blocks):
            Simulate pairs of data qubits across the two blocks one pair
            at a time: (D0_L1, D0_L2), (D1_L1, D1_L2), (D2_L1, D2_L2).

        Returns the updated full quantum state.
        """
        gate   = instruction["type"].upper()
        target = instruction["target"]

        def _make_x_drive(local_idx: int, phys_name: str, phase: float = 0.0) -> Tuple[Dict, float]:
            dur       = calibrations["x_dur"][phys_name]
            qubit_obj = self.qubit_engine.get_qubit(phys_name)
            evals     = qubit_obj.eigensys(evals_count=2)[0]
            w01       = float(evals[1] - evals[0])
            drive = {
                "target":     local_idx,
                "type":       "X",
                "amplitude":  0.025,
                "frequency":  w01,
                "phase":      phase,
                "start_time": 0.0,
                "end_time":   dur,
            }
            return drive, dur

        def _make_h_drive(local_idx: int, phys_name: str) -> Tuple[Dict, float]:
            # H gate uses the SAME duration as X (t_h = t_x) but half the
            # amplitude.  Using t_x/2 is wrong: Gaussian area is nonlinear
            # in T, so halving T does not halve the rotation angle.
            dur       = calibrations["x_dur"][phys_name]   # same as t_x
            qubit_obj = self.qubit_engine.get_qubit(phys_name)
            evals     = qubit_obj.eigensys(evals_count=2)[0]
            w01       = float(evals[1] - evals[0])
            # Read calibrated pi-pulse amplitude and halve it for H.
            amp_pi = calibrations["x_amp"].get(phys_name, 0.025)
            drive = {
                "target":     local_idx,
                "type":       "X",
                "amplitude":  amp_pi / 2.0,   # amp_h = amp_pi / 2
                "frequency":  w01,
                "phase":      -np.pi / 2,
                "start_time": 0.0,
                "end_time":   dur,
            }
            return drive, dur

        # ---- single-qubit transversal gates --------------------------------
        if isinstance(target, int):
            l_name    = logical_names[target]
            data      = mapping[l_name]["data"]    # [D0, D1, D2]
            sub_names = data                        # simulate only the 3 data qubits

            if gate == "X":
                drives_sub = []
                duration   = 0.0
                for local_idx, p in enumerate(data):
                    drv, dur = _make_x_drive(local_idx, p)
                    drives_sub.append(drv)
                    duration = max(duration, dur)

                #DEBUG PRINT
                print("\nDEBUG H drives:")
                for d in drives_sub:
                    print(d)
                
                #END DEBUG

                current_state = self._simulate_subsystem(
                    sub_names=sub_names,
                    sub_drives=drives_sub,
                    duration=duration,
                    sub_couplings=[],
                    full_state=current_state,
                    full_names=physical_names,
                    full_dims=full_dims,
                    gate_label=f"EC_{gate}",
                )

            elif gate == "H":
                drives_sub = []
                duration   = 0.0
                for local_idx, p in enumerate(data):
                    drv, dur = _make_h_drive(local_idx, p)
                    drives_sub.append(drv)
                    duration = max(duration, dur)

                current_state = self._simulate_subsystem(
                    sub_names=sub_names,
                    sub_drives=drives_sub,
                    duration=duration,
                    sub_couplings=[],
                    full_state=current_state,
                    full_names=physical_names,
                    full_dims=full_dims,
                    gate_label="EC_H",
                )

            elif gate == "RZ":
                pass   # virtual-Z: no physical drive, state unchanged

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
                # Simulate ALL 6 data qubits (D0/D1/D2 of L1 + D0/D1/D2 of L2)
                # as a single subsystem in one mesolve call.
                # Pair-by-pair simulation destroys inter-block entanglement:
                # e.g. a Bell state (H on L1, CX L1→L2) requires both blocks
                # to be entangled — ptrace collapses L1 to a mixed state before
                # L2 sees the CNOT, making the decoded output always mixed.
                combined_names = data1 + data2   # [D0_L1,D1_L1,D2_L1,D0_L2,D1_L2,D2_L2]
                # Max duration across all three transversal CNOT pairs
                dur = 0.0
                for d1, d2 in zip(data1, data2):
                    key_dur = calibrations["cnot_dur"].get(
                        (d1, d2), calibrations["cnot_dur"].get((d2, d1), 100.0)
                    )
                    dur = max(dur, key_dur)

                # Build three ideal CX gates in local indices:
                # (0,3), (1,4), (2,5) — each acts on the corresponding data qubits
                # across the two logical blocks.
                combined_drives = []
                combined_couplings = []
                for local_ctrl, local_targ in [(0, 3), (1, 4), (2, 5)]:
                    combined_drives.append({
                        "type": "ICX",
                        "control": local_ctrl,
                        "target": local_targ,
                    })

                current_state = self._simulate_subsystem(
                    sub_names=combined_names,
                    sub_drives=combined_drives,
                    duration=dur,
                    sub_couplings=combined_couplings,
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

    def _syndrome_extraction_drives(
        self,
        l_name: str,
        mapping: Dict,
        calibrations: Dict,
        coupling_strength: float,
    ) -> Tuple[List[Dict], List[Dict], float]:
        """
        Build the 4-CNOT syndrome extraction drive schedule for one logical block.

        CNOT sequence (sequenced in time, not concurrent):
            CNOT(D0 -> A0)   parity D0 xor D1
            CNOT(D1 -> A0)
            CNOT(D1 -> A1)   parity D1 xor D2
            CNOT(D2 -> A1)

        block_names (local ordering) = [D0, D1, D2, A0, A1]  (indices 0..4)

        All drive and coupling indices are LOCAL to the 5-qubit block so that
        _simulate_subsystem receives consistent 0-based indexing.

        Returns (drives_local, couplings_local, total_duration).
        """
        d = mapping[l_name]["data"]     # [D0, D1, D2]
        a = mapping[l_name]["ancilla"]  # [A0, A1]
        block_names = d + a             # local order: 0=D0,1=D1,2=D2,3=A0,4=A1

        cnot_pairs = [
            (d[0], a[0]),   # D0 -> A0  (local 0->3)
            (d[1], a[0]),   # D1 -> A0  (local 1->3)
            (d[1], a[1]),   # D1 -> A1  (local 1->4)
            (d[2], a[1]),   # D2 -> A1  (local 2->4)
        ]

        drives: List[Dict] = []
        couplings: List[Dict] = []
        t_cursor = 0.0

        for ctrl_name, targ_name in cnot_pairs:

            ic_local = block_names.index(ctrl_name)
            ia_local = block_names.index(targ_name)

            drives.append({
                "type": "ICX",
                "control": ic_local,
                "target": ia_local,
            })

        return drives, [], 0.0


    # ------------------------------------------------------------------
    # 7. Syndrome measurement (projective, with correction)
    # ------------------------------------------------------------------

    def _syndrome_measurement_and_correct(
        self,
        state,
        l_name,
        mapping,
        physical_names,
        physical_index,
        dims,
    )-> qt.Qobj:
        """
        Measure ancillas A0 and A1 for a single logical block, collapse the
        wavefunction, apply the appropriate X correction, and reset ancillas.

        Syndrome table:
            (A0=0, A1=0) → no error
            (A0=1, A1=0) → X on D0
            (A0=1, A1=1) → X on D1
            (A0=0, A1=1) → X on D2
        """
        N    = len(physical_names)

        idx_D0 = physical_index[mapping[l_name]["data"][0]]
        idx_D1 = physical_index[mapping[l_name]["data"][1]]
        idx_D2 = physical_index[mapping[l_name]["data"][2]]
        idx_A0 = physical_index[mapping[l_name]["ancilla"][0]]
        idx_A1 = physical_index[mapping[l_name]["ancilla"][1]]

        d_A0 = dims[idx_A0]
        d_A1 = dims[idx_A1]

        # Build projectors for each syndrome outcome
        projectors: Dict[Tuple, qt.Qobj] = {}
        for s0, s1 in [(0, 0), (1, 0), (0, 1), (1, 1)]:
            op_list = [qt.qeye(d) for d in dims]
            op_list[idx_A0] = _proj1_dim(d_A0) if s0 else _proj0_dim(d_A0)
            op_list[idx_A1] = _proj1_dim(d_A1) if s1 else _proj0_dim(d_A1)
            projectors[(s0, s1)] = qt.tensor(op_list)

        # Compute outcome probabilities
        # Handle both ket and density matrix states.
        # QuTiP's inner product can return either a 1x1 Qobj or a plain
        # complex scalar depending on version — extract a real float safely
        # in either case.
        def _qobj_to_real(val) -> float:
            if isinstance(val, qt.Qobj):
                arr = val.full().flatten()
                return float(np.real(arr[0]))
            return float(np.real(val))

        if state.type == "ket":
            probs = {
                synd: _qobj_to_real(state.dag() * proj * state)
                for synd, proj in projectors.items()
            }
        else:
            probs = {
                synd: float(np.real((proj * state).tr()))
                for synd, proj in projectors.items()
            }

        # Normalise (guard against floating-point drift)
        total = sum(probs.values())
        if total < 1e-12:
            print(f"    [EC] Warning: total probability ~0 for block {l_name}. State may be corrupted.")
            return state
        probs = {k: v / total for k, v in probs.items()}

        # Stochastic measurement
        syndromes    = list(probs.keys())
        prob_values  = [probs[s] for s in syndromes]
        chosen_idx   = np.random.choice(len(syndromes), p=prob_values)
        syndrome     = syndromes[chosen_idx]
        prob_outcome = prob_values[chosen_idx]

        print(
            f"    [EC] {l_name}  syndrome (A0,A1)={syndrome}  "
            f"p={prob_outcome:.4f}"
        )

        # Collapse
        collapsed = projectors[syndrome] * state
        if prob_outcome > 1e-12:
            collapsed = collapsed / np.sqrt(prob_outcome)
        state = collapsed

        # Feed-forward correction
        correction_map = {
            (1, 0): idx_D0,
            (1, 1): idx_D1,
            (0, 1): idx_D2,
        }
        if syndrome in correction_map:
            target_idx = correction_map[syndrome]
            label = physical_names[target_idx]
            print(f"    [EC] Applying X correction to {label}")
            X_op   = _sigmax_dim(dims[target_idx])
            X_full = _tensor_op_at(X_op, target_idx, dims)
            state  = X_full * state

        # Reset ancillas to |0⟩
        for s_val, idx in [(syndrome[0], idx_A0), (syndrome[1], idx_A1)]:
            if s_val == 1:
                X_op   = _sigmax_dim(dims[idx])
                X_full = _tensor_op_at(X_op, idx, dims)
                state  = X_full * state

        return state

    # ------------------------------------------------------------------
    # 8. Final state decoding
    # ------------------------------------------------------------------

    def _decode_logical_state(
        self,
        state: qt.Qobj,
        logical_names: List[str],
        mapping: Dict,
        physical_names: List[str],
        physical_index,
        dims: List[int],
    ) -> Dict[str, float]:
        """
        Extract logical populations via majority vote on data qubits.
        Handles both ket states and density matrices.
        """
        N_phys = len(physical_names)

        # Convert ket to density matrix for uniform treatment
        if state.type == "ket":
            rho = qt.ket2dm(state)
        else:
            rho = state

        diag = np.real(rho.diag())
        logical_pops: Dict[str, float] = {}

        total_states = int(np.prod(dims))
        for i, prob in enumerate(diag):
            if prob < 1e-8:
                continue

            # Decompose composite index into per-qubit levels
            # (respects non-uniform local dims)
            remainder = i
            levels = []
            for d in reversed(dims):
                levels.append(remainder % d)
                remainder //= d
            levels.reverse()   # levels[k] = level of physical qubit k

            # Majority vote per logical block
            logical_bits = ""
            for l_name in logical_names:
                d_idxs = [
                    physical_index[mapping[l_name]["data"][j]]
                    for j in range(3)
                ]
                bits  = [min(levels[idx], 1) for idx in d_idxs]   # project to {0,1}
                ones  = sum(bits)
                logical_bits += "1" if ones >= 2 else "0"

            logical_pops[logical_bits] = (
                logical_pops.get(logical_bits, 0.0) + float(prob)
            )

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
        Full 3-qubit repetition code workflow.

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

        # ── Step 1: Parse logical QASM ─────────────────────────────────
        print(f"[EC] 1. Parsing logical QASM from '{qasm_path}'...")
        transpiler      = QASMTranspiler()
        logical_circuit = transpiler.parse_file(qasm_path)
        print(f"[EC]    {len(logical_circuit)} logical instructions parsed.")

        # ── Step 2: Map & inject physical qubits (alias-only, no disk write) ─
        print("[EC] 2. Generating physical qubit mapping...")
        mapping        = self.generate_3q_repetition_mapping(logical_names)
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
                physical_names   = physical_names,
                coupling_type    = coupling_type,
                coupling_strength = coupling_strength,
                ec_every_n_gates  = ec_every_n_gates,
            )
            result = self._last_ec_result
        finally:
            # Always runs — deletes all _D0/_D1/_D2/_A0/_A1 qubits from
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

        # ── Step 7: Execute logical circuit, gate by gate ──────────────
        print(f"\n[EC] 6. Executing logical circuit ({len(logical_circuit)} gates)...\n")
        gate_counter = 0

        for step_idx, instruction in enumerate(logical_circuit):
            gate_label = instruction.get("type", "?")
            target     = instruction.get("target", "?")
            print(f"  [Gate {step_idx:03d}] {gate_label}  target={target}")

            # 7a. Transversal logical gate
            current_state = self._transversal_drives(
                instruction, logical_names, mapping,
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
                        l_name, mapping, physical_names, physical_index, dims,
                        calibrations, coupling_strength, coupling_type,
                        current_state,
                    )

        # ── Step 8: Final syndrome pass (always runs) ──────────────────
        print("  [EC final syndrome pass]")
        for l_name in logical_names:
            current_state = self._run_syndrome_block(
                l_name, mapping, physical_names, physical_index, dims,
                calibrations, coupling_strength, coupling_type,
                current_state,
            )

        # ── Step 9: Decode ─────────────────────────────────────────────
        print("\n[EC] 7. Circuit complete. Decoding final logical populations...")
        logical_pops = self._decode_logical_state(
            current_state, logical_names, mapping, physical_names, physical_index, dims
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
        physical_names: List[str],
        physical_index,
        dims: List[int],
        calibrations: Dict,
        coupling_strength: float,
        coupling_type: str,
        current_state: qt.Qobj,
    ) -> qt.Qobj:
        """Simulate syndrome CNOTs for one logical block, then measure & correct."""
        block_names = mapping[l_name]["data"] + mapping[l_name]["ancilla"]
        print(f"    Syndrome extraction for logical block: {l_name}")

        # _syndrome_extraction_drives now returns LOCAL indices (0..4)
        ec_drives, _, _ = self._syndrome_extraction_drives(
            l_name, mapping, calibrations, coupling_strength,
        )

        current_state = self._simulate_subsystem(
            sub_names      = block_names,
            sub_drives     = ec_drives,
            sub_couplings  = [],
            duration       = 0.0,
            full_state     = current_state,
            full_names     = physical_names,
            full_dims      = dims,
            gate_label     = "EC_Syndrome",
        )

        current_state = self._syndrome_measurement_and_correct(
            current_state,
            l_name,
            mapping,
            physical_names,
            physical_index,
            dims,
        )
        return current_state

