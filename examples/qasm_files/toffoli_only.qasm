// A bare Toffoli: q[0] and q[1] control, q[2] is the target.
// The initial state is supplied by the caller, so nothing prepares it here.
OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
ccx q[0],q[1],q[2];
