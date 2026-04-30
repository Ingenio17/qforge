OPENQASM 2.0;
include "qelib1.inc";

qreg q[3];
creg c[3];

// --- INITIALIZATION ---
// Set both control qubits to |1> to activate the Toffoli logic
x q[0];  // Control 1
x q[1];  // Control 2
// q[2] (Target) is left in its default |0> state

// --- EXECUTION ---
// Apply the Toffoli (CCX) gate
// Syntax: ccx control_1, control_2, target;
ccx q[0], q[1], q[2];

// --- MEASUREMENT ---
// Measure all qubits to verify the target flipped
measure q[0] -> c[0];
measure q[1] -> c[1];
measure q[2] -> c[2];