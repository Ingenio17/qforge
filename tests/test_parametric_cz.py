"""
Tests for the parametrically activated CZ used on strongly anharmonic pairs.

Regression: a tunable-coupler CNOT used to be compiled the transmon way whatever the
qubits were, flux-tuning |11> onto |02>. For two fluxonia that asked for a -8.65 GHz
shift of a 0.36 GHz qubit, the calibration scored 0.005, the score was ignored, and a
Bell circuit came out as |00> and |10> with no |11> at all.
"""

from pathlib import Path

import numpy as np
import pytest
import qutip as qt
import scqubits as scq

from QubitWeave.core.device_qubit import device_qubit_params
from QubitWeave.core.gate_engine import GAUSSIAN_AREA_PER_NS, GateEngine
from QubitWeave.core.parametric_gate import (
    _Pair,
    calibrate_parametric_cphase,
    evaluate_parametric_cphase,
    parametric_envelope,
)
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine

NETLIST = Path(__file__).parents[1] / "examples" / "device_files" / "fluxonium.qdl"
STRENGTH = 0.05
COUPLINGS = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": STRENGTH}]


def _levels(dim):
    qubit = scq.Fluxonium(EJ=8.9, EC=2.5, EL=0.5, flux=0.5, cutoff=110, truncated_dim=dim)
    return qubit.eigenvals(dim), qubit.matrixelement_table("n_operator", evals_count=dim)


@pytest.fixture(scope="module")
def pair():
    return (*_levels(4), *_levels(3))


@pytest.fixture(scope="module")
def schedule(pair):
    return calibrate_parametric_cphase(*pair, STRENGTH)


@pytest.fixture(scope="module")
def engines():
    """The fluxonium netlist registered twice as a device, plus a transmon pair."""
    q_eng = QubitEngine()
    source = NETLIST.read_text(encoding="utf-8")
    names = ["pcz_flux_a", "pcz_flux_b", "pcz_tr_a", "pcz_tr_b"]
    for name, dim in zip(names[:2], (4, 3)):
        q_eng.create_qubit("device", name, device_qubit_params(source, dim, "fluxonium"))
    q_eng.create_qubit("transmon", names[2], {"EJ": 15.0, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", names[3], {"EJ": 13.5, "EC": 0.2, "truncated_dim": 4})
    g_eng = GateEngine()
    sweep = g_eng.calibrate_gate

    def calibrate(q1, q2=None, gate_type="X", *args, **kwargs):
        # The single-qubit duration sweep is slow on a 0.36 GHz qubit and is not what is
        # under test; a Gaussian pi pulse has a closed-form duration.
        if q2 is not None:
            return sweep(q1, q2, gate_type, *args, **kwargs)
        n01 = abs(g_eng._get_qubit_hamiltonian(q1)[1]["n"].full()[1, 0])
        turns = 1.0 if gate_type == "X" else 0.5
        return turns / (2 * 0.025 * n01 * GAUSSIAN_AREA_PER_NS), 1.0

    g_eng.calibrate_gate = calibrate
    yield q_eng, g_eng
    for name in names:
        q_eng.delete_qubit(name)


# --- calibration -------------------------------------------------------------


def test_envelope_is_a_closed_flat_top():
    assert parametric_envelope(0.0, 100.0, 15.0) == 0.0
    assert parametric_envelope(7.5, 100.0, 15.0) == pytest.approx(0.5)
    assert parametric_envelope(50.0, 100.0, 15.0) == 1.0
    assert parametric_envelope(100.0, 100.0, 15.0) == pytest.approx(0.0)
    assert parametric_envelope(100.1, 100.0, 15.0) == 0.0


def test_modulation_addresses_the_11_to_02_transition(pair, schedule):
    e1, _, e2, _ = pair
    expected = (e2[2] - e2[0]) - (e1[1] - e1[0]) - (e2[1] - e2[0])
    assert schedule["frequency"] == pytest.approx(expected, abs=2e-3)
    assert schedule["rise_time"] < schedule["duration"] / 2


def test_cz_is_a_cz(schedule):
    assert schedule["fidelity"] > 0.999
    assert schedule["leakage"] < 1e-3
    assert schedule["conditional_phase"] == pytest.approx(np.pi, abs=0.02)
    assert schedule["warnings"] == []


@pytest.mark.parametrize("theta", [np.pi / 2, 1.5 * np.pi])
def test_arbitrary_controlled_phase(pair, theta):
    result = calibrate_parametric_cphase(*pair, STRENGTH, theta)
    assert result["fidelity"] > 0.999
    assert result["conditional_phase"] == pytest.approx(theta, abs=0.02)


def test_result_is_converged_in_truncation(schedule):
    """Keeping more levels must not change the gate."""
    wider = calibrate_parametric_cphase(*_levels(5), *_levels(5), STRENGTH)
    assert wider["duration"] == pytest.approx(schedule["duration"], rel=0.01)
    assert wider["fidelity"] > 0.999


def test_propagator_is_unitary_and_trivial_without_coupling(pair):
    coupled = _Pair(*pair, STRENGTH)._propagate(np.linspace(0, 1, 500), 0.003)
    assert np.allclose(coupled @ coupled.conj().T, np.eye(len(coupled)), atol=1e-10)

    _, blocks = _Pair(*pair, 0.0).computational_blocks(8.65, 5, np.array([40]))
    assert np.allclose(blocks[0], np.eye(4), atol=1e-9)


def test_too_short_a_pulse_says_so(pair, schedule):
    result = evaluate_parametric_cphase(*pair, schedule, 50.0)
    assert result["fidelity"] < 0.9
    assert any("does not complete" in w for w in result["warnings"])


def test_unusable_pairs_are_refused(pair):
    with pytest.raises(ValueError, match="truncated_dim"):
        calibrate_parametric_cphase(*_levels(2), *_levels(2), STRENGTH)
    with pytest.raises(ValueError, match="cannot activate"):
        calibrate_parametric_cphase(*pair, 0.0)


# --- choosing the mechanism --------------------------------------------------


def test_only_weakly_anharmonic_pairs_are_flux_activated(engines):
    _, g_eng = engines
    assert g_eng._flux_activation_is_physical("pcz_tr_a", "pcz_tr_b")
    assert not g_eng._flux_activation_is_physical("pcz_flux_a", "pcz_flux_b")
    assert not g_eng._flux_activation_is_physical("pcz_tr_a", "pcz_flux_b")


def test_rotation_axis_does_not_depend_on_the_eigenvector_gauge():
    """A real and an imaginary charge operator must give the same physical axis."""
    real = qt.Qobj(np.array([[0, 1.2], [1.2, 0]]))
    imaginary = qt.Qobj(np.array([[0, -0.05j], [0.05j, 0]]))
    for op in (real, imaginary):
        phase = GateEngine._rotation_phase(op, np.pi / 2)
        axis = np.angle(op.full()[1, 0]) - phase
        assert axis == pytest.approx(np.pi / 2)


def test_calibrate_gate_reports_the_parametric_gate(engines):
    _, g_eng = engines
    duration, fidelity = g_eng.calibrate_gate(
        "pcz_flux_a", "pcz_flux_b", "CNOT", "tunable_coupler", STRENGTH, "duration"
    )
    assert fidelity > 0.999
    assert duration == pytest.approx(604.7, rel=0.02)


def test_weak_calibration_is_reported(engines, capsys, monkeypatch):
    """A two-qubit calibration that failed must not be simulated silently."""
    q_eng, g_eng = engines
    monkeypatch.setattr(g_eng, "calibrate_gate", lambda *a, **k: (50.0, 0.0051))
    PhysicalWorkflowEngine(q_eng, g_eng).automate_calibrations(
        ["pcz_flux_a", "pcz_flux_b"], COUPLINGS, [{"type": "CX", "target": (0, 1)}]
    )
    output = capsys.readouterr().out
    assert "CNOT calibration" in output
    assert "CZ calibration" not in output  # not used by this circuit


# --- end to end --------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("start, end", [("00", "00"), ("01", "01"), ("10", "11"), ("11", "10")])
def test_cnot_truth_table(engines, start, end):
    _, g_eng = engines
    duration, _ = g_eng.calibrate_gate(
        "pcz_flux_a", "pcz_flux_b", "CNOT", "tunable_coupler", STRENGTH, "duration"
    )
    result = g_eng.simulate_two_qubit_dynamics(
        "pcz_flux_a",
        "pcz_flux_b",
        "CNOT",
        "tunable_coupler",
        STRENGTH,
        duration,
        steps=10,
        initial_state=start,
    )
    assert result["populations"][end][-1] > 0.99
    assert result["final_state"].dims[0] == [4, 3]


H = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
CX = np.eye(4)[[0, 1, 3, 2]]


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize(
    "body, ideal",
    [
        ("h q[0]; cx q[0],q[1];", np.array([1, 0, 0, 1]) / np.sqrt(2)),
        ("h q[0]; h q[0];", np.array([1, 0, 0, 0])),
        ("h q[0]; z q[0]; h q[0];", np.array([0, 0, 1, 0])),
        # Deutsch, balanced oracle: needs the phases of every gate to be right.
        (
            "x q[1]; h q[0]; h q[1]; cx q[0],q[1]; h q[0];",
            np.kron(H, np.eye(2)) @ CX @ np.kron(H, H) @ np.array([0, 1, 0, 0]),
        ),
        ("h q[0]; h q[1]; cz q[0],q[1]; h q[1];", np.array([1, 0, 0, 1]) / np.sqrt(2)),
    ],
    ids=["bell", "hh", "hzh", "deutsch", "cz"],
)
def test_workflow_produces_the_circuit_state(engines, tmp_path, body, ideal):
    """Compared as a state, so relative phases count and not just populations."""
    q_eng, g_eng = engines
    path = tmp_path / "circuit.qasm"
    path.write_text(f'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\n{body}\n')
    result = PhysicalWorkflowEngine(q_eng, g_eng).execute_workflow(
        ["pcz_flux_a", "pcz_flux_b"], COUPLINGS, str(path)
    )
    state = result["logical_state"].full().ravel()
    dims = result["logical_state"].dims[0]
    assert dims == [4, 3]
    computational = state[[0, 1, dims[1], dims[1] + 1]]
    assert abs(np.vdot(ideal, computational)) ** 2 > 0.99
