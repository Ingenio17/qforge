"""
Parametrically activated controlled-phase gate on a tunable coupler.

The usual tunable-coupler CZ is a transmon recipe: flux-tune one qubit by a few
hundred MHz until |11> meets |02>, then let the coupler swap population there and
back. That needs a qubit whose levels can be slid into place, which a strongly
anharmonic qubit is not. A fluxonium at its half-flux sweet spot has a 0-1
transition of a few hundred MHz and an anharmonicity of several GHz, so the
required "detuning" is many times the qubit frequency, and shifting level k by
``k * detuning`` would push |1> far below |0>.

The same transition can be reached without moving any level. The interaction
``g(t) n1 n2`` connects |11> to |02> and |20> directly, and those levels differ
from |11> by a fixed frequency. Modulating the coupler at that frequency,

    g(t) = g * envelope(t) * cos(2 pi f_mod t),      f_mod = |E_02 - E_11| / h

makes the exchange resonant. One full |11> -> |02>/|20> -> |11> cycle returns the
population with a phase of pi, which is a CZ. Both qubits stay at their operating
points throughout. Detuning the modulation slightly changes the phase picked up
over the cycle, which gives an arbitrary controlled phase.

Everything here is computed on the full multilevel product space from the exact
charge matrix elements, so off-resonant couplings, Stark shifts and leakage are in
the result rather than assumed away. No rotating-wave approximation is made.

Units: energies, frequencies and couplings in GHz, times in ns, phases in rad.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar

__all__ = [
    "EDGE_FRACTION",
    "FIDELITY_WARN",
    "calibrate_parametric_cphase",
    "evaluate_parametric_cphase",
    "parametric_envelope",
]

# Rise and fall of the flat-top coupler envelope, each as a fraction of the pulse.
# Matches the edge fraction of the flux pulse in GateEngine.
EDGE_FRACTION = 0.15

# Below this average gate fidelity the schedule carries a warning.
FIDELITY_WARN = 0.99

# Midpoint samples per modulation period, and per period of the fastest Bohr
# frequency in the truncated space. The step satisfies whichever is stricter.
_SAMPLES_PER_MODULATION = 32
_SAMPLES_PER_BOHR = 12

# |20> and |02> are treated as one collective ("bright") transition when they are
# closer than this many Rabi frequencies.
_BRIGHT_WINDOW = 3.0


def parametric_envelope(tau: float, duration: float, rise: float) -> float:
    """Raised-cosine flat top on ``[0, duration]``, zero outside it."""
    if tau < 0.0 or tau > duration:
        return 0.0
    edge = min(tau, duration - tau)
    if edge >= rise:
        return 1.0
    return 0.5 * (1.0 - np.cos(np.pi * edge / rise))


def _ordered_product(factors: np.ndarray) -> np.ndarray:
    """Time-ordered product of a stack of matrices, ``factors[0]`` acting first."""
    while len(factors) > 1:
        if len(factors) % 2:
            identity = np.eye(factors.shape[1], dtype=complex)[None]
            factors = np.concatenate([factors, identity])
        factors = factors[1::2] @ factors[0::2]
    return factors[0]


class _Pair:
    """Two qubits joined by a modulated ``n1 n2`` coupling."""

    def __init__(self, evals1, n1, evals2, n2, strength: float):
        evals1 = np.real(np.asarray(evals1, dtype=complex))
        evals2 = np.real(np.asarray(evals2, dtype=complex))
        self.e1 = evals1 - evals1[0]
        self.e2 = evals2 - evals2[0]
        self.n1 = np.asarray(n1, dtype=complex)
        self.n2 = np.asarray(n2, dtype=complex)
        self.strength = float(strength)

        d2 = len(self.e2)
        self.energies = (self.e1[:, None] + self.e2[None, :]).ravel()  # GHz
        coupling = 2.0 * np.pi * self.strength * np.kron(self.n1, self.n2)  # rad/ns
        self.v_evals, self.v_evecs = np.linalg.eigh(coupling)
        # |00>, |01>, |10>, |11> in the product basis.
        self.comp = np.array([0, 1, d2, d2 + 1])

    def transition(self) -> dict[str, Any]:
        """
        Pick the |11> -> |20>/|02> transition the modulation should address.

        Returns its frequency (GHz) and ``rabi``, the full-cycle frequency in GHz:
        a resonant flat pulse takes ``1 / rabi`` ns for one complete cycle. The
        cosine splits into two rotating halves, so the resonant coupling is half
        of ``strength * |matrix element|`` and the splitting is all of it.
        """
        candidates = []
        if len(self.e1) >= 3:
            element = abs(self.n1[2, 1] * self.n2[0, 1]) * self.strength
            candidates.append((element, self.e1[2] - self.e1[1] - self.e2[1], "|20>"))
        if len(self.e2) >= 3:
            element = abs(self.n1[0, 1] * self.n2[2, 1]) * self.strength
            candidates.append((element, self.e2[2] - self.e1[1] - self.e2[1], "|02>"))
        if not candidates:
            raise ValueError(
                "A parametric CZ goes through the second excited state of one of the "
                "qubits, so at least one of them needs truncated_dim >= 3."
            )

        candidates.sort(key=lambda c: c[0], reverse=True)
        rabi, frequency, label = candidates[0]
        if rabi < 1e-9:
            raise ValueError(
                "The coupler cannot activate a CZ on this pair: the charge operators "
                "do not connect |11> to |20> or |02> (or the coupling strength is zero)."
            )
        if len(candidates) == 2:
            other, other_frequency, other_label = candidates[1]
            if abs(frequency - other_frequency) < _BRIGHT_WINDOW * rabi:
                weights = np.array([rabi, other]) ** 2
                frequency = float(np.average([frequency, other_frequency], weights=weights))
                rabi = float(np.hypot(rabi, other))
                label = f"{label}+{other_label}"
        if abs(frequency) < 10.0 * rabi:
            raise ValueError(
                f"|11> and {label} are only {abs(frequency) * 1e3:.2f} MHz apart, so they "
                f"are already close to resonance and modulating the coupler cannot "
                f"address the transition selectively."
            )
        return {"frequency": abs(float(frequency)), "rabi": float(rabi), "label": label}

    def _propagate(self, amplitudes: np.ndarray, dt: float) -> np.ndarray:
        """
        Second-order split-operator propagator through midpoint amplitudes.

        Step k is D W e_k W^dag D, with D half a step of free evolution, W the
        eigenvectors of the coupling and e_k diagonal. Between neighbours, W^dag D D W is
        one constant matrix B, so the product is D W (prod e_k B) W^dag D^-1 and each
        factor is a row scaling of B rather than a matrix product.
        """
        half = np.exp(-1j * np.pi * self.energies * dt)
        adjoint = self.v_evecs.conj().T
        between = adjoint @ (half[:, None] ** 2 * self.v_evecs)
        total = np.eye(len(half), dtype=complex)
        for start in range(0, len(amplitudes), 2048):
            phases = np.exp(-1j * np.outer(amplitudes[start : start + 2048], self.v_evals) * dt)
            total = _ordered_product(phases[:, :, None] * between) @ total
        return (half[:, None] * self.v_evecs) @ total @ (adjoint * half.conj())

    def computational_blocks(self, frequency: float, rise_periods: int, plateaus: np.ndarray):
        """
        Computational 4x4 blocks, in the frame rotating at each qubit's own energies.

        The edges and plateau each span a whole number of modulation periods, so a
        plateau of k periods is a power of one Floquet propagator and an entire
        duration scan costs barely more than a single duration.

        Returns:
            (durations in ns, blocks with shape (len(plateaus), 4, 4))
        """
        period = 1.0 / frequency
        spread = float(self.energies.max())
        samples = int(max(_SAMPLES_PER_MODULATION, np.ceil(_SAMPLES_PER_BOHR * spread * period)))
        dt = period / samples

        t_rise = (np.arange(rise_periods * samples) + 0.5) * dt
        envelope = 0.5 * (1.0 - np.cos(np.pi * t_rise / (rise_periods * period)))
        carrier = np.cos(2.0 * np.pi * frequency * t_rise)
        rise = self._propagate(envelope * carrier, dt)
        fall = self._propagate(envelope[::-1] * carrier, dt)
        one_period = self._propagate(carrier[:samples], dt)

        floquet, modes = np.linalg.eig(one_period)
        left = fall[self.comp] @ modes
        right = np.linalg.solve(modes, rise[:, self.comp])
        powers = np.exp(1j * np.outer(plateaus, np.angle(floquet)))
        blocks = (left[None] * powers[:, None, :]) @ right

        durations = (2 * rise_periods + plateaus) * period
        rotating = np.exp(2j * np.pi * np.outer(durations, self.energies[self.comp]))
        return durations, rotating[:, :, None] * blocks


def _score(blocks: np.ndarray, target_phase: float) -> dict[str, np.ndarray]:
    """
    Average gate fidelity to diag(1, 1, 1, exp(i target_phase)) up to local Zs.

    Single-qubit Z rotations cost nothing (they are frame updates), so the phases
    the pulse leaves on each qubit are measured and factored out rather than
    counted as error. The Pedersen formula keeps Tr(M M^dag), so population that
    leaks out of the computational subspace does count.
    """
    diagonal = np.einsum("kii->ki", blocks)
    angles = np.angle(diagonal)
    phase1 = angles[:, 2] - angles[:, 0]
    phase2 = angles[:, 1] - angles[:, 0]
    undo = np.exp(-1j * np.stack([0 * phase1, phase2, phase1, phase1 + phase2], axis=1))
    target = np.array([1.0, 1.0, 1.0, np.exp(-1j * target_phase)])
    overlap = np.sum(target * undo * diagonal, axis=1)
    norm = np.sum(np.abs(blocks) ** 2, axis=(1, 2))
    return {
        "fidelity": (np.abs(overlap) ** 2 + norm) / 20.0,
        "leakage": 1.0 - norm / 4.0,
        "phase1": phase1,
        "phase2": phase2,
        "conditional_phase": (angles[:, 3] - angles[:, 2] - angles[:, 1] + angles[:, 0])
        % (2.0 * np.pi),
    }


def _schedule(
    pair: _Pair,
    label: str,
    frequency: float,
    rise_periods: int,
    duration: float,
    scores: dict[str, np.ndarray],
    index: int,
    target_phase: float,
) -> dict[str, Any]:
    return {
        "frequency": float(frequency),
        "strength": pair.strength,
        "duration": float(duration),
        "rise_time": float(rise_periods / frequency),
        "phases": (float(scores["phase1"][index]), float(scores["phase2"][index])),
        "conditional_phase": float(scores["conditional_phase"][index]),
        "target_phase": float(target_phase),
        "fidelity": float(scores["fidelity"][index]),
        "leakage": float(scores["leakage"][index]),
        "transition": label,
        "warnings": [],
    }


def calibrate_parametric_cphase(
    evals1, n1, evals2, n2, strength: float, target_phase: float = np.pi
) -> dict[str, Any]:
    """
    Find the modulation frequency and duration of a controlled-phase gate.

    Args:
        evals1, evals2: Level energies of each qubit (GHz), one per kept level.
        n1, n2: Charge operators in the corresponding eigenbases.
        strength: Peak coupling g (GHz) of ``H_int = g(t) n1 n2``.
        target_phase: Phase on |11>, in (0, 2 pi). Pi is a CZ.

    Returns:
        Schedule dict: "frequency" (GHz), "duration" and "rise_time" (ns),
        "strength" (GHz), "phases" (single-qubit Z phases the pulse leaves on each
        qubit, to be undone as frame updates), "conditional_phase", "fidelity"
        (average gate fidelity up to those Zs), "leakage", "transition", "warnings".

    Raises:
        ValueError: if no parametric transition exists for this pair.
    """
    target_phase = float(target_phase) % (2.0 * np.pi)
    if target_phase < 1e-9:
        raise ValueError("A controlled phase of zero needs no pulse.")

    pair = _Pair(evals1, n1, evals2, n2, strength)
    transition = pair.transition()
    centre, rabi = transition["frequency"], transition["rabi"]

    # A closed cycle detuned by delta picks up pi * (1 - delta / sqrt(rabi^2 + delta^2)),
    # so the target phase fixes |delta|. Its sign depends on whether |02> lies above or
    # below |11>, so both are tried and the propagator decides.
    cosine = float(np.clip(1.0 - target_phase / np.pi, -0.999, 0.999))
    offset = rabi * abs(cosine) / np.sqrt(1.0 - cosine**2)
    cycle = np.sqrt(1.0 - cosine**2) / rabi
    estimate = cycle / (1.0 - EDGE_FRACTION)

    def scan(frequency):
        rise_periods = max(1, int(round(EDGE_FRACTION * estimate * frequency)))
        lowest = max(1, int(0.2 * estimate * frequency))
        highest = max(lowest + 2, int(1.5 * estimate * frequency))
        plateaus = np.arange(lowest, highest)
        durations, blocks = pair.computational_blocks(frequency, rise_periods, plateaus)
        scores = _score(blocks, target_phase)
        index = int(np.argmax(scores["fidelity"]))
        return rise_periods, durations[index], scores, index

    def loss(frequency):
        _, _, scores, index = scan(frequency)
        return 1.0 - scores["fidelity"][index]

    step = rabi / 4.0
    centres = {centre + offset, centre - offset}
    grid = sorted({c + k * step for c in centres for k in (-2, -1, 0, 1, 2)})
    losses = [loss(f) for f in grid]
    best = grid[int(np.argmin(losses))]
    refined = minimize_scalar(
        loss,
        bounds=(best - step, best + step),
        method="bounded",
        options={"xatol": 2e-3 * rabi},
    )
    if refined.fun < min(losses):
        best = float(refined.x)

    rise_periods, duration, scores, index = scan(best)
    schedule = _schedule(
        pair, transition["label"], best, rise_periods, duration, scores, index, target_phase
    )
    if schedule["fidelity"] < FIDELITY_WARN:
        schedule["warnings"].append(
            f"The parametric controlled-phase gate only reaches an average gate fidelity "
            f"of {schedule['fidelity']:.4f} (leakage {schedule['leakage']:.4f}) at "
            f"g = {pair.strength} GHz. A neighbouring transition is too close to the "
            f"modulation frequency for this coupling; try a smaller coupling strength."
        )
    return schedule


def evaluate_parametric_cphase(
    evals1, n1, evals2, n2, calibrated: dict[str, Any], duration: float
) -> dict[str, Any]:
    """
    Score a calibrated gate when it is run for a different, caller-chosen duration.

    The pulse occupies the largest whole number of modulation periods that fits in
    ``duration``; the remainder (under one period) is idle.
    """
    frequency = calibrated["frequency"]
    periods = int(np.floor(duration * frequency + 1e-9))
    if periods < 3:
        raise ValueError(
            f"{duration} ns is shorter than three periods of the {frequency:.3f} GHz coupler "
            f"modulation, which is too short to shape a pulse."
        )
    rise_periods = max(1, int(round(EDGE_FRACTION * periods)))
    pair = _Pair(evals1, n1, evals2, n2, calibrated["strength"])
    durations, blocks = pair.computational_blocks(
        frequency, rise_periods, np.array([periods - 2 * rise_periods])
    )
    scores = _score(blocks, calibrated["target_phase"])
    schedule = _schedule(
        pair,
        calibrated["transition"],
        frequency,
        rise_periods,
        durations[0],
        scores,
        0,
        calibrated["target_phase"],
    )
    if schedule["fidelity"] < FIDELITY_WARN:
        schedule["warnings"].append(
            f"A {duration:g} ns coupler pulse does not complete the |11> <-> "
            f"{calibrated['transition']} cycle, so this is not the requested gate "
            f"(average gate fidelity {schedule['fidelity']:.4f}). At "
            f"g = {calibrated['strength']} GHz it needs about "
            f"{calibrated['duration']:.1f} ns."
        )
    return schedule
