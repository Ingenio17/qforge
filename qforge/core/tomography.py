import numpy as np
import qutip as qt
from typing import List, Tuple, Dict, Any
import itertools

class ProcessTomography:
    """
    Implements Quantum Process Tomography (QPT) for 1 and 2 qubit gates.
    """
    
    @staticmethod
    def get_basis_states(dims: List[int]) -> List[qt.Qobj]:
        """
        Generate the spanning basis states for QPT.
        For n qubits, we need d^2 linearly independent input states.
        Standard choice: tensor products of ``{|0>, |1>, |+>, |+i>}``.
        """
        # Single qubit basis
        # |0>, |1>, |+>, |+i>
        # Note: |+> = (|0>+|1>)/sqrt(2), |+i> = (|0>+i|1>)/sqrt(2)
        
        basis_1q = []
        # We need to work with specific dimensions, assuming first 2 levels are qubit
        # But qutip basis(N, 0) gives vector of length N.
        # We assume the user strips/projects to qubit subspace or we handle full dim.
        # For simplicity, we generate qubit states (dim=2) and tensor them.
        
        # Define 1Q basis in 2-level Hilbert space
        b0 = qt.basis(2, 0)
        b1 = qt.basis(2, 1)
        bp = (b0 + b1).unit()
        bi = (b0 + 1j*b1).unit()
        
        singles = [b0, b1, bp, bi]
        
        # Tensor product for N qubits
        # itertools.product
        basis_set = []
        for combo in itertools.product(singles, repeat=len(dims)):
            state = combo[0]
            for i in range(1, len(combo)):
                state = qt.tensor(state, combo[i])
            basis_set.append(state)
            
        return basis_set

    @staticmethod
    def calculate_process_fidelity(unitary_sim: qt.Qobj, unitary_ideal: qt.Qobj, dims: List[int]) -> float:
        """
        Calculate Process Fidelity F_pro directly from Unitaries (if available).
        ``F_pro = |Tr(U_sim^dag U_ideal)|^2 / d^2`` ? No.

        ``F_avg = ( |Tr(U)|^2 + d ) / (d(d+1))``
        
        If we have the effective propagator U_sim (projected to computational subspace).
        """
        # Project U_sim to 2^N x 2^N
        # Assuming U_sim is the propagator in the computational subspace
        
        d = np.prod(dims) # 2^N = 4 for 2 qubits
        
        # Calculate overlap
        # Tr(U_ideal^dag * U_sim)
        tr = (unitary_ideal.dag() * unitary_sim).tr()
        
        # Intrinsic Fidelity (Average Gate Fidelity)
        F_avg = (np.abs(tr)**2 + d) / (d * (d + 1))
        
        # Process Fidelity
        # F_pro = (d * F_avg - 1) / (d - 1)
        F_pro = (d * F_avg - 1) / (d - 1)
        
        return float(F_pro)

    @staticmethod
    def reconstruct_process_matrix(input_states: List[qt.Qobj], output_states: List[qt.Qobj]) -> qt.Qobj:
        """
        Reconstruct the Chi matrix from input/output pairs.
        (Simplified implementation or placeholder for qutip's qpt).
        
        For qutip, we can use `qutip.tomography.process_tomography`.
        But since we are running simulations, we just want the METRIC.
        
        Actually, running 16 simulations gives us the map.
        If we just want validation, measuring F_avg is sufficient and robust.
        
        The 'standard' QPT output is the Chi matrix plot.
        
        We will return a placeholder Chi matrix or calculate it if feasible.
        For now, we emphasize calculating Fidelity.
        """
        return None
