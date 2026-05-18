==================================
Welcome to qforge
==================================

**qforge** is a comprehensive, lightweight quantum simulation toolkit that bridges the gap between abstract quantum logic and physical hardware design. 

What is qforge?
---------------
Designed for students, researchers, engineers, and quantum enthusiasts, qforge moves beyond idealized statevectors to show you how quantum circuits actually execute at the lowest physical layers. qforge provides a rigorous, physics-first approach to quantum software.

Key Features
------------
* **Hardware-Realistic Simulation:** Simulate the actual physical Hamiltonians and time dependent dynamics of quantum gates including DRAG corrected microwave pulses, Stark shifts, and tunable coupler interactions, rather than just multiplying ideal unitary matrices.
* **Flexible Circuit Construction:** Build custom quantum circuits dynamically on the fly using our Python API, or directly parse and compile industry-standard **OpenQASM 2.0** files with zero heavy external dependencies.
* **Diverse Qubit Modalities:** Build circuits with multiple types of superconducting qubits (such as Transmons, Tunable Transmons, and Fluxoniums), each with fully customizable physical parameters and coherence profiles.

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   getting_started
   examples
   terminalplay

.. toctree::
   :maxdepth: 2
   :caption: Architecture & Reference  

   info
   parsing
   couplings
   api


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`