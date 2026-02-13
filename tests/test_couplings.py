import pytest
import numpy as np
import qutip as qt
from qforge.core.coupling import CouplingGenerator, CouplingType

def test_capacitive_coupling_shape():
    """Test standard capacitive coupling generation."""
    dim = 3
    g = 0.01
    hc = CouplingGenerator.get_coupling("capacitive", dim, dim, g)
    
    assert hc.type == "oper"
    assert hc.dims == [[dim, dim], [dim, dim]]
    
    # Check Hermiticity
    assert hc.isherm

def test_tunable_coupling():
    """Test tunable coupling."""
    dim = 3
    # Check default tunable (exchange)
    h_tun = CouplingGenerator.get_coupling("tunable_coupler", dim, dim, 0.05)
    assert h_tun.isherm
    
    # Check direct method
    h_tun2 = CouplingGenerator.tunable_coupler(dim, dim, 0.05)
    assert h_tun == h_tun2

def test_inductive_coupling():
    """Test inductive ZZ coupling."""
    dim = 4
    h_zz = CouplingGenerator.get_coupling("inductive", dim, dim, 0.02)
    
    # Needs to be diagonal given n1*n2 is diagonal in Fock basis (if destroy op is standard)
    # qt.destroy is standard in Fock.
    # So h_zz should be diagonal.
    
    # Get data
    data = h_zz.full()
    # Check off-diagonals are zero
    diag = np.diag(data)
    reconstructed = np.diag(diag)
    
    assert np.allclose(data, reconstructed)
