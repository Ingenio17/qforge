==========
Quickstart
==========

This page covers the toolkit end to end: build a qubit, examine its spectrum, drive
a gate, couple two qubits, run a QASM circuit on the pair, and encode it in a
stabilizer code. Everything here is plain Python. The wizard in :doc:`interfaces`
and the commands in :doc:`cli` cover the same ground.

1. Build a qubit
================

``QubitEngine`` wraps scqubits and keeps a named registry of every qubit created.
Parameters are energies in GHz.

.. code-block:: python

    from qforge.core.qubit_engine import QubitEngine

    qubits = QubitEngine()

    q1 = qubits.create_qubit(
        qubit_type="transmon",
        name="Q1",
        params={"EJ": 15.0, "EC": 0.3},
    )

Qubits are registered by name and persisted to
``outputs/qubits/.qforge_session.json``, so the rest of the toolkit refers to them
as ``"Q1"`` rather than by passing objects around. :doc:`conventions` describes what
that implies for cleanup.

2. Examine its spectrum
=======================

.. code-block:: python

    from qforge.utils.terminal_plot import TerminalPlotter

    spectrum = qubits.compute_spectrum(q1, n_levels=5, subtract_ground=True)
    TerminalPlotter.plot_spectrum(spectrum, title="Q1 energy levels")

    coherence = qubits.estimate_coherence(q1, temperature=0.015)
    for channel, data in coherence.items():
        print(f"{channel}: {data['value']:.1f} us  ({data['limit']})")

``compute_spectrum`` returns eigenvalues in GHz. With ``subtract_ground=True`` the
first entry is zero and the second is :math:`f_{01}`. The difference between the
first two level spacings is the anharmonicity, which determines whether the circuit
can be addressed as a qubit.

3. Drive a gate
===============

An X gate is a Gaussian microwave pulse on the charge operator, resonant with
:math:`\omega_{01}`, carrying a DRAG quadrature term that suppresses leakage into
:math:`|2\rangle`.

.. code-block:: python

    from qforge.core.gate_engine import GateEngine

    gates = GateEngine()

    result = gates.simulate_dynamics(
        qubit_name="Q1",
        gate_type="X",
        duration=40.0,          # ns
        noise_model="realistic",
        steps=200,
    )

    TerminalPlotter.plot_time_evolution(
        times=result["times"],
        expectations=result["expectations"],
        labels=result["labels"],
        title="Rabi flop under an X pulse",
    )

``noise_model="realistic"`` takes :math:`T_1` from the qubit's own coherence
estimate and supplies it to QuTiP's master equation as a collapse operator. With
``"none"`` the evolution is closed and unitary.

The returned populations cover every level in the truncated space, not only
:math:`|0\rangle` and :math:`|1\rangle`. Population appearing in :math:`|2\rangle`
is leakage out of the computational subspace.

4. Calibrate the pulse
======================

``calibrate_gate`` sweeps one parameter, locates the peak, then re-sweeps a narrow
window around it.

.. code-block:: python

    duration, score = gates.calibrate_gate(
        "Q1",
        gate_type="X",
        parameter="duration",
    )
    print(f"pi pulse at {duration:.2f} ns, target population {score:.4f}")

Calibrations are cached to ``outputs/calib_cache.json`` and persist between
sessions, since the sweeps dominate the cost of most workflows. Run
``qforge cache clear`` after changing a qubit's parameters, because a calibration
keyed to the old ones no longer describes the gate.

5. Couple two qubits
====================

.. code-block:: python

    qubits.create_qubit("transmon", "Q2", {"EJ": 11.63, "EC": 0.3})

    result = gates.simulate_two_qubit_dynamics(
        qubit1_name="Q1",
        qubit2_name="Q2",
        gate_type="CNOT",
        coupling_type="capacitive",
        coupling_strength=0.05,     # GHz
        duration=280.0,             # ns
        initial_state="10",
    )

    final = {k: v[-1] for k, v in result["populations"].items()}
    for state, p in sorted(final.items(), key=lambda kv: -kv[1])[:3]:
        print(f"|{state}>: {p:.3f}")
    # |11>: 0.953
    # |20>: 0.037
    # |01>: 0.006

    for warning in result["warnings"]:
        print(warning)

The two-qubit gate follows from the coupling. A fixed capacitive coupling has no
knob to switch, so the CNOT is a microwave-activated conditional rotation: a
:math:`\pi` pulse on the target at the transition frequency it only has while the
control is excited. A tunable coupler instead produces a controlled phase natively,
and a CNOT is compiled as :math:`X(-\pi/2)`, CZ, :math:`X(+\pi/2)` on the target.

The control starts in :math:`|1\rangle` here, so the target flips and the pair ends
in :math:`|11\rangle`. Starting from :math:`|00\rangle` the same pulse leaves the
state untouched, which is what makes it conditional rather than an unconditional X.
The remaining few percent sits in :math:`|20\rangle`, leakage the simulation reports
because the third level is part of the model.

The capacitive path returns the diagnostics behind its calibration.
``result["schedule"]`` carries the ZZ shift, the selectivity and the dressed-state
purity, and ``result["warnings"]`` describes any operating point that cannot support
the gate. The duration above was chosen from the ZZ shift for that reason: at
:math:`g = 0.05` GHz these two qubits give :math:`\zeta = -9.5` MHz, and separating
the two control branches needs a pulse spectrally narrower than that.

:doc:`gates` covers both mechanisms, and :doc:`couplings` covers the three
interaction models.

6. Run a circuit
================

``PhysicalWorkflowEngine`` takes an OpenQASM 2.0 file, decomposes it into a
hardware-native basis, calibrates the pulses it requires, schedules them in time,
and solves the result as one continuous Hamiltonian.

.. code-block:: python

    from qforge.core.workflow_engine import PhysicalWorkflowEngine

    workflow = PhysicalWorkflowEngine(qubits, gates)

    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05}]

    results = workflow.execute_workflow(
        qubit_names=["Q1", "Q2"],
        couplings=couplings,
        qasm_path="examples/qasm_files/bell_state.qasm",
    )

    print(results["final_state"])

There is no reset between instructions. The schedule is a single pulse sequence, so
accumulated phase, leakage and decoherence carry across the circuit as they would on
hardware. :doc:`qasm` describes what the parser accepts.

7. Encode it
============

The same circuit, run on a stabilizer code. Each logical qubit expands into physical
data and ancilla qubits, syndromes are extracted with CNOT drives, ancillas are
measured mid-circuit, and corrections are fed forward.

.. code-block:: python

    from qforge.core.error_correction_engine import ErrorCorrectionEngine

    ec = ErrorCorrectionEngine(qubits, gates)

    result = ec.execute_steane7_workflow(
        logical_names=["Q1"],
        qasm_path="examples/qasm_files/single_state.qasm",
        coupling_type="capacitive",
        coupling_strength=0.010,
    )

    print(result["logical_populations"])

Three codes are implemented: the 3-qubit repetition code, the 7-qubit Steane code
and the 9-qubit Shor code. Adding a fourth means writing a code specification rather
than modifying the engine. See :doc:`error_correction`.

Next steps
==========

* :doc:`conventions` before writing numerical code. Units and Hilbert-space
  dimensions are the usual source of error.
* :doc:`devices` to simulate a circuit that is not one of the preset qubit types,
  and to register one as a qubit.
* :doc:`examples` for thirteen worked scripts, from a single Rabi flop to Grover's
  algorithm executed as physical pulses.
