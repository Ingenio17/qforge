"""
Basic tests for QubitEngine.
"""

import pytest
from qforge.core.qubit_engine import QubitEngine


def test_create_transmon():
    """Test transmon creation."""
    engine = QubitEngine()
    
    params = {"EJ": 15.0, "EC": 0.3}
    qubit = engine.create_qubit("transmon", "test_transmon", params)
    
    assert qubit is not None
    assert "test_transmon" in engine._qubits


def test_create_fluxonium():
    """Test fluxonium creation."""
    engine = QubitEngine()
    
    params = {"EJ": 8.9, "EC": 2.5, "EL": 0.5}
    qubit = engine.create_qubit("fluxonium", "test_fluxonium", params)
    
    assert qubit is not None
    assert "test_fluxonium" in engine._qubits


def test_compute_spectrum():
    """Test spectrum calculation."""
    engine = QubitEngine()
    
    params = {"EJ": 15.0, "EC": 0.3}
    qubit = engine.create_qubit("transmon", "test", params)
    
    spectrum = engine.compute_spectrum(qubit, n_levels=5)
    
    assert len(spectrum) == 5
    assert spectrum[1] > spectrum[0]  # Energy levels should be increasing


def test_list_qubits():
    """Test listing qubits."""
    engine = QubitEngine()
    
    params1 = {"EJ": 15.0, "EC": 0.3}
    params2 = {"EJ": 8.9, "EC": 2.5, "EL": 0.5}
    
    engine.create_qubit("transmon", "q1", params1)
    engine.create_qubit("fluxonium", "q2", params2)
    
    qubits = engine.list_qubits()
    
    assert len(qubits) >= 2
    assert any(q["name"] == "q1" for q in qubits)
    assert any(q["name"] == "q2" for q in qubits)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
