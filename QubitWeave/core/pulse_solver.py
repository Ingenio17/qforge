"""
Time evolution under scheduled pulses.

A pulse schedule is a static Hamiltonian plus terms ``c_k(t) O_k``, where each
coefficient is zero outside its pulse. Handing QuTiP those coefficients as Python
functions costs one call per term per Runge-Kutta stage, close to a million calls per
microsecond of evolution, and makes every stage pay for terms that are switched off.
:func:`evolve` gives the same answer with four changes:

* The run is split at the edges of the pulses, so each stretch contains only the terms
  that are on, and the integrator never has to notice a discontinuity.
* Within a stretch each coefficient is a quintic spline sampled 40 times per period of
  its fastest oscillation, which QuTiP evaluates in compiled code. The interpolation
  error is below 1e-9 of the pulse amplitude.
* Stretches with no pulse are propagated exactly.
* The static Hamiltonian is shifted to the middle of its spectrum, which roughly halves
  the fastest phase the integrator has to follow. The phase is put back afterwards.

Units: rad/ns and ns.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import qutip as qt

__all__ = ["PulseCoefficient", "evolve"]

# Spline samples per period of a coefficient's fastest oscillation, and the least number
# of samples across a stretch, which is what resolves a slow envelope.
SAMPLES_PER_PERIOD = 40
MIN_SAMPLES = 400

# Registers larger than this are evolved with sparse operators: charge-charge couplings
# and embedded single-qubit drives are mostly zeros.
SPARSE_DIMENSION = 8

# Largest register whose pulse-free stretches are propagated by diagonalization.
EXACT_DIMENSION = 300


class PulseCoefficient:
    """
    A pulse shape with a known window, callable like any QuTiP coefficient.

    Args:
        shape: Vectorised function of time, smooth inside the window and continuing
            smoothly a little way past its ends. It must not apply the window itself.
        start, end: The window, ns. The coefficient is zero outside it.
        frequency: Fastest oscillation in the shape, in GHz (cycles per ns).
        knots: Times inside the window where a derivative jumps.
    """

    def __init__(
        self,
        shape: Callable[[np.ndarray], np.ndarray],
        start: float,
        end: float,
        frequency: float = 0.0,
        knots: Sequence[float] = (),
    ):
        self.shape = shape
        self.start = float(start)
        self.end = float(end)
        self.frequency = abs(float(frequency))
        self.knots = tuple(float(k) for k in knots)

    def __call__(self, t: float, args: Any = None) -> float:
        return float(self.shape(t)) if self.start <= t <= self.end else 0.0

    def spline(self, start: float, end: float) -> tuple[qt.Coefficient, float]:
        """
        This coefficient on ``[start, end]``, which must lie inside the window.

        The spline continues past both ends, because the integrator steps beyond its
        target time and interpolates back. Returns it with how far it reaches, which is
        the longest step that stays on it.
        """
        length = end - start
        rate = max(self.frequency, 1.0 / length)
        margin = min(1.0 / rate, length)
        count = max(MIN_SAMPLES, int(np.ceil((length + 2 * margin) * rate * SAMPLES_PER_PERIOD)))
        grid = np.linspace(start - margin, end + margin, count)
        return (
            qt.coefficient(np.asarray(self.shape(grid), dtype=float), tlist=grid, order=5),
            margin,
        )


def _breakpoints(terms: Sequence[PulseCoefficient], start: float, end: float) -> np.ndarray:
    """Every time at which some term switches or has a kink, strictly increasing."""
    edges = [start, end]
    for term in terms:
        edges += [term.start, term.end, *term.knots]
    inside = np.unique([e for e in edges if start <= e <= end])
    # Edges closer than rounding are the same edge.
    keep = np.concatenate([[True], np.diff(inside) > 1e-9 * max(end - start, 1.0)])
    points = inside[keep]
    points[-1] = end
    return points


def _idle_propagator(static: np.ndarray):
    """Exact evolution under a constant Hamiltonian, as a function of duration."""
    diagonal = np.real(np.diag(static))
    if np.allclose(static, np.diag(diagonal), atol=1e-14):
        return lambda vector, dt: np.exp(-1j * diagonal * dt) * vector
    energies, modes = np.linalg.eigh(static)
    return lambda vector, dt: modes @ (np.exp(-1j * energies * dt) * (modes.conj().T @ vector))


def evolve(
    hamiltonian: list,
    initial: qt.Qobj,
    times: np.ndarray,
    c_ops: Sequence[qt.Qobj] = (),
    args: dict | None = None,
    options: dict | None = None,
) -> list[qt.Qobj]:
    """
    Evolve a state and return it at every requested time.

    Args:
        hamiltonian: ``[H0, [O1, c1], ...]``. Coefficients that are not
            :class:`PulseCoefficient` are passed to QuTiP unchanged, in one piece.
        initial: Ket or density matrix.
        times: Increasing output times, the first being that of ``initial``.
        c_ops: Lindblad operators. With any, states come back as density matrices.
        args, options: As for QuTiP's solvers.
    """
    times = np.asarray(times, dtype=float)
    options = {"store_states": True, "progress_bar": "", **(options or {})}
    static, terms = hamiltonian[0], hamiltonian[1:]
    closed = initial.type == "ket" and not c_ops

    known = all(isinstance(coefficient, PulseCoefficient) for _, coefficient in terms)
    if not known or len(times) < 2 or times[-1] <= times[0]:
        return qt.mesolve(
            hamiltonian, initial, times, c_ops=list(c_ops), args=args, options=options
        ).states

    dimension = static.shape[0]
    shift = 0.0
    if closed:
        diagonal = np.real(static.diag())
        shift = float(diagonal.max() + diagonal.min()) / 2.0
        static = static - shift * qt.qeye(static.dims[0])
    if dimension > SPARSE_DIMENSION:
        static = static.to("csr")
        terms = [[operator.to("csr"), coefficient] for operator, coefficient in terms]

    idle = None
    state = initial if closed or initial.type != "ket" else qt.ket2dm(initial)
    states = [state]
    points = _breakpoints([c for _, c in terms], times[0], times[-1])
    done = 1  # output times already filled

    for start, end in zip(points[:-1], points[1:]):
        middle = 0.5 * (start + end)
        active = [(o, c) for o, c in terms if c.start <= middle <= c.end]
        last = int(np.searchsorted(times, end, side="right"))
        wanted = times[done:last]
        targets = wanted if len(wanted) and wanted[-1] == end else np.append(wanted, end)

        if not active and closed and dimension <= EXACT_DIMENSION:
            if idle is None:
                idle = _idle_propagator(static.full())
            vector = state.full().ravel()
            found = []
            for t in targets:
                ket = qt.Qobj(idle(vector, t - start).reshape(-1, 1), copy=False)
                ket.dims = state.dims
                found.append(ket)
        else:
            splines = [c.spline(start, end) for _, c in active]
            pieces = [static] + [[o, s] for (o, _), (s, _) in zip(active, splines)]
            local = dict(options)
            if splines:
                local["max_step"] = min(margin for _, margin in splines)
            grid = np.concatenate([[start], targets])
            system = qt.QobjEvo(pieces) if active else static
            if closed:
                found = qt.sesolve(system, state, grid, options=local).states[1:]
            else:
                found = qt.mesolve(system, state, grid, c_ops=list(c_ops), options=local).states[1:]

        states.extend(found[: len(wanted)])
        state = found[-1]
        done = last

    if shift:
        states = [
            s if i == 0 else np.exp(-1j * shift * (times[i] - times[0])) * s
            for i, s in enumerate(states)
        ]
    return states
