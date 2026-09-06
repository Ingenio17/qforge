"""
Device netlist: an ngspice-style schematic language for custom superconducting circuits.

This module owns the *front end* of the "Design Device" workflow. It turns a
plain-text circuit schematic made of capacitors, inductors, Josephson junctions,
resistors and a ground node into a validated, unit-resolved intermediate
representation (:class:`DeviceNetlist`), and emits the canonical scqubits circuit
YAML that :mod:`qforge.core.device_engine` quantizes.

Nothing here does physics beyond unit conversion: no Hamiltonians, no
diagonalization, no plotting. That keeps the language definition testable on its
own and leaves the engine as the single place where quantization happens.


The language
------------

Free-form, one card per line, case-insensitive for keywords::

    * A custom transmon                     -- '*' starts a full-line comment
    .title  Custom transmon
    .param  EJ0 = 15GHz                     -- named, sweepable parameter

    J1  1  0  EJ={EJ0}  EC=0.3GHz           -- Josephson junction
    C1  1  0  90fF                          -- shunt capacitor
    L1  1  0  100nH                         -- linear inductor
    R1  1  0  1MOhm                         -- resistor (dissipation only)
    K1  L1 L2  EML=1nH                      -- mutual inductance between L1 and L2

    .flux    1 = 0.5                        -- external flux through loop 1, in Phi_0
    .charge  1 = 0.0                        -- offset charge ng_1, in units of 2e
    .cutoff  n1 = 30                        -- basis cutoff for periodic variable 1
    .levels  8                              -- eigenvalues to compute
    .options ext_basis=discretized
    .end

Element cards are ``<name> <node+> <node-> <values...>``; the first letter of the
name selects the element type, exactly like SPICE (``C``, ``L``, ``J``, ``R``,
``K``). Node ``0``, ``gnd`` and ``ground`` all mean the ground node. Any other
node label is accepted and mapped onto a circuit node index.

Values may be written either as circuit quantities with physical units
(``90fF``, ``100nH``, ``30nA``, ``1MOhm``) or directly as the energies qforge and
scqubits use internally (``EJ=15``, ``EC=0.3``, ``EL=0.5``, all in GHz). A bare
number with no unit is always read as GHz, and the parser records a note saying
so, because a silently misread unit is the most common source of wrong answers in
this kind of code.

Units follow SI prefixes and are case-sensitive on the prefix (``M`` = mega,
``m`` = milli), so ``1MOhm`` and ``1mOhm`` are a million ohms apart, as they
should be. SPICE's case-insensitive ``MEG`` convention is deliberately not used:
a netlist that mixes GHz with fF and nH has no room for an ambiguous ``M``.
"""

from __future__ import annotations

import ast
import math
import operator
import os
import re
from dataclasses import dataclass, field

__all__ = [
    "NetlistError",
    "Element",
    "DeviceNetlist",
    "NetlistParam",
    "Value",
    "parse_netlist",
    "parse_netlist_file",
    "capacitance_to_EC",
    "EC_to_capacitance",
    "inductance_to_EL",
    "EL_to_inductance",
    "critical_current_to_EJ",
    "EJ_to_critical_current",
    "EJ_to_josephson_inductance",
    "mutual_inductance_to_EML",
    "EML_to_mutual_inductance",
    "coupling_coefficient",
    "format_si",
    "FORMAT_REFERENCE",
]


# ---------------------------------------------------------------------------
# Physical constants (SI, CODATA 2018 exact values)
# ---------------------------------------------------------------------------

PLANCK_H = 6.62607015e-34  # J s
ELEMENTARY_CHARGE = 1.602176634e-19  # C
FLUX_QUANTUM = PLANCK_H / (2.0 * ELEMENTARY_CHARGE)  # Wb, Phi_0 = h / 2e
REDUCED_FLUX_QUANTUM = FLUX_QUANTUM / (2.0 * math.pi)  # Wb, phi_0 = Phi_0 / 2pi

# A Josephson junction branch in scqubits always carries a capacitance, given as
# its charging energy. When a netlist declares a junction without one, qforge
# substitutes this value: EC = 1e6 GHz corresponds to C_J = e^2/(2 h EC) ~ 0.02 aF,
# five orders of magnitude below any physically meaningful junction capacitance.
# It therefore behaves as "no capacitance on this branch" while keeping the
# circuit's capacitance matrix invertible.
NEGLIGIBLE_JUNCTION_EC_GHZ = 1.0e6


def capacitance_to_EC(capacitance_farad: float) -> float:
    """Charging energy EC = e^2 / 2C, in GHz, for a capacitance in farads."""
    if capacitance_farad <= 0:
        raise ValueError("Capacitance must be positive.")
    return ELEMENTARY_CHARGE**2 / (2.0 * capacitance_farad * PLANCK_H) * 1e-9


def EC_to_capacitance(ec_ghz: float) -> float:
    """Capacitance in farads for a charging energy in GHz."""
    if ec_ghz <= 0:
        raise ValueError("Charging energy must be positive.")
    return ELEMENTARY_CHARGE**2 / (2.0 * ec_ghz * 1e9 * PLANCK_H)


def inductance_to_EL(inductance_henry: float) -> float:
    """Inductive energy EL = (Phi_0/2pi)^2 / L, in GHz, for an inductance in henries."""
    if inductance_henry <= 0:
        raise ValueError("Inductance must be positive.")
    return REDUCED_FLUX_QUANTUM**2 / (inductance_henry * PLANCK_H) * 1e-9


def EL_to_inductance(el_ghz: float) -> float:
    """Inductance in henries for an inductive energy in GHz."""
    if el_ghz <= 0:
        raise ValueError("Inductive energy must be positive.")
    return REDUCED_FLUX_QUANTUM**2 / (el_ghz * 1e9 * PLANCK_H)


def critical_current_to_EJ(current_ampere: float) -> float:
    """Josephson energy EJ = I_c Phi_0 / 2pi, in GHz, for a critical current in amperes."""
    if current_ampere <= 0:
        raise ValueError("Critical current must be positive.")
    return current_ampere * REDUCED_FLUX_QUANTUM / PLANCK_H * 1e-9


def EJ_to_critical_current(ej_ghz: float) -> float:
    """Critical current in amperes for a Josephson energy in GHz."""
    if ej_ghz <= 0:
        raise ValueError("Josephson energy must be positive.")
    return ej_ghz * 1e9 * PLANCK_H / REDUCED_FLUX_QUANTUM


def EJ_to_josephson_inductance(ej_ghz: float) -> float:
    """Zero-bias Josephson inductance L_J = (Phi_0/2pi)^2 / EJ, in henries."""
    if ej_ghz <= 0:
        raise ValueError("Josephson energy must be positive.")
    return REDUCED_FLUX_QUANTUM**2 / (ej_ghz * 1e9 * PLANCK_H)


# scqubits' ML branch parameter is not simply (Phi_0/2pi)^2 / M: it writes the
# same 1/EML into both off-diagonal entries of the inductance matrix, which makes
# the mutual inductance the circuit actually feels twice what that expression
# gives. The factor was measured, not assumed: two identical LC oscillators
# (L = 100 nH, C = 90 fF) coupled through an ML branch split into normal modes at
# f0/sqrt(1 -/+ k). Sweeping EML and fitting k reproduces 2*sqrt(EL1 EL2)/EML to
# six decimal places at small coupling, and never sqrt(EL1 EL2)/EML.
# tests: a netlist written with k = 0.05 must produce that split.
SCQUBITS_ML_FACTOR = 2.0


def mutual_inductance_to_EML(mutual_henry: float) -> float:
    """scqubits ML branch energy, in GHz, for a mutual inductance in henries."""
    if mutual_henry <= 0:
        raise ValueError("Mutual inductance must be positive.")
    return SCQUBITS_ML_FACTOR * inductance_to_EL(mutual_henry)


def EML_to_mutual_inductance(eml_ghz: float) -> float:
    """Mutual inductance in henries for an scqubits ML branch energy in GHz."""
    if eml_ghz <= 0:
        raise ValueError("Mutual coupling energy must be positive.")
    return EL_to_inductance(eml_ghz / SCQUBITS_ML_FACTOR)


def coupling_coefficient(el1_ghz: float, el2_ghz: float, eml_ghz: float) -> float:
    """
    The mutual coupling coefficient k = M / sqrt(L1 L2) of an ML branch.

    Follows from ``M = SCQUBITS_ML_FACTOR * (Phi_0/2pi)^2 / (h EML)`` and the same
    relation for each self-inductance, so the flux quantum cancels out.
    """
    return SCQUBITS_ML_FACTOR * math.sqrt(el1_ghz * el2_ghz) / eml_ghz


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

SI_PREFIXES: dict[str, float] = {
    "T": 1e12,
    "G": 1e9,
    "M": 1e6,
    "k": 1e3,
    "": 1.0,
    "m": 1e-3,
    "u": 1e-6,
    "µ": 1e-6,  # micro sign
    "μ": 1e-6,  # greek small letter mu
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "a": 1e-18,
}

# Base unit symbol -> the physical dimension it measures. Longer spellings are
# matched first so "Ohm" wins over "O" and "Hz" wins over "H".
BASE_UNITS: dict[str, str] = {
    "Ohm": "resistance",
    "ohm": "resistance",
    "R": "resistance",
    "Hz": "frequency",
    "eV": "energy",
    "F": "capacitance",
    "H": "inductance",
    "A": "current",
    "J": "energy",
}

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

# The four branch energies scqubits understands, and which written dimensions
# each of them accepts.
_ROLE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "EJ": ("frequency", "energy", "current", "inductance"),
    "EC": ("frequency", "energy", "capacitance"),
    "EL": ("frequency", "energy", "inductance"),
    "EML": ("frequency", "energy", "inductance"),
}

# Keys accepted on element cards, mapped to (role, required dimension or None).
# A key with a required dimension refuses anything else, so `C1 1 0 C=0.3` is an
# error telling the user to write either `90fF` or `EC=0.3`.
_VALUE_KEYS: dict[str, tuple[str, str | None]] = {
    "EJ": ("EJ", None),
    "IC": ("EJ", "current"),
    "I0": ("EJ", "current"),
    "LJ": ("EJ", "inductance"),
    "EC": ("EC", None),
    "ECJ": ("EC", None),
    "C": ("EC", "capacitance"),
    "CJ": ("EC", "capacitance"),
    "EL": ("EL", None),
    "L": ("EL", "inductance"),
    "EML": ("EML", None),
    "M": ("EML", "inductance"),
}

_GROUND_LABELS = {"0", "gnd", "ground"}

# Attribute names on a scqubits Circuit that a .param must not shadow.
_RESERVED_PARAM_NAMES = {
    "branches",
    "cutoffs_dict",
    "eigenvals",
    "eigensys",
    "flux",
    "hamiltonian",
    "hilbertdim",
    "nodes",
    "truncated_dim",
    "type_of_matrices",
    "vars",
}

_ELEMENT_KINDS = {"C": "C", "L": "L", "J": "JJ", "R": "R", "K": "ML"}


class NetlistError(Exception):
    """A netlist could not be parsed, or is not a well-formed circuit."""

    def __init__(self, message: str, line_no: int | None = None, line: str = ""):
        self.message = message
        self.line_no = line_no
        self.line = line
        full = f"line {line_no}: {message}" if line_no is not None else message
        if line and line.strip():
            full += f"\n    | {line.strip()}"
        super().__init__(full)


def format_si(value: float | None, unit: str, digits: int = 4) -> str:
    """Render an SI magnitude with the prefix that keeps it in the 1-1000 range."""
    if value is None:
        return "n/a"
    if value == 0:
        return f"0 {unit}"
    scales = [
        (1e12, "T"),
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "u"),
        (1e-9, "n"),
        (1e-12, "p"),
        (1e-15, "f"),
        (1e-18, "a"),
    ]
    magnitude = abs(value)
    for scale, prefix in scales:
        # The tolerance matters: a value that round-tripped through an energy
        # conversion lands a few parts in 1e12 below its decade, and without it
        # 1 fF would print as "1000 aF".
        if magnitude >= scale * (1 - 1e-9):
            return f"{value / scale:.{digits}g} {prefix}{unit}"
    return f"{value / 1e-18:.{digits}g} a{unit}"


def split_quantity(text: str) -> tuple[float, str | None, str | None]:
    """
    Split ``"90fF"`` into ``(9e-14, "F", "capacitance")``.

    Returns ``(magnitude_in_si, base_unit, dimension)``. A value written without a
    unit comes back as ``(number, None, None)``; in this language that always
    means GHz, and the caller is responsible for saying so.
    """
    text = text.strip()
    match = _NUMBER_RE.match(text)
    if not match:
        raise ValueError(f"'{text}' does not start with a number")

    number = float(match.group(0))
    suffix = text[match.end() :].strip()
    if not suffix:
        return number, None, None

    for symbol in sorted(BASE_UNITS, key=len, reverse=True):
        if suffix.endswith(symbol):
            prefix = suffix[: -len(symbol)]
            if prefix not in SI_PREFIXES:
                raise ValueError(
                    f"unknown SI prefix '{prefix}' in '{text}'; prefixes are "
                    f"case-sensitive (M = mega, m = milli)"
                )
            si_value = number * SI_PREFIXES[prefix]
            if symbol == "eV":
                si_value *= ELEMENTARY_CHARGE  # normalise eV onto joules
                return si_value, "eV", "energy"
            return si_value, symbol, BASE_UNITS[symbol]

    raise ValueError(
        f"unknown unit in '{text}'; expected Hz, F, H, A, J, eV or Ohm "
        f"with an optional SI prefix"
    )


def convert_to_ghz(si_value: float, dimension: str | None, role: str) -> float:
    """
    Convert a value carrying ``dimension`` into the branch energy (GHz) for ``role``.

    ``dimension is None`` means the netlist wrote a bare number, which this
    language defines as already being in GHz.
    """
    if dimension is None:
        return si_value
    if dimension == "frequency":
        return si_value * 1e-9
    if dimension == "energy":
        return si_value / PLANCK_H * 1e-9
    if dimension == "capacitance":
        return capacitance_to_EC(si_value)
    if dimension == "current":
        return critical_current_to_EJ(si_value)
    if dimension == "inductance":
        # A mutual inductance carries scqubits' factor of two; a self-inductance
        # and a Josephson inductance both map through (Phi_0/2pi)^2 / L.
        if role == "EML":
            return mutual_inductance_to_EML(si_value)
        return inductance_to_EL(si_value)
    raise ValueError(f"a {dimension} cannot be used as the {role} of a branch")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Value:
    """One resolved branch quantity, kept in both the written and internal units."""

    role: str  # EJ / EC / EL / EML
    ghz: float  # the number handed to scqubits
    source_text: str = ""  # exactly what the netlist said
    dimension: str | None = None  # capacitance / inductance / current / ...
    si_value: float | None = None  # magnitude in SI base units, when dimensional
    symbol: str | None = None  # name of the .param this came from, if any

    @property
    def is_symbolic(self) -> bool:
        """True when the value is bound to a named parameter and stays sweepable."""
        return self.symbol is not None

    def physical(self) -> tuple[float | None, str]:
        """
        The circuit-element value behind this energy, as ``(magnitude, unit)``.

        Junctions report a critical current, capacitors a capacitance, inductors
        an inductance. Returns ``(None, "")`` when the energy is non-positive and
        the inverse relation is undefined.
        """
        try:
            if self.role == "EJ":
                return EJ_to_critical_current(self.ghz), "A"
            if self.role == "EC":
                return EC_to_capacitance(self.ghz), "F"
            if self.role == "EML":
                return EML_to_mutual_inductance(self.ghz), "H"
            if self.role == "EL":
                return EL_to_inductance(self.ghz), "H"
        except ValueError:
            return None, ""
        return None, ""

    def describe(self) -> str:
        """A short human-readable rendering, e.g. ``"0.3 GHz (90.35 fF)"``."""
        magnitude, unit = self.physical()
        text = f"{self.ghz:.6g} GHz"
        if magnitude is not None:
            text += f" ({format_si(magnitude, unit)})"
        return text


@dataclass
class NetlistParam:
    """A ``.param`` declaration: a named knob the finished device can be swept over."""

    name: str
    value: float
    dimension: str | None = None
    si_value: float | None = None
    source_text: str = ""
    line_no: int = 0


@dataclass
class Element:
    """A single element card."""

    kind: str  # "C" | "L" | "JJ" | "R" | "ML"
    name: str
    nodes: tuple[str, str]  # node labels as written (inductor names for "ML")
    values: dict[str, Value] = field(default_factory=dict)
    node_indices: tuple[int, int] = (0, 0)  # circuit node indices, 0 = ground
    junction_order: int = 1  # 1 for a plain JJ, 2/3/... for higher harmonics
    resistance_ohm: float | None = None
    coupling_coefficient: float | None = None  # k = M/sqrt(L1 L2), for "ML" only
    line_no: int = 0
    raw: str = ""

    @property
    def is_hamiltonian_branch(self) -> bool:
        """Resistors are classical loads and never enter the circuit Hamiltonian."""
        return self.kind in ("C", "L", "JJ", "ML")

    @property
    def scqubits_type(self) -> str:
        """The branch keyword this element becomes in the scqubits YAML."""
        if self.kind == "JJ" and self.junction_order > 1:
            return f"JJ{self.junction_order}"
        return self.kind

    def value_summary(self) -> str:
        """All of this element's quantities, joined for display."""
        if self.kind == "R":
            return format_si(self.resistance_ohm, "Ohm")
        parts = []
        for role in ("EJ", "EJ2", "EJ3", "EJ4", "EC", "EL", "EML"):
            if role in self.values:
                parts.append(f"{role} = {self.values[role].describe()}")
        if self.coupling_coefficient is not None:
            parts.append(f"k = {self.coupling_coefficient:.4g}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Safe arithmetic for {...} expressions
# ---------------------------------------------------------------------------

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_EXPR_FUNCS = {
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
}
_EXPR_CONSTS = {"pi": math.pi, "PI": math.pi, "tau": math.tau}


def _eval_expression(expr: str, names: dict[str, float]) -> float:
    """
    Evaluate an arithmetic expression over ``.param`` values.

    Only literals, the usual arithmetic operators and a small whitelist of maths
    functions are permitted. Netlists are user-supplied files, so this must never
    become a general ``eval``.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"cannot parse expression '{expr}': {exc.msg}") from exc

    def _walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"{node.value!r} is not a number")
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_walk(node.left), _walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_walk(node.operand))
        if isinstance(node, ast.Name):
            if node.id in names:
                return float(names[node.id])
            if node.id in _EXPR_CONSTS:
                return _EXPR_CONSTS[node.id]
            raise ValueError(f"unknown name '{node.id}'; declare it with .param first")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _EXPR_FUNCS:
                raise ValueError(
                    "only sqrt/exp/log/log10/sin/cos/tan/abs/min/max/round may be called"
                )
            return float(_EXPR_FUNCS[node.func.id](*[_walk(arg) for arg in node.args]))
        raise ValueError("expression uses a construct that is not allowed here")

    try:
        result = _walk(tree)
    except ArithmeticError as exc:
        raise ValueError(f"cannot evaluate '{expr}': {exc}") from exc
    except TypeError as exc:
        raise ValueError(f"cannot evaluate '{expr}': {exc}") from exc
    if not math.isfinite(result):
        raise ValueError(f"expression '{expr}' evaluated to {result}")
    return result


def _expression_dimension(expr: str, params: dict[str, NetlistParam]) -> str | None:
    """
    Work out what an expression's result measures, from the parameters it uses.

    ``.param`` values are stored as SI magnitudes, so an expression over them
    produces an SI magnitude too, and the caller has to know which unit that is
    before it can be converted to an energy. Without this, ``.param EJ0 = 60GHz``
    followed by ``EJ={EJ0*ALPHA}`` would silently read 2.58e10 as GHz rather than
    as Hz: a factor of a billion, and exactly the kind of unit slip this language
    is built to prevent.

    The rule is deliberately simple: an expression inherits the one dimension its
    parameters carry, and mixing two different physical dimensions is an error.
    That covers scaling a quantity by a dimensionless factor, which is what these
    expressions are almost always for. It does not attempt real dimensional
    analysis, so a ratio of two like quantities comes back carrying their
    dimension rather than as dimensionless; the resulting value is far enough
    from anything physical that it shows up immediately in the element table.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    dimensions = {
        params[node.id].dimension
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in params and params[node.id].dimension
    }
    if len(dimensions) > 1:
        raise ValueError(
            f"'{expr}' mixes {' and '.join(sorted(dimensions))}; an expression may "
            f"only combine parameters that measure the same thing"
        )
    return dimensions.pop() if dimensions else None


def _clean_float(value: float) -> float:
    """
    Drop the binary-representation noise a unit conversion leaves behind.

    ``15 GHz`` written as ``15e9 Hz`` and converted back comes out as
    15.000000000000002; twelve significant digits is far beyond any physical
    precision here and keeps the emitted circuit and the reports readable.
    """
    return float(f"{value:.12g}")


# ---------------------------------------------------------------------------
# The parsed netlist
# ---------------------------------------------------------------------------


@dataclass
class DeviceNetlist:
    """
    A parsed, validated device schematic.

    This is a pure description of the circuit: which branches exist, what they
    are worth in both physical and energy units, which node each one touches,
    and how the user wants the resulting quantum problem set up. Turning it into
    a Hamiltonian is :mod:`qforge.core.device_engine`'s job.
    """

    name: str = "device"
    title: str = ""
    source: str = ""
    source_path: str | None = None
    elements: list[Element] = field(default_factory=list)
    params: dict[str, NetlistParam] = field(default_factory=dict)
    node_map: dict[str, int] = field(default_factory=dict)  # label -> index (0 = ground)
    ground_labels: list[str] = field(default_factory=list)
    fluxes: dict[str, float] = field(default_factory=dict)  # "1" / "all" -> Phi_0
    charges: dict[str, float] = field(default_factory=dict)  # "1" / "all" -> 2e
    cutoffs: dict[str, int] = field(default_factory=dict)  # "n1" / "ext" / "all"
    options: dict[str, object] = field(default_factory=dict)
    levels: int = 8
    notes: list[str] = field(default_factory=list)

    # -- derived views ----------------------------------------------------

    @property
    def branches(self) -> list[Element]:
        """Elements that enter the circuit Hamiltonian, in netlist order."""
        return [el for el in self.elements if el.is_hamiltonian_branch and el.kind != "ML"]

    @property
    def couplers(self) -> list[Element]:
        """Mutual-inductance couplers, which scqubits treats separately from branches."""
        return [el for el in self.elements if el.kind == "ML"]

    @property
    def resistors(self) -> list[Element]:
        """Dissipative elements, excluded from the Hamiltonian."""
        return [el for el in self.elements if el.kind == "R"]

    @property
    def junctions(self) -> list[Element]:
        return [el for el in self.elements if el.kind == "JJ"]

    @property
    def node_labels(self) -> list[str]:
        """Non-ground node labels, ordered by circuit node index."""
        return [label for label, _ in sorted(self.node_map.items(), key=lambda kv: kv[1])]

    @property
    def num_nodes(self) -> int:
        """Number of active (non-ground) nodes."""
        return len(self.node_map)

    @property
    def num_loops(self) -> int:
        """
        Independent loops that can hold an external flux.

        Only inductive branches count. A loop closed through a capacitor carries
        no persistent current, so no flux threads it and scqubits assigns it no
        external-flux variable; counting those would overstate how many knobs the
        device has. The count is Euler's formula applied to the subgraph of
        inductors and junctions: ``branches - nodes + components``.
        """
        inductive = [el for el in self.branches if el.kind in ("L", "JJ")]
        if not inductive:
            return 0

        parent: dict[int, int] = {}

        def find(node: int) -> int:
            parent.setdefault(node, node)
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def union(a: int, b: int) -> None:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_a] = root_b

        for el in inductive:
            union(el.node_indices[0], el.node_indices[1])

        components = len({find(node) for node in parent})
        return max(0, len(inductive) - len(parent) + components)

    @property
    def is_grounded(self) -> bool:
        return bool(self.ground_labels)

    def capacitance_between(self, node_a: int, node_b: int) -> float:
        """
        Total capacitance directly across a node pair, in farads.

        Sums every capacitor and every junction capacitance that spans exactly
        those two nodes. Used for the classical loading estimate reported for
        resistors; it is a local quantity, not the circuit's effective mode
        capacitance.
        """
        total = 0.0
        pair = {node_a, node_b}
        for el in self.elements:
            if el.kind not in ("C", "JJ") or set(el.node_indices) != pair:
                continue
            value = el.values.get("EC")
            if value is None or value.ghz <= 0:
                continue
            if el.kind == "JJ" and value.ghz >= NEGLIGIBLE_JUNCTION_EC_GHZ:
                continue
            total += EC_to_capacitance(value.ghz)
        return total

    # -- emission ---------------------------------------------------------

    def to_scqubits_yaml(self) -> str:
        """
        Render the circuit as the scqubits ``branches:`` YAML block.

        Named ``.param`` values are emitted symbolically (``EJ0 = 15.0`` on their
        first use, then a bare ``EJ0``) so that scqubits keeps them as circuit
        parameters. That is what makes ``DeviceEngine.sweep`` able to vary a
        junction energy without re-parsing the netlist. Values that came from an
        expression are baked in as numbers, since there is no single symbol to
        attach them to.
        """
        lines = ["branches:"]
        emitted_symbols: set = set()

        def render(value: Value) -> str:
            if value.symbol and value.symbol not in emitted_symbols:
                emitted_symbols.add(value.symbol)
                return f"{value.symbol} = {value.ghz!r}"
            if value.symbol:
                return value.symbol
            return repr(value.ghz)

        branch_index: dict[str, int] = {}
        for el in self.branches:
            branch_index[el.name.upper()] = len(branch_index)
            n1, n2 = el.node_indices
            parts = [el.scqubits_type, str(n1), str(n2)]
            for order in range(1, el.junction_order + 1):
                role = "EJ" if order == 1 else f"EJ{order}"
                if role in el.values:
                    parts.append(render(el.values[role]))
            if el.kind == "JJ":
                parts.append(render(el.values["EC"]))
            elif el.kind == "C":
                parts.append(render(el.values["EC"]))
            elif el.kind == "L":
                parts.append(render(el.values["EL"]))
            lines.append(f"- [{', '.join(parts)}]")

        # Couplers must follow the branches they reference: scqubits resolves an
        # ML card against the branch list it has accumulated so far.
        for el in self.couplers:
            i1 = branch_index[el.nodes[0].upper()]
            i2 = branch_index[el.nodes[1].upper()]
            lines.append(f"- [ML, {i1}, {i2}, {render(el.values['EML'])}]")

        return "\n".join(lines) + "\n"

    def symbol_defaults(self) -> dict[str, float]:
        """Named circuit parameters and the values the netlist gave them, in GHz."""
        defaults: dict[str, float] = {}
        for el in self.elements:
            for value in el.values.values():
                if value.symbol and value.symbol not in defaults:
                    defaults[value.symbol] = value.ghz
        return defaults

    def describe(self) -> dict[str, object]:
        """A compact, serializable summary for reports and session files."""
        return {
            "name": self.name,
            "title": self.title,
            "num_nodes": self.num_nodes,
            "num_branches": len(self.branches),
            "num_junctions": len(self.junctions),
            "num_couplers": len(self.couplers),
            "num_resistors": len(self.resistors),
            "num_loops": self.num_loops,
            "grounded": self.is_grounded,
            "levels": self.levels,
            "parameters": {p.name: p.value for p in self.params.values()},
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _strip_comment(line: str) -> str:
    """
    Remove an inline comment, ignoring comment characters inside ``{...}``.

    ``;``, ``#`` and ``//`` all start a comment. ``*`` only does so at the very
    start of a line, because it is also multiplication inside an expression.
    """
    depth = 0
    i = 0
    while i < len(line):
        char = line[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            if char in ";#":
                return line[:i]
            if char == "/" and line[i : i + 2] == "//":
                return line[:i]
        i += 1
    return line


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """
    Fold comments and SPICE ``+`` continuations into ``(line_no, content)`` pairs.

    The reported line number is that of the card's first physical line, which is
    what a user needs in order to find an error in their file.
    """
    out: list[tuple[int, str]] = []
    for raw_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped[0] == "*":
            continue
        content = _strip_comment(raw).strip()
        if not content:
            continue
        if content[0] == "+":
            if not out:
                raise NetlistError("continuation line '+' has nothing to continue", raw_no, raw)
            line_no, previous = out[-1]
            out[-1] = (line_no, previous + " " + content[1:].strip())
            continue
        out.append((raw_no, content))
    return out


def _normalize_spacing(content: str) -> str:
    """
    Collapse the whitespace around ``=`` so ``EJ = 15GHz`` tokenizes as one word.

    Text inside ``{...}`` is copied through untouched, since an expression may
    legitimately contain spaces.
    """
    out: list[str] = []
    depth = 0
    i = 0
    n = len(content)
    while i < n:
        char = content[i]
        if char == "{":
            depth += 1
            out.append(char)
        elif char == "}":
            depth = max(0, depth - 1)
            out.append(char)
        elif depth > 0:
            out.append(char)
        elif char.isspace():
            j = i
            while j < n and content[j].isspace():
                j += 1
            # Drop whitespace that only separates a key from its '=' or a '='
            # from its value; keep it anywhere else as a single space.
            if (j < n and content[j] == "=") or (out and out[-1] == "="):
                i = j
                continue
            out.append(" ")
            i = j
            continue
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _tokenize(content: str) -> list[str]:
    """
    Split a card into tokens, keeping ``key = value`` pairs and ``{...}`` intact.

    Whitespace around ``=`` is absorbed so that ``EJ = 15 GHz`` and ``EJ=15GHz``
    parse identically, and braces keep expressions such as ``{EJ0 / 50}`` whole.
    """
    tokens: list[str] = []
    current = ""
    depth = 0
    for char in _normalize_spacing(content):
        if char == "{":
            depth += 1
            current += char
        elif char == "}":
            depth = max(0, depth - 1)
            current += char
        elif char.isspace() and depth == 0:
            if current:
                tokens.append(current)
                current = ""
        else:
            current += char
    if current:
        tokens.append(current)
    return tokens


def _split_key_value(token: str) -> tuple[str | None, str]:
    """Split ``"EJ=15GHz"`` into ``("EJ", "15GHz")``; a bare value returns ``(None, token)``."""
    if "=" in token:
        key, _, value = token.partition("=")
        return key.strip(), value.strip()
    return None, token.strip()


class _Parser:
    """Single-use netlist parser. Instantiated by :func:`parse_netlist`."""

    def __init__(self, text: str, name: str, source_path: str | None):
        self.text = text
        self.netlist = DeviceNetlist(name=name, source=text, source_path=source_path)
        self._next_node_index = 1
        self._element_names: dict[str, Element] = {}
        self._ground_declared: str | None = None

    # -- helpers ----------------------------------------------------------

    def _note(self, message: str) -> None:
        if message not in self.netlist.notes:
            self.netlist.notes.append(message)

    def _node_index(self, label: str, line_no: int, raw: str) -> int:
        key = label.strip()
        if not key:
            raise NetlistError("empty node label", line_no, raw)
        lowered = key.lower()
        declared = self._ground_declared.lower() if self._ground_declared else None
        if lowered in _GROUND_LABELS or lowered == declared:
            self._register_ground(key)
            return 0
        if key not in self.netlist.node_map:
            self.netlist.node_map[key] = self._next_node_index
            self._next_node_index += 1
        return self.netlist.node_map[key]

    def _register_ground(self, label: str) -> None:
        if label not in self.netlist.ground_labels:
            self.netlist.ground_labels.append(label)

    def _param_values(self) -> dict[str, float]:
        return {name: p.value for name, p in self.netlist.params.items()}

    def _resolve(self, text: str, role: str, line_no: int, raw: str, required_dim=None) -> Value:
        """Turn one written value into a :class:`Value` in GHz."""
        text = text.strip()
        if not text:
            raise NetlistError(f"missing a value for {role}", line_no, raw)

        # {expression}: evaluated now and folded into a number, carrying whatever
        # dimension its parameters had so the unit conversion still applies.
        if text.startswith("{") and text.endswith("}"):
            try:
                number = _eval_expression(text[1:-1], self._param_values())
                dimension = _expression_dimension(text[1:-1], self.netlist.params)
            except ValueError as exc:
                raise NetlistError(str(exc), line_no, raw) from exc
            if dimension:
                self._note(
                    f"'{text}' was read as a {dimension}, from the units of the "
                    f"parameter(s) it uses."
                )
            return self._finish_value(
                number,
                dimension,
                number if dimension else None,
                role,
                text,
                None,
                line_no,
                raw,
                required_dim,
            )

        # A bare reference to a .param keeps the value symbolic and sweepable.
        if text in self.netlist.params:
            param = self.netlist.params[text]
            return self._finish_value(
                param.value,  # already the SI magnitude, or a bare number
                param.dimension,
                param.si_value,
                role,
                text,
                param.name,
                line_no,
                raw,
                required_dim,
            )

        try:
            magnitude, _unit, dimension = split_quantity(text)
        except ValueError as exc:
            raise NetlistError(str(exc), line_no, raw) from exc

        return self._finish_value(
            magnitude,
            dimension,
            magnitude if dimension else None,
            role,
            text,
            None,
            line_no,
            raw,
            required_dim,
        )

    def _finish_value(
        self,
        magnitude,
        dimension,
        si_value,
        role,
        source_text,
        symbol,
        line_no,
        raw,
        required_dim,
    ) -> Value:
        base_role = "EJ" if role.startswith("EJ") else role
        if required_dim is not None and dimension != required_dim:
            raise NetlistError(
                f"'{source_text}' must be given as a {required_dim} "
                f"(for example {'90fF' if required_dim == 'capacitance' else '100nH'}); "
                f"to give an energy instead, write {base_role}=<value in GHz>",
                line_no,
                raw,
            )
        allowed = _ROLE_DIMENSIONS[base_role]
        if dimension is not None and dimension not in allowed:
            raise NetlistError(
                f"a {dimension} cannot define {role}; {role} accepts {', '.join(allowed)}",
                line_no,
                raw,
            )
        if dimension is None:
            self._note(
                "Values written without a unit are read as GHz "
                "(write 90fF, 100nH, 30nA or 15GHz to be explicit)."
            )
        try:
            ghz = _clean_float(convert_to_ghz(magnitude, dimension, base_role))
        except ValueError as exc:
            raise NetlistError(str(exc), line_no, raw) from exc
        if ghz <= 0:
            raise NetlistError(f"{role} must be positive, got {ghz:g} GHz", line_no, raw)
        return Value(
            role=role,
            ghz=ghz,
            source_text=source_text,
            dimension=dimension,
            si_value=si_value,
            symbol=symbol,
        )

    # -- directives -------------------------------------------------------

    def _directive(self, tokens: list[str], line_no: int, raw: str) -> bool:
        """Handle a ``.something`` card. Returns False when parsing should stop."""
        keyword = tokens[0][1:].lower()
        rest = tokens[1:]
        joined = " ".join(rest)

        if keyword == "end":
            return False

        if keyword in ("title", "name"):
            if not joined:
                raise NetlistError(f".{keyword} needs a value", line_no, raw)
            if keyword == "title":
                self.netlist.title = joined
            else:
                self.netlist.name = joined.replace(" ", "_")
            return True

        if keyword == "ground":
            if len(rest) != 1:
                raise NetlistError(".ground takes exactly one node label", line_no, raw)
            label = rest[0]
            if label in self.netlist.node_map:
                raise NetlistError(
                    f"node '{label}' is already used as a circuit node; declare "
                    f".ground before the elements that reference it",
                    line_no,
                    raw,
                )
            self._ground_declared = label
            self._register_ground(label)
            return True

        if keyword == "param":
            self._directive_param(rest, line_no, raw)
            return True

        if keyword in ("flux", "charge"):
            target, value = self._directive_assignment(rest, keyword, line_no, raw)
            store = self.netlist.fluxes if keyword == "flux" else self.netlist.charges
            store[target] = float(value)
            return True

        if keyword == "cutoff":
            target, value = self._directive_assignment(rest, keyword, line_no, raw)
            if value <= 0 or value != int(value):
                raise NetlistError(".cutoff needs a positive integer", line_no, raw)
            self.netlist.cutoffs[target] = int(value)
            return True

        if keyword == "levels":
            if len(rest) != 1:
                raise NetlistError(".levels takes one integer", line_no, raw)
            try:
                levels = int(float(rest[0].lstrip("=")))
            except ValueError as exc:
                raise NetlistError(f"'{rest[0]}' is not an integer", line_no, raw) from exc
            if levels < 2:
                raise NetlistError(".levels must be at least 2", line_no, raw)
            self.netlist.levels = levels
            return True

        if keyword == "options":
            for token in rest:
                key, value = _split_key_value(token)
                if key is None:
                    raise NetlistError(f"'{token}' is not a key=value option", line_no, raw)
                self.netlist.options[key.lower()] = _coerce_option(value)
            return True

        raise NetlistError(
            f"unknown directive '.{keyword}'; expected one of .title .name .param "
            f".ground .flux .charge .cutoff .levels .options .end",
            line_no,
            raw,
        )

    def _directive_param(self, rest: list[str], line_no: int, raw: str) -> None:
        if not rest:
            raise NetlistError(".param needs NAME = value", line_no, raw)
        name, value_text = _split_key_value(rest[0])
        if name is None:
            if len(rest) < 2:
                raise NetlistError(".param needs NAME = value", line_no, raw)
            name, value_text = rest[0], rest[1]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise NetlistError(
                f"'{name}' is not a valid parameter name (letters, digits and "
                f"underscores, not starting with a digit)",
                line_no,
                raw,
            )
        if name in _RESERVED_PARAM_NAMES:
            raise NetlistError(
                f"'{name}' is reserved by the circuit model; pick another name",
                line_no,
                raw,
            )
        if name in self.netlist.params:
            raise NetlistError(f"parameter '{name}' is declared twice", line_no, raw)

        value_text = value_text.strip()
        if value_text.startswith("{") and value_text.endswith("}"):
            try:
                number = _eval_expression(value_text[1:-1], self._param_values())
                dimension = _expression_dimension(value_text[1:-1], self.netlist.params)
            except ValueError as exc:
                raise NetlistError(str(exc), line_no, raw) from exc
            self.netlist.params[name] = NetlistParam(
                name=name,
                value=number,
                dimension=dimension,
                si_value=number if dimension else None,
                source_text=value_text,
                line_no=line_no,
            )
            return

        try:
            magnitude, _unit, dimension = split_quantity(value_text)
        except ValueError as exc:
            raise NetlistError(str(exc), line_no, raw) from exc
        self.netlist.params[name] = NetlistParam(
            name=name,
            value=magnitude,
            dimension=dimension,
            si_value=magnitude if dimension else None,
            source_text=value_text,
            line_no=line_no,
        )

    def _directive_assignment(
        self, rest: list[str], keyword: str, line_no: int, raw: str
    ) -> tuple[str, float]:
        """Parse ``.<keyword> <target> = <number>`` into ``(target, value)``."""
        if not rest:
            raise NetlistError(f".{keyword} needs <target> = <value>", line_no, raw)
        target, value_text = _split_key_value(rest[0])
        if target is None:
            if len(rest) < 2:
                raise NetlistError(f".{keyword} needs <target> = <value>", line_no, raw)
            target, value_text = rest[0], rest[1]
        target = target.strip().lower()
        value_text = value_text.strip()
        if value_text.startswith("{") and value_text.endswith("}"):
            try:
                return target, _eval_expression(value_text[1:-1], self._param_values())
            except ValueError as exc:
                raise NetlistError(str(exc), line_no, raw) from exc
        if value_text in self.netlist.params:
            return target, self.netlist.params[value_text].value
        try:
            return target, float(value_text)
        except ValueError as exc:
            raise NetlistError(
                f"'{value_text}' is not a number in .{keyword}", line_no, raw
            ) from exc

    # -- element cards ----------------------------------------------------

    def _element(self, tokens: list[str], line_no: int, raw: str) -> None:
        name = tokens[0]
        kind = _ELEMENT_KINDS.get(name[0].upper())
        if kind is None:
            raise NetlistError(
                f"'{name}' does not name an element; the first letter selects the "
                f"type: C (capacitor), L (inductor), J (junction), R (resistor), "
                f"K (mutual inductance)",
                line_no,
                raw,
            )
        if name.upper() in self._element_names:
            previous = self._element_names[name.upper()]
            raise NetlistError(
                f"element '{name}' is already defined on line {previous.line_no}",
                line_no,
                raw,
            )
        if len(tokens) < 4:
            raise NetlistError(f"'{name}' needs at least two terminals and a value", line_no, raw)

        element = Element(
            kind=kind,
            name=name,
            nodes=(tokens[1], tokens[2]),
            line_no=line_no,
            raw=raw,
        )
        rest = tokens[3:]

        if kind == "ML":
            self._element_mutual(element, rest, line_no, raw)
        else:
            element.node_indices = (
                self._node_index(tokens[1], line_no, raw),
                self._node_index(tokens[2], line_no, raw),
            )
            if element.node_indices[0] == element.node_indices[1]:
                raise NetlistError(
                    f"'{name}' short-circuits node '{tokens[1]}' onto itself", line_no, raw
                )
            if kind == "R":
                self._element_resistor(element, rest, line_no, raw)
            elif kind == "C":
                element.values["EC"] = self._one_value(rest, "EC", element, line_no, raw)
            elif kind == "L":
                element.values["EL"] = self._one_value(rest, "EL", element, line_no, raw)
            elif kind == "JJ":
                self._element_junction(element, rest, line_no, raw)

        self._element_names[name.upper()] = element
        self.netlist.elements.append(element)

    def _one_value(self, rest, role, element, line_no, raw) -> Value:
        """Read the single value of a two-terminal linear element."""
        if len(rest) != 1:
            raise NetlistError(
                f"'{element.name}' takes exactly one value, got {len(rest)}", line_no, raw
            )
        key, text = _split_key_value(rest[0])
        required_dim = None
        if key is not None:
            mapped = _VALUE_KEYS.get(key.upper())
            if mapped is None or mapped[0] != role:
                raise NetlistError(
                    f"'{key}' is not a value of a {element.kind} element; use "
                    f"{role}=<GHz> or a physical value such as "
                    f"{'90fF' if role == 'EC' else '100nH'}",
                    line_no,
                    raw,
                )
            required_dim = mapped[1]
        return self._resolve(text, role, line_no, raw, required_dim)

    def _element_resistor(self, element, rest, line_no, raw) -> None:
        if len(rest) != 1:
            raise NetlistError(f"'{element.name}' takes exactly one resistance", line_no, raw)
        _key, text = _split_key_value(rest[0])
        try:
            magnitude, _unit, dimension = split_quantity(text)
        except ValueError as exc:
            raise NetlistError(str(exc), line_no, raw) from exc
        if dimension not in (None, "resistance"):
            raise NetlistError(
                f"a {dimension} cannot be a resistance; write for example 50Ohm or 1MOhm",
                line_no,
                raw,
            )
        if magnitude <= 0:
            raise NetlistError("resistance must be positive", line_no, raw)
        if dimension is None:
            self._note("Resistances written without a unit are read as ohms.")
        element.resistance_ohm = magnitude
        self._note(
            "Resistors are classical loads: they set the dissipation estimate but "
            "are not part of the circuit Hamiltonian."
        )

    def _element_junction(self, element, rest, line_no, raw) -> None:
        """Read ``EJ`` (plus optional harmonics ``EJ2..``) and the junction capacitance."""
        positional: list[str] = []
        keyed: dict[str, str] = {}
        for token in rest:
            key, text = _split_key_value(token)
            if key is None:
                positional.append(text)
            else:
                keyed[key.upper()] = text

        # Positional form: J1 1 0 15 0.3  ->  EJ then EC.
        if positional:
            if len(positional) > 2:
                raise NetlistError(
                    f"'{element.name}' takes at most two positional values "
                    f"(EJ then the junction capacitance); name the rest, e.g. EJ2=...",
                    line_no,
                    raw,
                )
            if "EJ" in keyed:
                raise NetlistError(
                    f"'{element.name}' gives EJ both positionally and by name", line_no, raw
                )
            keyed.setdefault("EJ", positional[0])
            if len(positional) == 2:
                if any(k in keyed for k in ("EC", "ECJ", "C", "CJ")):
                    raise NetlistError(
                        f"'{element.name}' gives the junction capacitance twice", line_no, raw
                    )
                keyed["EC"] = positional[1]

        if "EJ" not in keyed:
            for alias in ("IC", "I0", "LJ"):
                if alias in keyed:
                    keyed["EJ"] = keyed.pop(alias)
                    keyed["__EJ_DIM__"] = _VALUE_KEYS[alias][1]
                    break
        required_ej_dim = keyed.pop("__EJ_DIM__", None)
        if "EJ" not in keyed:
            raise NetlistError(
                f"'{element.name}' needs a Josephson energy: EJ=<GHz>, Ic=<current> "
                f"or Lj=<inductance>",
                line_no,
                raw,
            )

        element.values["EJ"] = self._resolve(keyed.pop("EJ"), "EJ", line_no, raw, required_ej_dim)

        # Higher junction harmonics, EJ2 / EJ3 / ..., must be contiguous.
        order = 1
        while f"EJ{order + 1}" in keyed:
            order += 1
            element.values[f"EJ{order}"] = self._resolve(
                keyed.pop(f"EJ{order}"), f"EJ{order}", line_no, raw
            )
        element.junction_order = order
        leftover_harmonics = [k for k in keyed if re.fullmatch(r"EJ\d+", k)]
        if leftover_harmonics:
            raise NetlistError(
                f"'{element.name}' skips a junction harmonic: {', '.join(sorted(leftover_harmonics))} "
                f"given but EJ{order + 1} missing",
                line_no,
                raw,
            )

        cap_key = next((k for k in ("EC", "ECJ", "C", "CJ") if k in keyed), None)
        if cap_key is None:
            element.values["EC"] = Value(
                role="EC",
                ghz=NEGLIGIBLE_JUNCTION_EC_GHZ,
                source_text="(none)",
            )
            self._note(
                f"'{element.name}' has no junction capacitance, so a negligible one "
                f"(EC = {NEGLIGIBLE_JUNCTION_EC_GHZ:.0e} GHz, about 0.02 aF) was used. "
                f"Add EC=<GHz> or Cj=<farads> to model the real junction capacitance."
            )
        else:
            element.values["EC"] = self._resolve(
                keyed.pop(cap_key), "EC", line_no, raw, _VALUE_KEYS[cap_key][1]
            )

        unknown = [k for k in keyed if k not in ("EC", "ECJ", "C", "CJ")]
        if unknown:
            raise NetlistError(
                f"'{element.name}' does not take {', '.join(sorted(unknown))}", line_no, raw
            )

    def _element_mutual(self, element, rest, line_no, raw) -> None:
        """
        A ``K`` card couples two named inductors, not two nodes.

        The value may be a coupling coefficient (``k=0.05``), a mutual inductance
        (``1nH`` or ``M=1nH``), or scqubits' branch energy (``EML=<GHz>``, or a
        bare number). A ``k`` is only resolvable once both inductors are known,
        so it is stashed and converted during validation.
        """
        if len(rest) != 1:
            raise NetlistError(
                f"'{element.name}' takes two inductor names and one value", line_no, raw
            )
        key, text = _split_key_value(rest[0])
        if key is not None and key.upper() == "K":
            try:
                coefficient = (
                    _eval_expression(text[1:-1], self._param_values())
                    if text.startswith("{") and text.endswith("}")
                    else float(text)
                )
            except ValueError as exc:
                raise NetlistError(
                    f"'{text}' is not a coupling coefficient (a plain number, 0 < k <= 1)",
                    line_no,
                    raw,
                ) from exc
            if not 0.0 < coefficient <= 1.0:
                raise NetlistError(
                    f"coupling coefficient k = {coefficient:g} must satisfy 0 < k <= 1: "
                    f"two inductors cannot share more flux than they store",
                    line_no,
                    raw,
                )
            element.coupling_coefficient = coefficient
            return
        element.values["EML"] = self._resolve(text, "EML", line_no, raw)

    # -- driver -----------------------------------------------------------

    def parse(self) -> DeviceNetlist:
        for line_no, content in _logical_lines(self.text):
            tokens = _tokenize(content)
            if not tokens:
                continue
            if tokens[0].startswith("."):
                if not self._directive(tokens, line_no, content):
                    break
            else:
                self._element(tokens, line_no, content)

        self._validate()
        return self.netlist

    def _validate(self) -> None:
        net = self.netlist

        if not net.elements:
            raise NetlistError("the netlist defines no elements")
        if not net.branches:
            raise NetlistError(
                "the netlist has no capacitors, inductors or junctions, so there is "
                "no circuit to quantize"
            )

        # Mutual inductances must name real inductors and stay physical.
        for coupler in net.couplers:
            coupled: list[Element] = []
            for label in coupler.nodes:
                target = self._element_names.get(label.upper())
                if target is None:
                    raise NetlistError(
                        f"'{coupler.name}' refers to '{label}', which is not an element",
                        coupler.line_no,
                        coupler.raw,
                    )
                if target.kind != "L":
                    raise NetlistError(
                        f"'{coupler.name}' couples '{label}', which is a "
                        f"{target.kind} element; mutual inductance is only defined "
                        f"between inductors",
                        coupler.line_no,
                        coupler.raw,
                    )
                coupled.append(target)
            if coupler.nodes[0].upper() == coupler.nodes[1].upper():
                raise NetlistError(
                    f"'{coupler.name}' couples '{coupler.nodes[0]}' to itself",
                    coupler.line_no,
                    coupler.raw,
                )

            # The coupling coefficient k = M / sqrt(L1 L2) cannot exceed 1: two
            # inductors cannot share more flux than they store.
            el1 = coupled[0].values["EL"].ghz
            el2 = coupled[1].values["EL"].ghz

            if "EML" not in coupler.values:
                # The card gave k directly; turn it into the branch energy now
                # that both self-inductances are known.
                k = coupler.coupling_coefficient
                eml = _clean_float(SCQUBITS_ML_FACTOR * math.sqrt(el1 * el2) / k)
                coupler.values["EML"] = Value(role="EML", ghz=eml, source_text=f"k={k:g}")
            else:
                eml = coupler.values["EML"].ghz
                k = coupling_coefficient(el1, el2, eml)
                coupler.coupling_coefficient = k

            if k > 1.0:
                mutual = EML_to_mutual_inductance(eml)
                limit = math.sqrt(EL_to_inductance(el1) * EL_to_inductance(el2))
                raise NetlistError(
                    f"'{coupler.name}' has a coupling coefficient k = {k:.3f}, which is "
                    f"impossible: the mutual inductance {format_si(mutual, 'H')} exceeds "
                    f"sqrt(L1 L2) = {format_si(limit, 'H')}. Use a smaller mutual "
                    f"inductance, or write k=<value> and let qforge do the conversion.",
                    coupler.line_no,
                    coupler.raw,
                )
            if k > 0.9:
                net.notes.append(
                    f"'{coupler.name}' couples with k = {k:.3f}, close to the k = 1 limit "
                    f"of perfectly shared flux."
                )

        if not net.node_map:
            raise NetlistError("every element is connected to ground only")

        # Each node needs at least two branches, or it is a dangling wire whose
        # variable is unconstrained and would make the capacitance matrix singular.
        degree: dict[int, int] = {index: 0 for index in net.node_map.values()}
        for el in net.branches:
            for index in el.node_indices:
                if index in degree:
                    degree[index] += 1
        index_to_label = {index: label for label, index in net.node_map.items()}
        dangling = [index_to_label[i] for i, count in degree.items() if count < 2]
        if dangling:
            raise NetlistError(
                f"node(s) {', '.join(sorted(dangling))} carry fewer than two branches; "
                f"a floating node has no dynamics. Connect them, or remove them."
            )

        # Every node needs a capacitive path or the kinetic term is singular.
        capacitive_nodes = set()
        for el in net.branches:
            if el.kind in ("C", "JJ"):
                capacitive_nodes.update(el.node_indices)
        no_capacitance = [
            index_to_label[i] for i in net.node_map.values() if i not in capacitive_nodes
        ]
        if no_capacitance:
            raise NetlistError(
                f"node(s) {', '.join(sorted(no_capacitance))} have no capacitance to "
                f"any other node. Every node needs a capacitor or a junction, "
                f"otherwise the circuit has no charging energy and cannot be quantized."
            )

        # A node whose only capacitance is the placeholder on a bare junction is
        # quantizable but physically meaningless: EC would be ~1e6 GHz.
        real_capacitance_nodes = set()
        for el in net.branches:
            value = el.values.get("EC")
            if value is None:
                continue
            if el.kind == "C" or value.ghz < NEGLIGIBLE_JUNCTION_EC_GHZ:
                real_capacitance_nodes.update(el.node_indices)
        placeholder_only = sorted(
            index_to_label[i] for i in net.node_map.values() if i not in real_capacitance_nodes
        )
        if placeholder_only:
            net.notes.append(
                f"Node(s) {', '.join(placeholder_only)} carry no real capacitance, only "
                f"the placeholder on a bare junction. The charging energy there will be "
                f"enormous and the level structure meaningless. Add a shunt capacitor "
                f"or a junction capacitance."
            )

        if not net.is_grounded:
            net.notes.append(
                "No ground node: the circuit is floating, so scqubits will carry a "
                "free charge variable. Tie a node to 0 or gnd to remove it."
            )

        if len(net.junctions) == 0:
            net.notes.append(
                "The circuit has no Josephson junctions, so it is a purely harmonic "
                "LC network: the levels are evenly spaced and the anharmonicity is zero."
            )

        for name, value in net.options.items():
            if name not in _KNOWN_OPTIONS:
                raise NetlistError(
                    f"unknown option '{name}'; known options are "
                    f"{', '.join(sorted(_KNOWN_OPTIONS))}"
                )
            expected = _KNOWN_OPTIONS[name]
            if expected and value not in expected:
                raise NetlistError(
                    f"option {name}={value!r} must be one of {', '.join(map(str, expected))}"
                )


_KNOWN_OPTIONS: dict[str, tuple] = {
    "ext_basis": ("discretized", "harmonic"),
    "basis_completion": ("heuristic", "canonical"),
    "truncated_dim": (),
    "use_dynamic_flux_grouping": (True, False),
    "generate_noise_methods": (True, False),
}


def _coerce_option(text: str):
    """Turn an option's text into a bool, int, float or string, in that order."""
    lowered = text.strip().lower()
    if lowered in ("true", "yes", "on", "1"):
        return True
    if lowered in ("false", "no", "off", "0"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return lowered


def parse_netlist(
    text: str, name: str | None = None, source_path: str | None = None
) -> DeviceNetlist:
    """
    Parse a device netlist from a string.

    Args:
        text: The netlist source.
        name: Device name. A ``.name`` directive in the source wins over this;
            otherwise it defaults to the file stem, or ``"device"``.
        source_path: Where the text came from, recorded for reporting.

    Returns:
        A validated :class:`DeviceNetlist`.

    Raises:
        NetlistError: If the text is not a syntactically valid, quantizable circuit.
            The message carries the offending line number wherever one applies.
    """
    default_name = name or (
        os.path.splitext(os.path.basename(source_path))[0] if source_path else "device"
    )
    return _Parser(text, default_name, source_path).parse()


def parse_netlist_file(path: str, name: str | None = None) -> DeviceNetlist:
    """Parse a device netlist from a file. See :func:`parse_netlist`."""
    if not os.path.isfile(path):
        raise NetlistError(f"netlist file not found: {path}")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return parse_netlist(text, name=name, source_path=os.path.abspath(path))


FORMAT_REFERENCE = """\
qforge device netlist - format reference

  A device schematic, one card per line, like a SPICE netlist.
  Comments: '*' at the start of a line, or ';', '#', '//' anywhere.
  A line starting with '+' continues the previous one.

ELEMENTS                    <name> <node+> <node-> <value...>

  C<n>  a b  <value>        Capacitor.  90fF          or EC=0.3  (GHz)
  L<n>  a b  <value>        Inductor.   100nH         or EL=0.5  (GHz)
  J<n>  a b  <EJ> [<EC>]    Junction.   EJ=15 EC=0.3  or Ic=30nA Cj=2fF
  R<n>  a b  <value>        Resistor.   1MOhm    (dissipation only)
  K<n>  L1 L2 <value>       Mutual L.   k=0.05   or M=1nH or EML=<GHz>

  Node '0', 'gnd' or 'ground' is ground. Any other label becomes a
  circuit node. Junctions take harmonics with EJ2=, EJ3=, ...

UNITS

  Bare numbers are GHz. Physical units are SI, case-sensitive prefixes
  (M = mega, m = milli):  T G M k m u n p f a
  Recognised units:  Hz  F  H  A  J  eV  Ohm

  Conversions used:   EC = e^2 / 2C      EL = (Phi_0/2pi)^2 / L
                      EJ = Ic Phi_0/2pi  EJ = (Phi_0/2pi)^2 / Lj

DIRECTIVES

  .title <text>               Human-readable title.
  .name  <text>               Device name (defaults to the file name).
  .param NAME = <value>       A named, sweepable circuit parameter.
  .ground <node>              Choose the ground node (default: 0 / gnd).
  .flux   <i|all> = <Phi_0>   External flux through loop i.
  .charge <i|all> = <2e>      Offset charge n_g on periodic variable i.
  .cutoff n<i>|ext<i>|all = N Basis cutoff for a variable.
  .levels <N>                 Eigenvalues to compute (default 8).
  .options k=v ...            ext_basis=discretized|harmonic
                              basis_completion=heuristic|canonical
                              truncated_dim=<N>
                              use_dynamic_flux_grouping=true|false
                              generate_noise_methods=true|false
  .end                        Stop parsing here.

EXPRESSIONS

  {EJ0 / 50}  evaluates over .param values with + - * / ** % and
  sqrt exp log log10 sin cos tan abs min max round, plus the constant pi.
  A bare .param name (EJ=EJ0) stays symbolic and can be swept afterwards.

EXAMPLE - a transmon in physical units

  .title  Transmon, 90 fF shunt
  J1  1  0  Ic=30nA  Cj=2fF
  C1  1  0  90fF
  .charge 1 = 0.0
  .cutoff n1 = 30
  .levels 6
  .end
"""
