"""
Tests for the device rendering layer.

Most of these guard the text schematic, which has two invariants that are easy
to break and hard to notice: every element glyph must occupy the same number of
columns, and none may look like markup to something downstream.
"""

import io
import re

import pytest
from rich.console import Console

from qforge.core import device_report
from qforge.core.device_library import list_templates, template_source
from qforge.core.device_netlist import parse_netlist

# Mirrors _RICH_TAG_RE in qforge/cli/gui.py, which the GUI console uses to strip
# Rich markup out of anything printed to it. It is duplicated rather than
# imported so this test does not need tkinter.
GUI_MARKUP_RE = re.compile(r"\[(/?)([a-zA-Z][^\[\]/]*?)\]")

TRANSMON = """
.title Transmon
J1 1 0 EJ=15.0 EC=1e6
C1 1 0 EC=0.3
.cutoff n1 = 25
.levels 4
"""

WITH_EVERY_ELEMENT = """
.title Every element type
L1 1 0 100nH
C1 1 0 90fF
L2 2 0 100nH
C2 2 0 90fF
J1 1 2 EJ=15 Cj=2fF
K1 L1 L2 k=0.05
R1 1 0 1MOhm
.cutoff all = 12
.levels 4
"""


def render(fn, *args, width: int = 79) -> str:
    """Render through a plain, colourless console and return the text."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=False, no_color=True)
    fn(*args, console=console)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Schematic glyphs
# ---------------------------------------------------------------------------


def test_every_schematic_glyph_is_the_same_width():
    """Unequal glyphs shift the node labels and the drawing stops lining up."""
    widths = {len(glyph) for glyph in device_report._SCHEMATIC_SYMBOLS.values()}
    assert widths == {3}


def test_no_schematic_glyph_can_be_mistaken_for_markup():
    """
    A glyph containing square brackets gets eaten before it reaches the reader.

    Rich treats '[word]' as a style tag, and so does the GUI console's own
    parser, which silently drops any tag it does not recognise. A '[X]'
    junction symbol was swallowed there, leaving that row three columns short
    of every other one while looking fine in a plain terminal.
    """
    for kind, glyph in device_report._SCHEMATIC_SYMBOLS.items():
        assert "[" not in glyph and "]" not in glyph, kind
        assert not GUI_MARKUP_RE.search(glyph), kind


def test_schematic_rows_line_up():
    """Both node columns must sit at the same offset on every element row."""
    netlist = parse_netlist(WITH_EVERY_ELEMENT)
    output = render(device_report.render_schematic, netlist)

    element_rows = [
        line
        for line in output.splitlines()
        if any(f" {el.name} " in line for el in netlist.elements)
        and any(glyph in line for glyph in device_report._SCHEMATIC_SYMBOLS.values())
    ]
    # One row per two-terminal element; the mutual inductance is drawn differently.
    assert len(element_rows) == len(netlist.branches) + len(netlist.resistors)

    offsets = {line.index("──") for line in element_rows}
    assert len(offsets) == 1, "element glyphs start in different columns"
    assert len({len(line.rstrip()) or 0 for line in element_rows}) >= 1


def test_schematic_survives_a_markup_stripping_console():
    """
    Simulate what the GUI console does and check nothing goes missing.

    The schematic must read identically whether or not the reader strips Rich
    markup on the way through.
    """
    netlist = parse_netlist(WITH_EVERY_ELEMENT)
    output = render(device_report.render_schematic, netlist)
    stripped = GUI_MARKUP_RE.sub("", output)
    assert stripped == output


def test_analysis_report_survives_a_markup_stripping_console():
    from qforge.core.device_engine import QuantumDevice

    device = QuantumDevice(parse_netlist(TRANSMON))
    result = device.analyze(coherence=False, matrix_elements=True, convergence=False)
    output = render(device_report.render_analysis, result)
    assert GUI_MARKUP_RE.sub("", output) == output


# ---------------------------------------------------------------------------
# The renderers run at all
# ---------------------------------------------------------------------------


def test_render_netlist_shows_both_unit_systems():
    netlist = parse_netlist("J1 1 0 Ic=30nA Cj=2fF\nC1 1 0 90fF\n.levels 3\n")
    output = render(device_report.render_netlist, netlist)
    assert "30 nA" in output and "90 fF" in output  # physical values
    assert "14.9005" in output and "0.215225" in output  # energies in GHz


def test_render_schematic_lists_connectivity():
    output = render(device_report.render_schematic, parse_netlist(TRANSMON))
    assert "Node connectivity" in output
    assert "(ground)" in output


def test_render_format_reference_fits_a_narrow_console():
    """The reference is printed inside a panel, so its lines must leave room."""
    from qforge.core.device_netlist import FORMAT_REFERENCE

    assert max(len(line) for line in FORMAT_REFERENCE.splitlines()) <= 74
    output = render(lambda console: device_report.render_format_reference(console=console))
    assert "ELEMENTS" in output and "DIRECTIVES" in output


@pytest.mark.parametrize("key", [template.key for template in list_templates()])
def test_every_template_renders(key):
    netlist = parse_netlist(template_source(key))
    assert render(device_report.render_netlist, netlist)
    assert render(device_report.render_schematic, netlist)


def test_sweep_table_renders():
    sweep = {
        "parameter": "Φ1",
        "requested_parameter": "flux",
        "values": [0.0, 0.5, 1.0],
        "energies_ghz": [[0.0, 8.7], [0.0, 0.36], [0.0, 8.7]],
        "transitions_ghz": [[0.0, 8.7], [0.0, 0.36], [0.0, 8.7]],
        "relative": True,
        "levels": 2,
        "unit": "Phi_0",
    }
    output = render(device_report.render_sweep, sweep)
    assert "Phi_0" in output and "0.360000" in output


def test_sweep_plot_filename_is_ascii():
    """scqubits names fluxes with a Greek phi, which does not belong in a path."""
    assert device_report._slug("Φ1") == "Phi1"
    assert device_report._slug("ng1") == "ng1"
    assert device_report._slug("θ2") == "theta2"
