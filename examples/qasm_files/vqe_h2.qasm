// One-parameter ansatz for H2: cos(THETA/2)|00> + sin(THETA/2)|11>.
// demo_09_vqe_h2.py substitutes the number for THETA before running it.
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
ry(THETA) q[0];
cx q[0],q[1];
