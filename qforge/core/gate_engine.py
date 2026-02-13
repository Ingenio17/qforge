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
        
    def _get_qubit_hamiltonian(self, qubit_name: str):
        """Get the Hamiltonian of a qubit in the computational basis (truncated)."""
        qubit = self.qubit_engine.get_qubit(qubit_name)
        dim = qubit.truncated_dim
        
        # Get eigenvalues for truncated diagonal Hamiltonian
        evals = qubit.eigenvals(evals_count=dim)
        # Convert to angular frequency (GHz -> rad/ns * 2pi? No, GHz * 2pi = rad/ns if t in ns)
        # Actually QuTiP usually assumes consistent units. If t is ns, E should be in GHz * 2pi.
        return qt.Qobj(np.diag(evals)) * 2 * np.pi

    def get_control_hamiltonian(self, gate_type: str, dimension: int) -> qt.Qobj:
        """
        Get the control Hamiltonian operator for a specific gate type.
        
        Args:
            gate_type: Type of gate (X, Y, Z, H)
            dimension: Dimension of the Hilbert space
            
        Returns:
            QuTiP Qobj operator
        """
        gate_type = gate_type.upper()
        
        # Define operators in truncated space
        # For simplicity, we assume the drive acts primarily on |0>-|1> transition
        
        # Destroy operator
        a = qt.destroy(dimension)
        
        if gate_type == "X":
            # Drive ~ (a + a_dag)
            return a + a.dag()
        elif gate_type == "Y":
            # Drive ~ i(a - a_dag)
            return 1j * (a - a.dag())
        elif gate_type == "Z":
            # Detuning / Stark shift ~ a_dag * a
            return a.dag() * a
        elif gate_type == "H":
            # Simplified Hadamard drive model
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
        Simulate single-qubit gate dynamics.
        
        Args:
            qubit_name: Name of the target qubit
            gate_type: Gate to simulate (X, Y, Z, H)
            duration: Gate duration in ns
            noise_model: 'none' or 'realistic'
            steps: Number of time steps
            
        Returns:
            Simulation result dictionary
        """
        # 1. Setup System
        qubit = self.qubit_engine.get_qubit(qubit_name)
        dim = qubit.truncated_dim
        
        # Drift Hamiltonian (H0)
        evals = qubit.eigenvals(evals_count=dim)
        w01 = evals[1] - evals[0]
        
        # Rotating Wave Approximation (RWA)
        # Transform to frame rotating at qubit frequency w01
        evals_rot = np.array([e - i * w01 for i, e in enumerate(evals)])
        evals_rot = evals_rot - evals_rot[0]
        
        H0 = qt.Qobj(np.diag(evals_rot))
        
        # Control Hamiltonian (H_drive)
        # H_ctrl is (a + a^dag) for X
        H_ctrl = self.get_control_hamiltonian(gate_type, dim)
        
        # Calibration (Simple boxcar pulse)
        target_rotation = np.pi # Default to pi pulse (flip)
        if gate_type == "H": target_rotation = np.pi / 2 
        
        omega = target_rotation / duration
        amplitude = omega / 2.0
        
        # Time array
        tlist = np.linspace(0, duration, steps)
        
        # 2. Setup Noise
        c_ops = []
        if noise_model == "realistic":
            coherence = self.qubit_engine.estimate_coherence(qubit)
            # T1 in ns
            t1 = coherence.get("T1 (dielectric)", {}).get("value", 50.0) * 1000 
            
            if t1 > 0:
                rate_relax = 1.0 / t1
                c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))
            
        # 3. Initial State
        psi0 = qt.basis(dim, 0) 
        
        # 4. Evolve
        H_total = H0 + amplitude * H_ctrl
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

    def _get_two_qubit_hamiltonian(self, 
                                 qubit1_name: str, 
                                 qubit2_name: str, 
                                 coupling_type: str, 
                                 coupling_strength: float) -> Tuple[qt.Qobj, Any, Any]:
        """
        Construct the static two-qubit Hamiltonian including interaction.
        Delegates interaction term generation to CouplingGenerator.
        """
        q1 = self.qubit_engine.get_qubit(qubit1_name)
        q2 = self.qubit_engine.get_qubit(qubit2_name)
        
        dim1 = q1.truncated_dim
        dim2 = q2.truncated_dim
        
        # Individual Hamiltonians
        h1 = self._get_qubit_hamiltonian(qubit1_name)
        h2 = self._get_qubit_hamiltonian(qubit2_name)
        
        # Tensor product for non-interacting system
        H0 = qt.tensor(h1, qt.qeye(dim2)) + qt.tensor(qt.qeye(dim1), h2)
        
        # Interaction Term
        # Convert strength to angular frequency
        H_int = CouplingGenerator.get_coupling(coupling_type, dim1, dim2, coupling_strength * 2 * np.pi)
            
        return H0 + H_int, q1, q2




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
                      q2_name: str, 
                      gate_type: str, 
                      coupling_type: str, 
                      coupling_strength: float, 
                      parameter: str = "duration", 
                      range_vals: list = [],
                      **kwargs) -> Tuple[float, float]:
        """
        Calibrate a gate by sweeping a parameter to maximize fidelity/population.
        Accepts kwargs (e.g. detuning) passed to simulate().
        """
        print(f"Calibrating {gate_type} ({coupling_type}) on {q1_name}-{q2_name}...")
        best_val = 0.0
        max_metric = -1.0
        
        # Setup sweep
        if len(range_vals) == 0:
            if parameter == "duration":
                if coupling_type == "tunable_coupler":
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
                    if gate_type == "CNOT":
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

    def perform_process_tomography(self, q1_name: str, q2_name: str, gate_type: str = "CNOT") -> float:
        """
        Determine the Process Fidelity of the gate simulation by running
        it against a complete basis set.
        (Placeholder logic as simpler method calculate_gate_fidelity is preferred)
        """
        # ... logic ...
        return 0.0

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

    def simulate_two_qubit_dynamics(self, qubit1_name: str, qubit2_name: str, 
                                   gate_type: str, coupling_type: str, 
                                   coupling_strength: float, duration: float, 
                                   steps: int = 100, detuning: float = 0.0) -> Dict[str, Any]:
        """
        Simulate the dynamics of two coupled qubits under a gate operation.
        
        Args:
            detuning: Frequency shift amplitude (GHz) for Flux Pulse (CZ).
        """
        # 1. Get Hamiltonian
        # Determine static coupling strength (0 if tunable, else fixed)
        static_g = 0.0 if coupling_type == "tunable_coupler" else coupling_strength
        if gate_type == "CNOT" and coupling_type == "tunable_coupler":
             static_g = 0.0
             
        H_sys, q1, q2 = self._get_two_qubit_hamiltonian(qubit1_name, qubit2_name, coupling_type, static_g)
        
        dim1 = q1.truncated_dim
        dim2 = q2.truncated_dim
        
        # 2. Add Drives / Controls
        args = {}
        H_total = H_sys  # Start with static system
        
        # ... (CNOT logic unchanged) ...
        if gate_type == "CNOT":
            if coupling_type == "capacitive":
                evals2 = q2.eigenvals(2)
                w2 = evals2[1] - evals2[0]
                a1 = qt.destroy(dim1)
                op_drive = qt.tensor(a1 + a1.dag(), qt.qeye(dim2))
                amp = 0.100 * 2 * np.pi 
                def drive_coeff(t, args): return args['amp'] * np.cos(args['w'] * t)
                H_total = [H_sys, [op_drive, drive_coeff]]
                args = {'amp': amp, 'w': w2 * 2 * np.pi}
                
            elif coupling_type == "tunable_coupler":
                # Exchange Pulse
                H_int_op = CouplingGenerator.tunable_coupler(dim1, dim2, 1.0)
                def coupling_coeff(t, args): 
                    return args['g'] * (np.sin(np.pi * t / args['T'])**2)
                H_total = [H_sys, [H_int_op, coupling_coeff]]
                args = {'g': coupling_strength * 2 * np.pi, 'T': duration}

        elif gate_type == "CZ":
             if coupling_type == "tunable_coupler":
                # 1. Coupling Pulse (Adiabatic)
                H_int_op = CouplingGenerator.tunable_coupler(dim1, dim2, 1.0)
                
                # 2. Flux Pulse (Frequency Shift on Q2)
                # Operator: I x number_op
                n2_op = qt.tensor(qt.qeye(dim1), qt.num(dim2)) 
                
                # Combined Time-Dependent Hamiltonian
                # [H0, [H_int, c_g], [H_flux, c_f]]
                
                def coupling_coeff(t, args): 
                    return args['g'] * (np.sin(np.pi * t / args['T'])**2)
                
                # Flux pulse matches the window (simplest case: square or same sine-squared)
                # Let's use Square pulse for Flux to hold the resonance? 
                # Or adiabatic? Usually flux follows coupling envelope or is wider.
                # Let's use the same Sine-Squared envelope for now to act as "AC-Stark-like" shift or just synced.
                def flux_coeff(t, args):
                    return args['det'] * (np.sin(np.pi * t / args['T'])**2)
                
                H_total = [H_sys, [H_int_op, coupling_coeff], [n2_op, flux_coeff]]
                args = {
                    'g': coupling_strength * 2 * np.pi, 
                    'det': detuning * 2 * np.pi,
                    'T': duration
                }

        # 3. Initial State
        psi0 = qt.tensor(qt.basis(dim1, 0), qt.basis(dim2, 0)) # Default
        if gate_type == "CNOT":
            psi0 = qt.tensor(qt.basis(dim1, 1), qt.basis(dim2, 0))
        elif gate_type == "CZ":
            psi0 = qt.tensor(qt.basis(dim1, 1), qt.basis(dim2, 1))

        # 4. Evolution
        # mesolve automatically handles time-dependent H if format is [H0, [H1, coeff]]
        
        times = np.linspace(0, duration, steps)
        
        # Options
        opts = {"store_states": True, "nsteps": 50000} # Ensure states are stored, handle stiffness
        
        res = qt.mesolve(H_total, psi0, times, [], [], args=args, options=opts)
        
        # 5. Process Results
        result = {
            "times": times,
            "states": res.states, 
            "populations": {
                "00": np.real(qt.expect(qt.tensor(qt.projection(dim1, 0, 0), qt.projection(dim2, 0, 0)), res.states)),
                "01": np.real(qt.expect(qt.tensor(qt.projection(dim1, 0, 0), qt.projection(dim2, 1, 1)), res.states)),
                "10": np.real(qt.expect(qt.tensor(qt.projection(dim1, 1, 1), qt.projection(dim2, 0, 0)), res.states)),
                "11": np.real(qt.expect(qt.tensor(qt.projection(dim1, 1, 1), qt.projection(dim2, 1, 1)), res.states))
            },
            "final_state": res.states[-1]
        }
        
        # Post-processing for Tunable CNOT
        if gate_type == "CNOT" and coupling_type == "tunable_coupler":
            # Construct H operator for dim2
            # H is 2x2 on subspace 0,1. Identity elsewhere?
            # Or assume we only care about qubit subspace.
            # Let's embed 2x2 H into dim2 x dim2 Matrix
            
            mat_h = np.eye(dim2, dtype=complex)
            h_sub = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
            mat_h[0:2, 0:2] = h_sub
            
            h_obj = qt.Qobj(mat_h, dims=[[dim2], [dim2]])
            
            U_H = qt.tensor(qt.qeye(dim1), h_obj)
            new_final = U_H * res.states[-1]
            result["final_state"] = new_final
            p11 = qt.expect(qt.tensor(qt.projection(dim1, 1, 1), qt.projection(dim2, 1, 1)), new_final)
            result["populations"]["11"][-1] = np.real(p11)

        return result

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
            static_g = 0.0 if is_tunable else strength
            if gate_type == "CNOT" and coupling_type == "tunable_coupler": 
                 # CNOT tunable uses CZ internally? 
                 static_g = 0.0
            
            H_sys, q1, q2 = self._get_two_qubit_hamiltonian(q1_name, q2_name, coupling_type, static_g)
            
            dim1 = q1.truncated_dim
            dim2 = q2.truncated_dim
            
            # Control / Pulse
            args = {}
            H_total = H_sys
            
            if gate_type == "CNOT":
                if coupling_type == "capacitive":
                    evals2 = q2.eigenvals(2)
                    w2 = evals2[1] - evals2[0]
                    a1 = qt.destroy(dim1)
                    op_drive = qt.tensor(a1 + a1.dag(), qt.qeye(dim2))
                    amp = 0.100 * 2 * np.pi 
                    def drive_coeff(t, args): return args['amp'] * np.cos(args['w'] * t)
                    H_total = [H_sys, [op_drive, drive_coeff]]
                    args = {'amp': amp, 'w': w2 * 2 * np.pi}
                    
                elif coupling_type == "tunable_coupler":
                    # CZ pulse logic
                    H_int_op = CouplingGenerator.tunable_coupler(dim1, dim2, 1.0)
                    def coupling_coeff(t, args): 
                        return args['g'] * (np.sin(np.pi * t / args['T'])**2)
                    H_total = [H_sys, [H_int_op, coupling_coeff]]
                    args = {'g': strength * 2 * np.pi, 'T': duration}
            
            elif gate_type == "CZ":
                 if coupling_type == "tunable_coupler":
                    H_int_op = CouplingGenerator.tunable_coupler(dim1, dim2, 1.0)
                    def coupling_coeff(t, args): 
                        return args['g'] * (np.sin(np.pi * t / args['T'])**2)
                    H_total = [H_sys, [H_int_op, coupling_coeff]]
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
