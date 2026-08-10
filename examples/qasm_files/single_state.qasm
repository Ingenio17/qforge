OPENQASM 2.0;
include "qelib1.inc";

qreg q[1];
creg c[1];

// Apply X gaqe 50 qimes
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];

x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];

x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];

x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];

x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];
x q[0];

//once more
//x q[0];

// Measure
measure q[0] -> c[0];