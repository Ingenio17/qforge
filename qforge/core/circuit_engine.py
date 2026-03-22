import numpy as np
import scipy.linalg
import qutip as qt
from typing import Dict, List, Any, Optional

try:
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel
    from qiskit.quantum_info import Kraus, QuantumError
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False


class CircuitEngine:
    """
    QForge Circuit Simulation Engine bridging QuTiP physics to Qiskit Aer.
    """
    
    def __init__(self):
        if not QISKIT_AVAILABLE:
            raise ImportError("Qiskit and Qiskit-Aer are required for the CircuitEngine.")
        self.simulator = AerSimulator()
        self.noise_model = NoiseModel()
        
    def generate_kraus_from_choi(self, choi_matrix: qt.Qobj) -> List[np.ndarray]:
        """
        Convert a QuTiP Choi matrix to a set of trace-preserving Kraus operators
        suitable for Qiskit QuantumError. Approximates leakage as Markovian decoherence.
        """
        # 1. Get QuTiP Kraus operators
        kraus_qobjs = qt.to_kraus(choi_matrix)
        kraus_ops = [k.full() for k in kraus_qobjs]
        
        # 2. Check for trace preservation (Leakage)
        dim = choi_matrix.shape[0]
        N_states = int(np.sqrt(dim))
        
        I = np.eye(N_states, dtype=complex)
        sum_K_dag_K = np.zeros((N_states, N_states), dtype=complex)
        
        for K in kraus_ops:
            sum_K_dag_K += K.conj().T @ K
            
        # 3. Compute the residual loss matrix E
        E = I - sum_K_dag_K
        
        # Check if E is non-negligible (Leakage occurred)
        leakage_norm = np.linalg.norm(E)
        if leakage_norm > 1e-4:
            print(f"⚠️ [CircuitEngine] Abstracting leakage: residual trace distance {leakage_norm:.2e}")
            # Ensure E is positive semi-definite due to numerical errors
            evals, evecs = np.linalg.eigh(E)
            evals[evals < 0] = 0.0 # Rectify small negative eigenvalues
            E_rect = evecs @ np.diag(evals) @ evecs.conj().T
            
            # Add a compensatory Kraus operator to enforce CPTP
            # K_leak = sqrt(E)
            K_leak = scipy.linalg.sqrtm(E_rect)
            kraus_ops.append(K_leak)
            
        return kraus_ops

    def add_custom_gate_noise(self, gate_name: str, qubits: List[int], choi_matrix: qt.Qobj):
        """
        Register a physical QuTiP Choi matrix as a Qiskit noise model for a specific gate.
        """
        kraus_ops = self.generate_kraus_from_choi(choi_matrix)
        error = QuantumError(kraus_ops)
        self.noise_model.add_quantum_error(error, gate_name, qubits)
        print(f"Successfully bound {len(kraus_ops)}-Kraus error profile to gate '{gate_name}' on qubits {qubits}.")
        
    def execute_circuit(self, circuit: Any, shots: int = 1024) -> Dict[str, int]:
        """
        Execute a Qiskit QuantumCircuit using the generated physical noise model.
        """
        # Transpile for the simulator
        t_circ = transpile(circuit, self.simulator)
        
        # Run with noise model
        result = self.simulator.run(t_circ, noise_model=self.noise_model, shots=shots).result()
        counts = result.get_counts(0)
        return counts
