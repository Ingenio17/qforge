====================
Circuits and QASM
====================

QubitWeave parses OpenQASM 2.0 directly, with no external circuit framework. The circuit
is then decomposed into a gate set the hardware can produce, each of those gates is
calibrated as a pulse, the pulses are laid out on a timeline, and the result is
solved as one continuous Hamiltonian.

Two classes do the work, both in ``QubitWeave/core/workflow_engine.py``:

* ``QASMTranspiler`` parses and decomposes.
* ``PhysicalWorkflowEngine`` calibrates, schedules and simulates.

.. code-block:: python

    from QubitWeave.core.qubit_engine import QubitEngine
    from QubitWeave.core.gate_engine import GateEngine
    from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine

    q_eng = QubitEngine()
    g_eng = GateEngine()
    workflow = PhysicalWorkflowEngine(q_eng, g_eng)

    qubit_names = ["Q1", "Q2"]
    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.050}]

    results = workflow.execute_workflow(qubit_names, couplings, "bell_state.qasm")
    final_state = results["final_state"]

The pipeline
============

.. code-block:: text

    OpenQASM 2.0 file
        │
        ▼  QASMTranspiler.parse_file
    instruction list in the native basis
        │
        ▼  automate_calibrations
    pulse durations for every X, H, CZ and CX the circuit needs
        │
        ▼  compile_schedule
    a chronological drive schedule, per qubit, in ns
        │
        ▼  GateEngine.simulate_n_qubit_dynamics
    one continuous time evolution over the whole algorithm

The result carries ``times``, ``states``, ``populations`` keyed by computational
basis string, and ``final_state``.

There is no reset between gates. Accumulated phase, leakage and decoherence carry
from one instruction to the next, as they do on hardware.

The native basis
================

Control electronics cannot execute an arbitrary unitary, so every instruction is
reduced to this set:

``{x, h, rz, cx, cz, swap, cp}``

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Gate
     - Physical meaning
   * - ``x``
     - A calibrated :math:`\pi` microwave pulse.
   * - ``h``
     - A calibrated Hadamard microwave pulse, natively calibrated rather than
       decomposed.
   * - ``rz(theta)``
     - A virtual Z. A phase update in the software frame. Zero duration, zero
       decoherence. Aliases ``p`` and ``u1``.
   * - ``cz``
     - A coupler pulse on the interaction operator, with a :math:`\sin^2` envelope.
   * - ``cx`` / ``cnot``
     - On a tunable coupler, compiled to
       :math:`X(-\pi/2) \rightarrow \mathrm{CZ} \rightarrow X(+\pi/2)` on the target,
       with a flux pulse holding the avoided crossing and a Stark-shift-corrected
       closing pulse. On any other coupling the scheduler emits a single drive on the
       control at the target's frequency.
   * - ``swap``
     - Three alternating ``cx`` sequences, laid out in time.
   * - ``cp(theta)``
     - A fractional ``cz``, with the coupler pulse duration scaled by
       :math:`|\theta|/\pi`.

Decompositions
==============

Anything outside the native basis is decomposed recursively until it lands inside it.

Single qubit
------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - QASM gate
     - Becomes
   * - ``z``
     - ``rz(pi)``
   * - ``s``, ``sdg``, ``t``, ``tdg``
     - Pure virtual ``rz`` of :math:`\pi/2`, :math:`-\pi/2`, :math:`\pi/4`,
       :math:`-\pi/4`.
   * - ``y``
     - ``rz(pi/2)`` then ``x`` then ``rz(-pi/2)``.
   * - ``rx(theta)``, ``ry(theta)``
     - Wrapped in Hadamards, since ``h`` is natively calibrated:
       ``h`` then ``rz(theta)`` then ``h``.
   * - ``u2``, ``u3``, ``u``
     - Standard Euler decomposition into alternating ``rz`` updates and
       :math:`\pi/2` drives, which then decompose further.

Multi qubit
-----------

* ``ccx`` (Toffoli) expands into the standard six CNOT construction using ``h``,
  ``cx``, ``t`` and ``tdg``, so it runs on a two qubit physical topology.
* ``cy``, ``ch``, ``crz``, ``cu1``, ``cu3`` and ``cswap`` are not hand derived. The
  transpiler preloads the exact gate bodies published in OpenQASM 2.0's
  ``qelib1.inc`` and expands them through the same machinery as any user defined
  gate, so nothing new enters the physical layer.

User defined gates
------------------

Any ``gate name(params) qargs { ... }`` block is registered before the circuit body
is processed, and calls to it are expanded recursively with actual qubits and
parameters substituted for the formal ones. Custom composite gates therefore
decompose all the way down to the native basis.

``opaque`` declarations are parsed but their calls are ignored, since there is no
body to expand.

Registers and indexing
======================

* **Multiple ``qreg`` declarations** map into one contiguous physical index space in
  declaration order. ``qreg q[2]; qreg anc[1];`` puts ``q[0]``, ``q[1]``, ``anc[0]``
  at physical indices 0, 1, 2.
* **Register broadcasts** work. ``h q;`` applies to every qubit in ``q``, and
  ``cx q, r;`` on two same size registers expands qubit by qubit.
* Multiple statements per line, statements and parameter lists spanning several
  lines, and both ``// line`` and ``/* block */`` comments are all fine.

Measurement and classical control
=================================

QubitWeave simulates the Hamiltonian, so there is no classical register to collapse into
mid circuit. These directives are deliberately ignored:

``measure``, ``barrier``, ``creg``, ``reset``, and ``if (...)``.

For ``if``, both the condition and the operation it wraps are dropped. A QASM file
gives the simulator no classical feedback path, and executing the guarded gate
unconditionally would quietly change what the circuit means.

Instead of measuring, read populations off the final state:

.. code-block:: python

    final = {k: v[-1] for k, v in results["populations"].items()}
    print(final["11"])

Mid-circuit measurement with feed-forward is implemented in the error-correction
engine. See :doc:`error_correction`.

Unsupported gates
=================

A mnemonic that is neither in the native basis, nor in the decomposition set, nor
defined by a ``gate { ... }`` block is skipped, with a one time warning per unknown
name. A reference to an undeclared register, or a broadcast size mismatch, warns and
skips that one instruction rather than aborting the parse.

Calibration and scheduling
==========================

``automate_calibrations`` sweeps what the circuit needs before anything is
simulated: an X and an H duration for each qubit, and a CZ and CX duration for each
declared coupling, in both directions. Results come from the calibration cache when
they are already there, so a second run of the same topology is fast.

``compile_schedule`` then walks the instruction list, keeping a running clock per
qubit. Single-qubit drives advance one clock. Two-qubit gates synchronise both clocks
to the later of the two and advance together. Virtual Z instructions advance nothing,
since they cost no time. The schedule is a list of drive dictionaries with
``start_time`` and ``end_time`` in ns, together with the total circuit depth.

.. note::

   The scheduler's CX for a fixed capacitive coupling drives the control at the
   target's frequency, which is the cross-resonance form. The calibrated
   microwave-activated CNOT described in :doc:`gates` is compiled by
   ``simulate_n_qubit_dynamics`` for direct two-qubit calls and is not yet used by
   this scheduling path.

Reading the logical circuit
===========================

``print_logical_circuit_diagram`` draws the circuit as written, before decomposition,
which is the useful view when checking that a file expresses the intended circuit:

.. code-block:: python

    from QubitWeave.core.workflow_engine import print_logical_circuit_diagram

    print_logical_circuit_diagram("bell_state.qasm", title="Bell state")

Both ``execute_workflow`` and the error correction workflows print it automatically.

Bundled circuits
================

``examples/qasm_files/`` contains ``bell_state.qasm``, ``deutsch.qasm``,
``toffoli.qasm`` and ``single_state.qasm``. They are deliberately small, since
simulating a wide circuit at the pulse level is far more expensive than a statevector
simulation of the same circuit.
