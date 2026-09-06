=========
Couplings
=========

Two qubit gates need an interaction. qforge models three of them, and which one you
pick changes both the Hamiltonian and the gate that falls out of it naturally.

Couplings live in ``qforge/core/coupling.py`` and are described to the engines as
plain dictionaries:

.. code-block:: python

    couplings = [
        {"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05},
    ]

``q1`` and ``q2`` are indices into the qubit name list you pass alongside, and
``strength`` is :math:`g` in GHz. Ordering is preserved throughout, so index 0 is
the first qubit you named.

Capacitive
==========

.. math::

    H_{\mathrm{int}} = g \left( a^\dagger b + a b^\dagger \right)

A transverse exchange interaction, the usual model for two fixed frequency
transmons sharing a coupling capacitor. Excitations hop between the qubits.

In the dispersive limit :math:`|\Delta| \gg g` the qubits barely hybridize, and
driving the control at the target's frequency turns the interaction into an
effective :math:`ZX` term. That is the cross resonance gate, and it is how qforge
builds a CNOT on a capacitively coupled pair.

Use it for: fixed frequency architectures, cross resonance, always on coupling that
you would rather not switch off.

Inductive and ZZ
================

.. math::

    H_{\mathrm{int}} = g \, \hat{n}_1 \hat{n}_2

A longitudinal coupling. Neither qubit's population changes. Instead each one's
energy shifts depending on the state of the other, which accumulates a conditional
phase and gives you a CPHASE naturally over a time of order :math:`\pi/g`.

qforge refuses an ``inductive`` coupling on a plain transmon and says so. A transmon
lives in the charge basis and has no :math:`E_L \hat{\varphi}^2` term to couple
through, so the model would be describing a circuit you did not build. Use a
fluxonium or zero-pi if you want a genuine inductive branch.

Use it for: dispersive interactions, native CZ, residual ZZ you want to quantify.

Tunable coupler
===============

.. math::

    H(t) = g_{\max} f(t) \left( a^\dagger b + a b^\dagger \right)

The same exchange interaction as the capacitive case, but with the strength
modulated in time by a flux pulse on a dedicated coupler element. That is what lets
you turn the interaction on for exactly as long as the gate needs and leave it off
the rest of the time.

qforge shapes the coupler pulse as :math:`\sin^2`, which switches on and off smoothly
from zero:

.. math::

    f(t) = \sin^2\!\left(\frac{\pi (t - t_0)}{T}\right)

Use it for: iSWAP, flux activated CZ, anything where you need the interaction gated
in time rather than always on.

Choosing one
============

.. list-table::
   :header-rows: 1
   :widths: 22 26 26 26

   * -
     - Capacitive
     - Inductive / ZZ
     - Tunable coupler
   * - Interaction
     - Transverse exchange
     - Longitudinal
     - Gated exchange
   * - Native gate
     - Cross resonance CNOT
     - CPHASE / CZ
     - iSWAP, CZ
   * - On when idle
     - Yes
     - Yes
     - No
   * - Works on a transmon
     - Yes
     - No, needs an inductive branch
     - Yes

Comparing them directly
=======================

``GateEngine.compare_couplings`` runs the same logical gate under each model and
reports the target state population and the accumulated interaction phase side by
side:

.. code-block:: python

    results = gates.compare_couplings(q1="Q1", q2="Q2", gate="CNOT")

The wizard exposes the same thing under "Analyze multi-qubit gates", which sweeps
several coupling strengths per architecture and prints a table.

Adding a coupling model
=======================

If you add one, keep it honest:

* Write the Hamiltonian out explicitly, and say what :math:`g` means and in what
  units.
* Preserve qubit ordering and tensor dimensions. Local dimensions differ between
  qubits and the operator has to agree with ``dims``.
* Keep static coupling separate from driven coupling. A time dependent interaction
  is a different object from a constant one.
* Put it in ``coupling.py``. Do not hard code an interaction inside an engine that
  is meant to be agnostic about it.
