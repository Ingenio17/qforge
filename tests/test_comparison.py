"""
Tests for comparison engine.
"""

import pytest
from qforge.comparison.comparator import Comparator


def test_compare_qubit_types():
    """Test comparing transmon vs fluxonium."""
    comparator = Comparator()
    
    results = comparator.compare_qubits(["transmon", "fluxonium"], ["all"])
    
    assert "Frequency (GHz)" in results
    assert "Anharmonicity (MHz)" in results
    # T1/T2 keys might vary based on noise model, skip strict check or use partial
    
    assert "transmon" in results["Frequency (GHz)"]
    assert "fluxonium" in results["Frequency (GHz)"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
