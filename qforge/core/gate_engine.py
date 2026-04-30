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
        self._calib_cache = {}
        
    def _get_qubit_hamiltonian(self, qubit_name: str) -> Tuple[qt.Qobj, Dict[str, qt.Qobj]]:
        """
        Get the Hamiltonian of a qubit in its eigenbasis (truncated),
        along with its physical operators (charge, flux) projected into that same basis.
        """
        self.qubit_engine.load_session()
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
        self.qubit_engine.load_session()
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
                n_mat = operators['n'].full()
                # Multiply lower triangle by 1j and upper by -1j to keep the operator Hermitian
                return qt.Qobj(1j * np.tril(n_mat, -1) - 1j * np.triu(n_mat, 1))
            else:
                a = qt.destroy(operators['n'].shape[0])
                return 1j * (a.dag() - a)
        elif gate_type == "Z":
            # Flux tuning or Stark shift
            if 'phi' in operators:
                return operators['phi'] # Technically Stark shift is n^2, flux is phi. Using phi as placeholder.
            else:
                a = qt.destroy(operators['n'].shape[0])
                return a.dag() * a
        elif gate_type == "H":
            # Synthesize Hadamard via Y(pi/2) to preserve algorithmic phase
            if 'n' in operators:
                n_mat = operators['n'].full()
                return qt.Qobj(1j * np.tril(n_mat, -1) - 1j * np.triu(n_mat, 1))
            else:
                a = qt.destroy(operators['n'].shape[0])
                return 1j * (a.dag() - a)
        else:
            raise ValueError(f"Unknown gate control: {gate_type}")

    def simulate_dynamics(self, 
                          qubit_name: str, 
                          gate_type: str, 
                          duration: float, 
                          noise_model: str = "none",
                          steps: int = 100,
                          drag_lambda: float = 0.5,
                          use_drag: bool = True) -> Dict[str, Any]:
        """
        Simulate single-qubit gate dynamics using extracted scqubits matrices.
        """
        self.qubit_engine.load_session()
        # 1. Setup System
        qubit = self.qubit_engine.get_qubit(qubit_name)
        dim = qubit.truncated_dim
        
        # Get Drift Hamiltonian and true physical operators
        H0, operators = self._get_qubit_hamiltonian(qubit_name)
        
        # Rotating Wave Approximation (RWA)
        # Transform to frame rotating at qubit frequency w01
        evals_ang = H0.diag()
        w01_ang = evals_ang[1] - evals_ang[0]
        
        # Calculate Anharmonicity for DRAG
        if dim >= 3:
            w12_ang = evals_ang[2] - evals_ang[1]
            alpha_ang = w12_ang - w01_ang
        else:
            alpha_ang = 0.0
            
        drag_coef = -drag_lambda / alpha_ang if (use_drag and alpha_ang != 0) else 0.0
        
        evals_rot = np.array([e - i * w01_ang for i, e in enumerate(evals_ang)])
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
        
        # Time array
        tlist = np.linspace(0, duration, steps)
        
        #Gaussian envelope parameters (6-sigma width)
        sigma = duration / 6.0 if duration > 0 else 1.0
        mu = duration / 2.0
        
        # Calculate the numerical integral of the envelope to properly calibrate the peak amplitude
        envelope_array = np.exp(-0.5 * ((tlist - mu) / sigma)**2)
        env_integral = np.trapezoid(envelope_array, tlist)
        if env_integral == 0: env_integral = 1.0
        
        amplitude = target_rotation / (2.0 * matrix_element_01 * env_integral)
        
        def drive_shape(t, args):
            return amplitude * np.exp(-0.5 * ((t - mu) / sigma)**2)
        
        def drag_shape(t, args):
            if drag_coef == 0.0: 
                return 0.0
            derivative = amplitude * (-(t - mu) / (sigma**2)) * np.exp(-0.5 * ((t - mu) / sigma)**2)
            return drag_coef * derivative
        
        # Setup Noise
        c_ops = []
        if noise_model == "realistic":
            coherence = self.qubit_engine.estimate_coherence(qubit)
            t1 = coherence.get("T1 (dielectric)", {}).get("value", 50.0) * 1000  # ns
            if t1 > 0:
                rate_relax = 1.0 / t1
                # Still using a simple collapse operator for single-qubit relax, 
                # but could use exact loss operators mapped to `n` in the future.
                c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))
            
        # Initial State
        psi0 = qt.basis(dim, 0) 
        
        # Evolve
        H_total = [H0_rot, [H_ctrl, drive_shape]]
        
        if use_drag and drag_coef != 0.0:
            # Create orthogonal RWA operator (90-degree phase shift)
            H_ctrl_mat = H_ctrl.full()
            H_drag_mat = 1j * np.tril(H_ctrl_mat, -1) - 1j * np.triu(H_ctrl_mat, 1)
            H_total.append([qt.Qobj(H_drag_mat), drag_shape])
            
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
        self.qubit_engine.load_session()
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
                     # Requires phi_operator support from the underlying scqubits model.
                     # Charge-basis qubits (Transmon, TunableTransmon) do not expose phi_operator.
                     # Use Fluxonium, FluxQubit, or ZeroPi for inductive coupling instead.
                     for idx, name in [(i, qubit_names[i]), (j, qubit_names[j])]:
                         if 'phi' not in local_ops[idx]:
                             raise ValueError(
                                 f"Qubit '{name}' does not support inductive coupling.\n\n"
                                 f"Inductive (mutual inductance) coupling requires a shared geometric "
                                 f"inductor between the two circuits, producing an interaction of the "
                                 f"form g*phi_i*phi_j. Fluxonium, FluxQubit, and ZeroPi qubits have "
                                 f"an explicit inductor (EL*phi^2) in their circuit, making this "
                                 f"coupling natural and physically meaningful.\n\n"
                                 f"A Transmon has no such inductor — it is a Josephson junction "
                                 f"shunted by a large capacitor (EJ >> EC). Its dominant coupling "
                                 f"mechanism is capacitive (g*n_i*n_j), and its scqubits model "
                                 f"operates in the charge basis, which does not expose a phi_operator.\n\n"
                                 f"To fix this: use 'capacitive' coupling for Transmon/TunableTransmon "
                                 f"qubits, or switch to Fluxonium/FluxQubit/ZeroPi if inductive "
                                 f"coupling is required."
                             )
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
        self.qubit_engine.load_session()
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
        self.qubit_engine.load_session()
        try:
             # 1. Full simulation — use a coupler pulse identical to what compile_schedule will use,
             #    so the calibrated duration matches actual execution.
             coupler_drive = [{"target": (0, 1), "type": "coupler_pulse", "strength": strength, "start_time": 0.0, "end_time": duration}]
             res = self.simulate_n_qubit_dynamics(
                 [q1, q2], "CZ", duration,
                 couplings=[{"q1": 0, "q2": 1, "type": coupling_type, "strength": strength}],
                 drives=coupler_drive,
                 initial_state="11", steps=20, detuning=detuning
             )
             final_state = res["final_state"]

             # 2. Reference simulation — same coupler pulse but coupling strength 0 so only
             #    the dynamical (single-qubit) phase accumulates. Subtracting it isolates the
             #    entangling phase contribution from the coupling.
             ref_drive = [{"target": (0, 1), "type": "coupler_pulse", "strength": 0.0, "start_time": 0.0, "end_time": duration}]
             res_ref = self.simulate_n_qubit_dynamics(
                 [q1, q2], "CZ", duration,
                 couplings=[{"q1": 0, "q2": 1, "type": coupling_type, "strength": 0.0}],
                 drives=ref_drive,
                 initial_state="11", steps=20, detuning=detuning
             )
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
        self.qubit_engine.load_session()
        target_str = f"{q1_name}-{q2_name}" if q2_name else q1_name
        
        # 1. SETUP RANGES FIRST (Crucial for correct caching behavior)
        if len(range_vals) == 0:
            if parameter == "duration":
                if gate_type in ["X", "Y", "H"]:
                    # Physics-informed estimate: T_pi = 6 / (amp * n01 * sqrt(2pi))
                    # where amp is the drive amplitude (before 2pi factor) and n01 is the
                    # |<1|n|0>| matrix element of the charge operator in the eigenbasis.
                    try:
                        _, ops = self._get_qubit_hamiltonian(q1_name)
                        n01 = float(abs(ops['n'].full()[0, 1])) if 'n' in ops else 0.0
                    except Exception:
                        n01 = 0.0
                    amp_in = kwargs.get("amplitude", 0.025)
                    if n01 > 0.01:
                        # Rabi freq (RWA): Omega = amp*2pi/2 * n01
                        # Gaussian integral factor: sigma*sqrt(2pi) = (T/6)*sqrt(2pi)
                        # T_pi = pi / (Omega * (1/6)*sqrt(2pi)) = 6 / (amp * n01 * sqrt(2pi))
                        T_est = 6.0 / (amp_in * n01 * np.sqrt(2 * np.pi))
                        if gate_type == "H":
                             # Target is a pi/2 pulse instead of a pi pulse
                             T_est = T_est / 2.0
                        range_vals = np.linspace(max(2.0, 0.4 * T_est), 1.8 * T_est, 20)
                    else:
                        range_vals = np.linspace(5, 80, 20)
                elif coupling_type == "tunable_coupler":
<<<<<<< HEAD
                     range_vals = np.linspace(5, 100, 20)
                elif coupling_type == "capacitive" and gate_type == "CZ" and coupling_strength > 0:
                    # Physics-informed range: optimal CZ duration ≈ π/(4g)
                    T_est = np.pi / (4 * coupling_strength)
                    range_vals = np.linspace(0.3 * T_est, 2.0 * T_est, 30)
                else: # Capacitive CR drives / inductive
                     range_vals = np.linspace(50, 400, 20)
=======
                     range_vals = np.linspace(5, 200, 30)
                else: # Capacitive CR drives
                     range_vals = np.linspace(50, 400, 20) 
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df
            elif parameter == "amplitude":
                range_vals = np.linspace(0.01, 0.2, 15)
            elif parameter == "detuning":
                range_vals = np.linspace(-1.0, 1.0, 20)

        # 2. GENERATE CACHE KEY
        if not hasattr(self, "_calib_cache"):
            self._calib_cache = {}
            
        kw_tuple = tuple(sorted(kwargs.items()))
        try:
            rv_tuple = tuple(float(v) for v in range_vals)
        except TypeError:
            rv_tuple = ()
            
        cache_key = (q1_name, q2_name, gate_type, coupling_type, coupling_strength, parameter, kw_tuple, rv_tuple)
        
        # --- FIX: Return quietly if in cache to prevent optimization loop spam ---
        if cache_key in self._calib_cache:
            return self._calib_cache[cache_key]

        # Only print the banner if we are actually performing a new calibration
        target_str = f"{q1_name}-{q2_name}" if q2_name else q1_name
        print(f"Calibrating {gate_type} ({coupling_type or 'local'}) on {target_str}...")

        # 3. EVALUATION FUNCTION
        def evaluate_metric(val):
            metric = -1.0 # Default to severe penalty on failure
            default_dur = 40.0 if gate_type in ["X", "Y", "H"] else 150.0
            default_det = 0.0
            if gate_type in ["CNOT", "CZ"] and coupling_type == "tunable_coupler":
                default_det = self._calculate_resonant_flux(q1_name, q2_name)
            current_dur = val if parameter == "duration" else kwargs.get("duration", default_dur)
            current_amp = val if parameter == "amplitude" else kwargs.get("amplitude", 0.025)
            current_det = val if parameter == "detuning" else kwargs.get("detuning", default_det)
            
            try:
                if gate_type in ["X", "Y", "H"]:
                    evals = self.qubit_engine.get_qubit(q1_name).eigensys(evals_count=2)[0]
                    w01 = evals[1] - evals[0]
                    current_use_drag = kwargs.get("use_drag", True)
                    current_drag_lambda = kwargs.get("drag_lambda", 0.5)
                    
                    if gate_type == "H":
                        # Calibrate H (Y(pi/2)) by applying it twice to simulate H^2=I (Y(pi))
                        # This enforces robust phase calibration and penalizes leakage.
                        drives = [
                            {"target": 0, "type": gate_type, "amplitude": current_amp, "frequency": w01, "phase": 0.0, "start_time": 0.0, "end_time": current_dur},
                            {"target": 0, "type": gate_type, "amplitude": current_amp, "frequency": w01, "phase": 0.0, "start_time": current_dur, "end_time": 2 * current_dur}
                        ]
                        res = self.simulate_n_qubit_dynamics([q1_name], f"Calibrate_{gate_type}", 2 * current_dur, [], drives, "0", steps=40, use_drag=current_use_drag, drag_lambda=current_drag_lambda)
                        p1 = res["populations"]["1"][-1] if "1" in res["populations"] else 0.0
                        metric = p1
                    else:
                        drives = [{"target": 0, "type": gate_type, "amplitude": current_amp, "frequency": w01, "phase": 0.0, "start_time": 0.0, "end_time": current_dur}]
                        res = self.simulate_n_qubit_dynamics([q1_name], f"Calibrate_{gate_type}", current_dur, [], drives, "0", steps=20, use_drag=current_use_drag, drag_lambda=current_drag_lambda)
                        p1 = res["populations"]["1"][-1] if "1" in res["populations"] else 0.0
                        metric = p1
                        
                elif gate_type == "CNOT":
                    current_use_drag = kwargs.get('use_drag', True)
                    current_drag_lambda = kwargs.get('drag_lambda', 0.5)
                    res = self.simulate_two_qubit_dynamics(
                        q1_name, q2_name, gate_type, coupling_type, coupling_strength, 
                        duration=current_dur, 
                        steps=40, 
                        detuning=current_det, 
                        use_drag=current_use_drag,
                        drag_lambda=current_drag_lambda,
                        initial_state="10"
                    )
                    metric = res["populations"]["11"][-1]
                    
                elif gate_type == "CZ":
                    phase_pi = self._calculate_interaction_phase_metric(
                        q1_name, q2_name, coupling_type, coupling_strength, current_dur, detuning=current_det
                    )
                    ph = phase_pi % 2.0
                    metric = 1.0 - (ph - 1.0)**2
                    
            except Exception as e:
                print(f"      [!] Metric eval failed at {parameter}={val:.3f}: {e}")
                metric = -1.0 
                
            return metric

        # 4. COARSE SWEEP
        print(f" -> Coarse sweep ({len(range_vals)} points)...")
        metrics = [evaluate_metric(v) for v in range_vals]
        best_idx = np.argmax(metrics)
        best_val = range_vals[best_idx]
        max_metric = metrics[best_idx]
        
        # 5. WIDENED FINE SWEEP
        if max_metric > 0.1:
             step = abs(range_vals[1] - range_vals[0]) if len(range_vals) > 1 else 5.0
             
             # Loosen bounds to ±1.5 steps to safely catch offset peaks
             bound_lower = best_val - (1.5 * step)
             bound_upper = best_val + (1.5 * step)
             
             # Physical bounds clamping
             if parameter == "duration":
                 bound_lower = max(0.1, bound_lower) 
             elif parameter == "amplitude":
                 bound_lower = max(0.001, bound_lower)
             
             # Higher density (50 points) required due to widened search net
             fine_range = np.linspace(bound_lower, bound_upper, 50)
             print(f" -> Fine sweep (50 points) widened to [{bound_lower:.2f}, {bound_upper:.2f}]...")
             
             fine_metrics = [evaluate_metric(v) for v in fine_range]
             fine_best_idx = np.argmax(fine_metrics)
             
             if fine_metrics[fine_best_idx] > max_metric:
                 best_val = fine_range[fine_best_idx]
                 max_metric = fine_metrics[fine_best_idx]
             
        # Save the computed value to the cache before returning
        print(f"  -> Calibrated {parameter.capitalize()}: {best_val:.4f} (Metric: {max_metric:.4f})")
        self._calib_cache[cache_key] = (best_val, max_metric)
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
                                          detuning: float = 0.0,
                                          drag_scheme: bool = True,
                                          drag_lambda: float = 0.5) -> Tuple[List[Any], Dict[str, Any]]:
        self.qubit_engine.load_session()
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
                
            elif drive.get("type") == "flux_pulse":
                target_idx = drive["target"]
                # Safeguard: if a tuple is passed, assume the flux is applied to the target qubit
                if isinstance(target_idx, (tuple, list)):
                    target_idx = target_idx[-1]
                det = drive.get("detuning", 0.0) * 2 * np.pi
                t_start = drive.get("start_time", 0.0)
                t_end = drive.get("end_time", duration)
                pulse_dur = t_end - t_start
                if pulse_dur <= 0: continue
                
                op_list = [qt.qeye(d) for d in dims]
                op_list[target_idx] = qt.num(dims[target_idx])
                op_flux = qt.tensor(op_list)
                
                def make_flux_coeff(det_val, ts, dur):
                     # Synchronize the flux pulse to match the sin^2 coupler pulse
                     return lambda t, args: det_val * (np.sin(np.pi * (t - ts) / dur)**2) if (ts <= t <= ts + dur) else 0.0
                     
                flux_func = make_flux_coeff(det, t_start, pulse_dur)
                H_total.append([op_flux, flux_func])
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
                
                # Calculate Anharmonicity for DRAG
                target_qubit = self.qubit_engine.get_qubit(qubit_names[target_idx])
                evals_ang = target_qubit.eigenvals(evals_count=3) * 2 * np.pi
                if len(evals_ang) >= 3:
                    w01_ang = evals_ang[1] - evals_ang[0]
                    w12_ang = evals_ang[2] - evals_ang[1]
                    alpha_ang = w12_ang - w01_ang
                else:
                    alpha_ang = 0.0
                    
                drag_coef = -drag_lambda / alpha_ang if (drag_scheme and alpha_ang != 0) else 0.0
                
                def make_drive_coeff(a, f, p, ts, te, d_coef):
                     dur = te - ts
                     mu = ts + dur / 2.0
                     sigma = dur / 6.0 if dur > 0 else 1.0
                     return lambda t, args: (
                         (a * np.exp(-0.5 * ((t - mu) / sigma)**2) * np.cos(f * t + p) - 
                          d_coef * a * (-(t - mu) / (sigma**2)) * np.exp(-0.5 * ((t - mu) / sigma)**2) * np.sin(f * t + p))
                         if (ts <= t <= te) else 0.0
                     )
                         
                coeff_func = make_drive_coeff(amp, freq, phase, t_start, t_end, drag_coef)
                H_total.append([op_drive, coeff_func])
            
        # B) Tunable Couplers
        for c_idx, coupling in enumerate(couplings):
            if coupling["type"] == "tunable_coupler":
                idx1 = coupling["q1"]
                idx2 = coupling["q2"]
                g_amp = coupling.get("strength", 0.0) * 2 * np.pi
                
<<<<<<< HEAD
                has_explicit_drive = False
                for d in drives:
                    if d.get("type") == "coupler_pulse":
                        targ = d.get("target")
                        if isinstance(targ, (list, tuple)) and len(targ) == 2:
                            if (targ[0] == idx1 and targ[1] == idx2) or (targ[0] == idx2 and targ[1] == idx1):
                                has_explicit_drive = True
                                break
                                
                if not has_explicit_drive and gate_type not in ["Compiled_Algorithm", "CNOT_COMPILED"]:
                    op_list = [qt.qeye(d) for d in dims]
                    op_list[idx1] = local_ops[idx1]['n']
                    op_list[idx2] = local_ops[idx2]['n']
                    op_int = qt.tensor(op_list)
                    
                    def make_pulse_coeff(g_val, dur):
                         mu = dur / 2.0
                         sigma = dur / 6.0 if dur > 0 else 1.0
                         return lambda t, args: g_val * np.exp(-0.5 * ((t - mu) / sigma)**2) if (0 <= t <= dur) else 0.0
                         
                    pulse_func = make_pulse_coeff(g_amp, duration)
                    H_total.append([op_int, pulse_func])
=======
                op_list = [qt.qeye(d) for d in dims]
                op_list[idx1] = local_ops[idx1]['n']
                op_list[idx2] = local_ops[idx2]['n']
                op_int = qt.tensor(op_list)
                
                def make_pulse_coeff(g_val, dur): #sin^2 pulse
                     return lambda t, args: g_val * (np.sin(np.pi * t / dur)**2) if (0 <= t <= dur) else 0.0
                     
                pulse_func = make_pulse_coeff(g_amp, duration)
                H_total.append([op_int, pulse_func])
>>>>>>> f2b308b3923f4adb88b7f5afaa1c4f3ed215b8df
                
        # C) Specific gate overrides for compatibility with old 2-qubit caller
        if N == 2:
            if gate_type == "CNOT" and couplings[0].get("type") == "capacitive":
                H0_2, _ = self._get_qubit_hamiltonian(qubit_names[1])
                e2 = H0_2.diag() / (2*np.pi)
                w2 = e2[1] - e2[0]
                
                if not any(d["target"] == 1 for d in drives):
                    op_list = [qt.qeye(d) for d in dims]
                    op_list[0] = self.get_control_hamiltonian("X", local_ops[0])
                    op_drive = qt.tensor(op_list)
                    amp = 0.040 * 2 * np.pi 
                    
                    def cr_drive(t, args):
                        T = args['dur']
                        mu = T / 2.0
                        sigma = T / 6.0 if T > 0 else 1.0
                        env = np.exp(-0.5 * ((t - mu) / sigma)**2) if (0 <= t <= T) else 0.0
                        return args['cr_amp'] * env * np.cos(args['cr_w'] * t)
                    H_total.append([op_drive, cr_drive])
                    args['cr_amp'] = amp
                    args['cr_w'] = w2 * 2 * np.pi
                    args['dur'] = duration
                    
            elif gate_type == "CZ":
                if couplings[0]["type"] == "tunable_coupler":
                    op_list = [qt.qeye(d) for d in dims]
                    op_list[1] = qt.num(dims[1]) 
                    n2_op = qt.tensor(op_list)
                    
                    def flux_coeff(t, args):
                        T = args['T']
                        mu = T / 2.0
                        sigma = T / 6.0 if T > 0 else 1.0
                        return args['det'] * np.exp(-0.5 * ((t - mu) / sigma)**2) if (0 <= t <= T) else 0.0
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
        self.qubit_engine.load_session()
        import itertools
        import numpy as np
        
        N = len(qubit_names)
        H_sys, qubits, local_ops = self._get_n_qubit_hamiltonian(qubit_names, couplings)
        dims = [q.truncated_dim for q in qubits]
        
        H_total, args = self._build_time_dependent_hamiltonian(
            H_sys, dims, local_ops, qubit_names, gate_type, duration, couplings, drives, detuning
        )
        
        opts = qt.Options(nsteps=10000000, max_step=0.01)
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
        self.qubit_engine.load_session()
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
    
    def _calculate_resonant_flux(self, q_ctrl_name: str, q_targ_name: str) -> float:
        """Dynamically calculate the flux required to align |11> and |02>."""
        evals_ctrl = self.qubit_engine.get_qubit(q_ctrl_name).eigensys(evals_count=3)[0]
        evals_targ = self.qubit_engine.get_qubit(q_targ_name).eigensys(evals_count=3)[0]

        w1 = np.real(evals_ctrl[1] - evals_ctrl[0])
        w2 = np.real(evals_targ[1] - evals_targ[0])
        alpha2 = np.real(evals_targ[2] - evals_targ[1] - w2)

        return w1 - w2 - alpha2

    def simulate_n_qubit_dynamics(self,
                                  qubit_names: List[str],
                                  gate_type: str,
                                  duration: float,
                                  couplings: List[Dict[str, Any]] = [],
                                  drives: List[Dict[str, Any]] = [],
                                  initial_state: Optional[Any] = None,
                                  steps: int = 200,
                                  detuning: float = 0.0,
                                  use_drag: bool = True,
                                  drag_lambda: float = 0.5) -> Dict[str, Any]:
        """
        Simulate the generalized dynamics of an N-qubit system.
        
        Args:
            qubit_names: List of N qubit names defining the topology
            gate_type: Name of the gate being executed (e.g., 'TOFFOLI', 'CZ', 'CNOT')
            duration: Gate duration in ns
            couplings: Static and tunable couplings between qubits (adjacency list)
            drives: Microwave pulses applied to specific qubits
            initial_state: String like "011", or a QuTiP Qobj. Defaults to all-zero state.
            use_drag: Whether to apply DRAG correction to microwave drives.
        """
        self.qubit_engine.load_session()
        N = len(qubit_names)

        # flux pulse detuning implicit calculation
        if N == 2 and gate_type in ["CNOT", "CZ"] and couplings and couplings[0].get("type") == "tunable_coupler":
            if detuning == 0.0:
                detuning = self._calculate_resonant_flux(qubit_names[0], qubit_names[1])
        
        # For a tunable coupler, a CNOT is physically implemented as an H-CZ-H sequence.
        # This block compiles that logical gate into a single, continuous physical pulse schedule.
        if N == 2 and gate_type == "CNOT" and couplings and couplings[0].get("type") == "tunable_coupler":
            # 1. Calibrate Pi pulse duration
            t_cz = duration
            t_x, _ = self.calibrate_gate(
                qubit_names[1], gate_type="X", parameter="duration",
                use_drag=use_drag, drag_lambda=drag_lambda
            )
            t_h = t_x / 2.0

            # 2. Extract physical frequencies to auto-tune the avoided crossing
            H0_control, _ = self._get_qubit_hamiltonian(qubit_names[0])
            H0_target, _ = self._get_qubit_hamiltonian(qubit_names[1])

            e_ctrl = H0_control.diag() / (2 * np.pi)
            e_tgt = H0_target.diag() / (2 * np.pi)

            w01_ctrl = np.real(e_ctrl[1] - e_ctrl[0])
            w01_tgt = np.real(e_tgt[1] - e_tgt[0])

            alpha_tgt = np.real((e_tgt[2] - e_tgt[1]) - w01_tgt) if len(e_tgt) >= 3 else 0.0
            auto_detuning = (w01_ctrl - w01_tgt - alpha_tgt) if detuning == 0.0 and alpha_tgt != 0.0 else detuning

            # Calculate Virtual Z Phase Correction
            exact_flux_phase = (auto_detuning * 2 * np.pi) * (t_cz / 2.0)

            # 3. Build the chronologically scheduled list
            full_drives = []
            current_time = 0.0

            # First Y(pi/2) gate
            full_drives.append({
                "target": 1, 
                "type": "X", 
                "amplitude": 0.025, 
                "frequency": w01_tgt, 
                "phase": -np.pi / 2, 
                "start_time": current_time, 
                "end_time": current_time + t_h
            })
            current_time += t_h

            # CZ-pulse (Coupler + Auto-Tuned Flux)
            full_drives.append({
                "target": (0, 1), 
                "type": "coupler_pulse", 
                "strength": couplings[0]["strength"], 
                "start_time": current_time, 
                "end_time": current_time + t_cz
            })
            full_drives.append({
                "target": 1, 
                "type": "flux_pulse", 
                "detuning": auto_detuning, 
                "start_time": current_time, 
                "end_time": current_time + t_cz
            })
            current_time += t_cz

            # Second -Y(pi/2) gate with Virtual Z Phase Correction to align physical drive
            full_drives.append({
                "target": 1, 
                "type": "X", 
                "amplitude": 0.025, 
                "frequency": w01_tgt, 
                "phase": (np.pi / 2) + exact_flux_phase, 
                "start_time": current_time, 
                "end_time": current_time + t_h
            })
            current_time += t_h

            # 4. Execute the entire compiled sequence
            res = self.simulate_n_qubit_dynamics(
                qubit_names=qubit_names,
                gate_type="CNOT_COMPILED",
                duration=current_time,
                couplings=[], 
                drives=full_drives,
                initial_state=initial_state,
                steps=steps,
                detuning=0.0, 
                use_drag=use_drag,
                drag_lambda=drag_lambda
            )

            # --- FIX: VIRTUAL Z CORRECTION FOR LOGICAL FRAME ---
            # The Strobed RWA cancels static phase, but is blind to the dynamic 
            # phase accumulated by the flux pulse. We must manually cancel this 
            # residual phase to restore the target qubit to the global logical clock.
            
            # Extract dimensions directly from the Hamiltonians we already loaded
            dim_ctrl = H0_control.shape[0]
            dim_tgt = H0_target.shape[0]
            
            z_corr = qt.Qobj(np.diag([np.exp(1j * k * exact_flux_phase) for k in range(dim_tgt)]))
            U_z = qt.tensor(qt.qeye(dim_ctrl), z_corr)
            
            res["final_state"] = U_z * res["final_state"]
            
            return res

        # --- Original simulation logic for all other gate types ---

        # 1. Get Static System Hamiltonian
        H_sys, qubits, local_ops = self._get_n_qubit_hamiltonian(qubit_names, couplings)
        dims = [q.truncated_dim for q in qubits]

        # 2. Add Time-Dependent Drives and Tunable Couplers
        H_total, args = self._build_time_dependent_hamiltonian(
            H_sys, dims, local_ops, qubit_names, gate_type, duration, couplings, drives, detuning, drag_scheme=use_drag, drag_lambda=drag_lambda
        )

        # 3. Initial State
        if initial_state is None:
            initial_state = "0" * N

        if isinstance(initial_state, str):
            basis_list = []
            for i, char in enumerate(initial_state):
                 lvl = int(char)
                 if lvl >= dims[i]: lvl = dims[i] - 1
                 basis_list.append(qt.basis(dims[i], lvl))
            psi0 = qt.tensor(basis_list)
        else:
            # Assume initial_state is already a precise QuTiP Qobj state
            psi0 = initial_state

        # 4. Evolution
        # For lab-frame simulation at ~5 GHz, a 0.2ns period dictates we need ~50 points/ns 
        # to satisfy the Nyquist limit and avoid ODE aliasing.
        dynamic_steps = max(steps, int(duration * 50))
        times = np.linspace(0, duration, dynamic_steps)
        
        # Force max_step so the solver doesn't skip over microwave drive oscillations
        opts = qt.Options(
            store_states=True, 
            nsteps=10000000,
            max_step=0.01  
        )

        res = qt.mesolve(H_total, psi0, times, [], [], args=args, options=opts)

        # 5. Process Results (Populations up to 4 states per qubit: 0, 1, 2, 3)
        comp_states = {}
        if len(res.states) > 0:
            import itertools
            # Track up to level 3 (ket 0, 1, 2, 3)
            ranges = [range(min(4, d)) for d in dims]

            is_ket = res.states[0].type == 'ket'
            if is_ket:
                state_data = np.array([s.full().flatten() for s in res.states])
                probs = np.abs(state_data)**2
            else:
                state_data = np.array([s.diag() for s in res.states])
                probs = np.real(state_data)

            for k_tuple in itertools.product(*ranges):
                state_str = "".join(str(k) for k in k_tuple)
                idx = np.ravel_multi_index(k_tuple, dims)
                comp_states[state_str] = probs[:, idx]

        result = {
            "times": times,
            "states": res.states,
            "populations": comp_states,
            "final_state": res.states[-1]
        }

        # ---------------------------------------------------------
        # 6. Logical Frame Transformation (Strobed RWA)
        # Cancel the lab-frame dynamical phase so sequential gates 
        # maintain Local Oscillator sync for the next simulation call.
        # ---------------------------------------------------------
        if len(res.states) > 0:
            import itertools
            
            # Extract absolute eigenvalues for all qubits
            e_list = [self._get_qubit_hamiltonian(name)[0].diag() for name in qubit_names]
            dim_total = np.prod(dims)
            phases = np.zeros(dim_total)
            
            # Calculate the exact phase accumulated by every basis state
            ranges = [range(d) for d in dims]
            for k_tuple in itertools.product(*ranges):
                idx = np.ravel_multi_index(k_tuple, dims)
                energy = sum(e_list[q][k] for q, k in enumerate(k_tuple))
                # phase = E * t
                phases[idx] = energy * duration
                
            # Build the inverse rotation matrix
            U_frame = qt.Qobj(np.diag(np.exp(1j * phases)), dims=[dims, dims])
            
            # Rotate the final state back into the logical frame
            result["final_state"] = U_frame * res.states[-1]

        return result

    # --- Legacy Bridge ---
    def simulate_two_qubit_dynamics(self, qubit1_name: str, qubit2_name: str, 
                                   gate_type: str, coupling_type: str, 
                                   coupling_strength: float, duration: float, 
                                   steps: int = 100, detuning: float = 0.0, use_drag: bool = True,
                                   drag_lambda: float = 0.5,
                                   initial_state: Optional[Any] = None) -> Dict[str, Any]:
        """Legacy wrapper bridging old tests to the new N-Qubit Engine"""
        self.qubit_engine.load_session()
        couplings = [{"q1": 0, "q2": 1, "type": coupling_type, "strength": coupling_strength}]
        
        # If initial_state is not provided, use legacy defaults.
        init = initial_state
        if init is None:
            init = "10" if gate_type == "CNOT" else "11"
            
        return self.simulate_n_qubit_dynamics([qubit1_name, qubit2_name], gate_type, duration, 
                                              couplings, initial_state=init, steps=steps, detuning=detuning, use_drag=use_drag, drag_lambda=drag_lambda)

    def calculate_gate_fidelity(self, q1_name: str, q2_name: str, 
                                gate_type: str, coupling_type: str, 
                                strength: float, duration: float) -> Dict[str, float]:
        """
        Calculate Average Gate Fidelity using the full propagator.
        This effectively performs Process Tomography w/o 16 simulations.
        """
        self.qubit_engine.load_session()
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
            opts = qt.Options(nsteps=50000, max_step=0.01)
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
                    
            # ... existing code ...
            U_sim_qt = qt.Qobj(U_comp, dims=[[2,2],[2,2]])
            
            # --- FIX: Cancel out the lab-frame dynamical phase ---
            H0_1, _ = self._get_qubit_hamiltonian(q1_name)
            H0_2, _ = self._get_qubit_hamiltonian(q2_name)
            
            # Extract bare angular frequencies
            e1 = H0_1.diag() 
            e2 = H0_2.diag()

            # Calculate the natural phase accumulation (exp(i * E * t))
            # QuTiP evolves with exp(-i H t), so to reverse it, we apply positive phase
            phase_00 = (e1[0] + e2[0]) * duration
            phase_01 = (e1[0] + e2[1]) * duration
            phase_10 = (e1[1] + e2[0]) * duration
            phase_11 = (e1[1] + e2[1]) * duration

            # Build the frame transformation operator
            U_frame = qt.Qobj(np.diag([
                np.exp(1j * phase_00),
                np.exp(1j * phase_01),
                np.exp(1j * phase_10),
                np.exp(1j * phase_11)
            ]), dims=[[2,2],[2,2]])

            # Rotate the simulated unitary into the logical rotating frame
            U_logical = U_frame * U_sim_qt
            
            # 4. Ideal Unitary
            if gate_type == "CNOT":
                U_ideal = qt.Qobj([[1,0,0,0],[0,1,0,0],[0,0,0,1],[0,0,1,0]], dims=[[2,2],[2,2]])
                
                if coupling_type == "tunable_coupler":
                     h_mat = qt.Qobj([[1, 1], [1, -1]], dims=[[2],[2]]) / np.sqrt(2)
                     op_H = qt.tensor(qt.qeye(2), h_mat)
                     # Apply H gates to the logical unitary, not the raw sim unitary
                     U_logical = op_H * U_logical * op_H

            elif gate_type == "CZ":
                 U_ideal = qt.Qobj([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,-1]], dims=[[2,2],[2,2]])
            
            # 5. Calculate Average Gate Fidelity
            d = 4
            # Trace inner product using the corrected logical unitary
            tr = (U_ideal.dag() * U_logical).tr()
            F_avg = (np.abs(tr)**2 + d) / (d * (d + 1))
            
            return {"average_fidelity": float(F_avg)}
            
        except Exception as e:
            print(f"Fidelity Calc Failed: {e}")
            import traceback
            traceback.print_exc()
            return {"average_fidelity": 0.0}
