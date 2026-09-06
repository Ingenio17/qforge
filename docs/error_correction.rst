================
Error correction
================

qforge runs stabilizer error correction as physics, not bookkeeping. Logical qubits
are expanded into real physical qubits, syndromes are extracted with actual CNOT
drives onto ancillas, those ancillas are projectively measured so the wavefunction
genuinely collapses, and the correction is fed forward as a Pauli applied to the
data.

Three codes ship today:

.. list-table::
   :header-rows: 1
   :widths: 26 12 12 12 38

   * - Code
     - Data
     - Ancilla
     - Total
     - Corrects
   * - 3 qubit repetition
     - 3
     - 2
     - 5
     - Any single bit flip.
   * - 7 qubit Steane
     - 7
     - 6
     - 13
     - Any single qubit Pauli error.
   * - 9 qubit Shor
     - 9
     - 8
     - 17
     - Any single qubit error.

Counts are per logical qubit.

.. code-block:: python

    from qforge.core.error_correction_engine import ErrorCorrectionEngine

    ec = ErrorCorrectionEngine(qubit_engine, gate_engine)

    result = ec.execute_steane7_workflow(
        logical_names=["Q1"],
        qasm_path="circuit.qasm",
        coupling_type="capacitive",
        coupling_strength=0.010,
        ec_every_n_gates=0,
    )

    print(result["logical_populations"])   # decoded, per logical basis state
    print(result["final_physical_state"])  # the raw physical state vector

The three entry points are ``execute_3q_repetition_workflow``,
``execute_steane7_workflow`` and ``execute_shor9_workflow``. All take the same
arguments.

The workflow
============

.. code-block:: text

    logical QASM circuit
        │
        ▼  parse and draw the logical circuit
    logical to physical mapping        Q1 -> Q1_D0..Q1_D6, Q1_A0..Q1_A5
        │
        ▼  register physical clones, build couplings, calibrate once
    prepare |0>_L via the code's encoding circuit
        │
        ▼  for each logical instruction
    transversal physical drives
        │
        ▼  every N gates, or once at the end
    syndrome extraction, generator by generator
        │
        ▼
    ancilla measurement and wavefunction collapse
        │
        ▼
    feed-forward Pauli correction, then ancilla reset
        │
        ▼
    decode by projective measurement of the logical Z operator

Physical qubits are clones of the logical qubit: same scqubits type, same
parameters. They are registered while the workflow runs and deleted in a ``finally``
block afterwards, so they never linger in your qubit list.

Stabilizer codes are data
=========================

The engine hard codes nothing about any particular code. Everything it needs lives in
a ``StabilizerCode`` in ``qforge/core/stabilizer_codes.py``:

.. code-block:: python

    from qforge.core.stabilizer_codes import (
        StabilizerCode, StabilizerGenerator, EncodingStep,
        REPETITION_3, STEANE_7, SHOR_9,
    )

    REPETITION_3.generators
    # (StabilizerGenerator(basis='Z', data_qubits=(0, 1), ancilla=0),
    #  StabilizerGenerator(basis='Z', data_qubits=(1, 2), ancilla=1))

A specification carries:

* **generators**, one Pauli string each, with the ancilla that measures it,
* **syndrome_to_correction**, mapping a syndrome bit tuple to a list of
  ``(data_qubit, pauli)`` corrections,
* **logical X and Z operators**, as a Pauli type plus the data qubits they act on,
* **encoding_circuit**, the gate sequence that turns :math:`|00\ldots0\rangle` into
  the codeword :math:`|0\rangle_L`.

Adding a fourth CSS code means writing one of these. It does not mean touching
``ErrorCorrectionEngine``.

The CSS restriction
-------------------

Every generator must be uniformly X-type or Z-type across the qubits it touches.
No mixed generators, no bare Y. That is the Calderbank-Shor-Steane restriction, and
it is what makes one generic syndrome extraction circuit work for every code the
engine supports.

Corrections are lists rather than single tuples because independent generators can
diagnose independent errors that need fixing at the same time. A Shor code syndrome
can call for an X correction from an inner block and a Z correction from the outer
pair simultaneously.

Syndrome extraction
===================

Generators are measured one at a time, never as one combined operation:

* **Z-type generator**: CNOT from each participating data qubit onto the ancilla.
* **X-type generator**: H on the ancilla, CNOT from the ancilla onto each data
  qubit, H on the ancilla again. A plain Z-basis readout then gives the stabilizer
  eigenvalue either way.

Then that one ancilla is measured, the wavefunction collapses, and the bit is
recorded. Once every generator has reported, the full syndrome is looked up and each
correction applied, and any ancilla left in :math:`|1\rangle` is reset with an X.

Measuring generators one at a time is not an approximation. A valid stabilizer code's
generators mutually commute, so sequential measurement gives exactly the same joint
outcome distribution and the same post-measurement state as a joint measurement
would. The reason to do it this way is size: each simulated subsystem is bounded by
the largest generator weight, up to 7 qubits for Shor, instead of the code's full
qubit count.

Decoding
========

Decoding is a joint projective measurement of the declared logical Z operator, with

.. math::

    P(\text{logical} = 0) = \frac{1 + \langle \bar{Z} \rangle}{2}

It is joint across all logical qubits, so entanglement between logical qubits
survives into the returned populations.

This matters, and a simpler reading of the data qubit populations would be wrong in
general. The repetition code's codewords happen to be computational basis states, so
majority voting the raw populations gives the same answer there. It does not for the
Shor code: :math:`|0\rangle_L` and :math:`|1\rangle_L` touch exactly the same basis
strings with exactly the same probabilities and differ only in relative phase. A
population reading of the diagonal cannot see that. A logical Z measurement can.

The codes
=========

3 qubit repetition
------------------

Data D0, D1, D2 with ancillas measuring :math:`Z_0 Z_1` and :math:`Z_1 Z_2`.

.. code-block:: text

    (A0=0, A1=0)  no error
    (A0=1, A1=0)  X on D0
    (A0=1, A1=1)  X on D1
    (A0=0, A1=1)  X on D2

Bit flips only. Its :math:`|0\rangle_L` is just :math:`|000\rangle`, so the encoding
circuit is a formal no-op, declared anyway for uniformity.

7 qubit Steane
--------------

The CSS construction from the classical [7,4,3] Hamming code and its dual. Both the
X-type and Z-type generators come from the same 3 by 7 parity check matrix:

.. code-block:: text

    H = [ 1 0 1 0 1 0 1 ]   qubits {0,2,4,6}
        [ 0 1 1 0 0 1 1 ]   qubits {1,2,5,6}
        [ 0 0 0 1 1 1 1 ]   qubits {3,4,5,6}

Column :math:`j` is the binary representation of :math:`j+1`, so decoding needs no
lookup search: read the three Z-type syndrome bits as a binary number and you have
the 1-indexed qubit that suffered a bit flip. The three X-type bits do the same for
phase flips, and both corrections can apply together.

Steane uses the obvious logical operators, transversal X for :math:`\bar{X}` and
transversal Z for :math:`\bar{Z}`. It also has a valid transversal Hadamard, and
transversal CNOT and CZ between two Steane blocks implement the logical gates
directly with no direction reversal or basis mismatch. That is why the Steane path
reuses the fully generic transversal gate machinery unchanged.

9 qubit Shor
------------

The 3 qubit phase flip code concatenated with the 3 qubit bit flip code: three blocks
of three.

.. math::

    |0\rangle_L = \frac{(|000\rangle + |111\rangle)^{\otimes 3}}{2\sqrt{2}},
    \qquad
    |1\rangle_L = \frac{(|000\rangle - |111\rangle)^{\otimes 3}}{2\sqrt{2}}

Eight generators: six Z-type inner ones, two per block, catching bit flips exactly
like the repetition code does within each block; and two X-type outer ones,
:math:`X_0 \ldots X_5` and :math:`X_3 \ldots X_8`, comparing adjacent blocks to
catch phase flips.

A phase flip can only be localized to a block, not to a qubit within it, because
:math:`Z_i(|000\rangle + |111\rangle) = |000\rangle - |111\rangle` regardless of
which :math:`i` was hit. It is corrected by applying Z to any one representative
qubit of the affected block.

Its logical operators are not the obvious ones:

.. code-block:: text

    Z_bar = X0 X1 X2     transversal X on any one block
    X_bar = Z0 Z3 Z6     one Z per block

This is a textbook property of the concatenated construction, not a bug. :math:`X_0
X_1 X_2` fixes :math:`(|000\rangle + |111\rangle)` and negates
:math:`(|000\rangle - |111\rangle)`, so it has eigenvalue +1 on :math:`|0\rangle_L`
and -1 on :math:`|1\rangle_L`, which is the logical Z convention.

Running syndrome cycles
=======================

``ec_every_n_gates`` controls when syndromes run. The default is 0, meaning one
final pass and nothing mid-circuit.

Do not turn it on casually for circuits containing Hadamards. Stabilizer measurement
projects the state, and measuring Z-type stabilizers on a qubit sitting in an X-basis
superposition collapses it. That is correct physics, and it will also destroy the
superposition your algorithm depends on. Use ``ec_every_n_gates=0`` unless you
specifically want to study repeated rounds.

Memory
======

The state vector spans every physical qubit in the workflow at once, so its size is
:math:`2^{\text{total physical qubits}}`.

One Steane encoded logical qubit is 13 qubits, one Shor encoded logical qubit is 17.
Two Shor blocks is 34, which no dense state vector is going to fit.

For that reason the Steane and Shor paths reclaim each ancilla's dimension the moment
it has been measured. This is exact, not an approximation: a measured and reset
ancilla is in a known product state, so its factor can be dropped. The live Hilbert
space stays bounded by the number of data qubits plus at most one borrowed ancilla,
whatever the round count. The repetition code path keeps the simpler shared state
vector, which is fine at 5 qubits per block.

Gates are simulated on small per-generator or per-qubit-pair subsystems and embedded
back into the full register, so no single dense operator ever spans a whole code
block. Where a gate is an ideal logical Clifford that cannot populate a leakage
level, the engine evaluates it at dimension 2 and by matrix exponential of the
effective rotating frame Hamiltonian, :math:`U = \exp(-iH_{\mathrm{eff}}T)`, rather
than an ODE solve resolving GHz carriers that carry no information about the gate.

Writing a new code
==================

1. Enumerate the generators as ``StabilizerGenerator(basis, data_qubits, ancilla)``,
   one ancilla each. All generators must mutually commute.
2. Build ``syndrome_to_correction``, mapping each non-trivial syndrome tuple, ordered
   by ancilla index, to a list of ``(data_qubit, pauli)`` corrections. An absent
   syndrome means no correction.
3. Declare which data qubits and Pauli type realize logical X and logical Z.
4. Write the ``encoding_circuit`` that prepares :math:`|0\rangle_L` from
   :math:`|00\ldots0\rangle`, out of ``H`` and ``ICX`` steps. This is not optional
   for any code whose :math:`|0\rangle_L` is not itself a basis state, which is
   essentially every code except the repetition one.
5. Pass it in:

   .. code-block:: python

       ec.execute_stabilizer_workflow(
           logical_names=["Q1"],
           qasm_path="circuit.qasm",
           code=MY_CODE,
       )

No decode callback is needed. The generic decoder measures whatever logical Z
operator you declared.
