"""
Demo 7: a transmon chain as an analog quantum simulator.

Seven identical transmons, three levels each (2187 states), coupled capacitively to
their neighbours. One excitation placed in the middle spreads as a light cone; giving
the transmons random junction energies freezes it in place, Anderson localization. The
engine evolves the full charge-charge Hamiltonian with no rotating-wave approximation;
the reference is the one-particle tight-binding model with the hopping computed from
the transmon's own matrix element.
"""

import numpy as np
import pandas as pd
import scqubits as scq
from _common import (AQUA, BLUE, INK, INK2, ORANGE, SEQUENTIAL, SURFACE, Demo, colorbar, headline,
                     heatmap_axes, plt, quiet)

from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.qubit_engine import QubitEngine

demo = Demo("07_light_cone", "Demo 7: light cone and Anderson localization on 7 transmons")
SITES, LEVELS = 7, 3
EJ, EC, G = 15.0, 0.3, 0.006  # GHz
engine = QubitEngine()
with quiet():
    gates = GateEngine()
NAMES = [f"lc_{i}" for i in range(SITES)]
COUPLINGS = [{"q1": i, "q2": i + 1, "type": "capacitive", "strength": G} for i in range(SITES - 1)]


def site(ej):
    q = scq.Transmon(EJ=ej, EC=EC, ng=0, ncut=30, truncated_dim=LEVELS)
    return q.eigenvals(2)[1] - q.eigenvals(2)[0], abs(q.matrixelement_table("n_operator", evals_count=2)[0, 1])


def simulate(ejs, duration, steps, start="0001000"):
    with quiet():
        for name, ej in zip(NAMES, ejs):
            engine.create_qubit("transmon", name, {"EJ": float(ej), "EC": EC, "ng": 0.0, "ncut": 30, "truncated_dim": LEVELS})
        result = gates.simulate_n_qubit_dynamics(NAMES, "Idle", duration, COUPLINGS, [], start, steps=steps)
    pops = result["populations"]
    density = np.zeros((steps, SITES))
    leak = np.zeros(steps)
    for label, p in pops.items():
        occupation = np.array([int(c) for c in label])
        density += p[:, None] * occupation[None, :]
        if "2" in label:
            leak += p
    return result["times"], density, leak


def tight_binding(ejs, times):
    f, n = np.array([site(e) for e in ejs]).T
    h = np.diag(f).astype(float)
    for i in range(SITES - 1):
        h[i, i + 1] = h[i + 1, i] = G * n[i] * n[i + 1]
    w, v = np.linalg.eigh(h)
    start = np.zeros(SITES)
    start[SITES // 2] = 1
    amp = (v * (v.T @ start)) @ np.exp(-2j * np.pi * np.outer(w, times))
    return np.abs(amp.T) ** 2


hop = G * site(EJ)[1] ** 2
DURATION, STEPS = 2.0 / hop / 2, 121
clean = np.full(SITES, EJ)
times, density, leak = simulate(clean, DURATION, STEPS)
reference = tight_binding(clean, times)

rng = np.random.default_rng(3)
spreads = (0.0, 0.15, 0.45, 1.5)  # GHz, uniform half-width in EJ
noise = rng.uniform(-1, 1, SITES)
runs = []
for spread in spreads:
    ejs = EJ + spread * noise
    t, d, l = (times, density, leak) if spread == 0 else simulate(ejs, DURATION, STEPS)
    runs.append((spread, ejs, d, l, tight_binding(ejs, t)))

rows = []
distance = np.abs(np.arange(SITES) - SITES // 2)
for spread, ejs, d, l, ref in runs:
    f = np.array([site(e)[0] for e in ejs])
    rows.append({
        "EJ disorder (GHz)": f"±{spread:g}", "Frequency spread (MHz)": f"{np.ptp(f) * 1e3:.1f}",
        "Spread / hopping": f"{np.ptp(f) / hop:.1f}", "Mean P(start site)": f"{d[:, SITES // 2].mean():.3f}",
        "Max mean distance (sites)": f"{(d @ distance).max():.3f}", "Max error vs theory": f"{np.abs(d - ref).max():.4f}",
        "Max leakage to |2⟩": f"{l.max():.1e}", "Excitation number drift": f"{np.abs(d.sum(axis=1) - 1).max():.1e}",
    })
    demo.check(f"disorder ±{spread:g} GHz: engine vs tight binding, worst site and time", np.abs(d - ref).max(), 0.0, 0.02)
demo.check("clean chain: excitation number conserved", np.abs(density.sum(axis=1) - 1).max(), 0.0, 0.01)

# Ballistic front: on an infinite chain P_n(t) = J_n(2 J t)^2, so the front moves at 2J sites per unit time.
from scipy.special import jv

early = times < 0.28 / hop
bessel = jv(1, 4 * np.pi * hop * times) ** 2
demo.check("first neighbour follows the Bessel-function light cone", np.abs(density[early, SITES // 2 + 1] - bessel[early]).max(), 0.0, 0.02)
demo.check("localization: start-site population, strongest disorder", float(runs[-1][2][:, SITES // 2].mean() > 0.9), 1.0, 0)

# --- figure -------------------------------------------------------------------
fig = plt.figure(figsize=(17, 9.6))
headline(fig, "A photon light cone, and how disorder stops it",
         f"Seven capacitively coupled transmons, {LEVELS**SITES:,} states, full charge-charge Hamiltonian, no RWA. "
         f"Hopping {hop * 1e3:.2f} MHz. One excitation starts on the middle qubit.")
grid = fig.add_gridspec(2, 4, left=0.05, right=0.93, top=0.845, bottom=0.08, hspace=0.42, wspace=0.18, height_ratios=[1.25, 1])
for k, (spread, ejs, d, l, ref) in enumerate(runs):
    ax = fig.add_subplot(grid[0, k])
    image = ax.imshow(d, aspect="auto", origin="lower", cmap=SEQUENTIAL, vmin=0, vmax=1,
                      extent=[-0.5, SITES - 0.5, times[0], times[-1]], interpolation="nearest")
    heatmap_axes(ax)
    ax.set_title("Identical qubits" if spread == 0 else f"EJ disorder ±{spread:g} GHz")
    ax.set_xticks(range(SITES), [f"Q{i + 1}" for i in range(SITES)])
    ax.set_xlabel("Qubit")
    if k == 0:
        front = np.linspace(0, 3, 10)
        for sign in (-1, 1):
            ax.plot(3 + sign * front, front / (4 * np.pi * hop), color=ORANGE, lw=1.4)
        ax.text(3, times[-1] * 0.93, "orange: group velocity 2J", color=INK, fontsize=9, ha="center",
                bbox={"fc": SURFACE, "ec": "none", "alpha": 0.85, "pad": 1.5})
        ax.set_ylabel("Time (ns)")
        ax.set_ylim(times[0], times[-1])
        ax.set_xlim(-0.5, SITES - 0.5)
cax = fig.add_axes([0.943, 0.50, 0.010, 0.32])
bar = fig.colorbar(image, cax=cax)
bar.set_label("Excitation probability", color=INK2)
bar.outline.set_visible(False)

ax = fig.add_subplot(grid[1, :2])
for i, color in ((3, BLUE), (4, ORANGE), (6, AQUA)):
    ax.plot(times, reference[:, i], color=color, label=f"Q{i + 1}, tight binding")
    ax.plot(times[::4], density[::4, i], "o", color=color, ms=6)
ax.plot([], [], "o", color=INK2, label="dots: full simulation")
ax.set(title="Identical qubits: full simulation vs theory, no fitting", xlabel="Time (ns)", ylabel="Population", ylim=(0, 1.22))
ax.legend(loc="upper right", ncol=4, fontsize=9)

ax = fig.add_subplot(grid[1, 2:])
for (spread, ejs, d, l, ref), color in zip(runs, ("#86b6ef", "#3987e5", "#1c5cab", "#0d366b")):
    ax.plot(times, d @ distance, color=color, label="identical" if spread == 0 else f"±{spread:g} GHz")
ax.set(title="How far the excitation gets", xlabel="Time (ns)", ylabel="Mean distance (sites)", ylim=(0, 3.1))
ax.legend(loc="upper right", ncol=4, fontsize=9)
demo.save(fig, "light_cone_and_localization")
demo.table(pd.DataFrame(rows), "localization", "Transport vs disorder on a 7-transmon chain")
demo.finish()
