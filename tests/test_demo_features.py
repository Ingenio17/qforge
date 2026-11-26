"""
Tests for the features and fixes behind examples/demo: optimal control, randomized
benchmarking, the surface code, per-qubit noise, pi/2 calibration, solver accuracy and
the QASM decompositions.
"""

import itertools

import numpy as np
import pytest
import qutip as qt
import scqubits as scq
from scipy.linalg import expm

from QubitWeave.core.benchmarking import clifford_group, randomized_benchmarking
from QubitWeave.core.error_correction_engine import ErrorCorrectionEngine
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.pulse_optimizer import (
    Ladder,
    gate_metrics,
    gaussian_pulse,
    lab_frame_unitary,
    optimize_drag,
    optimize_grape,
    rotating_frame_unitary,
)
from QubitWeave.core.qec_benchmark import logical_error_polynomial, logical_error_rate
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.register_ops import pauli_string
from QubitWeave.core.stabilizer_codes import REPETITION_3, SHOR_9, STEANE_7, SURFACE_9
from QubitWeave.core.workflow_engine import QASMTranspiler


@pytest.fixture(scope="module")
def ladder():
    return Ladder.from_qubit(scq.Transmon(EJ=15.0, EC=0.3, ng=0.0, ncut=30), 4)


@pytest.fixture(scope="module")
def engines():
    q_eng = QubitEngine()
    q_eng.create_qubit("transmon", "df_t", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
    yield q_eng, GateEngine()
    q_eng.delete_qubit("df_t")


# --- optimal control -----------------------------------------------------------


def test_grape_beats_drag_and_survives_the_lab_frame(ladder):
    drag, grape = optimize_drag(ladder, 5.0), optimize_grape(ladder, 5.0)["pulse"]
    errors = [gate_metrics(lab_frame_unitary(ladder, p))["error"] for p in (drag, grape)]
    assert errors[1] < 1e-4
    assert errors[1] < errors[0] / 100


def test_propagators_are_unitary(ladder):
    pulse = gaussian_pulse(ladder, 12.0)
    for u in (rotating_frame_unitary(ladder, pulse), lab_frame_unitary(ladder, pulse)):
        assert np.allclose(u @ u.conj().T, np.eye(4), atol=1e-9)


# --- randomized benchmarking -----------------------------------------------------


def test_clifford_group_has_24_distinct_elements():
    assert len(clifford_group()) == 24


def test_rb_recovers_the_true_error(ladder):
    pulse = gaussian_pulse(ladder, 20.0, angle=np.pi / 2, drag=0.5)
    result = randomized_benchmarking(ladder, pulse, 50.0, 70.0, lengths=(1, 50, 200, 600, 1200))
    assert result["corrected_error"] == pytest.approx(result["true_error"], rel=0.08)


def test_impossible_coherence_times_are_refused(ladder, engines):
    with pytest.raises(ValueError, match="exceeds 2 T1"):
        randomized_benchmarking(ladder, gaussian_pulse(ladder, 20.0), 10.0, 30.0, lengths=(1, 2, 3))
    with pytest.raises(ValueError, match="exceeds 2 T1"):
        GateEngine._collapse_operators(["a"], [3], {"a": {"T1": 10.0, "T2": 30.0}})
    with pytest.raises(ValueError, match="not in the register"):
        GateEngine._collapse_operators(["a"], [3], {"b": {"T1": 10.0}})


# --- noise and solver accuracy ------------------------------------------------------


def test_t1_decay_is_exponential(engines):
    _, g_eng = engines
    result = g_eng.simulate_n_qubit_dynamics(
        ["df_t"], "Idle", 2000.0, [], [], "1", steps=5, noise={"df_t": {"T1": 2.0, "T2": 3.0}}
    )
    assert result["populations"]["1"][-1] == pytest.approx(np.exp(-1.0), abs=1e-4)


def test_t2_dephasing_rate(engines):
    _, g_eng = engines
    plus = (qt.basis(3, 0) + qt.basis(3, 1)).unit()
    plus.dims = [[3], [1]]
    result = g_eng.simulate_n_qubit_dynamics(
        ["df_t"], "Idle", 1000.0, [], [], plus, steps=3, noise={"df_t": {"T1": 5.0, "T2": 2.0}}
    )
    assert abs(result["final_state"].full()[0, 1]) == pytest.approx(0.5 * np.exp(-0.5), abs=1e-4)


def test_calibrated_half_pi_pulse_composes_to_the_identity(engines):
    """Opposite pi/2 pulses cancel only if the angle and the Stark phase are both right."""
    _, g_eng = engines
    duration, z_phase = g_eng.calibrate_half_pi("df_t", 0.025)
    drift, ops = g_eng._get_qubit_hamiltonian("df_t")
    f01 = float(np.real(drift.diag()[1] - drift.diag()[0])) / (2 * np.pi)
    drives = [
        {
            "target": 0,
            "type": "X",
            "amplitude": 0.025,
            "frequency": f01,
            "phase": g_eng._rotation_phase(ops["n"], axis, frame),
            "start_time": k * duration,
            "end_time": (k + 1) * duration,
        }
        for k, (axis, frame) in enumerate([(np.pi / 2, -z_phase), (-np.pi / 2, -3 * z_phase)])
    ]
    single = g_eng.simulate_n_qubit_dynamics(["df_t"], "c", duration, [], drives[:1], "0", steps=5)
    assert single["populations"]["1"][-1] == pytest.approx(0.5, abs=1e-4)
    both = g_eng.simulate_n_qubit_dynamics(["df_t"], "c", 2 * duration, [], drives, "0", steps=5)
    assert both["populations"]["0"][-1] > 0.9999


# --- error correction ------------------------------------------------------------------


@pytest.mark.parametrize("code", [STEANE_7, SHOR_9, SURFACE_9], ids=lambda c: c.name)
def test_every_single_qubit_pauli_is_corrected(engines, code):
    """
    Regression: syndrome circuits used to be regrouped by gate type, turning H-CNOT-H into
    H-H-CNOT, so X-type checks never fired and phase errors went uncorrected.
    """
    q_eng, g_eng = engines
    patterns = [[(q, p)] for q in range(code.num_data) for p in "XYZ"]
    rounds = ErrorCorrectionEngine(q_eng, g_eng).simulate_memory_rounds("df_t", code, patterns)
    assert min(r["fidelity"] for r in rounds) > 0.999


def test_a_logical_error_is_visible(engines):
    q_eng, g_eng = engines
    logical_x = [(q, "X") for q in SURFACE_9.logical_x_qubits]
    logical_z = [(q, "Z") for q in SURFACE_9.logical_z_qubits]
    ec = ErrorCorrectionEngine(q_eng, g_eng)
    rounds = ec.simulate_memory_rounds(
        "df_t", SURFACE_9, [logical_x, logical_z, logical_x + logical_z]
    )
    assert all(r["fidelity"] == pytest.approx(1 / 3, abs=1e-6) for r in rounds)
    assert all(sum(r["syndrome"]) == 0 for r in rounds)


def test_surface_code_generators_commute():
    for a in SURFACE_9.generators:
        for b in SURFACE_9.generators:
            if a.basis != b.basis:
                assert len(set(a.data_qubits) & set(b.data_qubits)) % 2 == 0


def test_surface_workflow_corrects_an_injected_error(engines, tmp_path):
    q_eng, g_eng = engines
    ec = ErrorCorrectionEngine(q_eng, g_eng)
    path = tmp_path / "x.qasm"
    path.write_text("OPENQASM 2.0;\nqreg q[1];\nx q[0];\n")
    result = ec.execute_surface9_workflow(["df_t"], str(path), inject_errors=[("df_t", 4, "Y")])
    assert result["logical_populations"]["1"] == pytest.approx(1.0, abs=1e-6)
    assert result["syndromes"]["df_t"] == (0, 1, 1, 0, 0, 1, 1, 0)


ENTRY_POINTS = [
    pytest.param(REPETITION_3, "execute_3q_repetition_workflow", "X", id="repetition"),
    pytest.param(STEANE_7, "execute_steane7_workflow", "XYZ", id="steane"),
    pytest.param(SHOR_9, "execute_shor9_workflow", "XYZ", id="shor"),
    pytest.param(SURFACE_9, "execute_surface9_workflow", "XYZ", id="surface"),
]


def _logical_pauli(array, axes, code, pauli):
    if pauli == "Y":
        return 1j * _logical_pauli(_logical_pauli(array, axes, code, "Z"), axes, code, "X")
    support = code.logical_x_qubits if pauli == "X" else code.logical_z_qubits
    physical = code.logical_x_pauli if pauli == "X" else code.logical_z_pauli
    return pauli_string(array, [axes[q] for q in support], physical)


def _assert_logical_state(result, code, names, ideal):
    """All 15 two-qubit logical Paulis, so phases count."""
    ket = result["final_physical_state"]
    array = ket.full().reshape(ket.dims[0])
    psi = np.array(ideal, dtype=complex) / np.linalg.norm(ideal)
    matrices = {"I": np.eye(2), "X": PX, "Y": PY, "Z": PZ}
    for pair in itertools.product("IXYZ", repeat=2):
        vector = array
        for name, pauli in zip(names, pair):
            if pauli != "I":
                vector = _logical_pauli(vector, result["data_axes"][name], code, pauli)
        expected = np.vdot(psi, np.kron(*(matrices[p] for p in pair)) @ psi)
        assert np.vdot(array, vector) == pytest.approx(expected, abs=1e-9)


@pytest.fixture
def logical_pair(engines):
    q_eng, g_eng = engines
    q_eng.create_qubit("transmon", "df_u", {"EJ": 14.0, "EC": 0.3, "truncated_dim": 2})
    yield ErrorCorrectionEngine(q_eng, g_eng), ["df_t", "df_u"]
    q_eng.delete_qubit("df_u")


@pytest.mark.parametrize("code, method, _paulis", ENTRY_POINTS)
@pytest.mark.parametrize(
    "body, ideal",
    [
        ("h q[0]; cx q[0],q[1];", [1, 0, 0, 1]),
        ("h q[1]; cx q[1],q[0];", [1, 0, 0, 1]),
        ("x q[0]; h q[0];", [1, 0, -1, 0]),
        ("h q[0]; z q[0]; h q[0];", [0, 0, 1, 0]),
        ("h q[0]; h q[1]; cz q[0],q[1]; h q[1];", [1, 0, 0, 1]),
    ],
    ids=["bell", "bell_reversed", "minus", "hzh", "cz"],
)
def test_encoded_state_is_right_in_every_basis(
    logical_pair, tmp_path, code, method, _paulis, body, ideal
):
    """
    Regression: Shor-encoded Bell circuits had perfect populations but were |00> - |11>,
    and the surface code refused H.
    """
    ec, names = logical_pair
    path = tmp_path / "c.qasm"
    path.write_text(f"OPENQASM 2.0;\nqreg q[2];\n{body}\n")
    _assert_logical_state(getattr(ec, method)(names, str(path)), code, names, ideal)


@pytest.mark.parametrize("code, method, paulis", ENTRY_POINTS)
def test_bell_state_survives_any_single_error(logical_pair, tmp_path, code, method, paulis):
    ec, names = logical_pair
    path = tmp_path / "c.qasm"
    path.write_text("OPENQASM 2.0;\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n")
    for seed, qubit in enumerate(range(0, code.num_data, 1 if code.num_data < 9 else 4)):
        for pauli in paulis:
            np.random.seed(seed)
            result = getattr(ec, method)(
                names, str(path), ec_every_n_gates=1, inject_errors=[("df_u", qubit, pauli)]
            )
            assert any(result["syndromes"]["df_u"])
            _assert_logical_state(result, code, names, [1, 0, 0, 1])


def test_exact_logical_error_rates():
    repetition = logical_error_polynomial(REPETITION_3, "bit_flip")
    assert logical_error_rate(repetition, 0.1)[0] == pytest.approx(3 * 0.01 - 2 * 0.001)
    for code in (STEANE_7, SHOR_9, SURFACE_9):
        assert logical_error_polynomial(code)["failures"][1] == 0  # distance 3


# --- QASM decompositions -------------------------------------------------------------------

PX = np.array([[0, 1], [1, 0]], dtype=complex)
PY = np.array([[0, -1j], [1j, 0]])
PZ = np.diag([1.0, -1.0]).astype(complex)
HAD = (PX + PZ) / np.sqrt(2)


def _controlled(u):
    return np.block([[np.eye(2), np.zeros((2, 2))], [np.zeros((2, 2)), u]])


def _u3(t, p, lam):
    return np.array(
        [
            [np.cos(t / 2), -np.exp(1j * lam) * np.sin(t / 2)],
            [np.exp(1j * p) * np.sin(t / 2), np.exp(1j * (p + lam)) * np.cos(t / 2)],
        ]
    )


def _matrix(statement, n):
    """Unitary of the transpiled statement, qubit 0 most significant."""
    source = f'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[{n}];\n{statement};'
    total = np.eye(2**n, dtype=complex)
    for gate in QASMTranspiler().parse_string(source):
        theta, target = gate.get("theta", np.pi), gate["target"]
        qubits = [target] if isinstance(target, int) else list(target)
        op = {
            "X": PX,
            "H": HAD,
            "RZ": np.diag([1, np.exp(1j * theta)]),
            "CX": _controlled(PX),
            "CZ": _controlled(PZ),
            "CP": np.diag([1, 1, 1, np.exp(1j * theta)]),
            "SWAP": np.eye(4)[[0, 2, 1, 3]],
        }[gate["type"]].astype(complex)
        k = len(qubits)
        tensor = total.reshape([2] * n + [2**n])
        tensor = np.tensordot(op.reshape([2] * (2 * k)), tensor, axes=(range(k, 2 * k), qubits))
        total = np.moveaxis(tensor, range(k), qubits).reshape(2**n, 2**n)
    return total


@pytest.mark.parametrize(
    "statement, expected",
    [
        ("rx(0.7) q[0]", expm(-0.35j * PX)),
        ("ry(0.7) q[0]", expm(-0.35j * PY)),  # regression: used to be ry(-0.7)
        ("y q[0]", PY),
        ("u2(0.7,1.1) q[0]", _u3(np.pi / 2, 0.7, 1.1)),
        ("u3(0.7,1.1,-0.4) q[0]", _u3(0.7, 1.1, -0.4)),
        ("u3((pi+1)/2,sin(pi/4),0) q[0]", _u3((np.pi + 1) / 2, np.sin(np.pi / 4), 0)),
        ("cy q[0],q[1]", _controlled(PY)),
        ("ch q[0],q[1]", _controlled(HAD)),
        ("crz(0.7) q[0],q[1]", _controlled(expm(-0.35j * PZ))),
        # regression: nested parentheses in a gate body used to drop instructions
        ("cu3(0.7,1.1,-0.4) q[0],q[1]", _controlled(_u3(0.7, 1.1, -0.4))),
        ("ccx q[0],q[1],q[2]", np.eye(8)[[0, 1, 2, 3, 4, 5, 7, 6]]),
        ("cswap q[0],q[1],q[2]", np.eye(8)[[0, 1, 2, 3, 4, 6, 5, 7]]),
    ],
)
def test_decomposition_matches_the_textbook_matrix(statement, expected):
    n = int(np.log2(len(expected)))
    overlap = abs(np.trace(expected.conj().T @ _matrix(statement, n))) / 2**n
    assert overlap == pytest.approx(1.0, abs=1e-9)
