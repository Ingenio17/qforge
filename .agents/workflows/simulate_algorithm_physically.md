---
description: Compiles and executes an idealized quantum algorithm on physical superconducting qubits.
---

# Physical Algorithm Simulation Workflow

This workflow guides the AI assistant to perform a full-stack compilation and simulation of an idealized, hardware-agnostic algorithm (e.g., Shor's, Grover's) on a simulated backend of physical QForge qubits.

## 📥 Required Inputs
When invoking this workflow, the user must provide:
1. **Target Algorithm**: The path to an ideal algorithmic script (e.g., `examples/06_shors_algorithm_simulation.py`).
2. **Qubit Choice**: The type of physical qubit (e.g., `transmon`, `fluxonium`) and its constituent parameters (like $E_J$, $E_C$, $E_L$).
3. **Coupling Architecture**: The topology and type of coupling (e.g., `tunable_coupler`, `capacitive`) to connect the physical qubits.

## 🛠️ Execution Steps

### Step 1: Algorithm Deconstruction
Parse the target algorithmic script to extract its mathematical requirements.
- Count the total number of qubits ($N$) required for the registers.
- Identify the sequence of discrete, idealized unitary gates (H, X, CNOT, CPHASE, SWAP, etc.) applied in the circuit in order.

### Step 2: Hardware Instantiation & Topology
- Instantiate $N$ physical qubits utilizing `QubitEngine.create_qubit` and the specified qubit parameters.
- Create a `couplings` array that wires these physical qubits together using the required coupling architecture, ensuring necessary connectivity for the algorithm's multi-qubit gates (e.g., a linear chain $0 \leftrightarrow 1 \leftrightarrow 2 \leftrightarrow 3$).

### Step 3: Global Gate Calibration
Ideal gates apply instantly. Physical gates require tailored microwave pulses. Use `GateEngine` to calibrate each unique gate identified in Step 1.
- **Single-Qubit Optimization**: Sweep pulse amplitude and duration for X, Y, and H gates to find the peak target population. Log these physical parameters.
- **Two-Qubit Optimization**: Sweep parameters for entangling gates across the chosen couplings to maximize interaction fidelity.
- **Output**: Compile a "Hardware Dictionary" mapping every idealized gate type to its calibrated physical duration (ns), drive amplitude, frequency, and coupling strength.

### Step 4: Pulse Schedule Compilation (Chronological Flattening)
Real physical simulations require a chronological sequence of drives, not a stacked list of matrices.
- Iterate through the algorithm's gate sequence.
- Maintain a running tally of `current_time` (ns).
- Convert each abstract gate into a time-dependent physical drive dictionary containing:
  - `start_time` and `end_time`
  - Amplitude, frequency, phase, and target qubit index (or coupling index).
- *Crucial Implementation Detail*: The compilation logic must wrap the `coeff` functions handled by `GateEngine._build_time_dependent_hamiltonian` inside a custom time-window condition (e.g., `if start <= t <= end: ... else: 0`) so that distinct pulses trigger exactly at the right time in the continuous simulation.

### Step 5: Full System Evolution
- Compute the total runtime $T$ of the entire pulse schedule.
- Invoke `GateEngine.simulate_n_qubit_dynamics` using the global `couplings` and scheduled `drives` over `duration=T`.
- Use a heavily refined `steps` parameter (e.g., 2000+) to capture smooth microwave dynamics across the long string of algorithms.

### Step 6: Result Decoding & Classical Post-Processing
- Extract the final raw state vector and computational `populations` at $t=T$.
- Pipe these physical state probabilities back into the algorithm's native classical post-processing logic (e.g., the Continued Fractions code at the bottom of the Shor's script).

### Step 7: Visual Analysis and Reporting
Conclude the workflow by generating a rich, detailed markdown and graphical report:
- **Time Evolution Plot**: Use `TerminalPlotter` to display a beautiful trajectory of the computational states over the entire compiled simulation window.
- **Fidelity Comparison**: Provide a table correlating the pristine ideal mathematical probabilities versus the measured physical outcome probabilities.
- **Leakage & Performance Analysis**: Report any accumulation of probability in non-computational states (e.g., population pooling in state $|2\rangle$ within a Transmon during fast pulsing), and detail the final total execution time overhead of the physical simulation vs the ideal matrix multiplication.
