"""
Demo 10: a distance-3 surface code, next to Steane, Shor and repetition.

Every possible single-qubit Pauli error is injected into the state-vector engine, its
syndrome is measured and the correction applied. Exact logical error rates come from
enumerating all 4^9 Pauli patterns; random errors run through the full engine, with real
syndrome extraction and collapse, land on the same curve.
"""

import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from _common import (AQUA, BLUE, INK, INK2, MUTED, ORANGE, RED, SURFACE, VIOLET, Demo, headline, heatmap_axes,
                     plt, quiet)
from matplotlib.colors import ListedColormap
from matplotlib.patches import Polygon

from QubitWeave.core.error_correction_engine import ErrorCorrectionEngine
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.qec_benchmark import logical_error_polynomial, logical_error_rate, pseudo_threshold
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.stabilizer_codes import REPETITION_3, SHOR_9, STEANE_7, SURFACE_9

NAME = "sc_transmon"
SHOTS, RATES = 4000, (0.02, 0.05, 0.10, 0.18)


def engine():
    q_eng = QubitEngine()
    with quiet():
        q_eng.create_qubit("transmon", NAME, {"EJ": 15.0, "EC": 0.3, "truncated_dim": 3})
        return ErrorCorrectionEngine(q_eng, GateEngine())


def rounds(code, patterns):
    with quiet():
        return engine().simulate_memory_rounds(NAME, code, patterns)


def shots(job):
    """Random depolarizing errors through the engine, in this worker's own directory."""
    seed, rate, count = job
    folder = Path(f"worker_{seed}")
    folder.mkdir(exist_ok=True)
    os.chdir(folder)
    rng = np.random.default_rng(seed)
    np.random.seed(seed)
    patterns = [[(q, rng.choice(list("XYZ"))) for q in range(9) if rng.random() < rate] for _ in range(count)]
    out = rounds(SURFACE_9, patterns)
    os.chdir("..")
    return rate, sum(r["fidelity"] < 0.9 for r in out), count


def draw_lattice(ax, error, syndrome):
    """The 3x3 lattice, plaquettes filled if their stabilizer fired."""
    xy = {q: (q % 3, 2 - q // 3) for q in range(9)}
    bumps = {(0, 3): (-0.55, 1.5), (5, 8): (2.55, 0.5), (1, 2): (1.5, 2.55), (6, 7): (0.5, -0.55)}
    for gen, bit in zip(SURFACE_9.generators, syndrome):
        points = [xy[q] for q in gen.data_qubits]
        if len(points) == 2:
            points.append(bumps[gen.data_qubits])
        centre = np.mean(points, axis=0)
        points.sort(key=lambda p: np.arctan2(p[1] - centre[1], p[0] - centre[0]))
        colour = BLUE if gen.basis == "Z" else ORANGE
        ax.add_patch(Polygon(points, closed=True, facecolor=colour, alpha=0.85 if bit else 0.14, lw=0))
        ax.text(*centre, gen.basis, ha="center", va="center", fontsize=11, color=SURFACE if bit else INK2,
                fontweight="bold" if bit else "normal")
    for q, (x, y) in xy.items():
        hit = q == error[0]
        ax.plot(x, y, "o", ms=23, color=RED if hit else INK, mec=SURFACE, mew=2)
        ax.text(x, y, error[1] if hit else str(q), color=SURFACE, ha="center", va="center", fontsize=10, fontweight="bold")
    ax.set_aspect("equal")
    ax.set_xlim(-0.65, 2.65)
    ax.set_ylim(-0.65, 2.65)
    heatmap_axes(ax)
    ax.set_xticks([])
    ax.set_yticks([])


def main():
    demo = Demo("10_surface_code", "Demo 10: distance-3 surface code")
    table, singles = [], {}
    for code in (STEANE_7, SHOR_9, SURFACE_9):
        patterns = [[(q, p)] for p in "XZY" for q in range(code.num_data)]
        singles[code.name] = list(zip(patterns, rounds(code, patterns)))
        corrected = sum(r["fidelity"] > 0.999 for _, r in singles[code.name])
        demo.check(f"{code.name}: single-qubit errors corrected", corrected, 3 * code.num_data, 0)
    none = rounds(SURFACE_9, [[]])[0]
    demo.check("surface code: no error, no syndrome", sum(none["syndrome"]), 0, 0)

    codes = [("Repetition (3)", REPETITION_3, MUTED), ("Steane (7)", STEANE_7, AQUA), ("Shor (9)", SHOR_9, VIOLET),
             ("Surface d=3 (9)", SURFACE_9, BLUE)]
    p = np.logspace(-3, np.log10(0.35), 200)
    poly = {label: logical_error_polynomial(code) for label, code, _ in codes}
    for label, code, _ in codes:
        polynomial = poly[label]
        threshold = pseudo_threshold(polynomial)
        corrected = (f"{sum(r['fidelity'] > 0.999 for _, r in singles[code.name])} / {3 * code.num_data}"
                     if code.name in singles else "bit flips only")
        table.append({
            "Code": label, "Data + ancilla": f"{code.num_data} + {code.num_ancilla}", "Single errors corrected (engine)": corrected,
            "Weight-2 failures": f"{polynomial['failures'][2]} / {polynomial['patterns'][2]}",
            "P_L at p = 0.1%": f"{logical_error_rate(polynomial, 1e-3)[0]:.2e}",
            "P_L at p = 1%": f"{logical_error_rate(polynomial, 1e-2)[0]:.2e}",
            "Break-even p": "never" if threshold is None else f"{threshold * 100:.2f} %",
        })
    analytic = logical_error_polynomial(REPETITION_3, "bit_flip")
    demo.check("repetition code vs 3p² − 2p³ at p = 0.07", logical_error_rate(analytic, 0.07)[0], 3 * 0.07**2 - 2 * 0.07**3, 1e-12)
    demo.check("surface code has distance 3 (weight-1 failures)", poly["Surface d=3 (9)"]["failures"][1], 0, 0)
    slope = np.diff(np.log(logical_error_rate(poly["Surface d=3 (9)"], [1e-4, 1.1e-4])))[0] / np.log(1.1)
    demo.check("logical error falls as p²", slope, 2.0, 0.01)

    workers = 8
    jobs = [(100 * i + w, rate, SHOTS // workers) for i, rate in enumerate(RATES) for w in range(workers)]
    with Pool(workers) as pool:
        outcome = pool.map(shots, jobs, chunksize=1)
    measured = []
    for rate in RATES:
        failures = sum(f for r, f, _ in outcome if r == rate)
        total = sum(n for r, _, n in outcome if r == rate)
        value = failures / total
        sigma = np.sqrt(max(value * (1 - value), 1 / total) / total)
        exact = logical_error_rate(poly["Surface d=3 (9)"], rate)[0]
        measured.append((rate, value, sigma, exact, total))
        demo.check(f"engine Monte Carlo at p = {rate:.0%} vs exact (σ away)", (value - exact) / sigma, 0.0, 3.0)

    # --- figure -------------------------------------------------------------------
    fig = plt.figure(figsize=(17, 10.4))
    headline(fig, "A distance-3 surface code that corrects all 27 single-qubit errors",
             "Every stabilizer is extracted with ancillas and measured on the state vector. Logical error rates are exact "
             "(4⁹ = 262,144 Pauli patterns), with the engine's own Monte Carlo on top.")
    grid = fig.add_gridspec(2, 6, left=0.05, right=0.985, top=0.865, bottom=0.085, hspace=0.24, wspace=0.75, height_ratios=[1.1, 1.2])
    lookup = {tuple(pattern[0]): r["syndrome"] for pattern, r in singles[SURFACE_9.name]}
    for k, error in enumerate(((4, "X"), (2, "Z"), (7, "Y"))):
        ax = fig.add_subplot(grid[0, 2 * k:2 * k + 2])
        draw_lattice(ax, error, lookup[error])
        kind = {"X": "bit flip: Z checks fire", "Z": "phase flip: X checks fire", "Y": "both: X and Z checks fire"}[error[1]]
        ax.set_title(f"{error[1]} on qubit {error[0]} ({kind})")

    ax = fig.add_subplot(grid[1, :3])
    matrix = np.array([r["syndrome"] for _, r in singles[SURFACE_9.name]]).T.astype(float)
    shown = matrix.copy()
    shown[4:] *= 2  # separate colours for the two check types
    ax.imshow(shown, cmap=ListedColormap(["#f0efec", BLUE, ORANGE]), vmin=0, vmax=2, aspect="auto")
    for edge in np.arange(-0.5, 27):
        ax.axvline(edge, color=SURFACE, lw=2.5 if (edge + 0.5) % 9 else 7)
    for edge in np.arange(-0.5, 8):
        ax.axhline(edge, color=SURFACE, lw=2)
    heatmap_axes(ax)
    ax.set_xlim(-0.5, 26.5)
    ax.set_ylim(7.5, -0.5)
    ax.set_xticks(range(27), [str(q) for q in list(range(9)) * 3], fontsize=9)
    ax.set_yticks(range(8), [f"{g.basis} " + "".join(map(str, g.data_qubits)) for g in SURFACE_9.generators], fontsize=9)
    for k, name in enumerate(("X errors", "Z errors", "Y errors")):
        ax.text(4 + 9 * k, 8.75, name, ha="center", color=INK2)
    ax.set_title("Measured syndrome of every single-qubit error (blue: Z check fired, orange: X check)")

    ax = fig.add_subplot(grid[1, 3:])
    ax.loglog(p, p, color=INK2, lw=1.2, label="bare qubit")
    for label, code, color in codes:
        ax.loglog(p, logical_error_rate(poly[label], p), color=color, label=label, zorder=4 if code is SURFACE_9 else 2,
                  ls="-")
    ax.errorbar([m[0] for m in measured], [m[1] for m in measured], yerr=[m[2] for m in measured], fmt="o", color=ORANGE,
                ms=9, lw=1.4, zorder=6, label=f"surface code, engine ({SHOTS:,} shots)")
    cross = pseudo_threshold(poly["Surface d=3 (9)"])
    ax.axvline(cross, color=MUTED, lw=0.9)
    ax.text(0.0035, 2.6e-4, "Steane, Shor and surface\nnearly coincide (see table)", color=INK2, fontsize=9.5, ha="right")
    ax.text(cross * 0.95, 2e-5, f"break-even\n{cross * 100:.1f} %", ha="right", color=INK2)
    ax.set(title="Logical vs physical error rate (depolarizing)", xlabel="Physical error rate p", ylabel="Logical error rate",
           ylim=(1e-5, 1))
    ax.legend(loc="upper left", fontsize=9)
    demo.save(fig, "surface_code")
    demo.table(pd.DataFrame(table), "code_comparison", "Codes compared: exact logical error rates, depolarizing noise, perfect measurement")
    demo.table(pd.DataFrame([{"p": f"{r:.2f}", "Shots": n, "Engine P_L": f"{v:.4f} ± {s:.4f}", "Exact P_L": f"{e:.4f}",
                              "Deviation (σ)": f"{(v - e) / s:+.2f}"} for r, v, s, e, n in measured]),
               "monte_carlo", "State-vector engine vs exact enumeration, surface code")
    demo.finish()


if __name__ == "__main__":
    main()
    sys.exit(0)
