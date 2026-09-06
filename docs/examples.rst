========
Examples
========

Thirteen worked scripts ship with qforge, under ``examples/``. They run in order of
difficulty, from a single qubit's spectrum to Grover's algorithm executed as physical
microwave pulses.

.. code-block:: bash

    $ qforge example list
    $ qforge example run --name 02_single_qubit_gates

Or from the wizard, "Run an example" under LEARN. Each script prints what it is doing
and plots its results in the terminal.

Qubits and single qubit gates
=============================

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Script
     - What it shows
   * - ``01_qubit_creation.py``
     - Qubits as physical multi-level circuits. Creates several, computes their
       spectra, extracts the physical operators a drive couples to.
   * - ``02_single_qubit_gates.py``
     - A real microwave pulse on one qubit. Sweeps the pulse duration to find the
       :math:`\pi` pulse that maximises :math:`|1\rangle`, and plots the sweep.

Two and three qubit gates
=========================

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Script
     - What it shows
   * - ``03_two_qubit_gates.py``
     - A CNOT through cross resonance or a tunable coupler, with the population
       evolution over the gate.
   * - ``04_three_qubit_gates.py``
     - A native three qubit continuous time interaction implementing a Toffoli.
   * - ``05_n_qubit_gates.py``
     - Generalized N qubit mapping. Strong static capacitive coupling showing
       excitation hopping, then a calibrated X drive applied to all four qubits at
       once.
   * - ``09_CNOT_drag_scheme_simulation.py``
     - The same CNOT with and without DRAG, so you can see what the correction buys
       you.
   * - ``11_pairwise_CNOT_simulation.py``
     - Pairwise CNOTs among three qubits, comparing fidelity and leakage across
       pairs.
   * - ``12_CNOT_max_distance.py``
     - Sweeps the target transmon's :math:`E_J` against a fixed control and plots how
       CNOT fidelity falls off with detuning.

Algorithms
==========

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Script
     - What it shows
   * - ``06_shors_algorithm_simulation.py``
     - Phase estimation standing in for Shor's period finding, with a 3 qubit phase
       register and a 1 qubit target. The encoded unitary is X, so
       :math:`X^2 = I` and the period is exactly 2.
   * - ``07_grovers_algorithm_simulation.py``
     - Grover's search over a 4 qubit space, marking :math:`|1010\rangle`, showing
       the amplitude grow cycle by cycle.
   * - ``08_physical_algorithm_workflow.py``
     - The full workflow. A hardware agnostic circuit compiled down to a
       chronologically scheduled sequence of microwave drives and coupler flux pulses
       on an instantiated topology.
   * - ``10_bell_state_simulation.py``
     - Bell state preparation through a physical H then CNOT sequence, with and
       without DRAG.
   * - ``13_deutsch.py``
     - The two qubit Deutsch algorithm on physical pulses through a tunable coupler,
       verifying that a balanced oracle drives the data qubit deterministically to
       :math:`|1\rangle`.

Other bundled files
===================

``examples/qasm_files/``
    ``bell_state.qasm``, ``deutsch.qasm``, ``toffoli.qasm`` and
    ``single_state.qasm``. Feed these to ``PhysicalWorkflowEngine.execute_workflow``
    or to any of the error correction workflows. See :doc:`qasm`.

``examples/device_files/``
    ``transmon.qdl``, a fully commented netlist showing the schematic, the design
    parameters in physical units, and what the analysis should produce. See
    :doc:`devices`.

Notebook walkthrough
====================

:doc:`tutorial` is an executable narrative version: build a transmon, calibrate a
gate analytically, simulate the dynamics, and plot it. Start there if you would
rather read prose than scripts.
