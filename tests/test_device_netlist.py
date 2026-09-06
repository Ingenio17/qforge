"""
Tests for the device netlist language: parsing, units, validation and emission.

These cover the front end only. The physics that comes out the other side is
tested in ``test_device_engine.py``, against the scqubits qubit classes whose
circuits the netlists reproduce.
"""

import pytest

from qforge.core.device_netlist import (
    EC_to_capacitance,
    EJ_to_critical_current,
    EJ_to_josephson_inductance,
    EL_to_inductance,
    EML_to_mutual_inductance,
    NetlistError,
    capacitance_to_EC,
    coupling_coefficient,
    critical_current_to_EJ,
    format_si,
    inductance_to_EL,
    mutual_inductance_to_EML,
    parse_netlist,
    split_quantity,
)

TRANSMON = """
.title Transmon
J1 1 0 EJ=15.0 EC=1e6
C1 1 0 EC=0.3
.levels 5
"""


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def test_capacitance_energy_round_trip():
    """EC = e^2/2C must invert exactly."""
    for farads in (1e-15, 9e-14, 2.5e-13):
        assert EC_to_capacitance(capacitance_to_EC(farads)) == pytest.approx(farads, rel=1e-12)


def test_inductance_energy_round_trip():
    for henries in (1e-9, 1e-7, 3.27e-7):
        assert EL_to_inductance(inductance_to_EL(henries)) == pytest.approx(henries, rel=1e-12)


def test_critical_current_energy_round_trip():
    for amps in (1e-9, 3e-8, 1e-6):
        assert EJ_to_critical_current(critical_current_to_EJ(amps)) == pytest.approx(
            amps, rel=1e-12
        )


def test_known_conversion_values():
    """Spot-check against the numbers a superconducting-qubit designer expects."""
    # A 90 fF shunt is a typical transmon, giving EC around 0.2 GHz.
    assert capacitance_to_EC(90e-15) == pytest.approx(0.2152, rel=1e-3)
    # A 327 nH superinductor is a typical fluxonium, giving EL around 0.5 GHz.
    assert inductance_to_EL(327e-9) == pytest.approx(0.4999, rel=1e-3)
    # 30 nA of critical current is a typical transmon junction, EJ near 15 GHz.
    assert critical_current_to_EJ(30e-9) == pytest.approx(14.90, rel=1e-3)


def test_josephson_inductance_matches_inductive_energy():
    """L_J and a linear L map onto their energy through the same expression."""
    ej = 15.0
    assert EJ_to_josephson_inductance(ej) == pytest.approx(EL_to_inductance(ej), rel=1e-12)


def test_split_quantity_units_and_prefixes():
    assert split_quantity("90fF") == (pytest.approx(9e-14), "F", "capacitance")
    assert split_quantity("100nH") == (pytest.approx(1e-7), "H", "inductance")
    assert split_quantity("30nA") == (pytest.approx(3e-8), "A", "current")
    assert split_quantity("15GHz") == (pytest.approx(1.5e10), "Hz", "frequency")
    assert split_quantity("0.3") == (pytest.approx(0.3), None, None)


def test_si_prefixes_are_case_sensitive():
    """'M' is mega and 'm' is milli; conflating them is a million-fold error."""
    mega, _, _ = split_quantity("1MOhm")
    milli, _, _ = split_quantity("1mOhm")
    assert mega == pytest.approx(1e6)
    assert milli == pytest.approx(1e-3)


def test_unknown_unit_is_rejected():
    with pytest.raises(ValueError):
        split_quantity("5Watt")


def test_format_si_picks_the_natural_prefix():
    assert format_si(9e-14, "F") == "90 fF"
    assert format_si(1e-15, "F") == "1 fF"
    assert format_si(1e6, "Ohm") == "1 MOhm"
    assert format_si(None, "F") == "n/a"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_minimal_transmon():
    netlist = parse_netlist(TRANSMON, name="t")
    assert netlist.title == "Transmon"
    assert netlist.levels == 5
    assert len(netlist.elements) == 2
    assert netlist.num_nodes == 1
    assert netlist.is_grounded
    assert [el.kind for el in netlist.elements] == ["JJ", "C"]


def test_physical_and_energy_units_agree():
    """The same junction written two ways must produce the same energies."""
    energy_form = parse_netlist("J1 1 0 EJ=14.9005 EC=9.68511\nC1 1 0 EC=0.215225\n")
    physical_form = parse_netlist("J1 1 0 Ic=30nA Cj=2fF\nC1 1 0 90fF\n")
    for a, b in zip(energy_form.elements, physical_form.elements):
        for role, value in a.values.items():
            assert value.ghz == pytest.approx(b.values[role].ghz, rel=1e-4)


def test_ground_aliases():
    for label in ("0", "gnd", "GND", "ground"):
        netlist = parse_netlist(f"J1 1 {label} EJ=15 EC=1e6\nC1 1 {label} EC=0.3\n")
        assert netlist.num_nodes == 1
        assert netlist.is_grounded


def test_named_nodes_are_mapped_to_indices():
    netlist = parse_netlist("J1 island gnd EJ=15 EC=1e6\nC1 island gnd EC=0.3\n")
    assert set(netlist.node_map) == {"island"}
    assert netlist.node_map["island"] == 1


def test_comments_and_continuations():
    netlist = parse_netlist("""
* a full-line comment
.title Continued   ; trailing comment
J1 1 0 EJ=15
+ EC=1e6              # continued onto the next line
C1 1 0 EC=0.3         // and another comment style
""")
    assert netlist.title == "Continued"
    assert netlist.elements[0].values["EC"].ghz == pytest.approx(1e6)


def test_params_and_expressions():
    netlist = parse_netlist("""
.param EJ0 = 15
.param RATIO = 50
J1 1 0 EJ=EJ0 EC=1e6
C1 1 0 EC={EJ0/RATIO}
""")
    assert netlist.params["EJ0"].value == 15
    assert netlist.elements[1].values["EC"].ghz == pytest.approx(0.3)
    # A bare .param reference stays symbolic and therefore sweepable; an
    # expression is folded into a number.
    assert netlist.elements[0].values["EJ"].symbol == "EJ0"
    assert netlist.elements[1].values["EC"].symbol is None


def test_expression_rejects_arbitrary_code():
    with pytest.raises(NetlistError):
        parse_netlist("J1 1 0 EJ={__import__('os').getcwd()} EC=1e6\nC1 1 0 EC=0.3\n")


def test_expression_inherits_the_units_of_its_parameters():
    """
    A .param with a unit is stored in SI, so an expression over it is SI too.

    Without this, '.param EJ0 = 60GHz' with 'EJ={EJ0*ALPHA}' would read 2.58e10
    as GHz instead of Hz: a factor of a billion, silently.
    """
    netlist = parse_netlist("""
.param EJ0 = 60GHz
.param ALPHA = 0.43
J1 1 0 EJ={EJ0*ALPHA} EC=1e6
C1 1 0 EC=0.3
""")
    assert netlist.elements[0].values["EJ"].ghz == pytest.approx(25.8, rel=1e-9)
    assert any("read as a frequency" in note for note in netlist.notes)


def test_expression_over_dimensionless_params_stays_in_ghz():
    netlist = parse_netlist(
        ".param EJ0 = 60\n.param ALPHA = 0.43\nJ1 1 0 EJ={EJ0*ALPHA} EC=1e6\nC1 1 0 EC=0.3\n"
    )
    assert netlist.elements[0].values["EJ"].ghz == pytest.approx(25.8, rel=1e-9)


def test_expression_mixing_physical_dimensions_is_rejected():
    with pytest.raises(NetlistError, match="only combine parameters"):
        parse_netlist(
            ".param CAP = 90fF\n.param IND = 100nH\n" "J1 1 0 EJ={CAP*IND} EC=1e6\nC1 1 0 EC=0.3\n"
        )


def test_derived_param_keeps_its_dimension():
    """A .param defined from another one carries the same units onward."""
    netlist = parse_netlist("""
.param EJ0 = 60GHz
.param EJ_SMALL = {EJ0*0.43}
J1 1 0 EJ=EJ_SMALL EC=1e6
C1 1 0 EC=0.3
""")
    assert netlist.params["EJ_SMALL"].dimension == "frequency"
    assert netlist.elements[0].values["EJ"].ghz == pytest.approx(25.8, rel=1e-9)


def test_junction_without_capacitance_gets_a_negligible_one():
    netlist = parse_netlist("J1 1 0 EJ=15\nC1 1 0 EC=0.3\n")
    from qforge.core.device_netlist import NEGLIGIBLE_JUNCTION_EC_GHZ

    assert netlist.elements[0].values["EC"].ghz == NEGLIGIBLE_JUNCTION_EC_GHZ
    assert any("negligible" in note for note in netlist.notes)


def test_higher_junction_harmonics():
    netlist = parse_netlist("J1 1 0 EJ=15 EJ2=1.5 EC=0.3\nC1 1 0 EC=0.3\n")
    junction = netlist.elements[0]
    assert junction.junction_order == 2
    assert junction.scqubits_type == "JJ2"
    assert junction.values["EJ2"].ghz == pytest.approx(1.5)


def test_resistors_are_parsed_but_excluded_from_the_hamiltonian():
    netlist = parse_netlist("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\nR1 1 0 1MOhm\n")
    assert len(netlist.resistors) == 1
    assert netlist.resistors[0].resistance_ohm == pytest.approx(1e6)
    assert netlist.resistors[0] not in netlist.branches
    assert "R" not in netlist.to_scqubits_yaml()


def test_loop_count_ignores_capacitive_loops():
    """Only inductive loops can hold a flux, so only they count."""
    # A transmon's junction and capacitor form a loop in the graph, but a
    # capacitor carries no persistent current, so there is no flux to thread.
    assert parse_netlist(TRANSMON).num_loops == 0
    # A fluxonium's junction and inductor do form a real, flux-threaded loop.
    assert parse_netlist("J1 1 0 EJ=8.9 EC=2.5\nL1 1 0 EL=0.5\n").num_loops == 1
    # Three junctions in a ring is still one loop.
    three_jj = parse_netlist(
        "J1 0 1 EJ=35 EC=1\nJ2 1 2 EJ=35 EC=1\nJ3 2 0 EJ=24 EC=1.4\n" "C1 1 0 EC=50\nC2 2 0 EC=50\n"
    )
    assert three_jj.num_loops == 1


# ---------------------------------------------------------------------------
# Mutual inductance
# ---------------------------------------------------------------------------


def test_mutual_inductance_conversion_carries_the_scqubits_factor():
    """
    scqubits' EML is not simply (Phi_0/2pi)^2 / M; it carries a factor of two.

    The factor was measured from the normal-mode splitting of two coupled LC
    oscillators. If it ever changes, a netlist written with k = 0.05 would
    silently model a different circuit, so it is pinned here.
    """
    from qforge.core.device_netlist import SCQUBITS_ML_FACTOR

    assert SCQUBITS_ML_FACTOR == 2.0
    mutual = 5e-9
    assert mutual_inductance_to_EML(mutual) == pytest.approx(2.0 * inductance_to_EL(mutual))
    assert EML_to_mutual_inductance(mutual_inductance_to_EML(mutual)) == pytest.approx(
        mutual, rel=1e-12
    )


def test_coupling_coefficient_forms_agree():
    """k=0.05 and the equivalent mutual inductance must produce the same branch."""
    by_k = parse_netlist("L1 1 0 100nH\nC1 1 0 90fF\nL2 2 0 100nH\nC2 2 0 90fF\nK1 L1 L2 k=0.05\n")
    by_m = parse_netlist("L1 1 0 100nH\nC1 1 0 90fF\nL2 2 0 100nH\nC2 2 0 90fF\nK1 L1 L2 M=5nH\n")
    assert by_k.couplers[0].values["EML"].ghz == pytest.approx(
        by_m.couplers[0].values["EML"].ghz, rel=1e-9
    )
    assert by_k.couplers[0].coupling_coefficient == pytest.approx(0.05, rel=1e-6)


def test_coupling_coefficient_is_computed_from_energies():
    el = inductance_to_EL(100e-9)
    eml = mutual_inductance_to_EML(5e-9)
    assert coupling_coefficient(el, el, eml) == pytest.approx(0.05, rel=1e-9)


def test_impossible_mutual_inductance_is_rejected():
    """k > 1 means the inductors share more flux than they store."""
    with pytest.raises(NetlistError, match="impossible"):
        parse_netlist("L1 1 0 100nH\nC1 1 0 90fF\nL2 2 0 100nH\nC2 2 0 90fF\nK1 L1 L2 M=500nH\n")
    with pytest.raises(NetlistError, match="0 < k"):
        parse_netlist("L1 1 0 100nH\nC1 1 0 90fF\nL2 2 0 100nH\nC2 2 0 90fF\nK1 L1 L2 k=1.5\n")


def test_mutual_inductance_only_couples_inductors():
    with pytest.raises(NetlistError, match="only defined"):
        parse_netlist("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\nK1 J1 C1 M=1nH\n")


# ---------------------------------------------------------------------------
# Validation and error reporting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, fragment",
    [
        ("Z9 1 0 5\n", "does not name an element"),
        ("J1 1 1 EJ=15 EC=0.3\n", "short-circuits"),
        ("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\n.foo 3\n", "unknown directive"),
        ("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\n.param x = {1/0}\n", "division by zero"),
        ("J1 1 0 EJ=15 EC=1e6\nC1 1 0 C=0.3\n", "must be given as a capacitance"),
        ("J1 1 0 EJ=15 EC=1mOhm\nC1 1 0 EC=0.3\n", "cannot define EC"),
        ("R1 1 0 1MOhm\n", "no capacitors, inductors or junctions"),
        ("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\nJ1 1 0 EJ=1 EC=1\n", "already defined"),
        ("J1 1 0 EJ=-5 EC=0.3\n", "positive"),
    ],
)
def test_invalid_netlists_are_rejected(source, fragment):
    with pytest.raises(NetlistError) as excinfo:
        parse_netlist(source)
    assert fragment in str(excinfo.value)


def test_errors_carry_a_line_number():
    with pytest.raises(NetlistError) as excinfo:
        parse_netlist("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\nZ9 1 0 5\n")
    assert excinfo.value.line_no == 3
    assert "line 3" in str(excinfo.value)


def test_dangling_node_is_rejected():
    """A node with one branch has no dynamics and a singular capacitance matrix."""
    with pytest.raises(NetlistError, match="fewer than two branches"):
        parse_netlist("J1 1 0 EJ=15 EC=1e6\nC1 1 0 EC=0.3\nCx 1 pad EC=0.1\n")


def test_node_without_capacitance_is_rejected():
    with pytest.raises(NetlistError, match="no capacitance"):
        parse_netlist("L1 1 0 EL=0.5\nL2 1 0 EL=0.6\n")


def test_floating_circuit_is_allowed_but_noted():
    netlist = parse_netlist("J1 1 2 EJ=15 EC=0.3\nC1 1 2 EC=0.4\n")
    assert not netlist.is_grounded
    assert any("floating" in note for note in netlist.notes)


def test_harmonic_circuit_is_noted():
    netlist = parse_netlist("L1 1 0 100nH\nC1 1 0 90fF\n")
    assert any("no Josephson junctions" in note for note in netlist.notes)


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def test_emitted_yaml_has_one_branch_per_element():
    netlist = parse_netlist(TRANSMON)
    lines = [line for line in netlist.to_scqubits_yaml().splitlines() if line.startswith("- [")]
    assert len(lines) == 2
    assert lines[0].startswith("- [JJ, 1, 0,")
    assert lines[1].startswith("- [C, 1, 0,")


def test_symbols_are_declared_once_then_referenced():
    """scqubits wants 'NAME = value' on first use and a bare 'NAME' afterwards."""
    netlist = parse_netlist("""
.param EJ0 = 35
J1 0 1 EJ=EJ0 EC=1.0
J2 1 2 EJ=EJ0 EC=1.0
C1 1 0 EC=50
C2 2 0 EC=50
""")
    yaml = netlist.to_scqubits_yaml()
    assert yaml.count("EJ0 = 35.0") == 1
    assert "EJ0]" in yaml or "EJ0," in yaml  # the second use is a bare reference
    assert netlist.symbol_defaults()["EJ0"] == pytest.approx(35.0)


def test_couplers_are_emitted_after_the_branches_they_reference():
    netlist = parse_netlist(
        "L1 1 0 100nH\nC1 1 0 90fF\nL2 2 0 100nH\nC2 2 0 90fF\nK1 L1 L2 k=0.1\n"
    )
    lines = [line for line in netlist.to_scqubits_yaml().splitlines() if line.startswith("- [")]
    assert lines[-1].startswith("- [ML, 0, 2,")  # branch indices of L1 and L2


def test_capacitance_between_sums_the_right_branches():
    netlist = parse_netlist("J1 1 0 EJ=15 Cj=2fF\nC1 1 0 90fF\nR1 1 0 1MOhm\n")
    assert netlist.capacitance_between(1, 0) == pytest.approx(92e-15, rel=1e-3)


def test_describe_is_serializable():
    import json

    json.dumps(parse_netlist(TRANSMON).describe())
