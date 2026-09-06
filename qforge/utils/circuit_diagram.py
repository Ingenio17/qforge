"""
Terminal ASCII circuit-diagram renderer.

Draws a compact, single-line-per-qubit circuit diagram using the same
visual vocabulary as Qiskit's default (matplotlib-backend) circuit drawing:
a solid dot for a control, a circled plus for a CNOT target, crossed
markers for SWAP, and bracketed boxes for everything else, including
measurement. It is display-only: it never participates in transpilation,
calibration, or simulation, so a bug here can never change simulated
physics, only what gets printed.

Input is plain data (`num_qubits` + a list of operation dicts), not tied to
any particular parser, so it can be reused anywhere a circuit needs to be
shown. See `qforge.core.workflow_engine.QASMTranspiler.parse_logical` for
the producer used by the QASM-driven workflows.
"""

from fractions import Fraction
from typing import Any, Dict, List

import numpy as np

# Gates whose logical name (as written in QASM/gate calls) gets a fixed,
# per-qubit symbol rather than a generic bracketed box.
_TWO_QUBIT_FIXED = {
    "cx": ("●", "⊕"),  # control dot, circled-plus target
    "cnot": ("●", "⊕"),
    "cz": ("●", "●"),
    "swap": ("✕", "✕"),
}
_TWO_QUBIT_CONTROLLED_BOX = {
    "cp": "P",
    "cphase": "P",
    "crz": "RZ",
    "cu1": "U1",
    "cu3": "U3",
    "cy": "Y",
    "ch": "H",
}
_THREE_QUBIT_FIXED = {
    "ccx": ("●", "●", "⊕"),
    "toffoli": ("●", "●", "⊕"),
    "ccnot": ("●", "●", "⊕"),
    "cswap": ("●", "✕", "✕"),
    "fredkin": ("●", "✕", "✕"),
}


def _format_angle(theta: float) -> str:
    """Renders a rotation angle as a small multiple of pi when it is one
    (e.g. 1.5708 -> 'π/2'), otherwise as a 2-decimal number."""
    if abs(theta) < 1e-9:
        return "0"
    ratio = theta / np.pi
    frac = Fraction(ratio).limit_denominator(16)
    if abs(float(frac) - ratio) < 1e-6 and 1 <= frac.denominator <= 8:
        num, den = frac.numerator, frac.denominator
        sign = "-" if num < 0 else ""
        num = abs(num)
        num_str = "π" if num == 1 else f"{num}π"
        return f"{sign}{num_str}" if den == 1 else f"{sign}{num_str}/{den}"
    return f"{theta:.2f}"


def _label(name: str, params: List[float]) -> str:
    label = name.upper()
    if params:
        label += "(" + ",".join(_format_angle(p) for p in params) + ")"
    return label


def _tokens_for_op(op: Dict[str, Any]) -> Dict[int, str]:
    """Maps one logical operation to {qubit_index: rendered_symbol}, for
    every qubit the operation directly touches (not the qubits it merely
    passes over on the wire diagram, which the caller fills in itself)."""
    name = op["name"].lower()
    qs = list(dict.fromkeys(op["qubits"]))  # de-duplicate, keep order
    params = op.get("params") or []

    if name == "measure":
        return {qs[0]: "[M]"}

    if len(qs) == 1:
        return {qs[0]: f"[{_label(name, params)}]"}

    if len(qs) == 2:
        a, b = qs
        if name in _TWO_QUBIT_FIXED:
            ctrl_sym, targ_sym = _TWO_QUBIT_FIXED[name]
            return {a: ctrl_sym, b: targ_sym}
        if name in _TWO_QUBIT_CONTROLLED_BOX:
            sub = _TWO_QUBIT_CONTROLLED_BOX[name]
            if params:
                sub += "(" + ",".join(_format_angle(p) for p in params) + ")"
            return {a: "●", b: f"[{sub}]"}
        box = f"[{_label(name, params)}]"
        return {a: box, b: box}

    if len(qs) == 3 and name in _THREE_QUBIT_FIXED:
        syms = _THREE_QUBIT_FIXED[name]
        return dict(zip(qs, syms))

    box = f"[{_label(name, params)}]"
    return {q: box for q in qs}


def _center(token: str, width: int, fill: str) -> str:
    if len(token) >= width:
        return token
    pad = width - len(token)
    left = pad // 2
    return fill * left + token + fill * (pad - left)


def draw_circuit(
    num_qubits: int,
    ops: List[Dict[str, Any]],
    max_qubits: int = 24,
    max_columns: int = 40,
    max_ops: int = 2000,
) -> str:
    """
    Renders `ops` (each `{"name": str, "qubits": [int, ...], "params":
    [float, ...]}`, or `{"name": "measure", "qubits": [q]}`) over
    `num_qubits` wires as a compact ASCII diagram, one line per qubit.

    Gates are laid out greedily into the earliest free column spanning
    every wire between (and including) their lowest and highest qubit
    index, so non-adjacent multi-qubit gates draw a connecting "|" through
    any wires they pass over, matching how a real circuit diagram reads.

    Truncates gracefully rather than producing an unusable wall of text:
    qubits beyond `max_qubits` are dropped (any gate touching one is
    skipped rather than drawn with a dangling connection), and columns
    beyond `max_columns` are replaced with a single "..." column. Both
    omissions are reported in a trailing note.
    """
    if num_qubits <= 0:
        return "(empty circuit)"

    notes: List[str] = []
    qubits_shown = min(num_qubits, max_qubits)
    if qubits_shown < num_qubits:
        notes.append(f"{num_qubits - qubits_shown} additional qubit(s) not shown")

    if len(ops) > max_ops:
        notes.append(f"{len(ops) - max_ops} additional operation(s) not shown (circuit too deep)")
        ops = ops[:max_ops]

    # Drop any operation that reaches outside the visible qubit range,
    # rather than drawing a gate with a dangling connection to a hidden wire.
    visible_ops = [op for op in ops if op["qubits"] and all(q < qubits_shown for q in op["qubits"])]

    next_free_col = [0] * qubits_shown
    columns: List[Dict[int, str]] = []
    measured_at: Dict[int, int] = {}

    for op in visible_ops:
        qs = list(dict.fromkeys(op["qubits"]))
        lo, hi = min(qs), max(qs)
        col = max(next_free_col[q] for q in range(lo, hi + 1))
        while col >= len(columns):
            columns.append({})

        tokens = _tokens_for_op(op)
        for q in range(lo, hi + 1):
            columns[col][q] = tokens.get(q, "PASS")
            next_free_col[q] = col + 1

        if op["name"].lower() == "measure":
            measured_at[qs[0]] = col

    truncated_columns = len(columns) > max_columns
    if truncated_columns:
        columns = columns[:max_columns]
        notes.append("additional gate(s) not shown (circuit too long)")

    col_widths = [
        max([len(tok) for tok in col.values() if tok != "PASS"], default=1) for col in columns
    ]

    if truncated_columns:
        columns.append({q: "⋯" for q in range(qubits_shown)})
        col_widths.append(1)

    label_width = max((len(f"q{i}:") for i in range(qubits_shown)), default=2)

    lines = []
    for q in range(qubits_shown):
        parts = [f"q{q}:".ljust(label_width)]
        for c, col in enumerate(columns):
            width = col_widths[c]
            fill = "═" if (q in measured_at and measured_at[q] < c) else "─"
            tok = col.get(q)
            if tok is None:
                cell = fill * width
            elif tok == "PASS":
                cell = _center("│", width, fill)
            else:
                cell = _center(tok, width, fill)
            parts.append(fill + cell + fill)
        lines.append("".join(parts))

    if notes:
        lines.append("(" + "; ".join(notes) + ")")

    return "\n".join(lines)
