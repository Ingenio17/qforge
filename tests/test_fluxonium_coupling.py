import unittest
import numpy as np
import qutip as qt
from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine

class TestFluxoniumCoupling(unittest.TestCase):
    """
    Test suite for coupling dynamics with Fluxonium qubits.
    Fluxonium has high anharmonicity and distinct spectra compared to Transmons.
    """
    
    def setUp(self):
        self.q_eng = QubitEngine()
        # Create two fluxoniums
        # Parameters typical for heavy fluxonium or similar
        self.q_eng.create_qubit("fluxonium", "f1", {"EJ": 8.9, "EC": 2.5, "EL": 0.5, "truncated_dim": 5})
        self.q_eng.create_qubit("fluxonium", "f2", {"EJ": 9.0, "EC": 2.4, "EL": 0.5, "truncated_dim": 5})
        
        self.g_eng = GateEngine() # Picks up the session

    def test_capacitive_coupling_generation(self):
        """Verify capacitive coupling Hamiltonian construction for Fluxonium."""
        # Check if Hamiltonian exists
        g = 0.05
        # Use internal method to construct full system Hamiltonian
        H_sys, _, _ = self.g_eng._get_two_qubit_hamiltonian("f1", "f2", "capacitive", g)
        
        # Verify dimensions (5*5 = 25)
        self.assertEqual(H_sys.shape, (25, 25))
        
        # Verify interaction terms exist (off-diagonal elements in composite basis)
        # H_int ~ (n1 n2) or (q1 q2)? Capacitive is usually charge-charge (n1 n2).
        # QubitEngine models usually expose creation/annihilation or charge ops.
        # This test ensures no crash and correct dimensionality.
        
    def test_cnot_simulation(self):
        """Simulate a CNOT gate on Fluxoniums (physics might be messy, just checking execution)."""
        # Run a short simulation
        try:
            res = self.g_eng.simulate_two_qubit_dynamics(
                "f1", "f2", "CNOT", 
                coupling_type="capacitive", 
                coupling_strength=0.02, 
                duration=50.0,
                steps=50
            )
            # Check population exists
            self.assertIn("11", res["populations"])
            self.assertEqual(len(res["times"]), 50)
        except Exception as e:
            self.fail(f"Fluxonium CNOT simulation failed: {e}")

    def test_cz_inductive_simulation(self):
        """Simulate CZ with Inductive coupling (ZZ)."""
        # Inductive coupling often used for Fluxonium CZ
        try:
            res = self.g_eng.simulate_two_qubit_dynamics(
                "f1", "f2", "CZ",
                coupling_type="inductive",
                coupling_strength=0.01,
                duration=50.0
            )
            final_st = res["final_state"]
            # Check normalisation
            self.assertAlmostEqual(final_st.norm(), 1.0)
        except Exception as e:
            self.fail(f"Fluxonium CZ simulation failed: {e}")

if __name__ == '__main__':
    unittest.main()
