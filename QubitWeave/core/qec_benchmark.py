"""
Exact logical error rates of stabilizer codes under code-capacity noise.

Each data qubit suffers an independent Pauli error, the syndrome is measured
perfectly, the code's own lookup table picks the correction, and the round fails if
what is left over is a logical operator. All 4^n Pauli patterns are enumerated, so the
result is the exact polynomial in the physical error rate rather than a Monte Carlo
estimate, and it can be evaluated at any rate for free.

Measurement and gate errors are not included: this is the standard code-capacity
setting, an upper bound on how well a code can do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from QubitWeave.core.stabilizer_codes import StabilizerCode

__all__ = ["logical_error_polynomial", "logical_error_rate", "pseudo_threshold"]


def _support(qubits: Sequence[int], num_data: int) -> np.ndarray:
    row = np.zeros(num_data, dtype=np.uint8)
    row[list(qubits)] = 1
    return row


def logical_error_polynomial(code: StabilizerCode, channel: str = "depolarizing") -> dict[str, Any]:
    """
    Count the failing Pauli patterns of each weight.

    Args:
        code: Any StabilizerCode with a syndrome table.
        channel: "depolarizing" (X, Y, Z equally likely), "bit_flip" or "phase_flip".

    Returns:
        dict with "failures" (failing patterns by weight) and "patterns" (all patterns
        by weight), both of length n + 1, and "errors_per_site" (3 or 1).
    """
    n = code.num_data
    kinds = {"depolarizing": (1, 2, 3), "bit_flip": (1,), "phase_flip": (2,)}
    if channel not in kinds:
        raise ValueError(f"Unknown channel '{channel}'. Use one of {sorted(kinds)}.")
    alphabet = np.array((0, *kinds[channel]), dtype=np.uint8)  # bit 0 = X part, bit 1 = Z part

    base = len(alphabet)
    index = np.arange(base**n)
    digits = (index[:, None] // base ** np.arange(n)) % base
    paulis = alphabet[digits]
    weight = np.count_nonzero(paulis, axis=1)
    x_part, z_part = paulis & 1, paulis >> 1

    syndromes = np.zeros((len(index), code.num_ancilla), dtype=np.uint8)
    for gen in code.generators:
        # A Z-type check sees the X part of an error and vice versa.
        part = x_part if gen.basis == "Z" else z_part
        syndromes[:, gen.ancilla] = part[:, list(gen.data_qubits)].sum(axis=1) % 2

    # Residual after the code's own correction, per distinct syndrome.
    place = 1 << np.arange(code.num_ancilla)
    keys = syndromes @ place
    fix_x = np.zeros((2**code.num_ancilla, n), dtype=np.uint8)
    fix_z = np.zeros_like(fix_x)
    for syndrome, corrections in code.syndrome_to_correction.items():
        key = int(np.dot(syndrome, place))
        for qubit, pauli in corrections:
            (fix_x if pauli == "X" else fix_z)[key, qubit] ^= 1
    left_x, left_z = x_part ^ fix_x[keys], z_part ^ fix_z[keys]

    failed = np.zeros(len(index), dtype=bool)
    logicals = (
        (code.logical_x_qubits, code.logical_x_pauli),
        (code.logical_z_qubits, code.logical_z_pauli),
    )
    for qubits, pauli in logicals:
        # The residual acts as a logical error if it anticommutes with either logical.
        part = left_z if pauli == "X" else left_x
        failed |= (part @ _support(qubits, n)) % 2 == 1
    # Any check still violated after correction is a failure too.
    for gen in code.generators:
        part = left_x if gen.basis == "Z" else left_z
        failed |= part[:, list(gen.data_qubits)].sum(axis=1) % 2 == 1

    return {
        "failures": np.bincount(weight[failed], minlength=n + 1),
        "patterns": np.bincount(weight, minlength=n + 1),
        "errors_per_site": base - 1,
        "channel": channel,
    }


def logical_error_rate(polynomial: dict[str, Any], p) -> np.ndarray:
    """Exact logical error rate at physical error rate(s) ``p`` per data qubit."""
    p = np.atleast_1d(np.asarray(p, dtype=float))
    n = len(polynomial["failures"]) - 1
    total = np.zeros_like(p)
    for weight, count in enumerate(polynomial["failures"]):
        if count:
            each = (p / polynomial["errors_per_site"]) ** weight * (1 - p) ** (n - weight)
            total += count * each
    return total


def pseudo_threshold(polynomial: dict[str, Any]) -> float | None:
    """
    Physical error rate below which encoding helps, i.e. where P_L(p) = p.

    None if the code never beats a bare qubit for this channel.
    """
    grid = np.logspace(-5, np.log10(0.6), 4000)
    better = logical_error_rate(polynomial, grid) < grid
    if not better[0]:
        return None
    crossing = np.argmin(better)
    return float(grid[crossing]) if not better.all() else float(grid[-1])
