import pytest
import numpy as np
from qforge.core.coupling import CouplingGenerator

def test_capacitive_splitting():
    """
    Verify Jaynes-Cummings splitting for resonant capacitive coupling.
    For two resonant qubits (w1=w2) coupled by g(a+ a + a a+), 
    the excited states |10> and |01> should split by 2g.
    """
    dim = 2
    g = 0.100 # 100 MHz
    
    # Interaction only (assuming degenerate frame or zero detuning)
    # H = g(a+b + ab+)
    H_int = CouplingGenerator.capacitive(dim, dim, g)
    
    # Energy levels:
    # |00> -> E=0
    # |10>, |01> -> Mix into symmetric/antisymmetric states with energies +/- g
    # Splitting = 2g
    
    evals = H_int.eigenenergies()
    evals = np.sort(evals)
    
    # Levels should be [-g, 0, 0, g] (roughly, since |00> is 0, |11> is 0 in RWA if anharmonicity infinite? 
    # Actually |11> is separate.
    # Let's look at the subspace {|10>, |01>}
    # Matrix is [[0, g], [g, 0]]. Eigs are +g, -g. Gap is 2g.
    
    # Check the gap between the middle eigenvalues (or look for +/- g)
    # Evals: -0.1, 0, 0, 0.1?
    # |11>: a+b|11> -> |10>?? No. 
    # a+ b |11> = sqrt(1)*sqrt(0) -> 0.
    # a b+ |11> = 0.
    # So |11> is dark to this interaction if we only have 0/1 states?
    # No, |11> -> (a+b) |11> = |20>? (if dim > 2) or 0 (if dim=2).
    
    # Let's filter for relevant states.
    # We expect eigenvalues close to -g and +g.
    
    found_plus_g = np.any(np.isclose(evals, g))
    found_minus_g = np.any(np.isclose(evals, -g))
    
    assert found_plus_g and found_minus_g, f"Expected eigenvalues +-{g}, got {evals}"
    
def test_zz_shift():
    """
    Verify ZZ coupling properly shifts energy levels.
    H = g * n1 * n2
    """
    dim = 2
    g = 0.05
    H_zz = CouplingGenerator.inductive(dim, dim, g)
    
    # Diagonal elements:
    # |00> -> 0
    # |01> -> 0
    # |10> -> 0
    # |11> -> g * 1 * 1 = g
    
    evals = H_zz.eigenenergies()
    
    # Should have three 0s and one g
    zeros = np.sum(np.isclose(evals, 0.0))
    shift = np.sum(np.isclose(evals, g))
    
    assert zeros == 3
    assert shift == 1
