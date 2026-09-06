==========
Quickstart
==========

This page walks the whole toolkit in about five minutes: build a qubit, look at its
spectrum, drive a gate, entangle two qubits, then run a QASM circuit on the pair.
Everything here is plain Python. The same ground is covered by the wizard described
in :doc:`interfaces`, and by the commands in :doc:`cli`.

1. Build a qubit
================

``QubitEngine`` wraps scqubits and keeps a named registry of every qubit you create.
Parameters are energies in GHz.

.. code-block:: python

    from qforge.core.qubit_engine import QubitEngine

    qubits = QubitEngine()

    q1 = qubits.create_qubit(
        qubit_type="transmon",
        name="Q1",
        params={"EJ": 15.0, "EC": 0.3},
    )

Qubits are registered by name and persisted to ``outputs/qubits/.qforge_session.json``,
so the rest of the toolkit refers to them as ``"Q1"`` rather than passing objects
around. See :doc:`conventions` for what that means for cleanup.

2. Look at it
=============

.. code-block:: python

    from qforge.utils.terminal_plot import TerminalPlotter

    spectrum = qubits.compute_spectrum(q1, n_levels=5, subtract_ground=True)
    TerminalPlotter.plot_spectrum(spectrum, title="Q1 energy levels")

    coherence = qubits.estimate_coherence(q1, temperature=0.015)
    for channel, data in coherence.items():
        print(f"{channel}: {data['value']:.1f} us  ({data['limit']})")

``compute_spectrum`` returns eigenvalues in GHz. With ``subtract_ground=True`` the
first entry is zero and the second is :math:`f_{01}`. The gap between the first two
spacings is the anharmonicity, which is what makes the circuit addressable as a
qubit at all.

3. Drive a gate
===============

An X gate here is not a matrix. It is a Gaussian microwave pulse on the charge
operator, resonant with :math:`\omega_{01}`, with a DRAG quadrature term that
suppresses leakage into :math:`|2\rangle`.

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

``noise_model="realistic"`` pulls :math:`T_1` from the qubit's own coherence
estimate and feeds it to QuTiP's master equation as a collapse operator. With
``"none"`` the evolution is closed and unitary.

The populations you get back cover every level in the truncated space, not just
:math:`|0\rangle` and :math:`|1\rangle`. Whatever shows up in :math:`|2\rangle` is
leakage, and it is real.

4. Calibrate it
===============

You rarely know the right pulse length up front. ``calibrate_gate`` sweeps a
parameter, finds the peak, then re-sweeps a narrow window around it.

.. code-block:: python

    duration, score = gates.calibrate_gate(
        "Q1",
        gate_type="X",
        parameter="duration",
    )
    print(f"pi pulse at {duration:.2f} ns, target population {score:.4f}")

Calibrations are cached to ``outputs/calib_cache.json`` and survive between
sessions, because the sweeps are the expensive part of most workflows. Change a
qubit's parameters and you want a fresh sweep, so run ``qforge cache clear``.

5. Entangle two qubits
======================

.. code-block:: python

    qubits.create_qubit("transmon", "Q2", {"EJ": 14.2, "EC": 0.28})

    result = gates.simulate_two_qubit_dynamics(
        qubit1_name="Q1",
        qubit2_name="Q2",
        gate_type="CNOT",
        coupling_type="tunable_coupler",
        coupling_strength=0.05,     # GHz
        duration=150.0,             # ns
    )

    final = {k: v[-1] for k, v in result["populations"].items()}
    for state, p in sorted(final.items(), key=lambda kv: -kv[1])[:4]:
        print(f"|{state}>: {p:.3f}")

A tunable coupler natively gives you a controlled phase, so a CNOT request is
compiled into the physical sequence :math:`X(-\pi/2)`, CZ, :math:`X(+\pi/2)` on the
target, with the Stark phase accumulated during the flux pulse folded into the
second pulse. :doc:`gates` walks through that.

The three coupling models and what each is good for are in :doc:`couplings`.

6. Run a circuit
================

``PhysicalWorkflowEngine`` takes an OpenQASM 2.0 file, decomposes it to a hardware
native basis, calibrates whatever pulses it needs, schedules them in time, then
solves the whole thing as one continuous Hamiltonian.

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

There is no gate by gate reset between instructions. The schedule is one pulse
sequence, so accumulated phase, leakage and decoherence carry across the circuit
the way they would on hardware. :doc:`qasm` covers what the parser accepts.

7. Add error correction
=======================

Same circuit, now encoded. Each logical qubit expands into physical data and
ancilla qubits, syndromes are extracted with real CNOT drives, and corrections are
fed forward.

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

Three codes ship today: the 3 qubit repetition code, the 7 qubit Steane code and
the 9 qubit Shor code. Adding a fourth means writing a specification, not touching
the engine. See :doc:`error_correction`.

Where next
==========

* :doc:`conventions` if you are about to write numerical code. Units and Hilbert
  space dimensions are where this kind of work goes wrong.
* :doc:`devices` if you want to design a circuit that is not one of the four preset
  qubit types.
* :doc:`examples` for thirteen worked scripts, from a single Rabi flop to Grover's
  algorithm on physical pulses.
