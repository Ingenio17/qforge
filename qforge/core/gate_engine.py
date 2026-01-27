"""
Gate Engine: Simulation of quantum gates and dynamics using QuTiP.
"""

import numpy as np
import qutip as qt
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path

from qforge.core.qubit_engine import QubitEngine
from qforge.config.defaults import OUTPUT_DIRS


class GateEngine:
    """Engine for simulating quantum gates and dynamics."""

    def __init__(self):
        """Initialize the gate engine."""
        self.qubit_engine = QubitEngine()
        
    def _get_qubit_hamiltonian(self, qubit_name: str):
        """Get the Hamiltonian of a qubit in the computational basis (truncated)."""
        qubit = self.qubit_engine.get_qubit(qubit_name)
        # scqubits Hamiltonian
        H_scq = qubit.hamiltonian()
        # Convert to QuTiP Qobj if it isn't already (scqubits often returns Qobj)
        if not isinstance(H_scq, qt.Qobj):
            H_scq = qt.Qobj(H_scq)
        return H_scq

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
        # This is a simplification; realistic drives might be charge or flux operators.
        
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
            # Hadamard is usually composite, but we can model effective H drive?
            # Or simplified: X + Z (scaled)
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
        Simulate gate dynamics.
        
        Args:
            qubit_name: Name of the target qubit
            gate_type: Gate to simulate (X, Y, Z, H, CNOT) note: CNOT requires 2 qubits, handling single for now
            duration: Gate duration in ns
            noise_model: 'none' or 'realistic'
            steps: Number of time steps
            
        Returns:
            Simulation result dictionary
        """
        # 1. Setup System
        qubit = self.qubit_engine.get_qubit(qubit_name)
        dim = qubit.truncated_dim
        
        # Drift Hamiltonian (H0) - usually diagonal in eigenbasis
        evals = qubit.eigenvals(evals_count=dim)
        
        # Rotating Wave Approximation (RWA)
        # Transform to frame rotating at qubit frequency w01
        w01 = evals[1] - evals[0]
        
        # H_sys_rot = H_sys_lab - w_drive * a^dag a
        # Construct diagonal H with subtracted energies
        # E_n' = E_n - n * w01
        # E_0' = E_0 - 0 = E_0
        # E_1' = E_1 - w01 = E_1 - (E_1 - E_0) = E_0
        # So in this frame, levels are effectively:
        # 0: E_0
        # 1: E_0
        # 2: E_2 - 2*w01 (anharmonicity remains)
        
        evals_rot = np.array([e - i * w01 for i, e in enumerate(evals)])
        # Shift ground to 0 for convenience
        evals_rot = evals_rot - evals_rot[0]
        
        H0 = qt.Qobj(np.diag(evals_rot))
        
        # Control Hamiltonian (H_drive)
        # In RWA, a resonant drive H = A cos(wt) (a + a^dag) becomes:
        # H_rwa = (A/2) (a + a^dag)
        # We assume the user specifies the effective Rabi amplitude (Omega) directly or indirectly.
        # Earlier we defined amplitude = target_rotation / duration = Omega
        # So we just use this Omega as the coeff for the static operator in RWA.
        # H_ctrl is (a + a^dag)
        
        H_ctrl = self.get_control_hamiltonian(gate_type, dim)
        
        # Calibration: Omega * T = Angle.
        # If H_int = Omega/2 * sigma_x, then rotation angle is Omega * T.
        # Our H_ctrl is (a + a^dag) ~ sigma_x.
        # If we set coeff = Omega/2, then term is Omega/2 * sigma_x.
        # Time evolution U = exp(-i * Omega/2 * sigma_x * T) = Rx(Omega * T).
        # So we need Amplitude = Omega/2.
        
        target_rotation = np.pi # Default to pi pulse (flip)
        if gate_type == "H": target_rotation = np.pi / 2 
        
        omega = target_rotation / duration
        amplitude = omega / 2.0
        
        # Time array
        tlist = np.linspace(0, duration, steps)
        
        # 2. Setup Noise
        c_ops = []
        if noise_model == "realistic":
            # Get T1, T2 estimates
            coherence = self.qubit_engine.estimate_coherence(qubit)
            t1 = coherence.get("T1 (dielectric)", {}).get("value", 50.0) * 1000 # to ns
            
            # Collapse operator for relaxation: sqrt(1/T1) * a
            if t1 > 0:
                rate_relax = 1.0 / t1
                c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))
                
            # Dephasing can be added similarly
            
        # 3. Initial State
        psi0 = qt.basis(dim, 0) # Start in ground state
        
        # 4. Evolve
        # H = [H0, [H_ctrl, 'amp']] if time dependent, but constant pulse is just H0 + amp*H_ctrl
        H_total = H0 + amplitude * H_ctrl
        
        result = qt.mesolve(H_total, psi0, tlist, c_ops)
        
        # Calculate expectations
        # Occupation of |0>, |1>, |2>
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
