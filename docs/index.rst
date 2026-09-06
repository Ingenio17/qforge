======
qforge
======

qforge is a terminal native toolkit for simulating superconducting quantum hardware.
It starts from the circuit parameters you would hand a fabricator, builds the
Hamiltonian those parameters imply, drives it with real pulses, and carries the
result up through calibrated gates, QASM circuits and error correction.

Most quantum simulators start at the gate and multiply unitaries. qforge starts one
layer below, at :math:`E_J`, :math:`E_C`, :math:`E_L` and flux, and never throws
that layer away. A logical X is a microwave pulse on a charge operator. A CNOT is a
flux pulse through an avoided crossing. Leakage into :math:`|2\rangle` is something
you can measure, because the third level is still there.

The chain
=========

.. code-block:: text

    circuit netlist  or  qubit parameters (EJ, EC, EL, flux, ng)
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
    OpenQASM circuits scheduled on a real topology
        │
        ▼
    stabilizer error correction with feed-forward

Every stage is a plain Python object you can inspect, and every stage has a CLI
command behind it.

What is in the box
==================

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Area
     - What it does
   * - :doc:`qubits`
     - Transmon, fluxonium, flux and zero-pi models. Spectra, anharmonicity,
       coherence estimates, parameter sweeps.
   * - :doc:`gates`
     - Physical single and two qubit gates. Gaussian and DRAG pulses, virtual Z,
       tunable coupler CZ, calibration with a persistent cache, fidelity and
       tomography.
   * - :doc:`couplings`
     - Capacitive, inductive and tunable coupler interaction Hamiltonians.
   * - :doc:`qasm`
     - A dependency free OpenQASM 2.0 parser that compiles down to a hardware
       native basis and schedules it as pulses.
   * - :doc:`error_correction`
     - Declarative CSS stabilizer codes. The 3 qubit repetition code, the 7 qubit
       Steane code and the 9 qubit Shor code, with real syndrome extraction and
       feed-forward correction.
   * - :doc:`devices`
     - Write your own circuit as a SPICE style netlist, quantize it, and get the
       spectrum, dispersion and coherence of whatever you drew.

Where to start
==============

If you have never used qforge, install it and run ``qforge --interactive``. The
wizard covers most of the toolkit without writing any code. If you would rather
read first, :doc:`quickstart` shows the same ground in Python.

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
