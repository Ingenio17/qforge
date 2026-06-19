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
from typing import List, Dict, Tuple, Any, Optional

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
    X-like flip operator in a d-dimensional space: only |0>↔|1> subspace.
    For d==2 this is the standard Pauli-X.
    For d>2 (truncated transmon) we want the same |0>↔|1> action.
    """
    mat = np.zeros((d, d), dtype=complex)
    mat[0, 1] = 1.0
    mat[1, 0] = 1.0
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

    def _register_physical_qubits(
        self,
        logical_names: List[str],
        mapping: Dict,
    ) -> None:
        """
        Clone each logical qubit's type and parameters into the 5 physical
        qubits (D0, D1, D2, A0, A1) that represent it.

        "Same type" means the physical qubits are identical scqubits objects
        to the logical qubit — consistent with qforge's qubit-sharing semantics.

        Qubits that are already registered are skipped so re-runs are safe.
        """
        existing = {q["name"] for q in self.qubit_engine.list_qubits()}

        for l_name in logical_names:
            # Fetch the source qubit's stored type + params
            found = None
            for q_data in self.qubit_engine._qubits.values():
                if q_data["name"] == l_name:
                    found = q_data
                    break

            if found is None:
                raise ValueError(
                    f"Logical qubit '{l_name}' is not registered in QubitEngine. "
                    f"Create it first with qubit_engine.create_qubit(...)."
                )

            q_type   = found["type"]
            q_params = found["params"].copy()

            # Ancillas only need 2 levels — keep truncated_dim=2 for them
            # to reduce Hilbert-space size while data qubits keep the original dim.
            ancilla_params = q_params.copy()
            ancilla_params["truncated_dim"] = 2

            all_physical = (
                mapping[l_name]["data"] + mapping[l_name]["ancilla"]
            )
            for p_name in all_physical:
                if p_name in existing:
                    continue
                params = ancilla_params if p_name.endswith(("_A0", "_A1")) else q_params
                self.qubit_engine.create_qubit(q_type, p_name, params)
                existing.add(p_name)

        print(
            f"[EC] Physical qubits registered: "
            f"{sum(5 for _ in logical_names)} qubits for "
            f"{len(logical_names)} logical qubit(s)."
        )

    # ------------------------------------------------------------------
    # 3. Coupling topology for the physical register
    # ------------------------------------------------------------------

    def _build_physical_couplings(
        self,
        logical_names: List[str],
        mapping: Dict,
        physical_names: List[str],
        coupling_type: str = "capacitive",
        coupling_strength: float = 0.010,
    ) -> List[Dict[str, Any]]:
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
            ia = physical_names.index(qa)
            ib = physical_names.index(qb)
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

    def _seed_gate_engine_cache(
        self,
        gate_type: str,
        q1_name: str,
        q2_name: Optional[str],
        parameter: str,
        result: Tuple[float, float],
        coupling_type: Optional[str] = None,
        coupling_strength: float = 0.0,
        amplitude: float = 0.025,
        use_drag: bool = True,
        drag_lambda: float = 0.5,
        virtual_z: float = 0.0,
        detuning: float = 0.0,
        duration: float = 40.0,
    ) -> None:
        """
        Directly write a calibration result into GateEngine._calib_cache so
        that a subsequent calibrate_gate() call for these exact arguments is
        a zero-cost cache hit.

        The cache key must match exactly what calibrate_gate() constructs:
            (q1_name, q2_name, gate_type, coupling_type, coupling_strength,
             parameter, kw_tuple)
        where kw_tuple = tuple(sorted(kwargs.items())) after calibrate_gate
        has normalised kwargs and removed the swept parameter.
        """
        from qforge.core.gate_engine import GateEngine

        # Reproduce the kwargs normalisation inside calibrate_gate()
        kwargs: Dict[str, Any] = {
            "amplitude":   amplitude,
            "use_drag":    use_drag,
            "drag_lambda": drag_lambda,
            "virtual_z":   virtual_z,
        }

        # detuning is set to 0.0 unless this is a tunable-coupler 2Q gate
        if gate_type in ("CNOT", "CZ") and coupling_type == "tunable_coupler":
            kwargs["detuning"] = detuning
        else:
            kwargs["detuning"] = 0.0

        # When sweeping 'duration', calibrate_gate pops it from kwargs before
        # building the key; for other parameters it keeps duration in kwargs.
        if parameter != "duration":
            kwargs["duration"] = duration

        # Remove the swept parameter (calibrate_gate pops it)
        kwargs.pop(parameter, None)

        kw_tuple  = tuple(sorted(kwargs.items()))
        cache_key = (
            q1_name,
            q2_name,
            gate_type.upper(),
            coupling_type,
            float(coupling_strength),
            parameter,
            kw_tuple,
        )
        GateEngine._calib_cache[cache_key] = result

    def _calibrate(
        self,
        logical_names: List[str],
        mapping: Dict,
        physical_names: List[str],
        syndrome_couplings: List[Dict],
        coupling_type: str,
        coupling_strength: float,
    ) -> Dict:
        """
        Calibrate X and CNOT durations, exploiting the fact that every
        physical qubit in a logical block is a perfect clone of its parent.

        Strategy
        --------
        Single-qubit X
            Calibrate once per unique (qubit_type, params) fingerprint.
            For every clone, seed GateEngine._calib_cache directly so its
            calibrate_gate() call is an instant cache hit — no sweep runs.

        CNOT syndrome pairs
            All syndrome pairs share the same qubit physics and coupling
            strength, so they produce identical calibrated durations.
            Calibrate the first pair only; seed the cache for the rest.
        """
        from qforge.core.gate_engine import GateEngine

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
                    # Clone — pre-seed the cache so no sweep runs
                    dur, metric = x_results[fp]
                    self._seed_gate_engine_cache(
                        gate_type="X",
                        q1_name=p_name,
                        q2_name=None,
                        parameter="duration",
                        result=(dur, metric),
                    )
                    print(f"[EC]   {p_name}: clone → cache seeded "
                          f"(dur={dur:.4f}, metric={metric:.4f})")

                calibrations["x_dur"][p_name] = dur
                calibrations["x_amp"][p_name] = 0.025  # amplitude used for pi-pulse calibration

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
                # Clone pair — seed cache for both directions
                dur, metric = cnot_results[fp]
                for a, b in [(q1n, q2n), (q2n, q1n)]:
                    self._seed_gate_engine_cache(
                        gate_type="CNOT",
                        q1_name=a,
                        q2_name=b,
                        parameter="duration",
                        result=(dur, metric),
                        coupling_type=coupling_type,
                        coupling_strength=coupling_strength,
                    )
                print(f"[EC]   {q1n}-{q2n}: clone → cache seeded "
                      f"(dur={dur:.4f}, metric={metric:.4f})")

            calibrations["cnot_dur"][key_fwd] = dur
            calibrations["cnot_dur"][key_rev] = dur

        return calibrations

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
        Simulate a gate on a SUBSET of the full register, then embed the
        result back into the full state.

        Approach
        --------
        1. Extract the reduced density matrix of the subsystem qubits via
           partial trace of the full state.
        2. Simulate the subsystem dynamics with simulate_n_qubit_dynamics
           on the small subsystem Hilbert space.
        3. Re-embed: replace the subsystem's part of the full state by
           tensoring the new subsystem state with the unchanged remainder.

        This avoids building a 4096-dimensional Hamiltonian when only a
        3- or 5-qubit subsystem is actually driven.

        sub_drives must use LOCAL indices (0..len(sub_names)-1), not global
        indices into full_names.
        """
        # -- Step 1: extract initial subsystem state via partial trace -------
        # Indices of subsystem within full register
        sub_global_idxs = [full_names.index(n) for n in sub_names]
        # Indices to trace out (everything NOT in the subsystem)
        keep_set = set(sub_global_idxs)
        trace_out = [i for i in range(len(full_names)) if i not in keep_set]

        # full_state may be ket or dm
        if full_state.type == "ket":
            rho_full = qt.ket2dm(full_state)
        else:
            rho_full = full_state

        rho_full.dims = [full_dims, full_dims]

        # ptrace keeps the listed indices, so pass sub_global_idxs
        # (QuTiP ptrace signature: ptrace(rho, sel) keeps sel)
        rho_sub = rho_full.ptrace(sub_global_idxs)

        # -- Step 2: simulate on the small subsystem -------------------------
        sub_dims = [full_dims[i] for i in sub_global_idxs]
        # Need at least ~50 points per nanosecond to resolve a 5 GHz carrier
        # (10 points per oscillation period × 5 cycles/ns).
        # max(200, ...) guarantees a minimum even for very short pulses.
        steps_sub = max(200, int(duration * 50))

        sim = self.gate_engine.simulate_n_qubit_dynamics(
            qubit_names   = sub_names,
            gate_type     = gate_label,
            duration      = duration,
            couplings     = sub_couplings,
            drives        = sub_drives,
            initial_state = rho_sub,
            steps         = steps_sub,
        )
        rho_sub_new = sim["final_state"]
        if rho_sub_new.type == "ket":
            rho_sub_new = qt.ket2dm(rho_sub_new)

        # -- Step 3: re-embed subsystem into full state ----------------------
        # For qubits NOT in the subsystem, extract their reduced state too.
        remain_idxs = [i for i in range(len(full_names)) if i not in keep_set]

        if remain_idxs:
            rho_remain = rho_full.ptrace(remain_idxs)
            # Tensor product: sub qubits first (in sub_global_idxs order),
            # then remaining qubits.  We need to sort them back into the
            # original full register order.
            # Build the combined state and then permute back.
            all_idxs_ordered = sub_global_idxs + remain_idxs
            rho_combined = qt.tensor(rho_sub_new, rho_remain)

            # Permute dims back to the original full register ordering.
            # perm[i] = position of full qubit i in all_idxs_ordered
            perm = [all_idxs_ordered.index(i) for i in range(len(full_names))]
            combined_dims = [full_dims[i] for i in all_idxs_ordered]
            # MUST be a list of lists (nested), not a flat list, or permute
            # misinterprets the tensor structure and produces wrong subsystem
            # ordering.  QuTiP permute() expects dims = [[d0,d1,...],[d0,d1,...]].
            rho_combined.dims = [list(combined_dims), list(combined_dims)]
            rho_new_full = rho_combined.permute(perm)
        else:
            # Subsystem IS the full system
            rho_new_full = rho_sub_new

        # Canonicalise dims so diag() / ptrace() work correctly downstream.
        rho_new_full.dims = [list(full_dims), list(full_dims)]
        return rho_new_full

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

                # Build three independent coupler drives in local indices:
                # (0,3), (1,4), (2,5) — all run concurrently (same time window)
                combined_drives = []
                combined_couplings = []
                seen_coup_pairs = set()
                for local_ctrl, local_targ in [(0, 3), (1, 4), (2, 5)]:
                    combined_drives.append({
                        "target":     (local_ctrl, local_targ),
                        "type":       "coupler_pulse",
                        "strength":   0.010,
                        "start_time": 0.0,
                        "end_time":   dur,
                    })
                    pair_key = (local_ctrl, local_targ)
                    if pair_key not in seen_coup_pairs:
                        seen_coup_pairs.add(pair_key)
                        combined_couplings.append({
                            "q1":       local_ctrl,
                            "q2":       local_targ,
                            "type":     "capacitive",
                            "strength": 0.010,
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
        physical_names: List[str],
        calibrations: Dict,
        coupling_strength: float,
    ) -> Tuple[List[Dict], float]:
        """
        Build the 4-CNOT syndrome extraction circuit for one logical block:

            CNOT(D0 → A0)
            CNOT(D1 → A0)
            CNOT(D1 → A1)
            CNOT(D2 → A1)

        The CNOTs are sequenced in time (each starts after the previous ends)
        to avoid simultaneous multi-qubit drives on the same physical qubit.

        Returns (drive_list, total_duration).
        """
        drives: List[Dict] = []
        d      = mapping[l_name]["data"]     # [D0, D1, D2]
        a      = mapping[l_name]["ancilla"]  # [A0, A1]

        # The 4 CNOT pairs in order
        cnot_pairs = [
            (d[0], a[0]),   # D0 → A0
            (d[1], a[0]),   # D1 → A0
            (d[1], a[1]),   # D1 → A1
            (d[2], a[1]),   # D2 → A1
        ]

        t_cursor = 0.0
        for ctrl, targ in cnot_pairs:
            key = (ctrl, targ)
            dur = calibrations["cnot_dur"].get(
                key, calibrations["cnot_dur"].get((targ, ctrl), 150.0)
            )
            ic = physical_names.index(ctrl)
            ia = physical_names.index(targ)
            drives.append({
                "target":     (min(ic, ia), max(ic, ia)),
                "type":       "coupler_pulse",
                "strength":   coupling_strength,
                "start_time": t_cursor,
                "end_time":   t_cursor + dur,
            })
            t_cursor += dur

        return drives, t_cursor

    # ------------------------------------------------------------------
    # 7. Syndrome measurement (projective, with correction)
    # ------------------------------------------------------------------

    def _syndrome_measurement_and_correct(
        self,
        state: qt.Qobj,
        l_name: str,
        mapping: Dict,
        physical_names: List[str],
        dims: List[int],
    ) -> qt.Qobj:
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

        idx_D0 = physical_names.index(mapping[l_name]["data"][0])
        idx_D1 = physical_names.index(mapping[l_name]["data"][1])
        idx_D2 = physical_names.index(mapping[l_name]["data"][2])
        idx_A0 = physical_names.index(mapping[l_name]["ancilla"][0])
        idx_A1 = physical_names.index(mapping[l_name]["ancilla"][1])

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
                    physical_names.index(mapping[l_name]["data"][j])
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
        ec_every_n_gates: int = 1,
    ) -> Dict:
        """
        Full 3-qubit repetition code workflow.

        Parameters
        ----------
        logical_names : list of str
            Names of the logical qubits, which must already be registered
            in QubitEngine.  Each logical qubit is expanded to 5 physical
            qubits (3 data + 2 ancilla) of the same type and parameters.
        qasm_path : str
            Path to an OpenQASM 2.0 file describing the logical circuit.
        coupling_type : str
            Coupling type to use for syndrome-extraction CNOTs (default: "capacitive").
        coupling_strength : float
            Coupling strength in GHz for syndrome-extraction links (default: 0.010).
        ec_every_n_gates : int
            Run a syndrome-extraction cycle after every N logical gates (default: 1).
            Set to 0 to disable all MID-CIRCUIT syndrome passes — a final syndrome
            cycle always runs once after all gates regardless of this setting.
            Use ec_every_n_gates=0 for circuits involving superposition states (e.g.
            H gate), because the 3-qubit repetition code Z-stabilisers will collapse
            X-basis superpositions if measured mid-circuit.

        Returns
        -------
        dict with keys:
            "logical_populations" : Dict[str, float]
                Decoded logical state populations by majority vote.
            "final_physical_state" : qt.Qobj
                The raw final physical quantum state (ket or dm).
        """

        # ── Step 1: Parse logical QASM ─────────────────────────────────
        print(f"[EC] 1. Parsing logical QASM from '{qasm_path}'...")
        transpiler     = QASMTranspiler()
        logical_circuit = transpiler.parse_file(qasm_path)
        print(f"[EC]    {len(logical_circuit)} logical instructions parsed.")

        # ── Step 2: Map & register physical qubits ────────────────────
        print("[EC] 2. Generating physical qubit mapping...")
        mapping        = self.generate_3q_repetition_mapping(logical_names)
        physical_names = self._get_flat_physical_names(logical_names, mapping)

        print(
            f"[EC]    Logical qubits : {logical_names}\n"
            f"[EC]    Physical qubits: {physical_names}"
        )
        self._register_physical_qubits(logical_names, mapping)

        # ── Step 3: Collect local dims after registration ─────────────
        dims = [
            self.qubit_engine.get_qubit(name).truncated_dim
            for name in physical_names
        ]
        print(f"[EC]    Local dims: {dims}")

        # ── Step 4: Build coupling topology ───────────────────────────
        print("[EC] 3. Building syndrome-extraction coupling topology...")
        syndrome_couplings = self._build_physical_couplings(
            logical_names, mapping, physical_names,
            coupling_type, coupling_strength,
        )
        print(f"[EC]    {len(syndrome_couplings)} coupling links defined.")

        # ── Step 5: Calibrate pulses (cached by GateEngine) ───────────
        print("[EC] 4. Calibrating pulses (results cached for re-use)...")
        calibrations = self._calibrate(
            logical_names, mapping, physical_names,
            syndrome_couplings, coupling_type, coupling_strength,
        )

        # ── Step 6: Initial physical state  |00...0⟩ ─────────────────
        print("[EC] 5. Initialising physical state to |00...0⟩...")
        ground_states  = [qt.basis(d, 0) for d in dims]
        current_state  = qt.tensor(ground_states)

        # ── Step 7: Execute logical circuit, gate by gate ─────────────
        print(f"\n[EC] 6. Executing logical circuit ({len(logical_circuit)} gates)...\n")
        gate_counter = 0

        for step_idx, instruction in enumerate(logical_circuit):
            gate_label = instruction.get("type", "?")
            target     = instruction.get("target", "?")
            print(f"  [Gate {step_idx:03d}] {gate_label}  target={target}")

            # ── 7a. Transversal logical gate ──────────────────────────
            # Each logical gate is simulated on a small subsystem to avoid
            # the full 4096-dim Hilbert space.  _transversal_drives now
            # returns the updated full state directly.
            current_state = self._transversal_drives(
                instruction, logical_names, mapping,
                physical_names, dims, calibrations,
                current_state,
            )

            gate_counter += 1

            # ── 7b. Periodic syndrome extraction ─────────────────────
            # ec_every_n_gates=0 means "final only" — skip all mid-circuit
            # syndrome cycles.  This is required when the logical circuit
            # contains superposition states (e.g. H gate) because the
            # 3-qubit repetition code's Z-stabiliser measurements will
            # collapse X-basis superpositions mid-circuit.
            if ec_every_n_gates <= 0:
                pass
            elif gate_counter % ec_every_n_gates == 0:
                print(f"  [EC cycle after gate {step_idx}]")

                for l_name in logical_names:
                    print(f"    Syndrome extraction for logical block: {l_name}")

                    # Syndrome extraction: simulate only the 5-qubit block
                    # (D0, D1, D2, A0, A1) rather than all 10 qubits.
                    block_names = (
                        mapping[l_name]["data"] + mapping[l_name]["ancilla"]
                    )
                    block_dims = [
                        dims[physical_names.index(n)] for n in block_names
                    ]

                    # Build local-indexed syndrome drives (0..4)
                    ec_drives_local = []
                    t_cursor = 0.0
                    d  = mapping[l_name]["data"]
                    a  = mapping[l_name]["ancilla"]
                    cnot_pairs = [
                        (d[0], a[0]),
                        (d[1], a[0]),
                        (d[1], a[1]),
                        (d[2], a[1]),
                    ]
                    for ctrl, targ in cnot_pairs:
                        key = (ctrl, targ)
                        dur = calibrations["cnot_dur"].get(
                            key, calibrations["cnot_dur"].get((targ, ctrl), 150.0)
                        )
                        ic_local = block_names.index(ctrl)
                        ia_local = block_names.index(targ)
                        ec_drives_local.append({
                            "target":     (min(ic_local, ia_local),
                                           max(ic_local, ia_local)),
                            "type":       "coupler_pulse",
                            "strength":   coupling_strength,
                            "start_time": t_cursor,
                            "end_time":   t_cursor + dur,
                        })
                        t_cursor += dur

                    # Build local-indexed couplings
                    block_couplings_local = []
                    seen_pairs = set()
                    for ctrl, targ in cnot_pairs:
                        ic_local = block_names.index(ctrl)
                        ia_local = block_names.index(targ)
                        key = (min(ic_local, ia_local), max(ic_local, ia_local))
                        if key not in seen_pairs:
                            seen_pairs.add(key)
                            block_couplings_local.append({
                                "q1":       key[0],
                                "q2":       key[1],
                                "type":     coupling_type,
                                "strength": coupling_strength,
                            })

                    current_state = self._simulate_subsystem(
                        sub_names      = block_names,
                        sub_drives     = ec_drives_local,
                        duration       = t_cursor,
                        sub_couplings  = block_couplings_local,
                        full_state     = current_state,
                        full_names     = physical_names,
                        full_dims      = dims,
                        gate_label     = "EC_Syndrome",
                    )

                    # Measure ancillas, correct, and reset
                    current_state = self._syndrome_measurement_and_correct(
                        current_state, l_name, mapping,
                        physical_names, dims,
                    )

        # ── Step 8: Decode final logical state ────────────────────────
        # -- Step 7b (final): One last syndrome pass before decode ----------
        # Always run a final syndrome + correction cycle regardless of
        # ec_every_n_gates. This catches errors from the last gate and is
        # the ONLY syndrome pass when ec_every_n_gates=0 (recommended for
        # circuits with superposition states like H gates, where mid-circuit
        # Z-stabiliser measurement collapses X-basis superpositions).
        print("  [EC final syndrome pass]")
        for l_name in logical_names:
            print(f"    Final syndrome for logical block: {l_name}")
            block_names = (
                mapping[l_name]["data"] + mapping[l_name]["ancilla"]
            )
            d  = mapping[l_name]["data"]
            a  = mapping[l_name]["ancilla"]
            cnot_pairs = [
                (d[0], a[0]), (d[1], a[0]),
                (d[1], a[1]), (d[2], a[1]),
            ]
            t_cursor_f = 0.0
            ec_drives_f: list = []
            block_couplings_f: list = []
            seen_pairs_f: set = set()
            for ctrl, targ in cnot_pairs:
                dur_ec = calibrations["cnot_dur"].get(
                    (ctrl, targ),
                    calibrations["cnot_dur"].get((targ, ctrl), 150.0),
                )
                ic_l = block_names.index(ctrl)
                ia_l = block_names.index(targ)
                ec_drives_f.append({
                    "target":     (min(ic_l, ia_l), max(ic_l, ia_l)),
                    "type":       "coupler_pulse",
                    "strength":   coupling_strength,
                    "start_time": t_cursor_f,
                    "end_time":   t_cursor_f + dur_ec,
                })
                pair_key_f = (min(ic_l, ia_l), max(ic_l, ia_l))
                if pair_key_f not in seen_pairs_f:
                    seen_pairs_f.add(pair_key_f)
                    block_couplings_f.append({
                        "q1":       pair_key_f[0],
                        "q2":       pair_key_f[1],
                        "type":     coupling_type,
                        "strength": coupling_strength,
                    })
                t_cursor_f += dur_ec

            current_state = self._simulate_subsystem(
                sub_names      = block_names,
                sub_drives     = ec_drives_f,
                duration       = t_cursor_f,
                sub_couplings  = block_couplings_f,
                full_state     = current_state,
                full_names     = physical_names,
                full_dims      = dims,
                gate_label     = "EC_Syndrome_Final",
            )
            current_state = self._syndrome_measurement_and_correct(
                current_state, l_name, mapping, physical_names, dims,
            )

        print("\n[EC] 7. Circuit complete. Decoding final logical populations...")
        logical_pops = self._decode_logical_state(
            current_state, logical_names, mapping, physical_names, dims
        )

        print("[EC] Logical state populations (majority-vote decoded):")
        if not logical_pops:
            print("    [EC] WARNING: no logical populations decoded (all diagonal entries < 1e-8).")
            print(f"    [EC] Full state type={current_state.type}, dims={current_state.dims}")
        for bitstring, pop in sorted(logical_pops.items(), key=lambda x: -x[1]):
            bar = "█" * int(pop * 20) + "░" * (20 - int(pop * 20))
            print(f"    |{bitstring}⟩_L  {bar}  {pop * 100:5.2f}%")

        return {
            "logical_populations":  logical_pops,
            "final_physical_state": current_state,
        }
