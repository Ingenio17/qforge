"""
Scientific accuracy tests for qforge.
Compares qforge results directly with scqubits to ensure physics correctness.
"""

import pytest
import numpy as np
import scqubits as scq
from qforge import QubitEngine

class TestScientificAccuracy:
    """Compare qforge results against direct scqubits usage."""

    @pytest.fixture
    def engine(self):
        return QubitEngine()

    def test_transmon_accuracy(self, engine):
        """Compare Transmon energy levels with direct scqubits implementation."""
        # Parameters
        params = {"EJ": 15.0, "EC": 0.3, "ng": 0.0, "ncut": 30}
        
        # qforge Transmon
        qforge_qubit = engine.create_qubit("transmon", "acc_transmon", params)
        qforge_evals = engine.compute_spectrum(qforge_qubit, n_levels=10)
        
        # Direct scqubits Transmon
        scq_transmon = scq.Transmon(
            EJ=params["EJ"],
            EC=params["EC"],
            ng=params["ng"],
            ncut=params["ncut"]
        )
        scq_evals = scq_transmon.eigenvals(evals_count=10)
        
        # Assertions
        np.testing.assert_allclose(qforge_evals, scq_evals, rtol=1e-10, err_msg="Transmon eigenvalues mismatch")
        
        # Anharmonicity check
        qf_anharm = (qforge_evals[2] - qforge_evals[1]) - (qforge_evals[1] - qforge_evals[0])
        scq_anharm = scq_transmon.anharmonicity()
        np.testing.assert_allclose(qf_anharm, scq_anharm, rtol=1e-10, err_msg="Transmon anharmonicity mismatch")

    def test_fluxonium_accuracy(self, engine):
        """Compare Fluxonium energy levels with direct scqubits implementation."""
        # Parameters
        params = {"EJ": 8.9, "EC": 2.5, "EL": 0.5, "flux": 0.5, "cutoff": 110}
        
        # qforge Fluxonium
        qforge_qubit = engine.create_qubit("fluxonium", "acc_fluxonium", params)
        qforge_evals = engine.compute_spectrum(qforge_qubit, n_levels=10)
        
        # Direct scqubits Fluxonium
        scq_fluxonium = scq.Fluxonium(
            EJ=params["EJ"],
            EC=params["EC"],
            EL=params["EL"],
            flux=params["flux"],
            cutoff=params["cutoff"]
        )
        scq_evals = scq_fluxonium.eigenvals(evals_count=10)
        
        # Assertions
        np.testing.assert_allclose(qforge_evals, scq_evals, rtol=1e-10, err_msg="Fluxonium eigenvalues mismatch")

    def test_zeropi_accuracy(self, engine):
        """Compare ZeroPi energy levels with direct scqubits implementation."""
        # Parameters
        # grid must be tuple for qforge params but scqubits needs Grid1d object
        grid_min, grid_max, grid_pt = -19.0, 19.0, 200
        params = {
            "EJ": 10.0, "EL": 0.04, "ECJ": 20.0, "EC": 0.04, 
            "flux": 0.0, "ng": 0.1,
            "grid": (grid_min, grid_max, grid_pt)
        }
        
        # qforge ZeroPi
        qforge_qubit = engine.create_qubit("zeropi", "acc_zeropi", params)
        qforge_evals = engine.compute_spectrum(qforge_qubit, n_levels=6)
        
        # Direct scqubits ZeroPi
        scq_zeropi = scq.ZeroPi(
            EJ=params["EJ"],
            EL=params["EL"],
            ECJ=params["ECJ"],
            EC=params["EC"],
            ng=params["ng"],
            flux=params["flux"],
            grid=scq.Grid1d(grid_min, grid_max, grid_pt),
            ncut=30
        )
        scq_evals = scq_zeropi.eigenvals(evals_count=6)
        
        # Assertions with slightly looser tolerance for ZeroPi due to potential grid/internal handling differences
        np.testing.assert_allclose(qforge_evals, scq_evals, rtol=1e-8, err_msg="ZeroPi eigenvalues mismatch")

    def test_coherence_logic(self, engine):
        """Verify coherence estimation logic calls correct underlying methods."""
        # Use a mock or just verify values are consistent with independent calculation
        params = {"EJ": 15.0, "EC": 0.3}
        qubit = engine.create_qubit("transmon", "coh_check", params)
        
        # Get qforge estimate
        qforge_coh = engine.estimate_coherence(qubit, temperature=0.015)
        
        # Calculate manually using scqubits
        # scqubits returns ns. We want us.
        t1_diel = qubit.t1_capacitive(T=0.015, Q_cap=1e6) / 1000.0 # in us
        
        assert "T1 (dielectric)" in qforge_coh
        assert np.isclose(qforge_coh["T1 (dielectric)"]["value"], t1_diel, rtol=1e-5)
