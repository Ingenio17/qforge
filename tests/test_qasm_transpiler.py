import numpy as np
import pytest

from qforge.core.workflow_engine import QASMTranspiler


def _types(instrs):
    return [i["type"] for i in instrs]


class TestBasicParsing:
    def test_bell_state(self):
        qasm = """
        OPENQASM 2.0;
        include "qelib1.inc";
        qreg q[2];
        creg c[2];
        h q[0];
        cx q[0], q[1];
        measure q[0] -> c[0];
        measure q[1] -> c[1];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["H", "CX"]
        assert instrs[0]["target"] == 0
        assert instrs[1]["target"] == (0, 1)

    def test_multiple_statements_on_one_line(self):
        qasm = 'OPENQASM 2.0; include "qelib1.inc"; qreg q[2]; h q[0]; cx q[0],q[1];'
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["H", "CX"]

    def test_statement_spanning_multiple_lines(self):
        qasm = """
        qreg q[1];
        u3(0.5,
           0.25,
           0.1) q[0];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        # u3 decomposes into rz, rx(pi/2)->h,rz,h, rz, rx(-pi/2)->h,rz,h, rz = 5 rz + 4 h
        assert _types(instrs) == ["RZ", "H", "RZ", "H", "RZ", "H", "RZ", "H", "RZ"]

    def test_block_and_line_comments_stripped(self):
        qasm = """
        /* header
           block comment */
        qreg q[1];
        x q[0]; // trailing comment
        // another comment
        x q[0];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["X", "X"]

    def test_ignored_directives_do_not_crash(self):
        qasm = """
        qreg q[2];
        creg c[2];
        barrier q;
        h q[0];
        if (c==1) x q[0];
        measure q[0] -> c[0];
        reset q[1];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        # Only the unconditional h survives; the classically-conditioned x is dropped entirely.
        assert _types(instrs) == ["H"]


class TestRegisterHandling:
    def test_multiple_qregs_get_contiguous_offsets(self):
        qasm = """
        qreg q[2];
        qreg anc[1];
        x q[0];
        x q[1];
        x anc[0];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        targets = [i["target"] for i in instrs]
        assert targets == [0, 1, 2]

    def test_register_broadcast_single_qubit_gate(self):
        qasm = """
        qreg q[3];
        h q;
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["H", "H", "H"]
        assert [i["target"] for i in instrs] == [0, 1, 2]

    def test_register_broadcast_two_qubit_gate(self):
        qasm = """
        qreg q[2];
        qreg r[2];
        cx q, r;
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["CX", "CX"]
        assert [i["target"] for i in instrs] == [(0, 2), (1, 3)]

    def test_broadcast_size_mismatch_is_skipped_not_crashed(self, capsys):
        qasm = """
        qreg q[2];
        qreg r[3];
        cx q, r;
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert instrs == []
        assert "mismatch" in capsys.readouterr().out

    def test_undeclared_register_is_skipped_not_crashed(self, capsys):
        qasm = """
        qreg q[1];
        x nope[0];
        x q[0];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["X"]
        assert "undeclared" in capsys.readouterr().out


class TestCustomGateDefinitions:
    def test_user_defined_gate_expands_recursively(self):
        qasm = """
        qreg q[2];
        gate bell a, b { h a; cx a,b; }
        bell q[0], q[1];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["H", "CX"]
        assert instrs[1]["target"] == (0, 1)

    def test_custom_gate_with_parameter(self):
        qasm = """
        qreg q[1];
        gate myrz(theta) a { rz(theta) a; }
        myrz(1.23) q[0];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["RZ"]
        assert instrs[0]["theta"] == pytest.approx(1.23)

    def test_qelib1_cy_decomposition(self):
        qasm = """
        qreg q[2];
        cy q[0], q[1];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        # sdg b; cx a,b; s b;  ->  RZ(-pi/2) on b, CX(a,b), RZ(pi/2) on b
        assert _types(instrs) == ["RZ", "CX", "RZ"]
        assert instrs[0]["target"] == 1
        assert instrs[0]["theta"] == pytest.approx(-np.pi / 2)
        assert instrs[1]["target"] == (0, 1)
        assert instrs[2]["target"] == 1
        assert instrs[2]["theta"] == pytest.approx(np.pi / 2)

    def test_qelib1_lambda_parameter_gate(self):
        # crz uses the formal parameter name "lambda", which is a reserved
        # Python keyword and must not break expression evaluation.
        qasm = """
        qreg q[2];
        crz(1.5707963267948966) q[0], q[1];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["RZ", "CX", "RZ", "CX"]
        assert instrs[0]["theta"] == pytest.approx(np.pi / 4)
        assert instrs[2]["theta"] == pytest.approx(-np.pi / 4)

    def test_cswap_uses_toffoli_decomposition(self):
        qasm = """
        qreg q[3];
        cswap q[0], q[1], q[2];
        """
        instrs = QASMTranspiler().parse_string(qasm)
        # cx c,b; ccx a,b,c; cx c,b;  ->  1 CX + 15 (ccx decomposition) + 1 CX
        assert len(instrs) == 17
        assert instrs[0]["type"] == "CX"
        assert instrs[-1]["type"] == "CX"


class TestUnchangedDecompositions:
    """Regression checks: the existing hand-derived decompositions must be untouched."""

    def test_toffoli_decomposition_length(self):
        qasm = "qreg q[3]; ccx q[0], q[1], q[2];"
        instrs = QASMTranspiler().parse_string(qasm)
        assert len(instrs) == 15

    def test_swap_and_cp_stay_native(self):
        qasm = "qreg q[2]; swap q[0], q[1]; cp(0.5) q[0], q[1];"
        instrs = QASMTranspiler().parse_string(qasm)
        assert _types(instrs) == ["SWAP", "CP"]
        assert instrs[1]["theta"] == pytest.approx(0.5)

    def test_unrecognized_gate_is_ignored_with_warning(self, capsys):
        qasm = "qreg q[1]; totally_unknown_gate q[0];"
        instrs = QASMTranspiler().parse_string(qasm)
        assert instrs == []
        assert "Unrecognized gate" in capsys.readouterr().out
