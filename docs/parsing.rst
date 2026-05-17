====================================
OpenQASM 2.0 Compatibility & Parsing
====================================

.. contents:: Table of Contents
   :depth: 2
   :local:
   :backlinks: none

Overview
========
QForge includes a native, dependency-free parser for **OpenQASM 2.0** via the ``QASMTranspiler`` and ``PhysicalWorkflowEngine``. 

Unlike standard algorithmic simulators that simply multiply statevectors by ideal unitary matrices, QForge is a physical hardware simulator. When you pass a QASM file to QForge, the parser intercepts abstract logical instructions, decomposes them into a strict hardware-native basis, automatically calibrates the required physical parameters, and schedules them into a continuous microwave and flux pulse sequence.

The Physical Compilation Pipeline
=================================
Physical superconducting hardware cannot natively execute arbitrary mathematics. The QForge ``QASMTranspiler`` strictly funnels all quantum instructions into a highly restricted **Physical Universal Gate Set**: 

``{'x', 'h', 'rz', 'cx', 'cz', 'swap', 'cp'}``

1. **Virtual Z (``rz``, ``cp``):** Phase updates executed entirely in the software clock frame. They take zero simulation time and cause zero decoherence. The ``cp`` (controlled-phase) gate dynamically scales the duration of a ``cz`` interaction based on the requested angle fraction.
2. **Microwave Drives (``x``, ``h``):** Fixed-duration, calibrated microwave pulses mapping to $\pi$ and Hadamard rotations. The ``PhysicalWorkflowEngine`` automatically runs optimization sweeps to find the perfect duration and amplitude for these drives before execution.
3. **Entangling Gates (``cz``, ``cx``, ``swap``):** Time-dependent pulses applied to tunable couplers or via cross-resonance drives. 

Supported QASM Gates & Decompositions
=====================================
If a gate is not part of the strict native basis, QForge automatically recursively decomposes it.

Native Basis Gates
------------------
These map directly to the engine's pulse scheduler:

* ``x`` : Calibrated $\pi$ microwave pulse.
* ``h`` : Calibrated Hadamard microwave pulse.
* ``rz(theta)`` : Pure Virtual Z phase update (includes aliases ``p`` and ``u1``).
* ``cz`` : Calibrated tunable coupler or cross-resonance interaction pulse.
* ``cx`` / ``cnot`` : Compiled physically into a $X(-\pi/2) \rightarrow CZ \rightarrow X(+\pi/2)$ schedule.
* ``swap`` : Decomposed temporally into three alternating ``cx`` sequences.
* ``cp(theta)`` / ``cphase`` : Executed as a fractional ``cz`` pulse scaled by $|\theta| / \pi$.

Single-Qubit Decompositions
---------------------------
Standard QASM phase and rotation gates are mathematically decomposed into the native basis:

* **Pauli Z (``z``):** Decomposed into ``rz(pi)``.
* **Clifford Phase (``s``, ``sdg``, ``t``, ``tdg``):** Decomposed into pure Virtual ``rz`` operations ($\pi/2$, $-\pi/2$, $\pi/4$, $-\pi/4$).
* **Pauli Y (``y``):** Decomposed via Virtual Z frames: ``rz(pi/2) -> x -> rz(-pi/2)``.
* **Continuous X/Y Rotations (``rx``, ``ry``):** Since the engine natively calibrates ``h``, X-axis rotations are wrapped in Hadamards: 
  ``rx(theta)`` $\rightarrow$ ``h -> rz(theta) -> h``.
* **Universal Single Qubit (``u2``, ``u3``, ``u``):** Decomposed using standard Euler angle rotations, resulting in alternating ``rz`` updates and ``rx(pi/2)`` drives (which are recursively decomposed using the ``h`` logic above).

Multi-Qubit Decompositions
--------------------------
* **Toffoli (``ccx``):** The standard 3-qubit controlled-X is natively decomposed into the standard 6-CNOT breakdown involving ``h``, ``cx``, ``t``, and ``tdg`` gates, ensuring it can be executed on 2-qubit physical topologies.

Measurements & Classical Registers
==================================
Because QForge simulates physics at the Hamiltonian level via QuTiP's ``mesolve``, wave-functions are not "collapsed" mid-circuit into classical registers. 

The ``QASMTranspiler`` explicitly **ignores** the following OpenQASM directives:
* ``measure``
* ``barrier``
* ``creg`` and ``qreg`` allocations

Instead of writing to a classical bit, QForge computes the continuous density matrix throughout the entire algorithm. At the end of the ``execute_workflow`` simulation, users can extract the exact population probabilities (e.g., the probability of measuring $|11\rangle$) directly from the output states.

Unsupported Features
====================
Any instruction or custom ``opaque`` gate definition that does not match the transpiler's regular expressions or internal decomposition dictionary will be silently ignored by the physics engine. 

Example QASM Workflow
=====================
The ``PhysicalWorkflowEngine`` abstracts away the heavy lifting of calibrating and scheduling.

.. code-block:: python

    from qforge.compiler.workflow_engine import PhysicalWorkflowEngine
    from qforge.core.qubit_engine import QubitEngine
    from qforge.core.gate_engine import GateEngine

    # Initialize backend engines
    q_eng = QubitEngine()
    g_eng = GateEngine()
    workflow = PhysicalWorkflowEngine(q_eng, g_eng)

    # Define your hardware topology
    qubit_names = ["Transmon_0", "Transmon_1"]
    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.050}]

    # Execute! This will transpile the QASM, auto-calibrate the X, H, CZ, and CX 
    # pulses, schedule them chronologically, and simulate the master equation.
    results = workflow.execute_workflow(qubit_names, couplings, "my_algorithm.qasm")

    # Access the final physical state
    final_density_matrix = results["final_state"]