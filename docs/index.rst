======
QubitWeave
======

QubitWeave is a terminal-native toolkit for simulating superconducting quantum hardware.
It takes the circuit parameters that define a physical device, builds the Hamiltonian
those parameters imply, drives it with pulses, and carries the result up through
calibrated gates, OpenQASM circuits and stabilizer error correction.

The distinction from a gate-level simulator is where the model starts. QubitWeave works
from :math:`E_J`, :math:`E_C`, :math:`E_L`, flux and offset charge, and keeps that
layer available at every stage above it. An X gate is a microwave pulse acting on a
charge operator. A CNOT is whichever pulse the available coupling supports. Leakage
out of the computational subspace is measurable because the higher levels are still
in the simulation.

The simulation chain
====================

.. code-block:: text

    circuit netlist, or preset qubit parameters (EJ, EC, EL, flux, ng)
        │
        ▼
    Hamiltonian and eigenstates                       scqubits
        │
        ▼
    microwave drives, flux pulses, couplings
        │
        ▼
    time evolution in a truncated multi-level space   QuTiP
        │
        ▼
    calibrated gates, fidelity, leakage, tomography
        │
        ▼
    OpenQASM circuits scheduled on a declared topology
        │
        ▼
    stabilizer error correction with feed-forward

Each stage is an ordinary Python object and can be used on its own.

Components
==========

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Page
     - Contents
   * - :doc:`qubits`
     - Transmon, fluxonium, flux and zero-pi models, plus qubits backed by a custom
       circuit. Spectra, anharmonicity, coherence estimates, parameter sweeps.
   * - :doc:`couplings`
     - Capacitive, inductive and tunable-coupler interaction Hamiltonians.
   * - :doc:`gates`
     - Single and two-qubit gates as pulses. Gaussian and DRAG envelopes, virtual Z,
       tunable-coupler CZ, the microwave-activated CNOT, calibration with a
       persistent cache, fidelity and tomography.
   * - :doc:`qasm`
     - An OpenQASM 2.0 parser with no external circuit dependency, compiling to a
       hardware-native basis and scheduling it as pulses.
   * - :doc:`error_correction`
     - CSS stabilizer codes declared as data. The 3-qubit repetition code, the
       7-qubit Steane code and the 9-qubit Shor code, with syndrome extraction,
       mid-circuit measurement and feed-forward correction.
   * - :doc:`devices`
     - A SPICE-style netlist language for custom circuits, quantized through
       scqubits. Spectrum, dispersion, coherence, and registration as a qubit.

Getting started
===============

``QubitWeave --interactive`` opens a guided wizard that covers most of the toolkit
without writing code. :doc:`quickstart` covers the same ground in Python.

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   installation
   quickstart
   interfaces
   examples
   tutorial

.. toctree::
   :maxdepth: 2
   :caption: Physics

   conventions
   qubits
   couplings
   gates
   qasm
   error_correction
   devices

.. toctree::
   :maxdepth: 2
   :caption: Reference

   cli
   api

Indices
=======

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
