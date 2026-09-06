======
Qubits
======

``QubitEngine`` is the front door to qforge. It builds superconducting qubit models
through scqubits, keeps them in a named registry, and answers the questions you ask
of a circuit before you ever drive it: where are its levels, how anharmonic is it,
how long will it live, and what happens if you change one parameter.

.. code-block:: python

    from qforge.core.qubit_engine import QubitEngine

    engine = QubitEngine()
    q = engine.create_qubit("transmon", "Q1", {"EJ": 15.0, "EC": 0.3})

The registry is persistent. Every other engine refers to qubits by name, so ``"Q1"``
is enough to drive a gate, build a coupling or run a circuit.

Supported models
================

Four scqubits circuit types are wired up. They take different parameters, and qforge
deliberately does not paper over that.

Transmon
--------

.. math::

    H = 4 E_C (\hat{n} - n_g)^2 - E_J \cos\hat{\varphi}

A junction shunted by a large capacitor. Large :math:`E_J/E_C` flattens the charge
dispersion, which is the entire point, at the cost of a small anharmonicity of
roughly 200 to 300 MHz.

.. list-table::
   :header-rows: 1
   :widths: 22 15 63

   * - Parameter
     - Default
     - Meaning
   * - ``EJ``
     - 15.0
     - Josephson energy, GHz.
   * - ``EC``
     - 0.3
     - Charging energy, GHz.
   * - ``ng``
     - 0.0
     - Offset charge on the island, in Cooper pairs.
   * - ``ncut``
     - 30
     - Charge basis cutoff. Too small and the ground state lands hundreds of MHz off.
   * - ``truncated_dim``
     - 4
     - How many eigenstates the rest of qforge keeps. This is your leakage budget.

Fluxonium
---------

.. math::

    H = 4 E_C \hat{n}^2
        - E_J \cos(\hat{\varphi} - 2\pi\Phi_{\mathrm{ext}}/\Phi_0)
        + \tfrac{1}{2} E_L \hat{\varphi}^2

A junction shunted by a superinductor. At the half flux sweet spot the qubit
frequency drops to a few hundred MHz and coherence is long.

Parameters: ``EJ`` (8.9), ``EC`` (2.5), ``EL`` (0.5), ``flux`` (0.5, in
:math:`\Phi_0`), ``cutoff`` (110), ``truncated_dim`` (4).

Flux qubit
----------

Three junctions in a loop, one of them smaller than the others. Persistent current
states appear near half a flux quantum.

Parameters: ``EJ1``, ``EJ2``, ``EJ3`` (10.0 each), ``ECJ1``, ``ECJ2``, ``ECJ3``
(1.0 each), ``ECg1``, ``ECg2`` (50.0 each), ``ng1``, ``ng2`` (0.0), ``flux`` (0.5),
``ncut`` (10).

Zero-pi
-------

A noise protected circuit with two junctions, two superinductors and three modes.
Slow to diagonalize, which is the price of the topology.

Parameters: ``EJ`` (10.0), ``EL`` (0.1), ``ECJ`` (20.0), ``EC`` (0.04), ``ng``
(0.0), ``flux`` (0.0), ``grid`` (a ``(min, max, points)`` tuple, default
``(-6.0, 6.0, 100)``), ``ncut`` (30).

.. note::

   If the circuit you want is none of these four, write it as a netlist and let
   qforge quantize it. See :doc:`devices`.

Presets
=======

``qforge/config/defaults.py`` holds starting points for each type, so you do not
have to remember plausible values.

.. code-block:: python

    from qforge.config.defaults import QUBIT_PRESETS

    params = QUBIT_PRESETS["transmon"]["high_coherence"]
    engine.create_qubit("transmon", "Q_hc", params)

Transmon and fluxonium each carry ``typical``, ``high_coherence`` and ``fast_gates``
variants. The flux qubit and zero-pi carry ``typical`` only.

.. DYNAMIC_TABLE: QUBITS

.. list-table::
   :header-rows: 1
   :widths: 18 34 18 30

   * - Qubit type
     - Key parameters
     - Typical frequency
     - Best for
   * - **Transmon**
     - EJ, EC
     - 4-5 GHz
     - Fast gates, easier control
   * - **Fluxonium**
     - EJ, EC, EL
     - 0.1-1 GHz
     - Long coherence, reduced errors
   * - **Flux**
     - EJ1, EJ2, EJ3, ECJ1, ECJ2, ECJ3, ECg1, ECg2
     - 1-10 GHz
     - Flux-based control
   * - **Zeropi**
     - EJ, EL, ECJ, EC
     - Variable
     - Noise protection

.. END_DYNAMIC_TABLE

.. note::

   The table above is generated from ``QUBIT_PRESETS`` by ``qforge dev sync``. Edit
   the presets, not the table.

Spectra
=======

.. code-block:: python

    evals = engine.compute_spectrum(q, n_levels=5, subtract_ground=True)

    f01 = evals[1] - evals[0]
    f12 = evals[2] - evals[1]
    alpha_mhz = (f12 - f01) * 1e3

Eigenvalues come back in GHz. With ``subtract_ground=True`` the ground state sits at
zero, which is what you want for reading transition frequencies straight off the
array.

Anharmonicity is the number that decides whether a circuit is usable as a qubit. A
pulse short enough to be fast has a bandwidth wide enough to drive
:math:`1 \rightarrow 2` along with :math:`0 \rightarrow 1`, and it is
:math:`\alpha = f_{12} - f_{01}` that separates them.

Coherence
=========

.. code-block:: python

    coherence = engine.estimate_coherence(q, temperature=0.015)
    # {"T1 (dielectric)": {"value": 87.3,  "limit": "Capacitive loss"},
    #  "T2 (echo)":       {"value": 122.2, "limit": "Estimated from T1"}}

:math:`T_1` comes from scqubits' capacitive loss channel at the given bath
temperature, with a quality factor of :math:`10^6`. scqubits returns times in units
of inverse frequency, which with GHz energies means nanoseconds, and qforge converts
to microseconds.

:math:`T_2` is estimated as :math:`1.4 \times T_1`, that is the :math:`2T_1` ceiling
scaled by 0.7 to stand in for typical pure dephasing. It is a rule of thumb, not a
noise calculation. If dephasing is the interesting part of your problem, model it
explicitly rather than leaning on this number.

When scqubits cannot compute a channel for the model in question, qforge falls back
to the values in ``NOISE_DEFAULTS`` and labels them ``"Estimated"``. Check the
``limit`` field before quoting a number.

For a noise channel breakdown driven by the circuit topology itself, design the
circuit as a device and call ``QuantumDevice.coherence()``. See :doc:`devices`.

Parameter sweeps
================

.. code-block:: python

    import numpy as np

    sweep = engine.parameter_sweep(
        qubit_type="transmon",
        param_name="EJ",
        param_range=np.linspace(10, 25, 20),
        fixed_params={"EC": 0.3},
        property_name="frequency",   # or "anharmonicity", "T1", "T2"
    )

Each point builds a fresh qubit, computes the property and moves on. Frequency comes
back in GHz, anharmonicity in MHz, coherence times in microseconds. Points that fail
to converge are skipped rather than aborting the sweep.

Visualization
=============

.. code-block:: python

    from qforge.utils.terminal_plot import TerminalPlotter

    TerminalPlotter.plot_spectrum(evals, title="Q1 levels")

    paths = engine.visualize_enhanced(
        q,
        plot_types=["spectrum", "wavefunctions", "matrix_elements", "potential"],
        save=True,
    )

``TerminalPlotter`` draws in the terminal through plotext and needs no display.
``visualize_enhanced`` writes matplotlib figures under ``outputs/plots/`` and returns
the paths it wrote.

The engines themselves never plot. Simulation produces a structured result and
rendering is a separate step, so everything stays usable headless.

Export
======

.. code-block:: python

    engine.save_qubit(q, "q1.json")            # parameters, reloadable
    engine.export_to_qutip(q, "q1_qutip.py")   # Hamiltonian and operators for QuTiP
    engine.export_to_qiskit(q, "q1.json")      # frequency, anharmonicity, noise params

    q_again = engine.load_qubit("q1.json")

Managing the registry
=====================

.. code-block:: python

    engine.list_qubits()     # name, type, frequency, anharmonicity for each
    engine.get_qubit("Q1")   # the scqubits object
    engine.delete_qubit("Q1")
    engine.load_session()    # re-read the session file from disk

``get_qubit`` raises when the name is unknown rather than returning ``None``, so a
typo fails where you made it.
