"""
Worked device netlists, from an LC resonator to zero-pi.

Every template here is a complete, runnable schematic in the language defined by
:mod:`qforge.core.device_netlist`, and doubles as documentation of that language
by example. They are also the starting point the CLI and GUI offer when someone
asks to design a device without having a file to hand: pick one, save it, edit
the numbers, re-run.

Each template records a rough ``cost``, because a circuit's Hilbert space is the
product over its modes and a three-mode design takes a great deal longer than a
transmon. The parameters were chosen to sit in each circuit's usual regime and
were checked against the corresponding scqubits qubit class where one exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DeviceTemplate",
    "TEMPLATES",
    "list_templates",
    "get_template",
    "template_source",
    "write_template",
    "NETLIST_EXTENSIONS",
]

# Extensions the CLI and GUI offer when browsing for a device netlist.
NETLIST_EXTENSIONS = (".qdl", ".net", ".cir", ".sp", ".txt")


@dataclass(frozen=True)
class DeviceTemplate:
    """One bundled example netlist."""

    key: str
    title: str
    description: str
    cost: str  # "fast" | "moderate" | "heavy"
    source: str

    @property
    def label(self) -> str:
        """A one-line label for a menu."""
        return f"{self.title}  ({self.cost})"


_TRANSMON = """\
* Transmon: a junction shunted by a large capacitor.
*
* The large shunt capacitor pushes EJ/EC into the tens, which flattens the charge
* dispersion (the transmon's whole point) at the cost of a small anharmonicity.
* Written in physical units, so the numbers are the ones a fabricator works with.

.title  Transmon
.name   transmon

.param  IC = 30nA               ; junction critical current -> EJ ~ 14.9 GHz

J1  1  0  EJ=IC  Cj=2fF         ; junction, with its own self-capacitance
C1  1  0  90fF                  ; shunt capacitor -> EC ~ 0.215 GHz

.charge 1 = 0.0                 ; offset charge, in Cooper pairs
.cutoff n1 = 30                 ; charge basis cutoff
.levels 6
.end
"""

_COOPER_PAIR_BOX = """\
* Cooper-pair box: the transmon's ancestor, before the shunt capacitor.
*
* With EJ/EC of order 1 the levels depend strongly on the offset charge, which is
* what makes this a charge qubit and why it was superseded. Sweep the offset
* charge from -1 to 1 to see the charge dispersion directly.

.title  Cooper-pair box
.name   cooper_pair_box

J1  1  0  Ic=10nA  Cj=1fF       ; EJ ~ 4.97 GHz
C1  1  0  3fF                   ; EC ~ 6.5 GHz  ->  EJ/EC below 1

.charge 1 = 0.5                 ; the degeneracy point, where dephasing is slowest
.cutoff n1 = 20
.levels 5
.end
"""

_FLUXONIUM = """\
* Fluxonium: a junction shunted by a superinductor.
*
* The large inductance (hundreds of nH, from an array of junctions in practice)
* gives a small EL, and at half a flux quantum the two lowest states are deep in
* separate wells. That produces a very low transition frequency and long
* coherence. Sweep the flux from 0 to 1 to see the sweet spot.

.title  Fluxonium
.name   fluxonium

J1  1  0  Ic=17.9nA  Cj=7.75fF  ; EJ ~ 8.9 GHz, EC ~ 2.5 GHz
L1  1  0  327nH                 ; superinductor -> EL ~ 0.5 GHz

.flux   1 = 0.5                 ; half a flux quantum: the sweet spot
.cutoff ext1 = 110              ; the flux variable needs a fine grid here
.levels 6
.end
"""

_FLUX_QUBIT = """\
* Three-junction flux qubit.
*
* A loop of three junctions, one of them smaller by a factor alpha. Near half a
* flux quantum the two lowest states are clockwise and anticlockwise persistent
* currents, and the gap between them is the qubit.

.title  Three-junction flux qubit
.name   flux_qubit

.param  EJ0   = 35.0            ; GHz, the two large junctions
.param  ALPHA = 0.7             ; the third junction is alpha times smaller

J1  0  1  EJ=EJ0    EC=1.0
J2  1  2  EJ=EJ0    EC=1.0
J3  2  0  EJ={EJ0*ALPHA}  EC={1.0/ALPHA}

Cg1 1  0  EC=50.0               ; small capacitance from each island to ground
Cg2 2  0  EC=50.0

.flux   1 = 0.5
.cutoff all = 10
.levels 5
.end
"""

_LC_RESONATOR = """\
* LC resonator: the simplest circuit this language can describe.
*
* No junction, so the potential is exactly quadratic, the ladder is evenly spaced
* and the anharmonicity is zero. Useful as a sanity check: the frequency should
* come out at 1/(2 pi sqrt(LC)) = 1.678 GHz.

.title  LC resonator
.name   lc_resonator

L1  1  0  100nH
C1  1  0  90fF

.levels 5
.end
"""

_TRANSMON_RESONATOR = """\
* A transmon capacitively coupled to a readout resonator.
*
* Two modes: the transmon near 4.7 GHz and the resonator near 7 GHz. The coupling
* capacitor Cc both couples them and loads each one's frequency downward, which
* is why the transmon here sits below the standalone transmon template.
*
* The resonator mode is nearly harmonic, so the harmonic oscillator basis needs
* far fewer states than a discretized flux grid would.

.title  Transmon coupled to a readout resonator
.name   transmon_resonator

J1  1  0  Ic=30nA  Cj=2fF       ; transmon junction
C1  1  0  90fF                  ; transmon shunt
Cc  1  2  5fF                   ; coupling capacitor
L2  2  0  2nH                   ; resonator inductance
C2  2  0  250fF                 ; resonator capacitance -> ~7 GHz

.options ext_basis=harmonic
.cutoff n1   = 12
.cutoff ext2 = 10
.levels 6
.end
"""

_COUPLED_TRANSMONS = """\
* Two transmons sharing a coupling capacitor.
*
* Slightly different critical currents detune them by about 200 MHz. Levels 1 and
* 2 are the two single-excitation states, one per qubit, so the spacing between
* them is a detuning and not an anharmonicity; qforge says so in the report.

.title  Two capacitively coupled transmons
.name   coupled_transmons

J1  1  0  Ic=30nA  Cj=2fF
C1  1  0  90fF

J2  2  0  Ic=28nA  Cj=2fF
C2  2  0  90fF

Cc  1  2  2fF                   ; capacitive coupling between the two islands

.cutoff all = 12
.levels 6
.end
"""

_ZERO_PI = """\
* Zero-pi: a protected qubit built from two junctions and two superinductors.
*
* The point of the topology is that the two logical states have disjoint support,
* which suppresses both relaxation and dephasing. It is also the most expensive
* circuit here: three modes, so the Hilbert space grows as the product of three
* cutoffs, and one analysis takes tens of seconds.
*
* The cutoffs below are deliberately coarse, for a first look. qforge's
* convergence check will say the spectrum has not converged, which is true: raise
* '.cutoff all' and watch the transitions settle. That is what the check is for.

.title  Zero-pi
.name   zero_pi

J1  0  2  EJ=10.0  EC=20.0
L1  2  3  EL=0.008
J2  3  4  EJ=10.0  EC=20.0
L2  4  0  EL=0.008
C1  0  3  EC=0.02
C2  2  4  EC=0.02

.flux   1 = 0.5
.cutoff all = 10
.levels 4
.options generate_noise_methods=false
.end
"""

_LOSSY_RESONATOR = """\
* An LC resonator with a resistor across it, and a second one coupled to it.
*
* Demonstrates the two elements that are not just C, L and JJ: a resistor, which
* is a classical load reported as an RC time and a loaded Q rather than entering
* the Hamiltonian, and a mutual inductance, written as a coupling coefficient k.
* Two identical resonators coupled by k split into normal modes at f0/sqrt(1 -/+ k).

.title  Coupled resonators with loss
.name   coupled_resonators

L1  1  0  100nH
C1  1  0  90fF
L2  2  0  100nH
C2  2  0  90fF

K1  L1 L2  k=0.05               ; mutual inductance, as a coupling coefficient
R1  1  0   1MOhm                ; environment loading node 1

.cutoff all = 40
.levels 4
.end
"""


TEMPLATES: dict[str, DeviceTemplate] = {
    template.key: template
    for template in (
        DeviceTemplate(
            "transmon",
            "Transmon",
            "A junction with a large shunt capacitor. The workhorse: ~4.8 GHz, "
            "anharmonicity around -235 MHz.",
            "fast",
            _TRANSMON,
        ),
        DeviceTemplate(
            "fluxonium",
            "Fluxonium",
            "A junction shunted by a 327 nH superinductor. Very low frequency at "
            "the half-flux sweet spot, long coherence.",
            "fast",
            _FLUXONIUM,
        ),
        DeviceTemplate(
            "cooper_pair_box",
            "Cooper-pair box",
            "A charge qubit with EJ/EC near 1. Strongly charge-dispersive; sweep "
            "the offset charge to see why the transmon replaced it.",
            "fast",
            _COOPER_PAIR_BOX,
        ),
        DeviceTemplate(
            "lc_resonator",
            "LC resonator",
            "No junction at all: an exactly harmonic mode at 1.678 GHz. The "
            "simplest thing that works, and a good sanity check.",
            "fast",
            _LC_RESONATOR,
        ),
        DeviceTemplate(
            "flux_qubit",
            "Three-junction flux qubit",
            "A loop of three junctions, one smaller by alpha. Persistent-current "
            "states near half a flux quantum.",
            "moderate",
            _FLUX_QUBIT,
        ),
        DeviceTemplate(
            "transmon_resonator",
            "Transmon + readout resonator",
            "Two modes: a transmon near 4.7 GHz coupled through 5 fF to a 7 GHz "
            "resonator, in the harmonic basis.",
            "moderate",
            _TRANSMON_RESONATOR,
        ),
        DeviceTemplate(
            "coupled_transmons",
            "Two coupled transmons",
            "A detuned pair sharing a coupling capacitor. Shows what a multi-mode "
            "spectrum looks like.",
            "moderate",
            _COUPLED_TRANSMONS,
        ),
        DeviceTemplate(
            "coupled_resonators",
            "Coupled resonators with loss",
            "Two resonators joined by a mutual inductance, with a resistor for "
            "loading. Demonstrates the K and R cards.",
            "moderate",
            _LOSSY_RESONATOR,
        ),
        DeviceTemplate(
            "zero_pi",
            "Zero-pi",
            "A protected qubit: two junctions, two superinductors, three modes. "
            "Exotic topology, and slow.",
            "heavy",
            _ZERO_PI,
        ),
    )
}


def list_templates() -> list[DeviceTemplate]:
    """Every bundled template, in the order the menus present them."""
    return list(TEMPLATES.values())


def get_template(key: str) -> DeviceTemplate:
    """Look up a template by key, case-insensitively."""
    lowered = key.strip().lower()
    if lowered in TEMPLATES:
        return TEMPLATES[lowered]
    for template in TEMPLATES.values():
        if template.title.lower() == lowered:
            return template
    raise KeyError(f"No device template '{key}'. Available: {', '.join(sorted(TEMPLATES))}")


def template_source(key: str) -> str:
    """The netlist text of a template."""
    return get_template(key).source


def write_template(key: str, path: str | None = None, directory: str | None = None) -> str:
    """
    Write a template's netlist to a file so it can be edited and re-run.

    Args:
        key: Which template.
        path: Exact file to write. Takes precedence over ``directory``.
        directory: Where to write ``<key>.qdl``. Defaults to the working directory.

    Returns:
        The path written.
    """
    template = get_template(key)
    if path:
        destination = Path(path)
    else:
        destination = Path(directory or os.getcwd()) / f"{template.key}.qdl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.source, encoding="utf-8")
    return str(destination)
