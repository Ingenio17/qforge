"""
Tests for registering a netlist-designed device as an ordinary qforge qubit.

The load-bearing test here is ``test_device_route_matches_preset_route``: the
same physical circuit, reached once through a netlist and once through
``scqubits.Transmon``, must produce the same energies and the same charge matrix
elements. If those ever diverge, every gate driven on a custom device is wrong,
and nothing else in this file would notice.
"""

import numpy as np
import pytest

from qforge.core.device_engine import DeviceError
from qforge.core.device_library import template_source
from qforge.core.device_qubit import (
    DEFAULT_TRUNCATED_DIM,
    DeviceQubit,
    build_device_qubit,
    clear_cache,
    device_qubit_params,
)
from qforge.core.qubit_engine import QubitEngine

scq = pytest.importorskip("scqubits")


# A junction with a negligible capacitance of its own, so the shunt alone sets
# EC. That is exactly the two-parameter transmon scqubits models, which is what
# makes the two routes directly comparable.
EQUIVALENT_TRANSMON = """
.title Equivalent transmon
J1 1 0 EJ=15.0 EC=1e6
C1 1 0 EC=0.3
.charge 1 = 0.0
.cutoff n1 = 30
.levels 6
"""


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    """
    Keep every test out of the user's real qubit session.

    QubitEngine resolves OUTPUT_DIRS relative to the working directory, so
    changing directory is enough to sandbox it.
    """
    monkeypatch.chdir(tmp_path)
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# The adapter is faithful
# ---------------------------------------------------------------------------


def test_device_route_matches_preset_route():
    """The same circuit, reached two ways, must give the same physics."""
    device_qubit = DeviceQubit(EQUIVALENT_TRANSMON, name="dev", truncated_dim=4)
    preset = scq.Transmon(EJ=15.0, EC=0.3, ng=0.0, ncut=30, truncated_dim=4)

    assert device_qubit.eigenvals(evals_count=4) == pytest.approx(
        preset.eigenvals(evals_count=4), abs=1e-4
    )

    device_table = np.abs(device_qubit.matrixelement_table("n_operator", evals_count=4))
    preset_table = np.abs(preset.matrixelement_table("n_operator", evals_count=4))
    assert device_table == pytest.approx(preset_table, abs=1e-4)


def test_transmon_template_reproduces_its_documented_numbers():
    qubit = DeviceQubit(template_source("transmon"), name="tm", truncated_dim=4)
    evals = qubit.eigenvals(evals_count=3)
    f01 = evals[1] - evals[0]
    anharmonicity = (evals[2] - evals[1]) - f01
    assert f01 == pytest.approx(4.789, abs=1e-3)
    assert anharmonicity * 1e3 == pytest.approx(-235.5, abs=1.0)


# ---------------------------------------------------------------------------
# The interface the engines rely on
# ---------------------------------------------------------------------------


def test_construction_does_not_quantize():
    """
    Building the object must stay cheap.

    QubitEngine reconstructs every registered qubit each time it loads its
    session, and GateEngine reloads the session on every Hamiltonian request, so
    quantizing eagerly here would make each of those calls seconds long.
    """
    qubit = DeviceQubit(EQUIVALENT_TRANSMON, name="lazy")
    assert qubit.device._circuit is None
    qubit.eigenvals(evals_count=2)
    assert qubit.device._circuit is not None


def test_periodic_mode_has_no_phi_operator():
    """
    A compact phase is not an observable.

    scqubits' own Transmon offers no phi_operator, and
    GateEngine._get_qubit_hamiltonian branches on hasattr, so reporting one here
    would hand the gate engine a meaningless operator.
    """
    qubit = DeviceQubit(EQUIVALENT_TRANSMON, name="periodic", truncated_dim=3)
    assert qubit.qubit_mode[0] == "periodic"
    assert hasattr(qubit, "n_operator")
    assert not hasattr(qubit, "phi_operator")
    assert not hasattr(scq.Transmon(EJ=15.0, EC=0.3, ng=0.0, ncut=30), "phi_operator")


def test_extended_mode_has_a_phi_operator():
    qubit = DeviceQubit(template_source("fluxonium"), name="extended", truncated_dim=3)
    assert qubit.qubit_mode[0] == "extended"
    assert hasattr(qubit, "phi_operator")
    table = qubit.matrixelement_table("phi_operator", evals_count=3)
    assert table.shape == (3, 3)


def test_matrix_element_table_is_hermitian_with_no_diagonal():
    qubit = DeviceQubit(EQUIVALENT_TRANSMON, name="matelem", truncated_dim=4)
    table = qubit.matrixelement_table("n_operator", evals_count=4)
    assert table == pytest.approx(table.conj().T, abs=1e-9)
    assert np.all(np.abs(np.diag(table)) < 1e-8)


def test_multi_mode_device_picks_the_mode_carrying_the_transition():
    """
    With two modes, the qubit is the one the 0-1 transition lives on.

    Level 1 of the transmon-plus-resonator template is the transmon excitation at
    4.67 GHz, with the resonator at 7.05 GHz, so the transmon's charge operator
    must be the one selected. The raw matrix elements point the other way (the
    resonator's Q is simply scaled differently), which is exactly why the
    selection normalises by each operator's own zero-point spread.
    """
    qubit = DeviceQubit(template_source("transmon_resonator"), name="multi", truncated_dim=3)
    kind, index = qubit.qubit_mode
    assert (kind, index) == ("periodic", 1)
    assert abs(qubit.matrixelement_table("n_operator", evals_count=3)[0, 1]) > 0.1


def test_mode_selection_is_not_fooled_by_operator_scale():
    """
    Guard the normalisation directly.

    Without it the raw ``|<0|Q|1>|`` picks the resonator, because that operator's
    own fluctuation is larger, not because it carries the transition.
    """
    qubit = DeviceQubit(template_source("transmon_resonator"), name="scale", truncated_dim=3)
    circuit = qubit.device.circuit
    _evals, evecs = qubit.device.eigensystem(3)

    raw, normalised = {}, {}
    for kind, index, attribute in qubit._mode_operators():
        matrix = getattr(circuit, attribute)()
        coupling = abs((evecs.conj().T @ (matrix @ evecs))[0, 1])
        spread = float(np.linalg.norm(matrix @ evecs[:, 0]))
        raw[(kind, index)] = coupling
        normalised[(kind, index)] = coupling / spread

    assert max(raw, key=raw.get) == ("extended", 2)  # the misleading answer
    assert max(normalised, key=normalised.get) == ("periodic", 1)  # the right one
    assert qubit.qubit_mode == ("periodic", 1)


def test_truncated_dim_is_respected():
    for dim in (2, 3, 5):
        qubit = DeviceQubit(EQUIVALENT_TRANSMON, name="dim", truncated_dim=dim)
        assert qubit.truncated_dim == dim
        assert len(qubit.eigenvals(evals_count=dim)) == dim


def test_eigensys_returns_values_and_vectors():
    qubit = DeviceQubit(EQUIVALENT_TRANSMON, name="esys", truncated_dim=4)
    evals, evecs = qubit.eigensys(evals_count=4)
    assert len(evals) == 4
    assert evecs.shape[1] == 4


# ---------------------------------------------------------------------------
# Construction and caching
# ---------------------------------------------------------------------------


def test_params_round_trip():
    params = device_qubit_params(EQUIVALENT_TRANSMON, truncated_dim=3, device_name="rt")
    qubit = build_device_qubit(params)
    assert qubit.truncated_dim == 3
    assert qubit.name == "rt"
    assert qubit.to_params()["source"] == EQUIVALENT_TRANSMON


def test_default_truncation_matches_the_preset_types():
    qubit = build_device_qubit(device_qubit_params(EQUIVALENT_TRANSMON))
    assert qubit.truncated_dim == DEFAULT_TRUNCATED_DIM == 4


def test_build_is_cached_per_netlist_and_truncation():
    params = device_qubit_params(EQUIVALENT_TRANSMON, truncated_dim=4)
    assert build_device_qubit(params) is build_device_qubit(params)
    other = device_qubit_params(EQUIVALENT_TRANSMON, truncated_dim=3)
    assert build_device_qubit(other) is not build_device_qubit(params)


def test_build_without_a_netlist_is_rejected():
    with pytest.raises(DeviceError, match="netlist"):
        build_device_qubit({"truncated_dim": 4})


# ---------------------------------------------------------------------------
# Registration with QubitEngine
# ---------------------------------------------------------------------------


def test_device_registers_as_a_qubit_and_survives_a_reload():
    """
    A device-backed qubit has to come back from the session file.

    GateEngine builds its own QubitEngine, which reloads from disk, so a qubit
    that cannot be rebuilt would simply be missing from every gate, workflow and
    error-correction run.
    """
    engine = QubitEngine()
    params = device_qubit_params(EQUIVALENT_TRANSMON, truncated_dim=4, device_name="mydev")
    engine.create_qubit("device", "mydev", params)

    reloaded = QubitEngine()
    assert "mydev" in [entry["name"] for entry in reloaded.list_qubits()]
    qubit = reloaded.get_qubit("mydev")
    assert isinstance(qubit, DeviceQubit)

    evals = qubit.eigenvals(evals_count=2)
    assert (evals[1] - evals[0]) == pytest.approx(5.6826, abs=1e-3)


def test_list_qubits_reports_a_device_qubit():
    engine = QubitEngine()
    engine.create_qubit("device", "listed", device_qubit_params(EQUIVALENT_TRANSMON, 4, "listed"))
    entry = next(q for q in engine.list_qubits() if q["name"] == "listed")
    assert entry["type"] == "device"
    assert entry["frequency"] == pytest.approx(5.6826, abs=1e-3)
    assert entry["anharmonicity"] == pytest.approx(-0.3448, abs=1e-3)


def test_preset_qubit_types_still_work():
    """The new branch must not disturb the four models that were already there."""
    engine = QubitEngine()
    engine.create_qubit("transmon", "t", {"EJ": 15.0, "EC": 0.3, "ng": 0.0, "ncut": 30})
    engine.create_qubit("fluxonium", "f", {"EJ": 8.9, "EC": 2.5, "EL": 0.5, "flux": 0.5})

    reloaded = QubitEngine()
    types = {entry["name"]: entry["type"] for entry in reloaded.list_qubits()}
    assert types == {"t": "transmon", "f": "fluxonium"}
    assert isinstance(reloaded.get_qubit("t"), scq.Transmon)


def test_unknown_qubit_type_is_still_rejected():
    engine = QubitEngine()
    with pytest.raises(ValueError, match="Unknown qubit type"):
        engine.create_qubit("not_a_type", "x", {})


def test_device_and_preset_qubits_coexist():
    engine = QubitEngine()
    engine.create_qubit("transmon", "preset", {"EJ": 15.0, "EC": 0.3, "ng": 0.0, "ncut": 30})
    engine.create_qubit("device", "custom", device_qubit_params(EQUIVALENT_TRANSMON, 4, "custom"))

    reloaded = QubitEngine()
    entries = {entry["name"]: entry["type"] for entry in reloaded.list_qubits()}
    assert entries == {"preset": "transmon", "custom": "device"}
    # The same circuit by two routes, so the two must agree.
    frequencies = {entry["name"]: entry["frequency"] for entry in reloaded.list_qubits()}
    assert frequencies["custom"] == pytest.approx(frequencies["preset"], abs=1e-4)


# ---------------------------------------------------------------------------
# The gate engine accepts it
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_gate_engine_uses_the_real_charge_operator():
    """
    A device qubit must reach the physical drive path, not the fallback.

    GateEngine falls back to a harmonic-oscillator operator when a qubit exposes
    neither n_operator nor phi_operator. That fallback is a different physical
    model, so landing in it silently would be a real regression.
    """
    from qforge.core.gate_engine import GateEngine

    engine = QubitEngine()
    engine.create_qubit("device", "dq", device_qubit_params(EQUIVALENT_TRANSMON, 4, "dq"))
    engine.create_qubit("transmon", "pq", {"EJ": 15.0, "EC": 0.3, "ng": 0.0, "ncut": 30})

    gate_engine = GateEngine()
    h_device, ops_device = gate_engine._get_qubit_hamiltonian("dq")
    h_preset, ops_preset = gate_engine._get_qubit_hamiltonian("pq")

    assert set(ops_device) == set(ops_preset) == {"n"}
    assert np.abs(ops_device["n"].full()) == pytest.approx(np.abs(ops_preset["n"].full()), abs=1e-4)
    assert np.real(h_device.full().diagonal()) == pytest.approx(
        np.real(h_preset.full().diagonal()), abs=1e-4
    )


@pytest.mark.slow
def test_x_gate_on_a_device_qubit_inverts_the_population():
    from qforge.core.gate_engine import GateEngine

    engine = QubitEngine()
    engine.create_qubit("device", "xq", device_qubit_params(EQUIVALENT_TRANSMON, 3, "xq"))

    result = GateEngine().simulate_dynamics("xq", "X", duration=20.0, steps=60)
    populations = dict(zip(result["labels"], result["expectations"]))
    excited = next(v for k, v in populations.items() if "1" in k)
    assert float(excited[-1]) > 0.98
