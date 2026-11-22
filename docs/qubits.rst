======
Qubits
======

``QubitEngine`` builds superconducting qubit models through scqubits, keeps them in
a named registry, and answers the questions that precede any dynamics: where the
levels sit, how anharmonic the circuit is, how long it is likely to live, and how
those change with a parameter.

.. code-block:: python

    from QubitWeave.core.qubit_engine import QubitEngine

    engine = QubitEngine()
    q = engine.create_qubit("transmon", "Q1", {"EJ": 15.0, "EC": 0.3})

The registry is persistent. Every other engine refers to qubits by name, so ``"Q1"``
is sufficient to drive a gate, declare a coupling or run a circuit.

Supported models
================

Four scqubits circuit types are available, along with a fifth backed by a custom
netlist. They take different parameters, and QubitWeave keeps those differences
explicit rather than hiding them behind a common signature.

Transmon
--------

.. math::

    H = 4 E_C (\hat{n} - n_g)^2 - E_J \cos\hat{\varphi}

A junction shunted by a large capacitor. A large :math:`E_J/E_C` ratio flattens the
charge dispersion, at the cost of a small anharmonicity of roughly 200 to 300 MHz.

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
     - Eigenstates retained by the rest of QubitWeave, which sets how much leakage the
       simulation can represent.

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

A noise-protected circuit with two junctions, two superinductors and three modes.
The three-mode Hilbert space makes it considerably slower to diagonalize than the
other presets.

Parameters: ``EJ`` (10.0), ``EL`` (0.1), ``ECJ`` (20.0), ``EC`` (0.04), ``ng``
(0.0), ``flux`` (0.0), ``grid`` (a ``(min, max, points)`` tuple, default
``(-6.0, 6.0, 100)``), ``ncut`` (30).

Device-backed
-------------

A circuit described by a netlist, quantized through scqubits' symbolic circuit
support and adapted to the same interface the preset models present. Registering one
uses the ``"device"`` type, with the netlist source carried in ``params``:

.. code-block:: python

    from QubitWeave.core.device_qubit import device_qubit_params

    params = device_qubit_params(netlist_source, truncated_dim=4)
    engine.create_qubit("device", "custom", params)

The source is stored in full rather than as a path, so a registered qubit survives
edits to the file it came from and a session file remains a complete record of the
circuit. Once registered it behaves like any preset qubit throughout gates,
couplings, workflows and error correction.

Two details distinguish it from a preset model. A designed circuit may carry several
modes, so the adapter selects the one holding the 0-1 transition by scoring each
mode's charge operator as :math:`|\langle 0|Q|1\rangle| / \sqrt{\langle 0|Q^2|0\rangle}`,
which compares modes on equal footing despite their different operator scalings. And
``phi_operator`` is exposed only for extended modes, since a periodic mode's phase is
compact and has no well-defined operator, which keeps the ``hasattr`` check in
``GateEngine`` honest.

The full workflow, from netlist to registered qubit, is in :doc:`devices`.

Presets
=======

``QubitWeave/config/defaults.py`` holds starting points for each of the four preset
types.

.. code-block:: python

    from QubitWeave.config.defaults import QUBIT_PRESETS

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

   The table above is generated from ``QUBIT_PRESETS`` by ``QubitWeave dev sync``. Edit
   the presets, not the table.

Spectra
=======

.. code-block:: python

    evals = engine.compute_spectrum(q, n_levels=5, subtract_ground=True)

    f01 = evals[1] - evals[0]
    f12 = evals[2] - evals[1]
    alpha_mhz = (f12 - f01) * 1e3

Eigenvalues are returned in GHz. With ``subtract_ground=True`` the ground state sits
at zero, so transition frequencies can be read directly off the array.

Anharmonicity determines whether a circuit is usable as a qubit at all. A pulse short
enough to be fast is spectrally wide enough to drive :math:`1 \rightarrow 2` along
with :math:`0 \rightarrow 1`, and :math:`\alpha = f_{12} - f_{01}` is what separates
the two.

Coherence
=========

.. code-block:: python

    coherence = engine.estimate_coherence(q, temperature=0.015)
    # {"T1 (dielectric)": {"value": 87.3,  "limit": "Capacitive loss"},
    #  "T2 (echo)":       {"value": 122.2, "limit": "Estimated from T1"}}

:math:`T_1` comes from scqubits' capacitive loss channel at the given bath
temperature, with a quality factor of :math:`10^6`. scqubits returns times in units
of inverse frequency, which with GHz energies means nanoseconds, and QubitWeave converts
to microseconds.

:math:`T_2` is estimated as :math:`1.4 \times T_1`, that is the :math:`2T_1` ceiling
scaled by 0.7 to stand in for typical pure dephasing. It is a rule of thumb, not a
noise calculation. Where dephasing is the quantity under study, it should be modelled
explicitly rather than inferred from this estimate.

When scqubits cannot compute a channel for a given model, QubitWeave falls back to the
values in ``NOISE_DEFAULTS`` and labels them ``"Estimated"``. The ``limit`` field
records which case applies.

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

Each point builds a fresh qubit and computes the requested property. Frequency is
returned in GHz, anharmonicity in MHz, and coherence times in microseconds. Points
that fail to converge are skipped rather than aborting the sweep.

Visualization
=============

.. code-block:: python

    from QubitWeave.utils.terminal_plot import TerminalPlotter

    TerminalPlotter.plot_spectrum(evals, title="Q1 levels")

    paths = engine.visualize_enhanced(
        q,
        plot_types=["spectrum", "wavefunctions", "matrix_elements", "potential"],
        save=True,
    )

``TerminalPlotter`` draws through plotext and requires no display.
``visualize_enhanced`` writes matplotlib figures under ``outputs/plots/`` and returns
the paths written.

The engines do not plot. Simulation produces a structured result and rendering is a
separate step, which keeps every method usable headless.

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

``get_qubit`` raises on an unknown name rather than returning ``None``, so a mistyped
name fails at the point of use.
