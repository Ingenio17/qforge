"""
Tests for the capacitively-coupled CNOT.

With a fixed capacitive coupling there is no coupler to pulse and no flux knob
to sweep, so the CNOT is realized as a ZZ-activated conditional rotation: a pi
pulse on the target, at the transition frequency the target only has while the
control is excited. These tests cover the calibration that picks that frequency
and amplitude, the physics it is supposed to produce, and the diagnostics that
say when the chosen parameters cannot support the gate.
"""

import numpy as np
import pytest
import qutip as qt

from qforge.core.gate_engine import (
    CONDITIONAL_SELECTIVITY_TARGET,
    GAUSSIAN_AREA_PER_NS,
    GateEngine,
)
from qforge.core.qubit_engine import QubitEngine

# Two transmons whose frequencies are far enough apart, and far enough from the
# |11>-|20> collision at detuning = |anharmonicity|, that the computational
# levels stay close to bare product states at this coupling.
CTRL = {"EJ": 15.0, "EC": 0.3, "ng": 0.0, "ncut": 30, "truncated_dim": 3}  # ~5.68 GHz
TARG = {"EJ": 11.63, "EC": 0.3, "ng": 0.0, "ncut": 30, "truncated_dim": 3}  # ~4.98 GHz
COUPLING = 0.03


@pytest.fixture(scope="module")
def engines():
    q_eng = QubitEngine()
    q_eng.create_qubit("transmon", "cc_ctrl", CTRL)
    q_eng.create_qubit("transmon", "cc_targ", TARG)
    g_eng = GateEngine()
    yield q_eng, g_eng
    for name in ("cc_ctrl", "cc_targ"):
        try:
            q_eng.delete_qubit(name)
        except Exception:
            pass


@pytest.fixture(scope="module")
def schedule(engines):
    """The calibrated conditional-pulse schedule at a workable operating point."""
    _, g_eng = engines
    zeta = g_eng._conditional_rotation_schedule("cc_ctrl", "cc_targ", COUPLING, 100.0)["zeta_ghz"]
    duration = CONDITIONAL_SELECTIVITY_TARGET * 1.05 / abs(zeta)
    return duration, g_eng._conditional_rotation_schedule("cc_ctrl", "cc_targ", COUPLING, duration)


def _run(g_eng, duration, initial_state, steps=30):
    return g_eng.simulate_two_qubit_dynamics(
        "cc_ctrl",
        "cc_targ",
        "CNOT",
        coupling_type="capacitive",
        coupling_strength=COUPLING,
        duration=duration,
        steps=steps,
        initial_state=initial_state,
    )


# --- the dressed-basis helper the calibration is built on --------------------


def test_dressed_basis_is_bare_without_coupling():
    """With no interaction the eigenstates are exactly the bare product states."""
    g_eng = GateEngine()
    dims = [3, 3]
    H = qt.tensor(qt.Qobj(np.diag([0.0, 5.0, 9.6])), qt.qeye(3)) + qt.tensor(
        qt.qeye(3), qt.Qobj(np.diag([0.0, 4.0, 7.7]))
    )
    basis = g_eng._dressed_computational_basis(H, dims)

    assert len(basis) == 9
    for label, (energy, vec, purity) in basis.items():
        assert purity == pytest.approx(1.0)
        assert vec.dims[0] == [3, 3]
        # Gauge fixing must leave the dominant amplitude real and positive.
        idx = int(np.ravel_multi_index(label, dims))
        assert complex(vec.full().flatten()[idx]).real == pytest.approx(1.0)

    # Uncoupled energies are additive, so |11> sits exactly where |01> and
    # |10> put it. Any deviation would mean the labelling had gone astray.
    energy = {label: entry[0] for label, entry in basis.items()}
    assert energy[(1, 1)] == pytest.approx(
        energy[(1, 0)] + energy[(0, 1)] - energy[(0, 0)]
    )


def test_dressed_basis_labels_every_computational_state_when_coupled(engines):
    """A coupled pair still has an identifiable |00>, |01>, |10> and |11>."""
    _, g_eng = engines
    H, qubits, _ = g_eng._get_n_qubit_hamiltonian(
        ["cc_ctrl", "cc_targ"],
        [{"q1": 0, "q2": 1, "type": "capacitive", "strength": COUPLING}],
    )
    dims = [q.truncated_dim for q in qubits]
    basis = g_eng._dressed_computational_basis(H, dims)

    for label in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        assert label in basis
        assert basis[label][2] > 0.5
        assert basis[label][1].norm() == pytest.approx(1.0)


# --- the calibration itself --------------------------------------------------


def test_drive_is_tuned_to_the_conditional_transition(engines, schedule):
    """
    The drive must sit on the target transition as it is with the control
    excited, and that must be a real shift away from the control=0 transition.
    """
    _, g_eng = engines
    duration, sched = schedule

    assert sched["frequency"] == pytest.approx(sched["target_frequency_control_1"])
    assert sched["zeta_ghz"] == pytest.approx(
        sched["target_frequency_control_1"] - sched["target_frequency_control_0"]
    )
    assert abs(sched["zeta_ghz"]) > 1e-4  # at least ~100 kHz of conditionality

    # It is the coupling that creates the shift: without it there is none.
    H, qubits, _ = g_eng._get_n_qubit_hamiltonian(["cc_ctrl", "cc_targ"], [])
    dims = [q.truncated_dim for q in qubits]
    basis = g_eng._dressed_computational_basis(H, dims)
    bare_zeta = (basis[(1, 1)][0] - basis[(1, 0)][0]) - (basis[(0, 1)][0] - basis[(0, 0)][0])
    assert bare_zeta / (2 * np.pi) == pytest.approx(0.0, abs=1e-9)


def test_pulse_area_realizes_a_pi_rotation(engines, schedule):
    """
    Amplitude x envelope area x drive matrix element must come to pi, which is
    what makes the pulse a flip rather than an arbitrary rotation.
    """
    _, g_eng = engines
    duration, sched = schedule

    H, qubits, local_ops = g_eng._get_n_qubit_hamiltonian(
        ["cc_ctrl", "cc_targ"],
        [{"q1": 0, "q2": 1, "type": "capacitive", "strength": COUPLING}],
    )
    dims = [q.truncated_dim for q in qubits]
    basis = g_eng._dressed_computational_basis(H, dims)
    op = qt.tensor(qt.qeye(dims[0]), g_eng.get_control_hamiltonian("X", local_ops[1]))
    element = complex(basis[(1, 0)][1].dag() * op * basis[(1, 1)][1])

    area = sched["amplitude"] * 2 * np.pi * duration * GAUSSIAN_AREA_PER_NS
    assert area * abs(element) == pytest.approx(np.pi, rel=1e-6)

    # The phase puts the rotation axis along x rather than somewhere arbitrary.
    assert sched["phase"] == pytest.approx(-np.angle(element))


def test_schedule_is_cached(engines, schedule):
    """Diagonalizing the coupled pair is not repeated for identical requests."""
    _, g_eng = engines
    duration, sched = schedule
    again = g_eng._conditional_rotation_schedule("cc_ctrl", "cc_targ", COUPLING, duration)
    assert again is sched


# --- the physics -------------------------------------------------------------


@pytest.mark.slow
def test_capacitive_cnot_is_conditional(engines, schedule):
    """
    The physics sanity check: the target flips when the control is excited and
    is left alone when it is not. Both branches are required - a pulse that
    flips the target either way scores perfectly on the first check alone and
    is an unconditional X, not a CNOT.
    """
    _, g_eng = engines
    duration, sched = schedule

    assert sched["warnings"] == []

    flips = _run(g_eng, duration, "10")["populations"]["11"][-1]
    stays = _run(g_eng, duration, "00")["populations"]["00"][-1]
    back = _run(g_eng, duration, "11")["populations"]["10"][-1]
    idle = _run(g_eng, duration, "01")["populations"]["01"][-1]

    assert flips > 0.9
    assert stays > 0.95
    assert back > 0.9
    assert idle > 0.95


@pytest.mark.slow
def test_capacitive_cnot_actually_evolves(engines, schedule):
    """
    Regression: a capacitive CNOT used to drive the control at the target's
    bare frequency with a fixed, uncalibrated amplitude, which for a pair whose
    frequencies are far apart left the state completely untouched over the whole
    gate. Any correct implementation has to move population.
    """
    _, g_eng = engines
    duration, _ = schedule

    populations = _run(g_eng, duration, "10")["populations"]
    assert populations["10"][0] == pytest.approx(1.0, abs=1e-6)
    assert populations["10"][-1] < 0.1
    assert max(populations["11"]) > 0.9


@pytest.mark.slow
def test_leakage_levels_are_preserved(engines, schedule):
    """The gate is simulated on the full multi-level space, not a qubit subspace."""
    _, g_eng = engines
    duration, _ = schedule

    result = _run(g_eng, duration, "10")
    final = result["final_state"]

    assert final.dims[0] == [3, 3]
    assert final.norm() == pytest.approx(1.0, abs=1e-4)
    assert "22" in result["populations"]


# --- the diagnostics ---------------------------------------------------------


def test_short_gate_reports_weak_conditionality(engines):
    """
    Too short a pulse is spectrally wider than the ZZ shift, so it cannot
    separate the two control branches. That has to be said, not hidden.
    """
    _, g_eng = engines
    sched = g_eng._conditional_rotation_schedule("cc_ctrl", "cc_targ", COUPLING, 5.0)

    assert sched["selectivity"] < 1.0
    assert any("Weak conditionality" in w for w in sched["warnings"])
    assert any("unconditional X" in w for w in sched["warnings"])


def test_warnings_reach_the_simulation_result(engines):
    """Callers see the diagnostics without having to ask for the schedule."""
    _, g_eng = engines
    result = _run(g_eng, 5.0, "10", steps=10)

    assert result["schedule"]["selectivity"] < 1.0
    assert result["warnings"]
    assert result["warnings"] == result["schedule"]["warnings"]


def test_explicit_target_drive_is_not_overridden(engines):
    """
    A caller that supplies its own drive on the target is building its own
    pulse sequence, so the compiled conditional pulse must stay out of the way.
    """
    _, g_eng = engines
    drives = [
        {
            "target": 1,
            "type": "X",
            "amplitude": 0.0,
            "frequency": 5.0,
            "phase": 0.0,
            "start_time": 0.0,
            "end_time": 10.0,
        }
    ]
    result = g_eng.simulate_n_qubit_dynamics(
        ["cc_ctrl", "cc_targ"],
        "CNOT",
        10.0,
        [{"q1": 0, "q2": 1, "type": "capacitive", "strength": COUPLING}],
        drives,
        initial_state="10",
        steps=5,
    )
    assert "schedule" not in result
