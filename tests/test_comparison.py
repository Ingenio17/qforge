"""
Tests for comparison engine.
"""

import pytest
from qforge.comparison.comparator import Comparator


def test_compare_qubit_types():
    """Test comparing transmon vs fluxonium."""
    comparator = Comparator()
    
    results = comparator.compare_qubits(["transmon", "fluxonium"], ["all"])
    
    assert "Frequency (ω₀₁)" in results
    assert "Anharmonicity (α)" in results
    assert "T1" in results
    assert "T2" in results
    
    assert "transmon" in results["Frequency (ω₀₁)"]
    assert "fluxonium" in results["Frequency (ω₀₁)"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
