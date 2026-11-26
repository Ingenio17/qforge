=========
Couplings
=========

A two-qubit gate requires an interaction between the qubits. QubitWeave models three,
and the choice determines both the interaction Hamiltonian and the gate that the
interaction can produce.

Couplings are passed to the engines as dictionaries:

.. code-block:: python

    couplings = [
        {"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05},
    ]

``q1`` and ``q2`` are indices into the accompanying list of qubit names, and
``strength`` is :math:`g` in GHz. Index order is preserved throughout, so index 0
refers to the first name in that list.

Interaction Hamiltonians
========================

``GateEngine._get_n_qubit_hamiltonian`` builds the static N-qubit Hamiltonian as the
sum of the local terms plus one interaction term per declared coupling:

.. math::

    \mathcal{H}_{\mathrm{sys}} = \sum_i \mathcal{H}_{0,i}
        + \sum_{\langle i,j \rangle} g_{ij}\, \hat{O}_i \otimes \hat{O}_j

The operators :math:`\hat{O}` are taken from the circuit's own eigenbasis through
``matrixelement_table``, not from a harmonic approximation, which is what allows the
interaction to remain correct outside the two lowest levels.

Capacitive
----------

.. math::

    H_{\mathrm{int}} = g \, \hat{n}_i \otimes \hat{n}_j

A charge-charge interaction between two circuits sharing a coupling capacitor. This
is the standard model for fixed-frequency transmons, and it is always on: there is
no knob that switches it off between gates.

Two consequences follow from that, and both are measured rather than assumed by the
CNOT calibration described in :doc:`gates`. The eigenstates of the coupled pair are
dressed, so bare :math:`|01\rangle` and :math:`|10\rangle` hybridize with each
other and bare :math:`|11\rangle` with :math:`|02\rangle` and :math:`|20\rangle`.
And the interaction shifts each qubit's 0-1 transition depending on the state of the
other, which is the ZZ shift the microwave-activated CNOT relies on.

Inductive
---------

.. math::

    H_{\mathrm{int}} = g \, \hat{\varphi}_i \otimes \hat{\varphi}_j

A flux-flux interaction, appropriate when the two circuits share a geometric
inductance.

This requires a circuit with an explicit inductive branch. A transmon is a junction
shunted by a capacitor, has no :math:`E_L \hat{\varphi}^2` term, and its scqubits
model in the charge basis exposes no phase operator, so QubitWeave raises an error
explaining this rather than substituting an approximation. Fluxonium, the flux qubit
and zero-pi all carry a real inductor and accept this coupling.

Tunable coupler
---------------

.. math::

    H_{\mathrm{int}}(t) = g\, f(t)\, \hat{n}_i \otimes \hat{n}_j

The same charge-charge interaction, modulated in time by a flux pulse on a dedicated
coupler element. There is no static term: a tunable coupler contributes nothing to
the Hamiltonian until its envelope is switched on, which is what allows the
interaction to be gated for exactly the duration of a gate.

Three envelopes appear, depending on how the interaction is driven:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Where
     - Envelope
   * - A two-qubit call with no explicit coupler pulse
     - Gaussian, :math:`\sigma = T/6`, centred at :math:`T/2`.
   * - A scheduled ``coupler_pulse`` drive, as emitted by the workflow engine and by
       the compiled CNOT
     - :math:`f(t) = \sin^2\!\left(\pi (t - t_0) / T\right)`, which starts and ends
       at zero.
   * - A ``coupler_pulse`` carrying a ``frequency``, as emitted for a parametric CZ
     - A raised-cosine flat top times
       :math:`\cos(2\pi f_{\mathrm{mod}}(t - t_0))`.

Which gate each supports
========================

.. list-table::
   :header-rows: 1
   :widths: 22 26 26 26

   * -
     - Capacitive
     - Inductive
     - Tunable coupler
   * - Interaction
     - Charge-charge, :math:`\hat{n}\hat{n}`
     - Flux-flux, :math:`\hat{\varphi}\hat{\varphi}`
     - Gated charge-charge
   * - Active when idle
     - Yes
     - Yes
     - No
   * - Two-qubit gate
     - Microwave-activated CNOT
     - CZ by accumulated interaction phase
     - CZ, and CNOT compiled from it
   * - Valid on a transmon
     - Yes
     - No, requires an inductive branch
     - Yes

Analytic forms in ``coupling.py``
=================================

``CouplingGenerator`` in ``QubitWeave/core/coupling.py`` provides harmonic-oscillator
versions of the same interactions, built from ladder operators on a truncated
oscillator: :math:`g(a^\dagger b + a b^\dagger)` for the capacitive case and
:math:`g\,\hat{n}_1 \hat{n}_2` for the inductive one.

These are convenient for analytic work and are what the coupling unit tests exercise,
but they are not what the simulation path builds. When reasoning about a simulation
result, use the Hamiltonians above.

Comparing couplings
===================

``GateEngine.compare_couplings`` runs the same logical gate under several couplings
and reports the final population of :math:`|11\rangle` for each, along with the
accumulated interaction phase in units of :math:`\pi` when the gate is a CZ:

.. code-block:: python

    results = gates.compare_couplings(q1="Q1", q2="Q2", gate="CNOT")
    # {"capacitive": {"population": ...}, "inductive": {...}, "tunable_coupler": {...}}

Passing ``coupling_type``, ``strength`` and ``duration`` together runs that single
scenario instead of the default set. The wizard exposes the same comparison under
"Analyze multi-qubit gates", sweeping several strengths per coupling.

Adding a coupling model
=======================

* State the Hamiltonian explicitly, together with the meaning and units of its
  coupling strength.
* Preserve qubit ordering and tensor dimensions. Local dimensions differ between
  qubits, and the operator has to agree with ``dims``.
* Keep static and time-dependent interactions distinct.
* Implement it in ``coupling.py`` and in ``_get_n_qubit_hamiltonian`` rather than
  inside an engine that should not depend on a particular interaction.
