===============
Getting Started
===============

qforge is designed to bridge the gap between abstract quantum algorithms and physical microwave physics. Whether you are a beginner prototyping a new transmon architecture or an advanced researcher scheduling hardware pulses, qforge provides both guided and scripted interfaces.

Interactive Mode
----------------

The easiest way to start exploring qforge without writing any code is through the Interactive Wizard. Powered by ``prompt_toolkit`` and ``rich``, this terminal UI guides you through creating hardware, auto-calibrating gates, and running full physical simulations step-by-step.

To launch the interactive wizard, run:

.. code-block:: bash

    $ qforge --interactive

Once inside, you will be presented with a dynamic menu offering several core workflows:

**1. Hardware Prototyping (Create, Analyze, Compare)**

* **Create a Qubit:** Select a predefined architecture (e.g., Transmon, Fluxonium) and the wizard will dynamically prompt you for the necessary circuit parameters (like :math:`E_J`, :math:`E_C`, and :math:`E_L`).
* **Analyze a Qubit:** Quickly generate energy spectrum plots, calculate anharmonicity, and estimate :math:`T_1`/:math:`T_2` coherence times based on realistic dielectric noise models.
* **Compare Qubits:** Select multiple defined qubits to generate side-by-side tables comparing their transition frequencies and coherence limits.

**2. Gate Calibration & Simulation**

* **Simulate Gates:** Test physical pulse drives for single-qubit gates (X, Y, Z, H) or two-qubit gates (CZ, CNOT). The wizard allows you to tweak pulse durations, swap between coupling architectures (capacitive, inductive, tunable coupler), and view beautiful ASCII/matplotlib plots of the resulting Rabi oscillations and state populations.
* **Analyze Multi-Qubit Gates:** A dedicated tool for benchmarking entangling gates. It runs multiple simulations across different coupling strengths and architectures, outputting a detailed terminal table comparing Target Population (Fidelity proxy) and geometric phase accumulation.

**3. The Full Physical Workflow (End-to-End)**

The interactive mode provides direct access to the ``PhysicalWorkflowEngine``. This wizard allows you to:

1. Select which of your defined qubits to use.
2. Define a custom hardware topology by drawing edges (couplings) between them.
3. Provide an abstract OpenQASM 2.0 file.
4. Watch as qforge automatically transpiles the circuit into your native basis, calibrates the :math:`\pi`-pulses, compiles a chronological microwave schedule, and simulates the entire algorithm natively in QuTiP.


Command Line Interface (CLI)
----------------------------

For users looking to integrate qforge into shell scripts, CI/CD pipelines, or batch processing, the CLI exposes all interactive features as direct commands. 

Here is a standard CLI workflow for creating and testing a two-qubit system:

**1. Create Physical Qubits**
Define the hardware parameters for your system. These are saved to your active qforge session.

.. code-block:: bash

    $ qforge qubit create transmon --name Q1 --EJ 15.0 --EC 0.3
    $ qforge qubit create transmon --name Q2 --EJ 14.2 --EC 0.28

**2. Analyze the Spectrum**
Verify the energy levels and transition frequencies of a newly created qubit.

.. code-block:: bash

    $ qforge qubit analyze --name Q1 --plot --coherence

**3. Simulate Single-Qubit Dynamics**
Apply an uncalibrated 40ns X-gate drive and observe the state evolution.

.. code-block:: bash

    $ qforge gate simulate --qubit Q1 --gate X --duration 40.0 --noise realistic

**4. Simulate Two-Qubit Entanglement**
Test a CZ gate using a tunable coupler architecture. The engine will automatically pulse the coupling strength and calculate the required flux detuning.

.. code-block:: bash

    $ qforge gate simulate-2q --control Q1 --target Q2 --gate CZ \
        --coupling-type tunable_coupler --strength 0.05 --duration 100.0

**5. Execute a Full QASM Algorithm**
Bypass manual simulations and let the Workflow Engine compile and simulate a quantum circuit file against your defined hardware.

.. code-block:: bash

    $ qforge workflow execute --qasm ./algorithms/bell_state.qasm \
        --qubits Q1,Q2 --topology "Q1,Q2,tunable_coupler,0.05"

Cache Management
----------------

Note: qforge utilizes a local JSON cache to save computationally expensive pulse calibrations (like optimal gate durations). If you alter a qubit's physical parameters, you may need to clear the cache to force a recalibration:

.. code-block:: bash

    $ qforge cache clear