"""
Every fast path against the slow, obvious calculation it replaces.

In-place register kernels against full operators, the segmented spline solver against
plain QuTiP, peak climbing against an exhaustive sweep, and the caches against the
changes that must invalidate them.
"""

import json
import os
import subprocess
import sys

import numpy as np
import pytest
import qutip as qt

from QubitWeave.core.error_correction_engine import (
    ErrorCorrectionEngine,
    _build_ideal_cz_operator,
    _logical_parities,
    _pauli_dim,
    _tensor_op_at,
    estimate_state_size,
)
from QubitWeave.core.gate_engine import GateEngine, _climb_to_peak, _physics_key
from QubitWeave.core.pulse_solver import PulseCoefficient, evolve
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.register_ops import (
    apply_cx,
    apply_cz,
    apply_hadamard,
    apply_matrix,
    apply_pauli,
    apply_rz,
)
from QubitWeave.core.stabilizer_codes import REPETITION_3, SHOR_9, STEANE_7, SURFACE_9

DIMS = [3, 2, 4, 2]  # leakage levels on two of the four qubits


@pytest.fixture
def ket():
    rng = np.random.default_rng(0)
    size = int(np.prod(DIMS))
    vector = rng.normal(size=size) + 1j * rng.normal(size=size)
    return vector / np.linalg.norm(vector)


@pytest.fixture(scope="module")
def engines():
    q_eng = QubitEngine()
    q_eng.create_qubit("transmon", "fp_t", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
    yield q_eng, GateEngine()
    q_eng.delete_qubit("fp_t")


# --- register kernels -----------------------------------------------------------------


def _check(ket, kernel, operator):
    array = ket.reshape(DIMS).copy()
    kernel(array)
    assert np.allclose(array.ravel(), operator.full() @ ket, atol=1e-13)


@pytest.mark.parametrize("control, target", [(0, 1), (2, 0), (3, 2)])
def test_cx_kernel(engines, ket, control, target):
    operator = engines[1]._build_ideal_cx_operator(DIMS, control, target)
    _check(ket, lambda a: apply_cx(a, control, target), operator)


@pytest.mark.parametrize("a_idx, b_idx", [(0, 2), (3, 1)])
def test_cz_kernel(ket, a_idx, b_idx):
    _check(ket, lambda a: apply_cz(a, a_idx, b_idx), _build_ideal_cz_operator(DIMS, a_idx, b_idx))


@pytest.mark.parametrize("pauli", ["X", "Z"])
@pytest.mark.parametrize("axis", range(4))
def test_pauli_kernel(ket, axis, pauli):
    operator = _tensor_op_at(_pauli_dim(pauli, DIMS[axis]), axis, DIMS)
    _check(ket, lambda a: apply_pauli(a, axis, pauli), operator)


def test_y_is_i_x_z(ket):
    array, other = ket.reshape(DIMS).copy(), ket.reshape(DIMS).copy()
    apply_pauli(array, 2, "Y")
    apply_pauli(other, 2, "Z")
    apply_pauli(other, 2, "X")
    levels = [slice(None)] * 4
    levels[2] = slice(0, 2)  # leakage levels carry no phase
    assert np.allclose(array[tuple(levels)], 1j * other[tuple(levels)])


@pytest.mark.parametrize("axis", range(4))
def test_hadamard_kernel_is_unitary_and_keeps_leakage(ket, axis):
    local = np.eye(DIMS[axis], dtype=complex)
    local[:2, :2] = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
    _check(ket, lambda a: apply_hadamard(a, axis), _tensor_op_at(qt.Qobj(local), axis, DIMS))


@pytest.mark.parametrize("pauli", ["X", "Z"])
def test_rz_kernel(ket, pauli):
    local = np.exp(0.7j) * (np.eye(4) - _pauli_dim(pauli, 4).full()) / 2
    local = local + (np.eye(4) + _pauli_dim(pauli, 4).full()) / 2
    operator = _tensor_op_at(qt.Qobj(local), 2, DIMS)
    _check(ket, lambda a: apply_rz(a, 2, 0.7, pauli), operator)


@pytest.mark.parametrize("axes", [[0], [2, 0], [1, 3], [3, 2, 1]])
def test_matrix_kernel_matches_permuted_tensor(ket, axes):
    rng = np.random.default_rng(3)
    local = [DIMS[a] for a in axes]
    k = int(np.prod(local))
    matrix, _ = np.linalg.qr(rng.normal(size=(k, k)) + 1j * rng.normal(size=(k, k)))
    rest = [i for i in range(4) if i not in axes]
    order = axes + rest
    full = qt.tensor(qt.Qobj(matrix, dims=[local, local]), *[qt.qeye(DIMS[i]) for i in rest])
    full = full.permute([order.index(i) for i in range(4)])
    got = apply_matrix(ket.reshape(DIMS), matrix, axes).ravel()
    assert np.allclose(got, full.full() @ ket, atol=1e-13)


@pytest.mark.parametrize("pauli", ["X", "Z"])
def test_logical_parities_match_projectors(ket, pauli):
    state = qt.Qobj(ket.reshape(-1, 1), dims=[DIMS, [1] * 4])
    groups = [[0, 1], [2, 3]]
    strings = []
    for group in groups:
        op = qt.tensor([qt.qeye(d) for d in DIMS])
        for axis in group:
            op = op * _tensor_op_at(_pauli_dim(pauli, DIMS[axis]), axis, DIMS)
        strings.append(op)
    joint = _logical_parities(state, DIMS, groups, pauli)
    identity = qt.tensor([qt.qeye(d) for d in DIMS])
    for a in (0, 1):
        for b in (0, 1):
            projector = (
                (identity + (-1) ** a * strings[0]) * (identity + (-1) ** b * strings[1]) / 4
            )
            assert joint[a, b] == pytest.approx(qt.expect(projector, state), abs=1e-12)


def test_state_size_counts_what_is_actually_held():
    for code in (STEANE_7, SHOR_9, SURFACE_9):
        # A two-qubit logical circuit fits in a few megabytes: one live ancilla, not all.
        assert estimate_state_size(code, 2)[0] == 2 ** (2 * code.num_data + 1)
        assert estimate_state_size(code, 2)[1] < 10 * 2**20
    assert estimate_state_size(REPETITION_3, 1, 3)[0] == 3**3 * 2**2


def test_three_logical_steane_qubits_are_affordable(engines, tmp_path):
    q_eng, g_eng = engines
    names = ["fp_l0", "fp_l1", "fp_l2"]
    for name in names:
        q_eng.create_qubit("transmon", name, {"EJ": 15.0, "EC": 0.3, "truncated_dim": 2})
    path = tmp_path / "ghz.qasm"
    path.write_text("OPENQASM 2.0;\nqreg q[3];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];\n")
    try:
        result = ErrorCorrectionEngine(q_eng, g_eng).execute_steane7_workflow(names, str(path))
    finally:
        for name in names:
            q_eng.delete_qubit(name)
    assert result["logical_populations"] == pytest.approx({"000": 0.5, "111": 0.5}, abs=1e-9)


# --- solver -----------------------------------------------------------------------------


def _pulse(start, end, frequency, amplitude):
    middle, sigma = (start + end) / 2, (end - start) / 6
    return PulseCoefficient(
        lambda t: amplitude
        * np.exp(-0.5 * ((t - middle) / sigma) ** 2)
        * np.cos(2 * np.pi * frequency * t),
        start,
        end,
        frequency=frequency + 1.0 / sigma,
    )


@pytest.fixture(scope="module")
def problem():
    h0 = qt.Qobj(np.diag(2 * np.pi * np.array([-3.0, 2.0, 6.7])))
    drive = qt.Qobj(np.array([[0, 1, 0], [1, 0, 1.4], [0, 1.4, 0]], dtype=complex))
    # An idle gap, overlapping windows, and a pulse running past the end.
    terms = [
        [drive, _pulse(1.0, 9.0, 5.0, 0.8)],
        [drive, _pulse(7.0, 16.0, 4.7, 0.5)],
        [drive, _pulse(21.0, 40.0, 5.0, 0.6)],
    ]
    return [h0, *terms], np.linspace(0, 30, 41)


TIGHT = {"method": "vern9", "atol": 1e-13, "rtol": 1e-11, "nsteps": 10**7, "max_step": 0.02}
FAST = {"method": "vern7", "atol": 1e-10, "rtol": 1e-8, "nsteps": 10**7}


def test_evolve_matches_plain_qutip(problem):
    hamiltonian, times = problem
    initial = (qt.basis(3, 0) + 1j * qt.basis(3, 1)).unit()
    reference = qt.sesolve(
        hamiltonian, initial, times, options={**TIGHT, "progress_bar": ""}
    ).states
    states = evolve(hamiltonian, initial, times, options=FAST)
    assert len(states) == len(times)
    for ours, theirs in zip(states, reference):
        # Phase included: the energy shift must be undone.
        assert np.allclose(ours.full(), theirs.full(), atol=2e-6)


def test_evolve_with_noise_matches_plain_qutip(problem):
    hamiltonian, times = problem
    c_ops = [0.2 * qt.destroy(3)]
    initial = qt.basis(3, 1)
    options = {"atol": 1e-12, "rtol": 1e-10, "nsteps": 10**7, "max_step": 0.02}
    reference = qt.mesolve(
        hamiltonian, initial, times, c_ops=c_ops, options={**options, "progress_bar": ""}
    ).states
    states = evolve(hamiltonian, initial, times, c_ops=c_ops, options=FAST)
    assert all(s.type == "oper" for s in states)
    assert max(np.abs(a.full() - b.full()).max() for a, b in zip(states, reference)) < 2e-6


def test_evolve_does_not_step_over_a_short_pulse():
    h0 = qt.Qobj(np.diag([0.0, 0.001]))
    sx = qt.Qobj(np.array([[0, 1], [1, 0]], dtype=complex))
    pulse = PulseCoefficient(lambda t: 0 * t + np.pi / 2, 500.0, 501.0)
    states = evolve([h0, [sx, pulse]], qt.basis(2, 0), np.array([0.0, 1000.0]), options=FAST)
    assert abs(states[-1].full()[1, 0]) ** 2 == pytest.approx(1.0, abs=1e-6)


def test_unknown_coefficients_still_work():
    h0 = qt.Qobj(np.diag([0.0, 1.0]))
    sx = qt.Qobj(np.array([[0, 1], [1, 0]], dtype=complex))
    states = evolve([h0, [sx, lambda t, args: 0.3]], qt.basis(2, 0), np.linspace(0, 2, 5))
    exact = (-1j * (h0 + 0.3 * sx) * 2).expm() * qt.basis(2, 0)
    assert abs(qt.fidelity(states[-1], exact) - 1) < 1e-6


def test_coefficient_is_zero_outside_its_window():
    pulse = _pulse(2.0, 4.0, 1.0, 1.0)
    assert pulse(1.999, {}) == 0.0 and pulse(4.001) == 0.0
    assert pulse(3.0) == pytest.approx(1.0)


# --- calibration and caches ---------------------------------------------------------------


@pytest.mark.parametrize("peak", [0.8, 3.3, 5.05, 9.9])
def test_climbing_finds_the_same_peak_as_a_full_sweep(peak):
    grid = np.linspace(0, 10, 20)
    calls = []

    def f(x):
        calls.append(x)
        return 1 - 0.01 * (x - peak) ** 2

    values = _climb_to_peak(f, grid)
    assert int(np.argmax(values)) == int(np.argmax([1 - 0.01 * (x - peak) ** 2 for x in grid]))
    assert len(calls) < 13 and len(set(calls)) == len(calls)


def test_climbing_refuses_two_peaks():
    grid = np.linspace(0, 10, 20)
    assert _climb_to_peak(lambda x: np.cos(3 * x), grid) is None


def test_operator_cache_sees_parameter_changes(engines):
    q_eng, g_eng = engines
    before = g_eng._get_qubit_hamiltonian("fp_t")[0]
    assert g_eng._get_qubit_hamiltonian("fp_t")[0] is before
    qubit = g_eng.qubit_engine.get_qubit("fp_t")
    original, key = qubit.EJ, _physics_key(qubit)
    try:
        qubit.EJ = 18.0
        assert _physics_key(qubit) != key
        after = g_eng._get_qubit_hamiltonian("fp_t")[0]
        assert abs((after - before).norm()) > 1.0
    finally:
        qubit.EJ = original


def test_session_changes_by_another_engine_are_seen(engines):
    first, second = QubitEngine(), QubitEngine()
    first.create_qubit("transmon", "fp_shared", {"EJ": 15.0, "EC": 0.3})
    try:
        second.load_session()
        assert second.get_qubit("fp_shared").EJ == 15.0
        first.create_qubit("transmon", "fp_shared", {"EJ": 16.5, "EC": 0.3})
        second.load_session()
        assert second.get_qubit("fp_shared").EJ == 16.5
    finally:
        first.delete_qubit("fp_shared")


def test_deferred_save_writes_once_and_survives_errors(monkeypatch):
    engine = QubitEngine()
    writes = []
    original = json.dump
    monkeypatch.setattr(json, "dump", lambda *a, **k: (writes.append(1), original(*a, **k)))
    with pytest.raises(RuntimeError):
        with engine.deferred_save():
            for i in range(5):
                engine.create_qubit("transmon", f"fp_d{i}", {"EJ": 15.0, "EC": 0.3})
            raise RuntimeError
    assert len(writes) == 1
    assert "fp_d4" in QubitEngine().list_qubit_names()
    with engine.deferred_save():
        for i in range(5):
            engine.delete_qubit(f"fp_d{i}")
    assert "fp_d0" not in QubitEngine().list_qubit_names()


def test_parameter_sweep_leaves_no_scratch_qubit():
    engine = QubitEngine()
    had = "_sweep_temp" in engine.list_qubit_names()
    result = engine.parameter_sweep("transmon", "EJ", [12.0, 15.0], {"EC": 0.3})
    assert result["property_values"][1] > result["property_values"][0]
    assert ("_sweep_temp" in engine.list_qubit_names()) == had


def test_importing_the_package_does_not_load_the_solvers(tmp_path):
    code = (
        "import sys, QubitWeave, QubitWeave.cli.main; "
        "assert 'qutip' not in sys.modules and 'scqubits' not in sys.modules; "
        "assert QubitWeave.GateEngine and QubitWeave.core.coupling"
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True)
    assert done.returncode == 0, done.stderr.decode()
