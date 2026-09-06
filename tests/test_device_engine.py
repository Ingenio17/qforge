"""
Tests for DeviceEngine: quantization, spectra and analysis of custom netlists.

The important tests here are the ones that check a hand-written netlist against
the scqubits qubit class describing the same circuit. A transmon netlist has to
reproduce ``scqubits.Transmon`` and a fluxonium netlist ``scqubits.Fluxonium``,
because if the netlist path drifts from the preset path, one of the two is wrong
and there is no other way to tell which.
"""

import json

import numpy as np
import pytest

from qforge.core.device_engine import DeviceEngine, DeviceError, QuantumDevice
from qforge.core.device_library import TEMPLATES, list_templates, template_source
from qforge.core.device_netlist import parse_netlist

scq = pytest.importorskip("scqubits")


# A junction with no capacitance of its own, so the shunt capacitor alone sets
# EC and the circuit is exactly the two-parameter transmon scqubits models.
TRANSMON_NETLIST = """
.title Transmon
J1 1 0 EJ=15.0 EC=1e6
C1 1 0 EC=0.3
.charge 1 = 0.0
.cutoff n1 = 30
.levels 5
"""

FLUXONIUM_NETLIST = """
.title Fluxonium
J1 1 0 EJ=8.9 EC=2.5
L1 1 0 EL=0.5
.flux 1 = 0.5
.cutoff ext1 = 110
.levels 5
"""


def build(source, name="dev"):
    return QuantumDevice(parse_netlist(source, name=name))


# ---------------------------------------------------------------------------
# Agreement with the scqubits qubit classes
# ---------------------------------------------------------------------------


def test_transmon_netlist_matches_scqubits_transmon():
    device = build(TRANSMON_NETLIST, "transmon")
    reference = scq.Transmon(EJ=15.0, EC=0.3, ng=0.0, ncut=30)

    device_levels = device.eigenvalues(5)
    reference_levels = reference.eigenvals(evals_count=5)
    assert device_levels == pytest.approx(reference_levels, abs=1e-4)

    spectrum = device.spectrum(5)
    assert spectrum["f01_ghz"] == pytest.approx(reference.E01(), abs=1e-5)
    assert spectrum["anharmonicity_ghz"] == pytest.approx(reference.anharmonicity(), abs=1e-5)


def test_fluxonium_netlist_matches_scqubits_fluxonium():
    device = build(FLUXONIUM_NETLIST, "fluxonium")
    reference = scq.Fluxonium(EJ=8.9, EC=2.5, EL=0.5, flux=0.5, cutoff=110)

    assert device.eigenvalues(5) == pytest.approx(reference.eigenvals(evals_count=5), abs=1e-3)
    assert device.spectrum(3)["f01_ghz"] == pytest.approx(reference.E01(), abs=1e-3)


def test_physical_units_reproduce_the_energy_form():
    """90 fF and 30 nA must give the same spectrum as the equivalent GHz values."""
    physical = build("J1 1 0 Ic=30nA Cj=2fF\nC1 1 0 90fF\n.cutoff n1 = 30\n.levels 4\n", "phys")
    energies = build(
        "J1 1 0 EJ=14.90048 EC=9.685115\nC1 1 0 EC=0.2152248\n.cutoff n1 = 30\n.levels 4\n",
        "ener",
    )
    assert physical.eigenvalues(4) == pytest.approx(energies.eigenvalues(4), abs=1e-4)


def test_lc_resonator_frequency_matches_the_classical_formula():
    """A junctionless LC circuit must land on 1/(2 pi sqrt(LC))."""
    inductance, capacitance = 100e-9, 90e-15
    device = build("L1 1 0 100nH\nC1 1 0 90fF\n.levels 4\n", "lc")
    expected_ghz = 1.0 / (2 * np.pi * np.sqrt(inductance * capacitance)) / 1e9
    assert device.spectrum(4)["f01_ghz"] == pytest.approx(expected_ghz, rel=1e-3)


def test_lc_resonator_ladder_is_evenly_spaced():
    """No junction means no anharmonicity, by construction."""
    device = build("L1 1 0 100nH\nC1 1 0 90fF\n.levels 5\n", "lc")
    spacings = device.spectrum(5)["level_spacings_ghz"]
    assert spacings == pytest.approx([spacings[0]] * len(spacings), rel=1e-4)


def test_mutual_inductance_reproduces_the_normal_mode_split():
    """
    Two identical LC oscillators coupled by k split into f0/sqrt(1 -/+ k).

    This is what pins the factor of two in scqubits' ML branch convention: if it
    were dropped, the modes would land at the k/2 positions instead.
    """
    k = 0.05
    device = build(
        "L1 1 0 100nH\nC1 1 0 90fF\nL2 2 0 100nH\nC2 2 0 90fF\n"
        f"K1 L1 L2 k={k}\n.cutoff all = 40\n.levels 3\n",
        "coupled",
    )
    relative = np.array(device.spectrum(3)["relative_ghz"])
    low, high = sorted(relative[1:3])
    bare = 1.0 / (2 * np.pi * np.sqrt(100e-9 * 90e-15)) / 1e9
    assert low == pytest.approx(bare / np.sqrt(1 + k), rel=2e-3)
    assert high == pytest.approx(bare / np.sqrt(1 - k), rel=2e-3)


# ---------------------------------------------------------------------------
# Basis handling
# ---------------------------------------------------------------------------


def test_default_charge_cutoff_is_large_enough_for_a_transmon():
    """
    scqubits defaults periodic variables to a charge cutoff of 5, which misplaces
    a transmon's levels badly. The engine must pick its own default instead.
    """
    device = build("J1 1 0 EJ=15.0 EC=1e6\nC1 1 0 EC=0.3\n.levels 4\n", "nocutoff")
    assert device.circuit.cutoff_n_1 >= 20
    reference = scq.Transmon(EJ=15.0, EC=0.3, ng=0.0, ncut=30)
    assert device.eigenvalues(4) == pytest.approx(reference.eigenvals(evals_count=4), abs=1e-4)


def test_netlist_cutoffs_are_applied():
    device = build("J1 1 0 EJ=15.0 EC=1e6\nC1 1 0 EC=0.3\n.cutoff n1 = 17\n.levels 4\n", "cut")
    assert device.circuit.cutoff_n_1 == 17


def test_convergence_check_passes_for_a_well_resolved_circuit():
    device = build(TRANSMON_NETLIST, "converged")
    report = device.check_convergence(4)
    assert report["converged"] is True
    assert report["max_transition_shift_mhz"] < 1e-3


def test_convergence_check_flags_a_starved_basis():
    """A charge cutoff of 3 cannot resolve a transmon, and must be reported as such."""
    device = build("J1 1 0 EJ=15.0 EC=1e6\nC1 1 0 EC=0.3\n.cutoff n1 = 3\n.levels 4\n", "starved")
    assert device.check_convergence(4)["converged"] is False


def test_convergence_check_restores_the_original_cutoffs():
    device = build(TRANSMON_NETLIST, "restore")
    before = dict(device.circuit.cutoffs_dict())
    device.check_convergence(4)
    assert dict(device.circuit.cutoffs_dict()) == before


# ---------------------------------------------------------------------------
# Bias, parameters and sweeps
# ---------------------------------------------------------------------------


def test_flux_and_charge_directives_reach_the_circuit():
    device = build(FLUXONIUM_NETLIST, "biased")
    fluxes = device.describe_circuit()["external_fluxes"]
    assert list(fluxes.values()) == [pytest.approx(0.5)]


def test_named_params_become_sweepable_circuit_parameters():
    device = build(
        ".param EJ0 = 15\nJ1 1 0 EJ=EJ0 EC=1e6\nC1 1 0 EC=0.3\n.cutoff n1=25\n.levels 3\n",
        "sweepable",
    )
    assert "EJ0" in device.sweepable_parameters()
    assert device.sweepable_parameters()["EJ0"] == pytest.approx(15.0)


def test_sweep_over_a_named_parameter():
    device = build(
        ".param EJ0 = 15\nJ1 1 0 EJ=EJ0 EC=1e6\nC1 1 0 EC=0.3\n.cutoff n1=25\n.levels 3\n",
        "sweep",
    )
    result = device.sweep("EJ0", [10.0, 15.0, 20.0], levels=3)
    f01 = [row[1] for row in result["transitions_ghz"]]
    # f01 ~ sqrt(8 EJ EC) - EC, so it must rise monotonically with EJ. The
    # tolerance is loose because that expression is the leading order of an
    # asymptotic expansion in EC/EJ, not the exact transition frequency.
    assert f01[0] < f01[1] < f01[2]
    assert f01[1] == pytest.approx(np.sqrt(8 * 15.0 * 0.3) - 0.3, rel=1e-2)
    assert result["unit"] == "GHz"


def test_sweep_restores_the_parameter_afterwards():
    device = build(FLUXONIUM_NETLIST, "restore_sweep")
    name = device.external_flux_names()[0]
    before = float(getattr(device.circuit, name))
    device.sweep("flux", [0.0, 0.25, 0.5], levels=3)
    assert float(getattr(device.circuit, name)) == pytest.approx(before)


def test_flux_sweep_is_symmetric_about_the_sweet_spot():
    """A fluxonium's spectrum is symmetric about half a flux quantum."""
    device = build(FLUXONIUM_NETLIST, "flux_sweep")
    result = device.sweep("flux", [0.25, 0.5, 0.75], levels=3)
    f01 = [row[1] for row in result["transitions_ghz"]]
    assert f01[0] == pytest.approx(f01[2], rel=1e-6)
    assert f01[1] < f01[0]  # the sweet spot is the minimum
    assert result["unit"] == "Phi_0"


def test_parameter_names_can_be_spelled_the_friendly_way():
    device = build(FLUXONIUM_NETLIST, "names")
    scqubits_name = device.external_flux_names()[0]
    for spelling in ("flux", "flux1", scqubits_name):
        assert device.resolve_parameter(spelling) == scqubits_name


def test_unknown_parameter_is_rejected():
    device = build(TRANSMON_NETLIST, "unknown")
    with pytest.raises(DeviceError):
        device.resolve_parameter("not_a_knob")


# ---------------------------------------------------------------------------
# Analysis output
# ---------------------------------------------------------------------------


def test_analysis_result_shape_and_serializability():
    device = build(TRANSMON_NETLIST, "analysis")
    result = device.analyze()
    for key in (
        "name",
        "energies_ghz",
        "relative_ghz",
        "f01_ghz",
        "anharmonicity_mhz",
        "circuit",
        "coherence",
        "matrix_elements",
        "dissipation",
        "notes",
        "warnings",
    ):
        assert key in result
    assert result["relative_ghz"][0] == pytest.approx(0.0)
    json.dumps(result)


def test_analysis_keys_are_present_even_when_sections_are_skipped():
    device = build(TRANSMON_NETLIST, "skipped")
    result = device.analyze(coherence=False, matrix_elements=False, convergence=False)
    assert result["coherence"]["available"] is False
    assert result["matrix_elements"]["operators"] == {}


def test_anharmonicity_is_flagged_as_meaningless_for_multiple_modes():
    """With two modes, levels 1 and 2 need not belong to the same ladder."""
    single = build(TRANSMON_NETLIST, "single").spectrum(4)
    assert single["anharmonicity_meaningful"] is True

    pair = build(
        "J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\nJ2 2 0 EJ=14 EC=1e6\nC2 2 0 EC=0.3\n"
        "Cc 1 2 EC=9.7\n.cutoff all = 10\n.levels 4\n",
        "pair",
    ).spectrum(4)
    assert pair["num_modes"] == 2
    assert pair["anharmonicity_meaningful"] is False
    assert "modes" in pair["anharmonicity_note"]


def test_harmonic_circuit_reports_no_meaningful_anharmonicity():
    result = build("L1 1 0 100nH\nC1 1 0 90fF\n.levels 4\n", "harmonic").spectrum(4)
    assert result["anharmonicity_meaningful"] is False
    assert result["anharmonicity_ghz"] == pytest.approx(0.0, abs=1e-3)


def test_charge_matrix_elements_are_hermitian_and_have_no_diagonal():
    device = build(TRANSMON_NETLIST, "matelem")
    table = device.charge_matrix_elements(4)["operators"]["n1"]["abs"]
    matrix = np.array(table)
    assert matrix == pytest.approx(matrix.T, abs=1e-9)
    assert np.all(np.abs(np.diag(matrix)) < 1e-9)
    # A transmon's charge operator connects neighbouring levels most strongly.
    assert matrix[0, 1] > matrix[0, 3]


def test_resistors_produce_a_classical_loading_estimate():
    device = build(
        "J1 1 0 EJ=15 Cj=2fF\nC1 1 0 90fF\nR1 1 0 1MOhm\n.cutoff n1=25\n.levels 3\n",
        "lossy",
    )
    result = device.analyze(coherence=False, matrix_elements=False, convergence=False)
    entry = result["dissipation"][0]
    assert entry["resistance_ohm"] == pytest.approx(1e6)
    # tau = R * C over the 92 fF that sit across the same node pair.
    assert entry["parallel_capacitance_f"] == pytest.approx(92e-15, rel=1e-3)
    assert entry["tau_rc_ns"] == pytest.approx(1e6 * 92e-15 * 1e9, rel=1e-3)
    assert entry["quality_factor"] == pytest.approx(
        2 * np.pi * result["f01_ghz"] * 1e9 * 1e6 * 92e-15, rel=1e-3
    )


def test_coherence_estimates_are_positive_and_in_microseconds():
    device = build(TRANSMON_NETLIST, "coherence")
    coherence = device.coherence()
    assert coherence["available"] is True
    assert coherence["channels"]
    for data in coherence["channels"].values():
        assert data["time_us"] > 0
    # A transmon of these parameters lands in the tens of microseconds.
    assert 1.0 < coherence["t1_effective_us"] < 1e4


def test_effective_operators_carry_the_2pi_conversion():
    device = build(TRANSMON_NETLIST, "operators")
    operators = device.effective_operators(levels=3)
    diagonal_ghz = np.real(operators["H_ghz"].full().diagonal())
    diagonal_rad = np.real(operators["H_rad_per_ns"].full().diagonal())
    assert diagonal_ghz[0] == pytest.approx(0.0)
    assert diagonal_rad == pytest.approx(2 * np.pi * diagonal_ghz)
    # Leakage levels survive the truncation rather than being projected away.
    assert operators["H_ghz"].shape == (3, 3)
    assert "n1" in operators["charge_operators"]


def test_ill_conditioned_circuit_still_diagonalizes():
    """
    A Hamiltonian spanning many orders of magnitude can defeat ARPACK.

    scqubits reaches for the sparse iterative solver by default, and on a circuit
    like this one it exhausts its iterations without converging. The engine must
    fall back to a dense solve rather than surfacing an ARPACK traceback for a
    circuit the user just drew.
    """
    device = build(
        "J1 0 1 EJ=60 EC=6.45674\n"
        "J2 1 2 EJ=60 EC=6.45674\n"
        "J3 2 0 EJ=2.58e10 EC=12.9135\n"
        "C1 2 0 EC=0.43045\n"
        "C2 1 0 EC=9.68511\n"
        ".cutoff all = 11\n"
        ".levels 5\n"
        ".options generate_noise_methods=false\n",
        "ill_conditioned",
    )
    energies = device.eigenvalues(5)
    assert len(energies) == 5
    assert np.all(np.isfinite(energies))


def test_netlist_notes_are_not_reported_as_warnings():
    """
    "This value was read as GHz" describes how the netlist was parsed; it is not
    a sign that anything went wrong, and must not be presented as one.
    """
    device = build("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\n.cutoff n1=25\n.levels 3\n", "notes")
    result = device.analyze(coherence=False, matrix_elements=False, convergence=False)
    assert any("read as GHz" in note for note in result["notes"])
    assert not any("read as GHz" in warning for warning in result["warnings"])


def test_eigensystem_returns_values_and_states():
    device = build(TRANSMON_NETLIST, "eigensystem")
    evals, evecs = device.eigensystem(4)
    assert len(evals) == 4
    assert evecs.shape[1] == 4
    assert evals == pytest.approx(device.eigenvalues(4))


def test_asking_for_more_levels_than_the_basis_holds_is_rejected():
    device = build("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\n.cutoff n1 = 2\n.levels 3\n", "tiny")
    with pytest.raises(DeviceError, match="Hilbert space"):
        device.eigenvalues(500)


# ---------------------------------------------------------------------------
# Registry and persistence
# ---------------------------------------------------------------------------


def test_engine_registers_and_retrieves_devices(tmp_path):
    engine = DeviceEngine(output_dir=str(tmp_path))
    device = engine.create_device(TRANSMON_NETLIST, name="mydev")
    assert device.name == "mydev"
    assert engine.has_device("mydev")
    assert engine.get_device("mydev") is device
    assert [entry["name"] for entry in engine.list_devices()] == ["mydev"]


def test_engine_refuses_to_shadow_an_existing_device(tmp_path):
    engine = DeviceEngine(output_dir=str(tmp_path))
    engine.create_device(TRANSMON_NETLIST, name="dup")
    with pytest.raises(DeviceError, match="already exists"):
        engine.create_device(TRANSMON_NETLIST, name="dup")
    engine.create_device(TRANSMON_NETLIST, name="dup", overwrite=True)


def test_session_round_trips_through_disk(tmp_path):
    """A reloaded session rebuilds from the netlist, so the physics is identical."""
    engine = DeviceEngine(output_dir=str(tmp_path))
    engine.create_device(TRANSMON_NETLIST, name="persisted")
    expected = engine.get_device("persisted").spectrum(3)["f01_ghz"]

    reloaded = DeviceEngine(output_dir=str(tmp_path))
    assert reloaded.has_device("persisted")
    assert reloaded.get_device("persisted").spectrum(3)["f01_ghz"] == pytest.approx(expected)


def test_delete_removes_a_device(tmp_path):
    engine = DeviceEngine(output_dir=str(tmp_path))
    engine.create_device(TRANSMON_NETLIST, name="gone")
    engine.delete_device("gone")
    assert not engine.has_device("gone")
    with pytest.raises(DeviceError):
        engine.get_device("gone")


def test_save_netlist_and_result(tmp_path):
    engine = DeviceEngine(output_dir=str(tmp_path))
    device = engine.create_device(TRANSMON_NETLIST, name="saved")
    netlist_path = engine.save_netlist("saved", str(tmp_path / "saved.qdl"))
    assert "J1" in open(netlist_path, encoding="utf-8").read()

    result = device.analyze(coherence=False, matrix_elements=False, convergence=False)
    result_path = engine.save_result("saved", result)
    with open(result_path, encoding="utf-8") as handle:
        assert json.load(handle)["name"] == "saved"


# ---------------------------------------------------------------------------
# Bundled templates
# ---------------------------------------------------------------------------


def test_every_template_parses():
    for template in list_templates():
        netlist = parse_netlist(template.source)
        assert netlist.elements
        assert netlist.title


@pytest.mark.parametrize(
    "key", [key for key, template in TEMPLATES.items() if template.cost == "fast"]
)
def test_fast_templates_produce_a_sensible_spectrum(key):
    device = QuantumDevice(parse_netlist(template_source(key)))
    result = device.spectrum()
    assert result["f01_ghz"] > 0
    assert result["relative_ghz"][0] == pytest.approx(0.0)
    assert all(
        later >= earlier
        for earlier, later in zip(result["relative_ghz"], result["relative_ghz"][1:])
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "key", [key for key, template in TEMPLATES.items() if template.cost != "fast"]
)
def test_slower_templates_quantize(key):
    device = QuantumDevice(parse_netlist(template_source(key)))
    assert device.spectrum()["f01_ghz"] > 0
