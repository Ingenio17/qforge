======================================
QForge Gate Engine: Technical Reference
======================================

.. contents:: Table of Contents
   :depth: 3
   :local:
   :backlinks: none

Introduction
============
The ``GateEngine`` module serves as the primary hardware-aware simulation backend for executing and calibrating quantum operations. It bridges physical superconducting circuit parameters (extracted via the ``QubitEngine``/scqubits) with open-system quantum dynamics (via QuTiP). 

Unlike purely algorithmic simulators, the ``GateEngine`` strictly operates in the physical layer. Gates are not simple unitary matrices; they are time-dependent microwave drives, flux biases, and tunable interactions acting on the physical Hamiltonian of the system.

Core System Hamiltonian Configuration
=====================================
The foundation of any gate simulation is the construction of the system's static and control Hamiltonians. 

Physical Operators vs. Harmonic Approximations
----------------------------------------------
The engine constructs the exact truncated eigenbasis for each circuit. For transmons and related circuits, driving the qubit physically means applying a voltage that couples to the charge operator $\hat{n}$ or a flux bias coupling to the phase operator $\hat{\phi}$.

The engine actively extracts these matrix elements natively from the eigenbasis:
    
.. code-block:: python

    n_mat = qubit.matrixelement_table('n_operator', evals_count=dim)
    phi_mat = qubit.matrixelement_table('phi_operator', evals_count=dim)

If a simplified or abstract qubit is passed that lacks these operators, it safely falls back to the harmonic oscillator approximation:
$\hat{n} \approx \frac{i}{\sqrt{2}}(\hat{a}^\dagger - \hat{a})$ and $\hat{\phi} \approx \frac{1}{\sqrt{2}}(\hat{a}^\dagger + \hat{a})$.

N-Qubit Static Hamiltonian
--------------------------
For multi-qubit systems, the engine recursively builds the $N$-dimensional Hilbert space tensor.
Static interactions rely on explicitly mapped topological definitions (``couplings``). 

The engine actively prevents unphysical coupling models. For instance, attempting an ``inductive`` coupling on a standard Transmon (which operates in the charge basis and lacks an explicit inductor $E_L \hat{\phi}^2$) throws a hard validation error, prompting the user to model a Fluxonium or ZeroPi circuit instead.

$$
\mathcal{H}_{sys} = \sum_{i} \mathcal{H}_{0,i} + \sum_{\langle i, j \rangle} g_{ij} \hat{O}_i \otimes \hat{O}_j
$$

Where $\hat{O}$ is $\hat{n}$ for capacitive coupling and $\hat{\phi}$ for inductive coupling.

Microwave Drives and Single Qubit Control
=========================================

Rotating Wave Approximation (RWA)
---------------------------------
To allow for stable numerical integration over nanosecond timescales, the static Hamiltonian is transformed into a frame rotating at the qubit's fundamental frequency $\omega_{01}$. 

$$
\mathcal{H}_{0, rot} = \text{diag}(0, 0, \alpha, \dots)
$$

Where $\alpha$ is the anharmonicity $(\omega_{12} - \omega_{01})$.

Control Mappings
----------------
Gates are mapped to specific physical drive operators:

* **X-Gate:** Capacitive drive mapping directly to $\hat{n}$.
* **Y-Gate:** 90-degree phase-shifted drive. The engine computes this by taking the full $\hat{n}$ matrix and forcing it to be perfectly anti-symmetric and imaginary: $i\text{tril}(\hat{n}) - i\text{triu}(\hat{n})$.
* **Z-Gate:** Stark shifts or flux tuning mapped to $\hat{\phi}$ or $\hat{n}^2$.
* **Hadamard:** Synthesized via a $Y(\pi/2)$-like control sequence to preserve algorithmic global phase.

Pulse Envelopes & DRAG Correction
---------------------------------
Pulses default to a 6-sigma Gaussian envelope:

$$
\Omega(t) = A \exp\left( -\frac{(t - \mu)^2}{2\sigma^2} \right)
$$

To suppress leakage into the $|2\rangle$ state for fast pulses, the engine implements Derivative Removal by Adiabatic Gate (DRAG) natively. 

$$
\Omega_{DRAG}(t) = -\frac{\lambda}{\alpha} \dot{\Omega}(t)
$$

The engine accurately computes the numerical integral of the envelope to calibrate the peak amplitude $A$ such that the total rotated area equals the target angle (e.g., $\pi$ or $\pi/2$).

Open Quantum Systems and Noise Modeling
=======================================
Real hardware is not perfectly isolated. The ``GateEngine`` incorporates environmental decoherence natively via QuTiP's master equation solver (``mesolve``).

When the ``noise_model="realistic"`` flag is active, the engine dynamically fetches the estimated coherence times from the ``QubitEngine``. Specifically, it calculates the relaxation rate ($\Gamma_1 = 1 / T_1$) based on the dominant dielectric loss channels of the modeled circuit. 

This relaxation is injected into the Lindblad master equation via collapse operators:

.. code-block:: python

    c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))

This allows the engine to accurately simulate fidelity drops due to finite coherence times during extended gate sequences.

Two-Qubit Gates and Tunable Couplers
====================================
The engine handles complex multi-qubit topologies, specifically supporting architectures with tunable coupling elements.

Capacitive vs. Tunable Architectures
------------------------------------
* **Capacitive (Cross-Resonance):** Implemented by driving the control qubit at the target qubit's frequency. The engine supports adding a static $\hat{n}_1 \otimes \hat{n}_2$ interaction and applying microwave drives.
* **Tunable Coupler:** The coupling strength $g$ is pulsed in time, usually via a fast flux bias on a dedicated coupler circuit. The engine simulates this using a $\sin^2$ envelope for the coupling operator.

The Compiled CNOT Sequence
--------------------------
Because a tunable coupler natively produces a controlled-phase (CZ) interaction, the engine automatically compiles logical ``CNOT`` requests into the physical hardware sequence: $H_{target} \rightarrow CZ \rightarrow H_{target}$. 

To achieve high-fidelity simulations, the engine:

1. Dynamically calculates the resonant flux detuning required to align the $|11\rangle$ and $|02\rangle$ states.
2. Applies a physical $X(-\pi/2)$ pulse (equivalent to $Y(\pi/2)$).
3. Applies a simultaneous Gaussian flux pulse to detune the target and a $\sin^2$ interaction pulse to the coupler.
4. Calculates the integrated **Stark Shift** phase accumulated during the flux pulse.
5. Applies a physical $X(+\pi/2)$ pulse with a phase offset compensating exactly for the Stark shift (Virtual Z correction).

QASM Parsing and Universal Gate Sets
====================================
To execute standard quantum algorithms, the ``GateEngine`` bridges the gap between algorithmic logical abstractions (like OpenQASM) and physical pulse schedules. 

Parsing Architecture
--------------------
When a QASM file is ingested, the parser translates the text-based quantum circuit into a Directed Acyclic Graph (DAG) or sequential Instruction Intermediate Representation (IR). 

Because the ``GateEngine`` simulates physics rather than matrix multiplication, it cannot directly execute arbitrary mathematical gates (like a $U_3$ or generic unitary). Instead, the parser decomposes every logical gate into a **Universal Gate Set** natively supported by the hardware's control electronics.

The Physical Universal Gate Set
-------------------------------
For superconducting architectures operating with microwave drives, the parser maps instructions to the following minimal physical set:

1. **Virtual Z ($R_Z$):** Executed entirely in software. Rather than applying a physical flux pulse (which risks decoherence and Stark shifts), $R_Z(\theta)$ gates are absorbed into the frame clock of the control electronics. Subsequent $X$ or $Y$ microwave pulses simply have their drive phases shifted by $\theta$.
2. **Physical X and SX ($\sqrt{X}$):** These are fixed-duration, calibrated microwave pulses mapping to $\pi$ and $\pi/2$ rotations.
3. **Entangling Gate (CZ or CX):** The natively calibrated two-qubit pulse generated by the tunable coupler or cross-resonance drive.

*Example Mapping:*
A standard QASM $H$ (Hadamard) gate is not a native physical pulse. The parser decomposes it as:
$$H \rightarrow R_Z(\pi/2) \cdot \sqrt{X} \cdot R_Z(\pi/2)$$
The engine then simulates the physical $\sqrt{X}$ microwave drive while applying the Virtual Z phase offsets to the drive phase parameters.

Calibration Engine and Cache Persistence
========================================
Physical gates require precise calibration of amplitude, duration, and detuning to maximize fidelity. Because open-system ``mesolve`` simulations are computationally heavy, repeating calibrations for the same circuit is highly inefficient.

The Sweeping Algorithm
----------------------
The ``calibrate_gate`` function operates in two phases to guarantee convergence without excessive simulation overhead:

1. **Analytical Initial Guess:** The engine uses lab-frame mathematical approximations to center the sweep window. For example, the duration of an X gate is estimated via:
   $$T_{est} = \frac{3 \theta}{\Omega_0 |\langle 0 | \hat{n} | 1 \rangle| \sqrt{2\pi}}$$
2. **Coarse Sweep:** Sweeps 20 points within a bounded window around the analytical guess.
3. **Fine Sweep:** Identifies the peak from the coarse sweep and zooms into a localized window, re-sweeping another 20 points for micro-optimization.

RAM/Disk Synchronization (The Caching Mechanism)
------------------------------------------------
To preserve calibrations across python sessions, the ``GateEngine`` utilizes a robust JSON-backed caching layer.

* **In-Memory Singleton:** A class-level dictionary ``GateEngine._calib_cache`` holds all known calibrations in RAM. To prevent redundant disk I/O, a class-level boolean ``_cache_loaded`` ensures the disk file is read strictly *once* upon the initialization of the very first ``GateEngine`` instance.
* **Tuple-to-String Determinism:** Calibrations are uniquely identified by a complex tuple of parameters (qubit names, gate types, drive kwargs). JSON strictly requires string keys. The engine safely circumvents this by casting the Python tuple to a deterministic string (``str(key_tuple)``) before saving.
* **AST Literal Evaluation:** When loading the JSON cache back into RAM, standard string parsing is insufficient to rebuild the tuple keys. The engine leverages Python's ``ast.literal_eval()`` to safely and exactly reconstruct the complex tuple objects from the string representations, ensuring cache hits instantly match incoming calibration requests.

Tomography and Fidelity Verification
====================================
The engine includes comprehensive tools for evaluating physical gate performance against ideal unitary targets.

State Tomography
----------------
Evaluates the output density matrix $\rho$ against the ideal target $\sigma$:

* **Fidelity:** $\mathcal{F} = \left( \text{Tr}\sqrt{\sqrt{\rho}\sigma\sqrt{\rho}} \right)^2$
* **Trace Distance:** Measures the distinguishability of the two states.
* **Purity:** $\text{Tr}(\rho^2)$ to track decoherence (T1/T2 effects).

Process Tomography (Choi Matrix)
--------------------------------
Generates the full process matrix by computing the exact unitary propagator over the time-dependent Hamiltonian (using up to $10^7$ integration steps for stiffness). It projects the high-dimensional physical space into the $2^N$ computational subspace, converts the unitary to a superoperator, and finally into a Choi matrix representation.

Average Gate Fidelity
---------------------
To avoid the overhead of running $4^N$ separate state simulations, the engine calculates the average gate fidelity directly from the subspace-projected propagator $U_{sim}$ and the ideal algorithm unitary $U_{ideal}$:

$$
\mathcal{F}_{avg} = \frac{|\text{Tr}(U_{ideal}^\dagger U_{sim})|^2 + d}{d(d+1)}
$$

Where $d = 2^N$. For tunable-coupler CNOTs, the engine automatically applies the local basis transformations (Hadamards) to the resulting propagator before tracing against the standard logical CNOT matrix.