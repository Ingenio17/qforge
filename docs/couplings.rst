Multi-Qubit Couplings
=====================

QForge provides flexible modeling for multi-qubit interactions, essential for simulating 2-qubit gates like CNOT and CZ. This page details the physical Hamiltonians used in the simulation.

Capacitive Coupling
-------------------

The most common coupling for fixed-frequency transmons (e.g., in Cross-Resonance gates). The interaction is transverse.

.. math::
    H_{int} = g \left( a^\dagger b + a b^\dagger \right)

where:
* :math:`a, a^\dagger` are operators for the control qubit (Q1).
* :math:`b, b^\dagger` are operators for the target qubit (Q2).
* :math:`g` is the coupling strength in GHz.

**Physics:**
This term represents exchange interaction. In the dispersive limit (:math:`|\Delta| \gg g`), it leads to a small hybridization of the states. When driven at the target frequency (Cross-Resonance), it activates a :math:`ZX` interaction essential for CNOT.

Inductive / ZZ Coupling
-----------------------

Often an effective model for weak dispersive interactions or residual coupling from higher levels.

.. math::
    H_{int} = g \hat{n}_1 \hat{n}_2 = g (a^\dagger a)(b^\dagger b)

where:
* :math:`\hat{n}_i` is the number operator for qubit :math:`i`.

**Physics:**
This is a longitudinal coupling that shifts energy levels depending on the state of the other qubit. It naturally implements a CPHASE (CZ) evolution over time :math:`T = \pi/g`.

Tunable Coupler (Effective)
---------------------------

For tunable couplers (like g-mon or transmons with flux loops), the effective coupling :math:`g` can be modulated in time. QForge models the identifying interaction Hamiltonian which is then modulated by a pulse envelope :math:`f(t)`.

For a tunable exchange interaction (Swap/iSwap):

.. math::
    H(t) = g_{max} f(t) \left( a^\dagger b + a b^\dagger \right)

For a tunable CZ gate (adiabatic or diabatic flux pulse):

.. math::
    H(t) = g_{eff}(t) |11\rangle\langle 11|

(Note: The exact Hamiltonian depends on the implementation details, e.g., using a third coupler element vs. direct flux tuning).
