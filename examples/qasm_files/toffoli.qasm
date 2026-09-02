OPENQASM 2.0;
include "qelib1.inc";

qreg q[3];
creg c[3];

// --- STATE PREPARATION: |000> -> |111> ---
// Flip q[0] and q[1] to |1> so they can act as the Toffoli's controls
x q[0];
x q[1];

// --- EXECUTION ---
// Both controls are now |1>, so the Toffoli (CCX) flips the target q[2]
// Syntax: ccx control_1, control_2, target;
ccx q[0], q[1], q[2];

// --- MEASUREMENT ---
// Measure all qubits to verify the final state is |111>
measure q[0] -> c[0];
measure q[1] -> c[1];
measure q[2] -> c[2];
