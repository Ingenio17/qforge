"""
Gate kernels that act on a multilevel register's state array in place.

A gate on one or two qubits of an N-qubit register touches one or two axes of the
state, so it costs time proportional to the state's size. Building the same gate as an
operator on the whole register costs a matrix of that size squared (or its sparse
pattern plus a permutation), which is what made encoded circuits slow: one CNOT inside
an 18-qubit block was a 262,144 x 262,144 operator.

Every kernel takes an array whose leading axes are the register's local dimensions.
Trailing axes, if any, are carried along untouched. Levels above |1> follow the same
rule as the operator builders in GateEngine and ErrorCorrectionEngine: the gate acts on
the computational subspace and is the identity on leakage levels.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "apply_cx",
    "apply_cz",
    "apply_hadamard",
    "apply_matrix",
    "apply_pauli",
    "apply_rz",
    "pauli_string",
]

_ROOT_HALF = 1.0 / np.sqrt(2.0)


def _level(state: np.ndarray, *fixed: tuple[int, int]) -> tuple:
    """Index selecting given levels on given axes, every other axis in full."""
    index: list = [slice(None)] * state.ndim
    for axis, level in fixed:
        index[axis] = level
    return tuple(index)


def apply_pauli(state: np.ndarray, axis: int, pauli: str) -> None:
    """X, Y or Z on the computational levels of one qubit, in place."""
    zero, one = _level(state, (axis, 0)), _level(state, (axis, 1))
    if pauli == "Z":
        state[one] *= -1.0
    elif pauli == "X":
        kept = state[zero].copy()
        state[zero] = state[one]
        state[one] = kept
    elif pauli == "Y":
        kept = state[zero].copy()
        state[zero] = -1j * state[one]
        state[one] = 1j * kept
    else:
        raise ValueError(f"Unknown Pauli {pauli!r}")


def apply_hadamard(state: np.ndarray, axis: int) -> None:
    """Hadamard on the computational levels of one qubit, in place."""
    zero, one = _level(state, (axis, 0)), _level(state, (axis, 1))
    kept = state[zero].copy()
    state[zero] = (kept + state[one]) * _ROOT_HALF
    state[one] = (kept - state[one]) * _ROOT_HALF


def apply_rz(state: np.ndarray, axis: int, theta: float, pauli: str = "Z") -> None:
    """
    Rotation with eigenvalues (1, e^{i theta}) about Z or X, in place.

    Leakage levels are in the +1 eigenspace, as in GateEngine._build_ideal_rz_operator.
    """
    phase = complex(np.exp(1j * theta))
    if pauli == "Z":
        state[_level(state, (axis, 1))] *= phase
    elif pauli == "X":
        zero, one = _level(state, (axis, 0)), _level(state, (axis, 1))
        kept = state[zero].copy()
        same, swap = (1.0 + phase) / 2.0, (1.0 - phase) / 2.0
        state[zero] = same * kept + swap * state[one]
        state[one] = same * state[one] + swap * kept
    else:
        raise ValueError(f"Unsupported rotation axis: {pauli!r}")


def apply_cx(state: np.ndarray, control: int, target: int) -> None:
    """CNOT, in place. The identity if either qubit is outside {|0>, |1>}."""
    if control == target:
        raise ValueError("CX requires different control and target qubits.")
    zero = _level(state, (control, 1), (target, 0))
    one = _level(state, (control, 1), (target, 1))
    kept = state[zero].copy()
    state[zero] = state[one]
    state[one] = kept


def apply_cz(state: np.ndarray, a: int, b: int) -> None:
    """CZ, in place."""
    state[_level(state, (a, 1), (b, 1))] *= -1.0


def apply_matrix(state: np.ndarray, matrix: np.ndarray, axes: Sequence[int]) -> np.ndarray:
    """
    Apply an operator to some axes of the state and return the result.

    ``matrix`` acts on the tensor product of the axes in the order given.
    """
    axes = list(axes)
    local = [state.shape[a] for a in axes]
    k = len(axes)
    tensor = np.asarray(matrix).reshape(local + local)
    out = np.tensordot(tensor, state, axes=(list(range(k, 2 * k)), axes))
    return np.moveaxis(out, range(k), axes)


def pauli_string(state: np.ndarray, axes: Sequence[int], pauli: str) -> np.ndarray:
    """A copy of the state with the same Pauli applied to several qubits."""
    out = state.copy()
    for axis in axes:
        apply_pauli(out, axis, pauli)
    return out
