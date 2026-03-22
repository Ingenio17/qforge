"""
Gate Engine: Simulation of quantum gates and dynamics using QuTiP.
"""

import numpy as np
import qutip as qt
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path

from qforge.core.qubit_engine import QubitEngine
from qforge.core.coupling import CouplingGenerator, CouplingType
from qforge.config.defaults import OUTPUT_DIRS


class GateEngine:
    """Engine for simulating quantum gates and dynamics."""

    def __init__(self):
        """Initialize the gate engine."""
        self.qubit_engine = QubitEngine()
        
    def _get_qubit_hamiltonian(self, qubit_name: str) -> Tuple[qt.Qobj, Dict[str, qt.Qobj]]:
        """
        Get the Hamiltonian of a qubit in its eigenbasis (truncated),
        along with its physical operators (charge, flux) projected into that same basis.
        """
        qubit = self.qubit_engine.get_qubit(qubit_name)
        dim = qubit.truncated_dim
        
        # Get eigenvalues for diagonal Hamiltonian (in GHz * 2pi)
        evals = qubit.eigenvals(evals_count=dim)
        H0 = qt.Qobj(np.diag(evals)) * 2 * np.pi
        
        operators = {}
        # Extract charge (n_operator) or flux (phi_operator) matrix elements
        # These are natively in the eigenbasis
        if hasattr(qubit, 'n_operator'):
            n_mat = qubit.matrixelement_table('n_operator', evals_count=dim)
            operators['n'] = qt.Qobj(n_mat)
        
        if hasattr(qubit, 'phi_operator'):
            phi_mat = qubit.matrixelement_table('phi_operator', evals_count=dim)
            operators['phi'] = qt.Qobj(phi_mat)
            
        # Fallback to harmonic oscillator approx if operators don't exist
        if not operators:
            a = qt.destroy(dim)
            operators['n'] = 1j * (a.dag() - a) / np.sqrt(2)
            operators['phi'] = (a.dag() + a) / np.sqrt(2)
            
        return H0, operators

    def get_control_hamiltonian(self, gate_type: str, operators: Dict[str, qt.Qobj]) -> qt.Qobj:
        """
        Get the control Hamiltonian operator for a specific gate type
        using exact physical matrix elements (e.g., charge operator).
        
        Args:
            gate_type: Type of gate (X, Y, Z, H)
            operators: Dictionary of physical operators from `_get_qubit_hamiltonian`
            
        Returns:
            QuTiP Qobj operator representing the physical drive
        """
        gate_type = gate_type.upper()
        
        # Driving a transmon typically acts on the charge operator `n`
        # Using exact transition matrices instead of harmonic oscillator (a + a.dag)
        
        if gate_type == "X":
            # Capacitive drive: H_drive ~ n
            if 'n' in operators:
                return operators['n']
            else:
                a = qt.destroy(operators['n'].shape[0])
                return a + a.dag()
        elif gate_type == "Y":
            # 90-degree phase shifted capacitive drive
            if 'n' in operators:
                return 1j * operators['n'] # Simplified phase representation
            else:
                a = qt.destroy(operators['n'].shape[0])
                return 1j * (a - a.dag())
        elif gate_type == "Z":
            # Flux tuning or Stark shift
            if 'phi' in operators:
                return operators['phi'] # Technically Stark shift is n^2, flux is phi. Using phi as placeholder.
            else:
                a = qt.destroy(operators['n'].shape[0])
                return a.dag() * a
        elif gate_type == "H":
            # Composite drive
            if 'n' in operators and 'phi' in operators:
                return operators['n'] + operators['phi']
            else:
                a = qt.destroy(operators['n'].shape[0])
                return (a + a.dag()) + (a.dag() * a)
        else:
            raise ValueError(f"Unknown gate control: {gate_type}")

    def simulate_dynamics(self, 
                          qubit_name: str, 
                          gate_type: str, 
                          duration: float, 
                          noise_model: str = "none",
                          steps: int = 100) -> Dict[str, Any]:
        """
        Simulate single-qubit gate dynamics using extracted scqubits matrices.
        """
        # 1. Setup System
        qubit = self.qubit_engine.get_qubit(qubit_name)
        dim = qubit.truncated_dim
        
        # Get Drift Hamiltonian and true physical operators
        H0, operators = self._get_qubit_hamiltonian(qubit_name)
        
        # Rotating Wave Approximation (RWA)
        # Transform to frame rotating at qubit frequency w01
        evals = H0.diag() / (2 * np.pi)
        w01 = evals[1] - evals[0]
        
        evals_rot = np.array([e - i * w01 * 2 * np.pi for i, e in enumerate(evals)])
        evals_rot = evals_rot - evals_rot[0]
        H0_rot = qt.Qobj(np.diag(evals_rot))
        
        # Control Hamiltonian (H_drive) using true matrix elements
        H_ctrl = self.get_control_hamiltonian(gate_type, operators)
        
        # Calibration
        # We need to find the effective matrix element for the 0->1 transition to calibrate pi-pulse
        # If H_ctrl is charge operator `n`, the rabi frequency is proportional to `n_01 * drive_amp`
        matrix_element_01 = np.abs(H_ctrl[0, 1])
        if matrix_element_01 == 0:
             matrix_element_01 = 1.0 # fallback
             
        target_rotation = np.pi # Default to pi pulse (flip)
        if gate_type == "H": target_rotation = np.pi / 2 
        
        # Drive amplitude needed to achieve target rotation in given duration
        # \int \Omega dt = target_rotation  => \Omega = target / duration
        # \Omega = 2 * drive_amp * |<0|n|1>| => drive_amp = (target / duration) / (2 * |<0|n|1>|)
        omega = target_rotation / duration
        amplitude = omega / (2.0 * matrix_element_01)
        
        # Time array
        tlist = np.linspace(0, duration, steps)
        
        # 2. Setup Noise
        c_ops = []
        if noise_model == "realistic":
            coherence = self.qubit_engine.estimate_coherence(qubit)
            t1 = coherence.get("T1 (dielectric)", {}).get("value", 50.0) * 1000  # ns
            if t1 > 0:
                rate_relax = 1.0 / t1
                # Still using a simple collapse operator for single-qubit relax, 
                # but could use exact loss operators mapped to `n` in the future.
                c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))
            
        # 3. Initial State
        psi0 = qt.basis(dim, 0) 
        
        # 4. Evolve
        H_total = H0_rot + amplitude * H_ctrl
        result = qt.mesolve(H_total, psi0, tlist, c_ops)
        
        # Calculate expectations
        expectations = []
        labels = []
        for i in range(min(3, dim)):
            proj = qt.basis(dim, i) * qt.basis(dim, i).dag()
            exp = qt.expect(proj, result.states)
            expectations.append(exp)
            labels.append(f"|{i}⟩")
            
        return {
            "times": tlist,
            "expectations": expectations,
            "labels": labels,
            "final_state": result.states[-1]
        }

    def _get_n_qubit_hamiltonian(self, 
                                 qubit_names: List[str], 
                                 couplings: List[Dict[str, Any]]) -> Tuple[qt.Qobj, List[Any], List[Dict[str, qt.Qobj]]]:
        """
        Construct the static N-qubit Hamiltonian including interactions.
        
        Args:
            qubit_names: List of N qubit names.
            couplings: List of dicts defining couplings: 
                       {"q1": idx, "q2": idx, "type": "capacitive", "strength": float}
                       where idx is the index in the qubit_names list.
                       
        Returns:
            Tuple of (H_static, list_of_qubit_objects, list_of_operators)
        """
        N = len(qubit_names)
        qubits = [self.qubit_engine.get_qubit(name) for name in qubit_names]
        dims = [q.truncated_dim for q in qubits]
        
        # 1. Build individual local Hamiltonians and operators
        local_H = []
        local_ops = []
        for name in qubit_names:
            H0, ops = self._get_qubit_hamiltonian(name)
            local_H.append(H0)
            local_ops.append(ops)
            
        # 2. Tensor them together into the N-qubit Hilbert space
        H_sys = qt.Qobj()
        for i in range(N):
            # Tensor: I x I x ... x H_i x ... x I
            op_list = [qt.qeye(d) for d in dims]
            op_list[i] = local_H[i]
            if i == 0:
                H_sys = qt.tensor(op_list)
            else:
                H_sys += qt.tensor(op_list)
                
        # 3. Add static interactions
        for coupling in couplings:
            i = coupling["q1"]
            j = coupling["q2"]
            c_type = coupling["type"]
            strength = coupling.get("strength", 0.0)
            
            # Static interaction is only non-zero if not a tunable coupler
            if c_type != "tunable_coupler" and strength != 0.0:
                 # Interaction shape is D_i x D_j, need to embed in N-qubit space
                 H_int_2body = CouplingGenerator.get_coupling(c_type, dims[i], dims[j], strength * 2 * np.pi)
                 
                 # H_int_2body usually returned as tensor(A_i, B_j) + tensor(B_i, A_j).
                 # The current CouplingGenerator creates a 2-qubit tensor directly.
                 # We must be careful to embed a 2-qubit operator into an N-qubit space.
                 # But our CouplingGenerator only knows 2-qubit spaces...
                 # We will rebuild it here for the N-qubit space using the exact operators.
                 
                 op_list_int = [qt.qeye(d) for d in dims]
                 
                 if c_type == "capacitive":
                     # H_int = g * n_i * n_j
                     op_list_int[i] = local_ops[i]['n']
                     op_list_int[j] = local_ops[j]['n']
                     H_sys += (strength * 2 * np.pi) * qt.tensor(op_list_int)
                 elif c_type == "inductive":
                     # H_int = g * phi_i * phi_j
                     op_list_int[i] = local_ops[i]['phi']
                     op_list_int[j] = local_ops[j]['phi']
                     H_sys += (strength * 2 * np.pi) * qt.tensor(op_list_int)

        return H_sys, qubits, local_ops




    def compare_couplings(self, q1: str, q2: str, gate: str = "CNOT", 
                          coupling_type: str = None, 
                          strength: float = None, 
                          duration: float = None) -> Dict[str, Dict[str, float]]:
        """
        Compare different coupling types for a given gate.
        Can optionally run a specific single scenario if arguments are provided.
        
        Args:
            q1: Control qubit name
            q2: Target qubit name
            gate: Gate type (CNOT, CZ)
            coupling_type: Optional override
            strength: Optional override
            duration: Optional override
            
        Returns:
            Dictionary mapping coupling type to metrics {'population': float, 'phase': float}
        """
        results = {}
        
        # Define scenarios to compare
        if coupling_type is not None and strength is not None and duration is not None:
             # Run specific scenario
             scenarios = [(coupling_type, strength, duration)]
        else:
            # Defaults
            scenarios = []
            if gate == "CNOT":
                scenarios = [
                    ("capacitive", 0.010, 200.0), # CR approx
                    ("inductive", 0.005, 100.0),   # Just for comparison (bad for CNOT usually)
                    ("tunable_coupler", 0.050, 40.0) # Tunable CNOT (H-CZ-H)
                ]
            elif gate == "CZ":
                scenarios = [
                    ("tunable_coupler", 0.050, 10.0), # Fast pulse (approx pi/2 or optimized)
                    ("inductive", 0.010, 50.00)      # Optimized via calibration
                ]
            
        print(f"Comparing couplings for {gate} on {q1}-{q2}:")
        
        for c_type, strength, dur in scenarios:
            try:
                res = self.simulate_two_qubit_dynamics(
                    q1, q2, gate, 
                    coupling_type=c_type, 
                    coupling_strength=strength, 
                    duration=dur
                )
                
                # Metric: Population of target state
                target_pop_key = "11"
                final_pop = res["populations"][target_pop_key][-1]
                
                metrics = {"population": final_pop}
                
                phase_msg = ""
                if gate == "CZ":
                    ph_pi = self._calculate_interaction_phase_metric(q1, q2, c_type, strength, dur)
                    metrics["phase"] = ph_pi
                    phase_msg = f", Phase = {metrics['phase']:.2f}π"
                
                results[c_type] = metrics
                print(f" -> {c_type}: Target Pop |{target_pop_key}> = {final_pop:.4f}{phase_msg}")
            except Exception as e:
                print(f" -> {c_type}: Failed ({e})")
                import traceback
                traceback.print_exc()
                results[c_type] = {"population": -1.0}
                
        return results

    def _calculate_interaction_phase_metric(self, q1: str, q2: str, 
                                            coupling_type: str, strength: float, duration: float, detuning: float = 0.0) -> float:
        """
        Calculate the interaction phase (normalized to pi) by subtracting reference dynamical phase.
        Returns phase in units of pi (e.g. 1.0 means pi).
        """
        try:
             # 1. Full Simulation
             # Use enough steps for numerical stability?
             res = self.simulate_two_qubit_dynamics(q1, q2, "CZ", coupling_type, strength, duration, steps=20, detuning=detuning)
             final_state = res["final_state"]
             
             # 2. Reference Simulation (g=0, but KEEP FLUX PULSE? No, ref usually means "unperturbed" rotating frame?)
             # If we subtract reference, we want to subtract the "dynamical phase" accumulated by the flux pulse itself?
             # E.g. flux pulse changes frequency -> accumulates Z phase.
             # We want the *entangling* phase (CZ).
             # If we default ref to (g=0, det=0), we measure total phase deviation.
             # If we default ref to (g=0, det=det), we measure only the interaction induced phase.
             # Ideally we want just the interaction phase.
             # So Ref should have detuning enabled but g=0.
             
             res_ref = self.simulate_two_qubit_dynamics(q1, q2, "CZ", coupling_type, 0.0, duration, steps=20, detuning=detuning)
             final_state_ref = res_ref["final_state"]
             
             # Indices
             q2_obj = self.qubit_engine.get_qubit(q2)
             idx_11 = 1 * q2_obj.truncated_dim + 1
             
             if final_state.type == "ket":
                 amp = final_state[idx_11, 0]
                 amp_ref = final_state_ref[idx_11, 0]
             else:
                 return 0.0 # TODO: DM support
                 
             if isinstance(amp, complex):
                 phi_total = np.angle(amp)
                 phi_ref = np.angle(amp_ref)
                 
                 diff = phi_total - phi_ref
                 
                 # Normalize diff to [0, 2pi)
                 diff = diff % (2*np.pi)
                 
                 return diff / np.pi
        except Exception as e:
             # print(f"Phase calc error: {e}")
             return 0.0
        return 0.0

    def calibrate_gate(self, 
                      q1_name: str, 
                      q2_name: str = None, 
                      gate_type: str = "X", 
                      coupling_type: str = None, 
                      coupling_strength: float = 0.0, 
                      parameter: str = "duration", 
                      range_vals: list = [],
                      **kwargs) -> Tuple[float, float]:
        """
        Calibrate a gate by sweeping a parameter to maximize fidelity/population.
        Accepts kwargs (e.g. detuning) passed to simulate().
        """
        if q2_name:
            print(f"Calibrating {gate_type} ({coupling_type}) on {q1_name}-{q2_name}...")
        else:
            print(f"Calibrating {gate_type} on {q1_name}...")
        best_val = 0.0
        max_metric = -1.0
        
        # Setup sweep
        if len(range_vals) == 0:
            if parameter == "duration":
                if gate_type in ["X", "Y", "H"]:
                     range_vals = np.linspace(5, 50, 40)
                elif coupling_type == "tunable_coupler":
                     # Fast dynamics: 0.1 to 50ns with high resolution
                     range_vals = np.linspace(0.1, 50, 100)
                else:
                     range_vals = np.linspace(1, 200, 40) 
            elif parameter == "amplitude":
                range_vals = np.linspace(0.01, 0.2, 20)
            elif parameter == "detuning":
                # Sweep -1.0 to 1.0 GHz
                range_vals = np.linspace(-1.0, 1.0, 50)

        # Helper to run a sweep
        def run_sweep(vals):
            best_v = 0.0
            max_m = -1.0 # 1.0 is max usually? Or maximize closeness?
            # For CNOT: Maximize Pop (0 to 1)
            # For CZ: Maximize (1 - dist_to_pi) (0 to 1)
            
            for val in vals:
                # kwargs = { "duration": val } if parameter == "duration" else { "duration": 100.0 }
                # ...
                
                try:
                    metric = 0.0
                    if gate_type in ["X", "Y", "H"]:
                        evals = self.qubit_engine.get_qubit(q1_name).eigensys(evals_count=2)[0]
                        w01 = evals[1] - evals[0]
                        amp = kwargs.get("amplitude", 0.025)
                        
                        drives = [{"target": 0, "type": "X", "amplitude": amp, "frequency": w01, "phase": 0.0, "start_time": 0.0, "end_time": val}]
                        res = self.simulate_n_qubit_dynamics([q1_name], f"Calibrate_{gate_type}", val, [], drives, "0", steps=5)
                        
                        p1 = res["populations"]["1"][-1] if "1" in res["populations"] else 0.0
                        if gate_type in ["X", "Y"]:
                            metric = p1
                        elif gate_type == "H":
                            metric = 1.0 - abs(p1 - 0.5) * 2.0
                            
                    elif gate_type == "CNOT":
                        res = self.simulate_two_qubit_dynamics(
                            q1_name, q2_name, gate_type, coupling_type, coupling_strength, 
                            duration=val, steps=40, **kwargs
                        )
                        metric = res["populations"]["11"][-1]
                        
                    elif gate_type == "CZ":
                        d_val = val if parameter == "detuning" else kwargs.get("detuning", 0.0)
                        dur_val = val if parameter == "duration" else kwargs.get("duration", 40.0)
                        
                        run_dur = val if parameter == "duration" else kwargs.get("duration", 40.0) # Fixed default?
                        run_det = val if parameter == "detuning" else kwargs.get("detuning", 0.0)
                        
                        # Robust Phase Metric
                        phase_pi = self._calculate_interaction_phase_metric(
                            q1_name, q2_name, coupling_type, coupling_strength, run_dur, detuning=run_det
                        )
                        ph = phase_pi % 2.0
                        # Distance to 1.0 (Target Pi)
                        dist = abs(ph - 1.0)
                        metric = 1.0 - dist # 1 at match, <1 otherwise
                    
                    if metric > max_m:
                        max_m = metric
                        best_v = val
                except: pass
            return best_v, max_m

        # 1. Coarse Sweep
        print(f" -> Coarse sweep ({len(range_vals)} points)...")
        best_val, max_metric = run_sweep(range_vals)
        
        # 2. Fine Sweep (if duration)
        if parameter == "duration" and max_metric > 0.5:
             center = best_val
             start = max(1.0, center - 5.0) # Tighter fine sweep
             end = center + 5.0
             if coupling_type == "tunable_coupler":
                 # Even tighter for fast gates
                 start = max(0.1, center - 2.0)
                 end = center + 2.0
                 fine_vals = np.linspace(start, end, 50) # High res
             else:
                 fine_vals = np.linspace(start, end, 30)
                 
             print(f" -> Fine sweep around {center:.1f}ns...")
             best_val, max_metric = run_sweep(fine_vals)
             
        return best_val, max_metric

    def _build_time_dependent_hamiltonian(self,
                                          H_sys: qt.Qobj,
                                          dims: List[int],
                                          local_ops: List[Dict[str, qt.Qobj]],
                                          qubit_names: List[str],
                                          gate_type: str,
                                          duration: float,
                                          couplings: List[Dict[str, Any]],
                                          drives: List[Dict[str, Any]],
                                          detuning: float = 0.0) -> Tuple[List[Any], Dict[str, Any]]:
        N = len(qubit_names)
        H_total = [H_sys]
        args = {}
        
        # A) Continuous microwave drives and scheduled pulses
        for i, drive in enumerate(drives):
            if drive.get("type") == "coupler_pulse":
                idx1, idx2 = drive["target"]
                g_amp = drive.get("strength", 0.0) * 2 * np.pi
                t_start = drive.get("start_time", 0.0)
                t_end = drive.get("end_time", duration)
                pulse_dur = t_end - t_start
                if pulse_dur <= 0: continue
                
                op_list = [qt.qeye(d) for d in dims]
                op_list[idx1] = local_ops[idx1]['n']
                op_list[idx2] = local_ops[idx2]['n']
                op_int = qt.tensor(op_list)
                
                def make_coupler_coeff(g_val, ts, dur):
                     return lambda t, args: g_val * (np.sin(np.pi * (t - ts) / dur)**2) if (ts <= t <= ts + dur) else 0.0
                     
                pulse_func = make_coupler_coeff(g_amp, t_start, pulse_dur)
                H_total.append([op_int, pulse_func])
            else:
                target_idx = drive["target"]
                d_type = drive.get("type", "X")
                amp = drive.get("amplitude", 0.0) * 2 * np.pi
                freq = drive.get("frequency", 0.0) * 2 * np.pi
                phase = drive.get("phase", 0.0)
                t_start = drive.get("start_time", 0.0)
                t_end = drive.get("end_time", duration)
                
                op_local = self.get_control_hamiltonian(d_type, local_ops[target_idx])
                op_list = [qt.qeye(d) for d in dims]
                op_list[target_idx] = op_local
                op_drive = qt.tensor(op_list)
                
                def make_drive_coeff(a, f, p, ts, te):
                     return lambda t, args: a * np.cos(f * t + p) if (ts <= t <= te) else 0.0
                         
                coeff_func = make_drive_coeff(amp, freq, phase, t_start, t_end)
                H_total.append([op_drive, coeff_func])
            
        # B) Tunable Couplers
        for c_idx, coupling in enumerate(couplings):
            if coupling["type"] == "tunable_coupler":
                idx1 = coupling["q1"]
                idx2 = coupling["q2"]
                g_amp = coupling.get("strength", 0.0) * 2 * np.pi
                
                op_list = [qt.qeye(d) for d in dims]
                op_list[idx1] = local_ops[idx1]['n']
                op_list[idx2] = local_ops[idx2]['n']
                op_int = qt.tensor(op_list)
                
                def make_pulse_coeff(g_val, dur):
                     return lambda t, args: g_val * (np.sin(np.pi * t / dur)**2)
                     
                pulse_func = make_pulse_coeff(g_amp, duration)
                H_total.append([op_int, pulse_func])
                
        # C) Specific gate overrides for compatibility with old 2-qubit caller
        if N == 2:
            if gate_type == "CNOT":
                H0_2, _ = self._get_qubit_hamiltonian(qubit_names[1])
                e2 = H0_2.diag() / (2*np.pi)
                w2 = e2[1] - e2[0]
                
                if not any(d["target"] == 1 for d in drives):
                    op_list = [qt.qeye(d) for d in dims]
                    op_list[1] = self.get_control_hamiltonian("X", local_ops[1])
                    op_drive = qt.tensor(op_list)
                    amp = 0.100 * 2 * np.pi 
                    
                    def cr_drive(t, args): return args['cr_amp'] * np.cos(args['cr_w'] * t)
                    H_total.append([op_drive, cr_drive])
                    args['cr_amp'] = amp
                    args['cr_w'] = w2 * 2 * np.pi
                    
            elif gate_type == "CZ":
                if couplings[0]["type"] == "tunable_coupler":
                    op_list = [qt.qeye(d) for d in dims]
                    op_list[1] = qt.num(dims[1]) 
                    n2_op = qt.tensor(op_list)
                    
                    def flux_coeff(t, args): return args['det'] * (np.sin(np.pi * t / args['T'])**2)
                    H_total.append([n2_op, flux_coeff])
                    args['det'] = detuning * 2 * np.pi
                    args['T'] = duration
                    
        return H_total, args

    def generate_process_tomography(self, 
                                  qubit_names: List[str], 
                                  gate_type: str,
                                  duration: float, 
                                  couplings: List[Dict[str, Any]] = [],
                                  drives: List[Dict[str, Any]] = [],
                                  detuning: float = 0.0) -> qt.Qobj:
        """
        Generate the process tomography Choi matrix for the gate by computing
        the exact unitary propagator and projecting it onto the computational subspace.
        """
        import itertools
        import numpy as np
        
        N = len(qubit_names)
        H_sys, qubits, local_ops = self._get_n_qubit_hamiltonian(qubit_names, couplings)
        dims = [q.truncated_dim for q in qubits]
        
        H_total, args = self._build_time_dependent_hamiltonian(
            H_sys, dims, local_ops, qubit_names, gate_type, duration, couplings, drives, detuning
        )
        
        opts = {"nsteps": 10000000}
        U_sim = qt.propagator(H_total, duration, [], args=args, options=opts)
        
        # Project U_sim to the 2^N computational subspace
        bases = []
        for bit_tuple in itertools.product([0, 1], repeat=N):
            basis_list = [qt.basis(dims[i], b) for i, b in enumerate(bit_tuple)]
            bases.append(qt.tensor(basis_list))
            
        dim_comp = 2**N
        U_comp_mat = np.zeros((dim_comp, dim_comp), dtype=complex)
        
        for r in range(dim_comp):
            for c in range(dim_comp):
                elem = bases[r].dag() * U_sim * bases[c]
                val = elem[0,0] if isinstance(elem, qt.Qobj) else elem
                U_comp_mat[r, c] = val
                
        U_comp = qt.Qobj(U_comp_mat, dims=[[2]*N, [2]*N])
        
        # Convert Unitary to Superoperator, then to Choi matrix
        S_comp = qt.to_super(U_comp)
        Choi_comp = qt.to_choi(S_comp)
        return Choi_comp

    def perform_state_tomography(self, state: qt.Qobj, target: qt.Qobj) -> Dict[str, float]:
        """
        Perform State Tomography Analysis (Fidelity Check).
        
        Real tomography involves measuring <P_i> for all Pauli strings.
        Here we calculate exact Fidelity and Trace Distance for simulation verification.
        
        Args:
            state: Simulation final state (ket or dm)
            target: Ideal target state (ket or dm)
            
        Returns:
            Dict with 'fidelity', 'trace_distance'
        """
        if state.type == 'ket':
            state_dm = qt.ket2dm(state)
        else:
            state_dm = state
            
        if target.type == 'ket':
            target_dm = qt.ket2dm(target)
        else:
            target_dm = target
            
        # 1. Fidelity: F = Tr(sqrt(sqrt(rho) * sigma * sqrt(rho)))^2
        # For pure states: |<psi|phi>|^2
        fid = qt.fidelity(state_dm, target_dm) ** 2
        
        # 2. Trace Distance
        tr_dist = qt.tracedist(state_dm, target_dm)
        
        # 3. Purity
        purity = state_dm.purity()
        
        return {
            "fidelity": fid,
            "trace_distance": tr_dist,
            "purity": purity
        }

    def simulate_n_qubit_dynamics(self, 
                                  qubit_names: List[str], 
                                  gate_type: str,
                                  duration: float, 
                                  couplings: List[Dict[str, Any]] = [],
                                  drives: List[Dict[str, Any]] = [],
                                  initial_state: str = None,
                                  steps: int = 200, 
                                  detuning: float = 0.0) -> Dict[str, Any]:
        """
        Simulate the generalized dynamics of an N-qubit system.
        
        Args:
            qubit_names: List of N qubit names defining the topology
            gate_type: Name of the gate being executed (e.g., 'TOFFOLI', 'CZ', 'CNOT')
            duration: Gate duration in ns
            couplings: Static and tunable couplings between qubits (adjacency list)
            drives: Microwave pulses applied to specific qubits
            initial_state: String like "011", defaults to "0" * N
        """
        N = len(qubit_names)
        
        # 1. Get Static System Hamiltonian
        H_sys, qubits, local_ops = self._get_n_qubit_hamiltonian(qubit_names, couplings)
        dims = [q.truncated_dim for q in qubits]
        
        # 2. Add Time-Dependent Drives and Tunable Couplers
        H_total, args = self._build_time_dependent_hamiltonian(
            H_sys, dims, local_ops, qubit_names, gate_type, duration, couplings, drives, detuning
        )

        # 3. Initial State
        if initial_state is None:
            initial_state = "0" * N
            
        basis_list = []
        for i, char in enumerate(initial_state):
             lvl = int(char)
             if lvl >= dims[i]: lvl = dims[i] - 1
             basis_list.append(qt.basis(dims[i], lvl))
        psi0 = qt.tensor(basis_list)

        # 4. Evolution
        times = np.linspace(0, duration, steps)
        opts = {"store_states": True, "nsteps": 10000000} 
        
        # Warning: H_total must be formatted exactly for QuTiP
        res = qt.mesolve(H_total, psi0, times, [], [], args=args, options=opts)
        
        # 5. Process Results (Populations up to 2^N computational space)
        # For performance, only track max 4 computational states if N=2, or 8 if N=3, or 16 if N=4
        comp_states = {}
        if N <= 4:
            import itertools
            for bit_tuple in itertools.product([0, 1], repeat=N):
                state_str = "".join(str(b) for b in bit_tuple)
                # Compute projection operator
                proj_list = [qt.projection(dims[i], b, b) for i, b in enumerate(bit_tuple)]
                proj_op = qt.tensor(proj_list)
                comp_states[state_str] = np.real(qt.expect(proj_op, res.states))
        
        result = {
            "times": times,
            "states": res.states, 
            "populations": comp_states,
            "final_state": res.states[-1]
        }
        
        # Post-processing for Tunable CNOT (legacy compat)
        if N == 2 and gate_type == "CNOT" and couplings[0]["type"] == "tunable_coupler":
            mat_h = np.eye(dims[1], dtype=complex)
            h_sub = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
            mat_h[0:2, 0:2] = h_sub
            h_obj = qt.Qobj(mat_h, dims=[[dims[1]], [dims[1]]])
            
            U_H = qt.tensor(qt.qeye(dims[0]), h_obj)
            new_final = U_H * res.states[-1]
            result["final_state"] = new_final
            if "11" in result["populations"]:
                p11 = qt.expect(qt.tensor(qt.projection(dims[0], 1, 1), qt.projection(dims[1], 1, 1)), new_final)
                result["populations"]["11"][-1] = np.real(p11)

        return result

    # --- Legacy Bridge ---
    def simulate_two_qubit_dynamics(self, qubit1_name: str, qubit2_name: str, 
                                   gate_type: str, coupling_type: str, 
                                   coupling_strength: float, duration: float, 
                                   steps: int = 100, detuning: float = 0.0) -> Dict[str, Any]:
        """Legacy wrapper bridging old tests to the new N-Qubit Engine"""
        couplings = [{"q1": 0, "q2": 1, "type": coupling_type, "strength": coupling_strength}]
        init = "10" if gate_type == "CNOT" else "11"
        return self.simulate_n_qubit_dynamics([qubit1_name, qubit2_name], gate_type, duration, 
                                              couplings, initial_state=init, steps=steps, detuning=detuning)

    def calculate_gate_fidelity(self, q1_name: str, q2_name: str, 
                                gate_type: str, coupling_type: str, 
                                strength: float, duration: float) -> Dict[str, float]:
        """
        Calculate Average Gate Fidelity using the full propagator.
        This effectively performs Process Tomography w/o 16 simulations.
        """
        import numpy as np
        print(f"Calculating Fidelity for {gate_type} ({coupling_type}) on {q1_name}-{q2_name}...")
        
        try:
            is_tunable = (coupling_type == "tunable_coupler")
            # If Tunable CZ, we pulse g. Static h_int is 0.
            if gate_type == "CNOT" and coupling_type == "tunable_coupler": 
                 # CNOT tunable uses CZ internally? 
                 pass
            
            H_sys, q_list, local_ops = self._get_n_qubit_hamiltonian(
                [q1_name, q2_name], 
                [{"q1": 0, "q2": 1, "type": coupling_type, "strength": strength if not is_tunable else 0.0}]
            )
            q1 = q_list[0]
            q2 = q_list[1]
            dim1 = q1.truncated_dim
            dim2 = q2.truncated_dim
            
            # Control / Pulse
            args = {}
            H_total = [H_sys]
            
            if gate_type == "CNOT":
                if coupling_type == "capacitive":
                    H0_2, _ = self._get_qubit_hamiltonian(q2_name)
                    e2 = H0_2.diag() / (2*np.pi)
                    w2 = e2[1] - e2[0]
                    op_drive = qt.tensor(self.get_control_hamiltonian("X", local_ops[0]), qt.qeye(dim2))
                    amp = 0.100 * 2 * np.pi 
                    def drive_coeff(t, args): return args['amp'] * np.cos(args['w'] * t)
                    H_total.append([op_drive, drive_coeff])
                    args = {'amp': amp, 'w': w2 * 2 * np.pi}
                    
                elif coupling_type == "tunable_coupler":
                    # CZ pulse logic
                    op_int = qt.tensor(local_ops[0]['n'], local_ops[1]['n'])
                    def coupling_coeff(t, args): 
                        return args['g'] * (np.sin(np.pi * t / args['T'])**2)
                    H_total.append([op_int, coupling_coeff])
                    args = {'g': strength * 2 * np.pi, 'T': duration}
            
            elif gate_type == "CZ":
                 if coupling_type == "tunable_coupler":
                    op_int = qt.tensor(local_ops[0]['n'], local_ops[1]['n'])
                    def coupling_coeff(t, args): 
                        return args['g'] * (np.sin(np.pi * t / args['T'])**2)
                    H_total.append([op_int, coupling_coeff])
                    args = {'g': strength * 2 * np.pi, 'T': duration}
            
            # 2. Compute Propagator U_sim
            # Use increased nsteps for stiff pulses and Dict options
            opts = qt.Options(nsteps=50000)
            U_sim = qt.propagator(H_total, duration, args=args, options=opts)
            
            # 3. Project to Computational Subspace (2x2 = 4 states)
            bases = []
            for i in range(2):
                for j in range(2):
                    bases.append(qt.tensor(qt.basis(dim1, i), qt.basis(dim2, j)))
            
            U_comp = np.zeros((4, 4), dtype=complex)
            for r in range(4):
                for c in range(4):
                    elem = bases[r].dag() * U_sim * bases[c]
                    # Handle both Qobj (1x1) and scalar return types
                    val = elem[0,0] if isinstance(elem, qt.Qobj) else elem
                    U_comp[r, c] = val
                    
            U_sim_qt = qt.Qobj(U_comp, dims=[[2,2],[2,2]])
            
            # 4. Ideal Unitary
            if gate_type == "CNOT":
                # Explicit Qobj for CNOT (|00>,|01> identity; |10><->|11> swap)
                # Basis order: 00, 01, 10, 11
                U_ideal = qt.Qobj([[1,0,0,0],[0,1,0,0],[0,0,0,1],[0,0,1,0]], dims=[[2,2],[2,2]])
                
                if coupling_type == "tunable_coupler":
                     h_mat = qt.Qobj([[1, 1], [1, -1]], dims=[[2],[2]]) / np.sqrt(2)
                     op_H = qt.tensor(qt.qeye(2), h_mat)
                     U_sim_qt = op_H * U_sim_qt * op_H

            elif gate_type == "CZ":
                 U_ideal = qt.Qobj([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,-1]], dims=[[2,2],[2,2]])
            
            # 5. Calculate Average Gate Fidelity
            d = 4
            tr = (U_ideal.dag() * U_sim_qt).tr()
            F_avg = (np.abs(tr)**2 + d) / (d * (d + 1))
            
            return {"average_fidelity": float(F_avg)}
            
        except Exception as e:
            print(f"Fidelity Calc Failed: {e}")
            import traceback
            traceback.print_exc()
            return {"average_fidelity": 0.0}
