"""
Optimal control of single-qubit gates on a real, multilevel superconducting qubit.

A superconducting qubit is a ladder, so a gate fast enough to be useful also drives
|1> to |2>. A Gaussian pulse is spectrally narrow but must be long, DRAG cancels the
first-order leakage with a derivative quadrature, and GRAPE (Khaneja et al. 2005)
drops the pulse shape altogether and optimises every sample of both quadratures by
gradient descent on the gate error.

The ladder is taken from the qubit's own spectrum and charge matrix elements. The
optimiser works in the frame rotating at the 0-1 frequency under the rotating-wave
approximation; :func:`lab_frame_unitary` then replays a finished pulse with the
carrier, every charge matrix element and no RWA, so the approximation is checked
rather than trusted.

Units: frequencies and Rabi rates in GHz (cycles per ns), times in ns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar

__all__ = [
    "Ladder",
    "Pulse",
    "gaussian_pulse",
    "gate_metrics",
    "lab_frame_unitary",
    "optimize_drag",
    "optimize_gaussian",
    "optimize_grape",
    "rotating_frame_unitary",
]

PAULI_X = np.array([[0, 1], [1, 0]], dtype=complex)


@dataclass(frozen=True)
class Ladder:
    """Levels of one qubit: energies (GHz, ground at zero) and its charge operator."""

    energies: np.ndarray
    charge: np.ndarray

    @classmethod
    def from_qubit(cls, qubit, levels: int = 4) -> Ladder:
        """Build from any scqubits-style qubit object, including a DeviceQubit."""
        energies = np.real(np.asarray(qubit.eigenvals(evals_count=levels)))
        charge = np.asarray(qubit.matrixelement_table("n_operator", evals_count=levels))
        return cls(energies - energies[0], charge.astype(complex))

    @property
    def dim(self) -> int:
        return len(self.energies)

    @property
    def f01(self) -> float:
        return float(self.energies[1])

    @property
    def anharmonicity(self) -> float:
        """f12 - f01 in GHz."""
        return float(self.energies[2] - 2 * self.energies[1])

    def rotating_drift(self) -> np.ndarray:
        """Drift in the frame rotating at f01, rad/ns."""
        return 2 * np.pi * np.diag(self.energies - np.arange(self.dim) * self.f01).astype(complex)

    def rotating_drives(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Operators multiplying the x and y Rabi rates (GHz), in rad/ns per GHz.

        Scaled so that a constant x drive of 1 GHz rotates the qubit at 1 GHz. Only
        neighbouring levels survive the rotating-wave approximation.
        """
        steps = np.diag(self.charge, -1) / abs(self.charge[1, 0])
        # Choose each level's phase so the raising elements are real and positive.
        raising = np.diag(np.abs(steps), -1).astype(complex)
        x = np.pi * (raising + raising.conj().T)
        y = np.pi * (1j * raising - 1j * raising.conj().T)
        return x, y


@dataclass(frozen=True)
class Pulse:
    """Piecewise-constant quadratures: ``x[k]``, ``y[k]`` are Rabi rates in GHz."""

    x: np.ndarray
    y: np.ndarray
    dt: float
    detuning: float = 0.0  # drive frequency minus f01, GHz

    @property
    def duration(self) -> float:
        return self.dt * len(self.x)

    @property
    def times(self) -> np.ndarray:
        """Sample midpoints, ns."""
        return (np.arange(len(self.x)) + 0.5) * self.dt


def _step_unitaries(hamiltonians: np.ndarray, dt: float):
    evals, evecs = np.linalg.eigh(hamiltonians)
    phases = np.exp(-1j * evals * dt)
    unitaries = (evecs * phases[:, None, :]) @ np.conj(np.swapaxes(evecs, 1, 2))
    return unitaries, evals, evecs, phases


def _hamiltonians(ladder: Ladder, pulse: Pulse) -> np.ndarray:
    op_x, op_y = ladder.rotating_drives()
    drift = ladder.rotating_drift()
    drift = drift - 2 * np.pi * pulse.detuning * np.diag(np.arange(ladder.dim))
    return drift + pulse.x[:, None, None] * op_x + pulse.y[:, None, None] * op_y


def rotating_frame_unitary(ladder: Ladder, pulse: Pulse, trajectory: bool = False):
    """
    Propagator of a pulse in the rotating frame.

    With ``trajectory`` the propagator after every sample is returned as well.
    """
    steps, *_ = _step_unitaries(_hamiltonians(ladder, pulse), pulse.dt)
    total = np.eye(ladder.dim, dtype=complex)
    history = []
    for step in steps:
        total = step @ total
        if trajectory:
            history.append(total)
    return (total, np.array(history)) if trajectory else total


def lab_frame_unitary(ladder: Ladder, pulse: Pulse, samples_per_period: int = 80) -> np.ndarray:
    """
    Propagator with the carrier included, returned in the rotating frame.

    No rotating-wave approximation, and every element of the charge operator is kept,
    so counter-rotating terms and couplings such as 0-3 are all present.
    """
    fastest = max(ladder.energies[-1], ladder.f01)
    substeps = int(np.ceil(pulse.dt * fastest * samples_per_period))
    dt = pulse.dt / substeps
    t = (np.arange(len(pulse.x) * substeps) + 0.5) * dt
    x, y = np.repeat(pulse.x, substeps), np.repeat(pulse.y, substeps)
    carrier = 2 * np.pi * (ladder.f01 + pulse.detuning) * t
    voltage = 2 * np.pi * (x * np.cos(carrier) + y * np.sin(carrier)) / abs(ladder.charge[1, 0])

    v_evals, v_evecs = np.linalg.eigh(ladder.charge)
    half = np.exp(-1j * np.pi * ladder.energies * dt)
    total = np.eye(ladder.dim, dtype=complex)
    for amplitude in voltage:
        kick = (v_evecs * np.exp(-1j * amplitude * v_evals * dt)) @ v_evecs.conj().T
        total = half[:, None] * (kick @ (half[:, None] * total))
    rotating = np.exp(2j * np.pi * np.arange(ladder.dim) * ladder.f01 * pulse.duration)
    return rotating[:, None] * total


def gate_metrics(unitary: np.ndarray) -> dict[str, float]:
    """
    Average gate error and leakage of an X gate, up to virtual Z rotations.

    Z rotations before and after the pulse are free frame updates, so only the
    magnitudes of the two flip amplitudes can be in error.
    """
    block = unitary[:2, :2]
    overlap = abs(block[1, 0]) + abs(block[0, 1])
    norm = float(np.sum(np.abs(block) ** 2))
    return {"error": float(1.0 - (overlap**2 + norm) / 6.0), "leakage": float(1.0 - norm / 2.0)}


def gaussian_pulse(
    ladder: Ladder,
    duration: float,
    amplitude: float | None = None,
    drag: float = 0.0,
    detuning: float = 0.0,
    angle: float = np.pi,
    dt: float = 0.05,
) -> Pulse:
    """
    Gaussian envelope (sigma = T/6, GateEngine's shape), optionally with DRAG.

    ``drag`` scales the derivative quadrature ``-drag * dx/dt / alpha``. Without an
    ``amplitude`` the pulse area is set to ``angle``.
    """
    count = max(8, int(round(duration / dt)))
    dt = duration / count
    t = (np.arange(count) + 0.5) * dt
    sigma = duration / 6.0
    shape = np.exp(-0.5 * ((t - duration / 2) / sigma) ** 2)
    if amplitude is None:
        amplitude = angle / (2 * np.pi * np.sum(shape) * dt)
    x = amplitude * shape
    derivative = -(t - duration / 2) / sigma**2 * x
    y = -drag * derivative / (2 * np.pi * ladder.anharmonicity)
    return Pulse(x, y, dt, detuning)


def _error(ladder: Ladder, pulse: Pulse) -> float:
    return gate_metrics(rotating_frame_unitary(ladder, pulse))["error"]


def optimize_gaussian(ladder: Ladder, duration: float) -> Pulse:
    """Best plain Gaussian X pulse: the amplitude is calibrated, nothing else."""
    base = gaussian_pulse(ladder, duration).x.max()
    found = minimize_scalar(
        lambda a: _error(ladder, gaussian_pulse(ladder, duration, a)),
        bounds=(0.6 * base, 1.4 * base),
        method="bounded",
    )
    return gaussian_pulse(ladder, duration, float(found.x))


def optimize_drag(ladder: Ladder, duration: float) -> Pulse:
    """Best DRAG X pulse: amplitude, derivative weight and detuning all calibrated."""
    base = gaussian_pulse(ladder, duration).x.max()

    def build(v):
        return gaussian_pulse(ladder, duration, base * v[0], v[1], v[2] * 0.01)

    best = None
    for start in ((1.0, 0.5, 0.0), (1.0, 1.0, 0.0), (1.0, -0.5, 0.0)):
        found = minimize(
            lambda v: np.log10(_error(ladder, build(v)) + 1e-14),
            start,
            method="Nelder-Mead",
            options={"xatol": 1e-5, "fatol": 1e-4, "maxiter": 600},
        )
        if best is None or found.fun < best.fun:
            best = found
    return build(best.x)


def optimize_grape(
    ladder: Ladder,
    duration: float,
    target: np.ndarray = PAULI_X,
    dt: float = 0.25,
    max_rabi: float = 0.5,
    smoothness: float = 1e-4,
    initial: Pulse | None = None,
    max_iterations: int = 600,
    seed: int = 7,
) -> dict[str, Any]:
    """
    Optimise every sample of both quadratures to realise ``target`` on {|0>, |1>}.

    Args:
        duration: Gate time, ns. Rounded to whole samples.
        target: 2x2 unitary. Matched up to a global phase.
        dt: Sample period, ns (0.25 is a 4 GS/s waveform generator).
        max_rabi: Bound on each quadrature, GHz.
        smoothness: Weight of the penalty on sample-to-sample jumps, which also
            pulls the pulse to zero at both ends.
        initial: Starting pulse. Defaults to a Gaussian plus a little noise.

    Returns:
        dict with "pulse", "history" (gate error per iteration), "error",
        "leakage" and "iterations".
    """
    count = max(4, int(round(duration / dt)))
    dt = duration / count
    op_x, op_y = ladder.rotating_drives()
    drift = ladder.rotating_drift()
    dim = ladder.dim

    if initial is None:
        initial = gaussian_pulse(ladder, duration, dt=dt)
    rng = np.random.default_rng(seed)
    t = (np.arange(count) + 0.5) * dt
    x0 = np.interp(t, initial.times, initial.x) + 1e-3 * rng.normal(size=count)
    y0 = np.interp(t, initial.times, initial.y) + 1e-3 * rng.normal(size=count)

    embedded = np.zeros((dim, dim), dtype=complex)
    embedded[:2, :2] = target.conj().T  # Tr(target^dag M) over the computational block
    projector = np.zeros((dim, dim), dtype=complex)
    projector[0, 0] = projector[1, 1] = 1.0
    history: list[float] = []

    def objective(v):
        x, y = v[:count], v[count:]
        hams = drift + x[:, None, None] * op_x + y[:, None, None] * op_y
        steps, evals, evecs, phases = _step_unitaries(hams, dt)

        forward = np.empty((count + 1, dim, dim), dtype=complex)
        forward[0] = np.eye(dim)
        for k in range(count):
            forward[k + 1] = steps[k] @ forward[k]
        unitary = forward[-1]
        block = projector @ unitary @ projector
        overlap = np.trace(embedded @ unitary)
        fidelity = (abs(overlap) ** 2 + np.sum(np.abs(block) ** 2)) / 6.0

        # dF = 2 Re Tr(W dU) / 6 with W collecting both terms of the fidelity.
        weight = np.conj(overlap) * embedded + block.conj().T
        backward = np.empty((count, dim, dim), dtype=complex)
        acc = weight
        for k in range(count - 1, -1, -1):
            backward[k] = acc
            acc = acc @ steps[k]

        # Exact derivative of each step through its eigenbasis.
        gaps = evals[:, :, None] - evals[:, None, :]
        same = np.abs(gaps) < 1e-9
        kernel = np.where(
            same,
            -1j * dt * phases[:, :, None],
            (phases[:, :, None] - phases[:, None, :]) / np.where(same, 1.0, gaps),
        )
        dagger = np.conj(np.swapaxes(evecs, 1, 2))
        # Tr(B dStep F) = sum over the eigenbasis of (F B)_rotated^T * (dH_rot * kernel)
        sandwich = dagger @ (forward[:-1] @ backward) @ evecs
        grads = []
        for op in (op_x, op_y):
            rotated = dagger @ op @ evecs
            grads.append(2.0 * np.real(np.einsum("kij,kji->k", rotated * kernel, sandwich)) / 6.0)
        gradient = -np.concatenate(grads)

        penalty = 0.0
        for offset, samples in ((0, x), (count, y)):
            padded = np.concatenate([[0.0], samples, [0.0]])
            jumps = np.diff(padded)
            penalty += smoothness * np.sum(jumps**2)
            gradient[offset : offset + count] += 2 * smoothness * (jumps[:-1] - jumps[1:])
        objective.last = 1.0 - fidelity
        return 1.0 - fidelity + penalty, gradient

    def record(_):
        history.append(max(objective.last, 1e-16))

    found = minimize(
        objective,
        np.concatenate([x0, y0]),
        jac=True,
        method="L-BFGS-B",
        bounds=[(-max_rabi, max_rabi)] * (2 * count),
        callback=record,
        options={"maxiter": max_iterations, "ftol": 1e-15, "gtol": 1e-10},
    )
    pulse = Pulse(found.x[:count], found.x[count:], dt)
    metrics = gate_metrics(rotating_frame_unitary(ladder, pulse))
    return {"pulse": pulse, "history": history, "iterations": int(found.nit), **metrics}
