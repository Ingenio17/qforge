"""
Coupling Engine: Handles generation of interaction Hamiltonians for multi-qubit systems.
"""

from enum import Enum, auto
import numpy as np
import qutip as qt
from typing import Dict, Any, Tuple, Optional, Callable

class CouplingType(Enum):
    """Enumeration of supported coupling types."""
    CAPACITIVE = "capacitive"
    INDUCTIVE = "inductive"
    TUNABLE_COUPLER = "tunable_coupler"  # Generic tunable coupler (often Transmon-based)

class CouplingGenerator:
    """
    Generator for multi-qubit interaction Hamiltonians.
    """

    @staticmethod
    def capacitive(dim1: int, dim2: int, strength: float) -> qt.Qobj:
        """
        Generate capacitive coupling Hamiltonian: g(a1^dag a2 + a1 a2^dag).
        Common for fixed-frequency transmons (e.g. Cross Resonance).

        Args:
            dim1: Dimension of qubit 1
            dim2: Dimension of qubit 2
            strength: Coupling strength g (GHz)

        Returns:
            Interaction Hamiltonian (Qobj)
        """
        a1 = qt.destroy(dim1)
        a2 = qt.destroy(dim2)
        
        # H_int = g * (a1^dag * a2 + a1 * a2^dag)
        return strength * (qt.tensor(a1.dag(), a2) + qt.tensor(a1, a2.dag()))

    @staticmethod
    def inductive(dim1: int, dim2: int, strength: float) -> qt.Qobj:
        """
        Generate inductive/ZZ coupling Hamiltonian: g * n1 * n2.
        Often an effective model for weak dispersive interactions.

        Args:
            dim1: Dimension of qubit 1
            dim2: Dimension of qubit 2
            strength: Coupling strength g (GHz)

        Returns:
            Interaction Hamiltonian (Qobj)
        """
        a1 = qt.destroy(dim1)
        a2 = qt.destroy(dim2)
        
        n1 = a1.dag() * a1
        n2 = a2.dag() * a2
        
        return strength * qt.tensor(n1, n2)

    @staticmethod
    def tunable_coupler(dim1: int, dim2: int, strength: float, coupler_type: str = "transmon") -> qt.Qobj:
        """
        Generate effective Hamiltonian for a system with a tunable coupler.
        
        Realistically, a tunable coupler is a 3rd quantum object. 
        For 2-qubit simulation, we often model the *effective* adjustable coupling
        that the coupler mediates.
        
        If 'strength' is the *maximum* effective coupling g_eff(t), 
        this returns the operator structure. The time-dependence is handled in the solver.
        
        E.g. for a tunable coupler mediating exchange: g(t)(a1^dag a2 + h.c.)
        For a coupler mediating ZZ: g(t) n1 n2 (e.g. for CZ)
        
        Here we assume the user wants to simulate a 'swap' type interaction turned on/off.
        
        Args:
             dim1: Dimension of qubit 1
             dim2: Dimension of qubit 2
             strength: Max coupling strength
             coupler_type: 'transmon' or other. 
             
        Returns:
             Operator Qobj (usually exchange-like)
        """
        # Default behavior: effective exchange interaction that can be modulated
        return CouplingGenerator.capacitive(dim1, dim2, strength)

    @staticmethod
    def get_coupling(c_type: str, dim1: int, dim2: int, strength: float, **kwargs) -> qt.Qobj:
        """
        Factory method to get coupling Hamiltonian.

        Args:
            c_type: "capacitive", "inductive", "tunable_coupler"
            dim1: Dimension 1
            dim2: Dimension 2
            strength: Coupling strength
            **kwargs: Extra args for specific couplers
        """
        c_type = c_type.lower()
        if c_type == CouplingType.CAPACITIVE.value:
            return CouplingGenerator.capacitive(dim1, dim2, strength)
        elif c_type == CouplingType.INDUCTIVE.value:
            return CouplingGenerator.inductive(dim1, dim2, strength)
        elif c_type == CouplingType.TUNABLE_COUPLER.value:
            return CouplingGenerator.tunable_coupler(dim1, dim2, strength, **kwargs)
        else:
            raise ValueError(f"Unknown coupling type: {c_type}")
