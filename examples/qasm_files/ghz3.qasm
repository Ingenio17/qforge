// Three-qubit GHZ state, fanned out from the middle qubit
OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
creg c[3];
h q[1];
cx q[1],q[0];
cx q[1],q[2];
measure q -> c;
