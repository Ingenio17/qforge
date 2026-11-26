"""
Randomized benchmarking of physical pulses.

Every Clifford is compiled to two physical pi/2 pulses and three virtual Zs, each
pulse is simulated on the multilevel ladder with T1 and T2 running, and random
sequences of those simulated channels are composed and inverted exactly as in the
laboratory. The decay of the survival probability gives the error per Clifford, with
state preparation and measurement error fitted out.

Standard RB assumes the qubit stays a qubit. When a fast pulse leaks to |2>, its decay
no longer equals the gate error, so the leakage-aware analysis of Wood and Gambetta
(Phys. Rev. A 97, 032306, 2018) is run on the same sequences: the population left in
the qubit gives the leakage rate L1, the polarisation left in it gives the decay
lambda2, and the average error is ((1 - lambda2) + L1) / 2.

Because this is a simulation, the true average error of the same 24 channels is also
available. Returning both is what makes the protocol checkable.

Units: GHz and ns, except T1 and T2 which are in microseconds.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.linalg import expm
from scipy.optimize import curve_fit

from QubitWeave.core.pulse_optimizer import Ladder, Pulse, _hamiltonians

__all__ = [
    "clifford_group",
    "coherence_limit",
    "pulse_superoperator",
    "randomized_benchmarking",
]


def _rz(angle: float, dim: int = 2) -> np.ndarray:
    """diag(1, e^{i a}, e^{2 i a}, ...): a frame update acts on the whole ladder."""
    return np.diag(np.exp(1j * angle * np.arange(dim)))


_SX = np.array([[1, -1j], [-1j, 1]]) / np.sqrt(2)  # exp(-i pi/4 X)


def clifford_group() -> list[dict[str, Any]]:
    """
    The 24 single-qubit Cliffords as Z(a) SX Z(b) SX Z(c), with the matrix of each.

    Every element costs two physical pulses, so all 24 have the same duration.
    """
    group: list[dict[str, Any]] = []
    quarter = np.pi / 2 * np.arange(4)
    for a in quarter:
        for b in quarter:
            for c in quarter:
                matrix = _rz(a) @ _SX @ _rz(b) @ _SX @ _rz(c)
                if all(abs(np.trace(g["matrix"].conj().T @ matrix)) < 2 - 1e-9 for g in group):
                    group.append({"angles": (a, b, c), "matrix": matrix})
    return group


def _super(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Column-stacking superoperator of rho -> left rho right."""
    return np.kron(right.T, left)


def _dissipator(op: np.ndarray) -> np.ndarray:
    identity = np.eye(len(op))
    number = op.conj().T @ op
    return _super(op, op.conj().T) - 0.5 * (_super(number, identity) + _super(identity, number))


def _noise(dim: int, t1: float, t2: float) -> np.ndarray:
    """Lindblad generator (1/ns) matching GateEngine's collapse operators."""
    gamma_1, gamma_2 = 1e-3 / t1, 1e-3 / t2
    gamma_phi = gamma_2 - gamma_1 / 2
    if gamma_phi < -1e-12:
        raise ValueError(f"T2 = {t2} us exceeds 2 T1 = {2 * t1} us.")
    lowering = np.diag(np.sqrt(np.arange(1, dim)), 1).astype(complex)
    number = np.diag(np.arange(dim)).astype(complex)
    return gamma_1 * _dissipator(lowering) + 2 * max(gamma_phi, 0.0) * _dissipator(number)


def pulse_superoperator(
    ladder: Ladder, pulse: Pulse, t1: float = np.inf, t2: float = np.inf
) -> np.ndarray:
    """Channel of one pulse on the full ladder, as a column-stacking superoperator."""
    identity = np.eye(ladder.dim)
    generator = _noise(ladder.dim, t1, t2)
    total = np.eye(ladder.dim**2, dtype=complex)
    for hamiltonian in _hamiltonians(ladder, pulse):
        coherent = -1j * (_super(hamiltonian, identity) - _super(identity, hamiltonian))
        total = expm((coherent + generator) * pulse.dt) @ total
    # Return to the frame rotating at f01 if the drive was detuned from it.
    frame = _rz(-2 * np.pi * pulse.detuning * pulse.duration, ladder.dim)
    return _super(frame, frame.conj().T) @ total


def _average_error(channel: np.ndarray, ideal: np.ndarray, dim: int) -> float:
    """1 - average gate fidelity over the six cardinal states (a 2-design)."""
    states = [
        np.array(v, dtype=complex) / np.linalg.norm(v)
        for v in ([1, 0], [0, 1], [1, 1], [1, -1], [1, 1j], [1, -1j])
    ]
    total = 0.0
    for state in states:
        full = np.zeros(dim, dtype=complex)
        full[:2] = state
        target = np.zeros(dim, dtype=complex)
        target[:2] = ideal @ state
        rho = (channel @ np.outer(full, full.conj()).flatten(order="F")).reshape(
            dim, dim, order="F"
        )
        total += np.real(target.conj() @ rho @ target)
    return 1.0 - total / len(states)


def coherence_limit(duration: float, t1: float, t2: float) -> float:
    """Average gate error of an ideal gate lasting ``duration`` ns under T1 and T2 (us)."""
    ratio = duration * 1e-3
    return (3.0 - np.exp(-ratio / t1) - 2.0 * np.exp(-ratio / t2)) / 6.0


def randomized_benchmarking(
    ladder: Ladder,
    half_pi: Pulse,
    t1: float = np.inf,
    t2: float = np.inf,
    lengths=(1, 10, 25, 50, 100, 200, 400, 700, 1000),
    sequences: int = 30,
    seed: int = 11,
    z_correction: float = 0.0,
) -> dict[str, Any]:
    """
    Run single-qubit randomized benchmarking on a physical pi/2 pulse.

    Args:
        half_pi: The pi/2 pulse about X that every Clifford is built from.
        t1, t2: Coherence times in us.
        lengths: Numbers of random Cliffords before the recovery gate.
        sequences: Random sequences per length.
        z_correction: Virtual Z (rad) applied before and after the pulse to cancel
            the phase error a short pulse leaves on the qubit.

    Returns:
        dict with "lengths", "survival" (length by sequence), "mean", "std", the fit
        ("A", "p", "B"), "error_per_clifford" from the standard decay, the
        leakage-aware "corrected_error", "leakage_rb" (L1) and "lambda2", "subspace"
        (mean population left in {|0>, |1>}), "true_error" and "leakage" computed
        directly from the channels, "coherence_limit" and "clifford_duration" in ns.
    """
    rng = np.random.default_rng(seed)
    dim = ladder.dim
    group = clifford_group()
    matrices = np.array([g["matrix"] for g in group])
    correction = _rz(z_correction, dim)
    pulse = pulse_superoperator(ladder, half_pi, t1, t2)
    pulse = (
        _super(correction, correction.conj().T) @ pulse @ _super(correction, correction.conj().T)
    )

    channels = []
    for element in group:
        z = [_rz(angle, dim) for angle in element["angles"]]
        za, zb, zc = (_super(m, m.conj().T) for m in z)
        channels.append(za @ pulse @ zb @ pulse @ zc)
    channels = np.array(channels)

    # Multiplication table and inverses, matched up to global phase.
    def index_of(matrix):
        overlaps = np.abs(np.einsum("kij,ij->k", matrices.conj(), matrix))
        return int(np.argmax(overlaps))

    table = np.array([[index_of(a @ b) for b in matrices] for a in matrices])
    inverse = np.array([index_of(a.conj().T) for a in matrices])

    ground = np.zeros(dim**2, dtype=complex)
    ground[0] = 1.0
    identity_index = index_of(np.eye(2))
    survival = np.zeros((len(lengths), sequences))
    excited = np.zeros_like(survival)
    for row, length in enumerate(lengths):
        for column in range(sequences):
            state, running = ground.copy(), identity_index
            for gate in rng.integers(0, len(group), size=length):
                state = channels[gate] @ state
                running = table[gate, running]
            state = channels[inverse[running]] @ state
            survival[row, column] = np.real(state[0])
            excited[row, column] = np.real(state[dim + 1])

    mean = survival.mean(axis=1)

    def model(m, a, p, b):
        return a * p**m + b

    # Ground-state survival decays towards 1/2 here unless the decay is still shallow,
    # in which case B is not identifiable and is fixed at the depolarised value.
    shallow = mean[-1] > 0.65
    if shallow:
        (a, p), _ = curve_fit(
            lambda m, a, p: model(m, a, p, 0.5), lengths, mean, p0=(0.5, 0.999), maxfev=20000
        )
        b = 0.5
    else:
        halfway = float(np.interp(-0.75, -mean, lengths))
        (a, p, b), _ = curve_fit(
            model,
            lengths,
            mean,
            p0=(0.5, 0.5 ** (1 / max(halfway, 1.0)), 0.5),
            bounds=((0, 0, 0), (1, 1, 1)),
            maxfev=20000,
        )

    # Leakage-aware analysis of the same sequences.
    subspace = (survival + excited).mean(axis=1)
    polarisation = (survival - excited).mean(axis=1)
    m = np.asarray(lengths, dtype=float)
    usable = polarisation > 0.02
    (_, lambda2), _ = curve_fit(
        lambda m, c, lam: c * lam**m,
        m[usable],
        polarisation[usable],
        p0=(1.0, p),
        bounds=((0, 0), (1.5, 1)),
        maxfev=20000,
    )
    if 1 - subspace.min() > 0.05:
        (floor, lambda1), _ = curve_fit(
            lambda m, a, lam: a + (1 - a) * lam**m,
            m + 1,
            subspace,
            p0=(0.6, 1 - 1 / m[-1]),
            bounds=((0, 0), (1, 1)),
            maxfev=20000,
        )
        leakage_rb = (1 - floor) * (1 - lambda1)
    else:
        # Too little leakage to see it saturate: the initial slope is L1 itself.
        leakage_rb = float(np.sum((1 - subspace) * (m + 1)) / np.sum((m + 1) ** 2))

    errors = [_average_error(c, g["matrix"], dim) for c, g in zip(channels, group)]
    leaked = 0.0
    for start in (0, 1):
        rho = np.zeros((dim, dim), dtype=complex)
        rho[start, start] = 1.0
        out = np.mean(channels, axis=0) @ rho.flatten(order="F")
        leaked += 0.5 * (1.0 - np.real(out[0]) - np.real(out[dim + 1]))
    duration = 2 * half_pi.duration
    return {
        "lengths": np.asarray(lengths),
        "survival": survival,
        "mean": mean,
        "std": survival.std(axis=1, ddof=1),
        "A": float(a),
        "p": float(p),
        "B": float(b),
        "error_per_clifford": float((1 - p) / 2),
        "corrected_error": float(((1 - lambda2) + leakage_rb) / 2),
        "leakage_rb": float(leakage_rb),
        "lambda2": float(lambda2),
        "subspace": subspace,
        "true_error": float(np.mean(errors)),
        "coherence_limit": (float(coherence_limit(duration, t1, t2)) if np.isfinite(t1) else 0.0),
        "leakage": float(leaked),
        "clifford_duration": float(duration),
    }
