"""
Demo 3: Schroedinger cats from a custom Kerr resonator.

kerr_resonator.qdl is quantized, a coherent state is placed in it, and it evolves
freely under the circuit's own energy levels. At simple fractions of the revival time
it becomes a superposition of 4, 3 and 2 distinct coherent states, then returns. Photon
loss is added through the Lindblad equation to show how fragile the cats are.
"""

import numpy as np
import pandas as pd
import qutip as qt
from _common import (BLUE, DEVICES, DIVERGING, INK2, ORANGE, AQUA, SERIES, Demo, headline,
                     heatmap_axes, plt)

from QubitWeave.core.device_engine import QuantumDevice
from QubitWeave.core.device_netlist import parse_netlist_file

demo = Demo("03_kerr_cats", "Demo 3: Schroedinger cats in a Kerr resonator")
device = QuantumDevice(parse_netlist_file(str(DEVICES / "kerr_resonator.qdl")))
N, ALPHA = 24, 2.0
energies = np.array(device.eigenvalues(N))
energies -= energies[0]
f01 = energies[1]
kerr = 2 * energies[1] - energies[2]  # GHz; E_n = f01 n - (K/2) n (n - 1)
n = np.arange(N)
revival = 1.0 / kerr  # ns

demo.check("Kerr constant vs perturbation theory EC·EJ/(EJ+EL) (MHz)", kerr * 1e3, 15.0, 0.05)
sextic = np.abs(np.diff(energies, 3)).max() * 1e3
demo.check("change of K per photon (MHz)", sextic, 0.0, 0.02)
demo.check("basis-truncation error (MHz)", device.check_convergence(N)["max_transition_shift_mhz"], 0, 0.01)

hamiltonian = qt.Qobj(np.diag(2 * np.pi * (energies - n * f01)))  # rotating at f01, rad/ns
start = qt.coherent(N, ALPHA, method="analytic").unit()
grid = np.linspace(-4.8, 4.8, 161)

moments = [("t = 0", 0.0, 1), ("T/4", 1 / 4, 4), ("T/3", 1 / 3, 3), ("T/2", 1 / 2, 2), ("T", 1.0, 1)]


def evolve(t, t1=None):
    if t == 0:
        return start * start.dag()
    c_ops = [] if t1 is None else [np.sqrt(1 / (t1 * 1e3)) * qt.destroy(N)]
    out = qt.mesolve(hamiltonian, start * start.dag(), [0, t], c_ops=c_ops,
                     options={"atol": 1e-11, "rtol": 1e-9, "nsteps": 10**6, "progress_bar": ""})
    return out.states[-1]


def ideal(fraction):
    """Pure Kerr evolution of the same state: an exact q-component cat at T/q."""
    return qt.Qobj(np.exp(1j * np.pi * fraction * n * (n - 1)).reshape(-1, 1) * start.full())


def coherent_cat(rho, legs):
    """Weight of rho in the span of `legs` coherent states evenly spaced on a circle."""
    best = 0.0
    for offset in np.linspace(0, 2 * np.pi / legs, 121):
        states = [qt.coherent(N, ALPHA * np.exp(1j * (offset + 2 * np.pi * k / legs)), method="analytic")
                  for k in range(legs)]
        basis = qt.Qobj(np.hstack([s.full() for s in states]))
        q, _ = np.linalg.qr(basis.full())
        best = max(best, float(np.real(np.trace(q.conj().T @ rho.full() @ q))))
    return best


def negativity(w):
    cell = (grid[1] - grid[0]) ** 2
    return float((np.abs(w).sum() * cell - w.sum() * cell) / 2)


rows, wigners = [], []
for label, fraction, legs in moments:
    rho = evolve(fraction * revival)
    w = qt.wigner(rho, grid, grid)
    wigners.append(w)
    fidelity = float(np.real((ideal(fraction).dag() * rho * ideal(fraction))))
    row = {"Time": label, "t (ns)": f"{fraction * revival:.2f}", "Components": legs,
           "Weight in their span": f"{coherent_cat(rho, legs):.5f}",
           "Fidelity to pure-Kerr cat": f"{fidelity:.5f}", "Wigner negativity": f"{negativity(w):.4f}"}
    for t1 in (50.0, 5.0, 1.0):
        lossy = evolve(fraction * revival, t1)
        row[f"Fidelity, T1 = {t1:g} µs"] = f"{float(np.real(ideal(fraction).dag() * lossy * ideal(fraction))):.4f}"
    rows.append(row)
    demo.check(f"{label}: fidelity of the netlist state to the ideal cat", fidelity, 1.0, 3e-3)
    demo.check(f"{label}: lies in the span of {legs} coherent state(s)", coherent_cat(rho, legs), 1.0, 3e-3)

# What infidelity there is comes from K drifting slightly with photon number, a fixed
# phase error per unit time, so it must grow as the square of the time.
infidelity = [1 - float(r["Fidelity to pure-Kerr cat"]) for r in (rows[3], rows[4])]
demo.check("residual infidelity grows as t^2 (T versus T/2)", infidelity[1] / infidelity[0], 4.0, 0.1)

# Independent check of loss: a two-legged cat decoheres at rate 2|alpha|^2 kappa.
lifetimes = np.logspace(-0.5, 2.5, 13)
t_cat = revival / 2
negative = [negativity(qt.wigner(evolve(t_cat, t1), grid, grid)) for t1 in lifetimes]
photons = []
for t1 in (1.0,):
    rho = evolve(t_cat, t1)
    photons.append(float(np.real((qt.num(N) * rho).tr())))
demo.check("mean photon number decays as exp(-t/T1), T1 = 1 µs", photons[0],
           ALPHA**2 * np.exp(-t_cat / 1000), 2e-3)

# --- figure -------------------------------------------------------------------
fig = plt.figure(figsize=(17, 9.2))
headline(fig, "Schrödinger cats grown by a custom circuit",
         f"Free evolution under the levels of kerr_resonator.qdl (f01 = {f01:.3f} GHz, K = {kerr * 1e3:.2f} MHz, "
         f"revival T = {revival:.1f} ns), starting from a coherent state of 4 photons.")
top = fig.add_gridspec(1, 5, left=0.035, right=0.93, top=0.855, bottom=0.475, wspace=0.12)
titles = ["Coherent state", "Four-legged cat", "Three-legged cat", "Schrödinger cat", "Full revival"]
for k, ((label, fraction, _), w) in enumerate(zip(moments, wigners)):
    ax = fig.add_subplot(top[k])
    image = ax.pcolormesh(grid, grid, np.pi * w, cmap=DIVERGING, vmin=-1, vmax=1, shading="gouraud")
    ax.set_aspect("equal")
    heatmap_axes(ax)
    ax.set_title(titles[k])
    ax.set_xlabel(f"{label}  ({fraction * revival:.1f} ns)")
    ax.set_xticks([-4, 0, 4])
    ax.set_yticks([-4, 0, 4] if k == 0 else [])
cax = fig.add_axes([0.945, 0.50, 0.010, 0.28])
bar = fig.colorbar(image, cax=cax)
bar.set_label("Wigner function × π", color=INK2)
bar.outline.set_visible(False)

bottom = fig.add_gridspec(1, 3, left=0.055, right=0.985, top=0.36, bottom=0.08, wspace=0.27)
ax = fig.add_subplot(bottom[0])
x = np.linspace(-6, 6, 601)
scale = np.sqrt(2)  # quadrature eigenstates of x = (a + a^dag)/sqrt(2)


def marginal(rho, angle):
    from scipy.special import eval_hermite, gammaln
    psi = np.array([np.exp(-x**2 / 2 - 0.5 * (gammaln(k + 1) + k * np.log(2))) * eval_hermite(k, x) / np.pi**0.25
                    for k in range(N)])
    rotated = np.exp(-1j * angle * n)
    m = rho.full() * np.outer(rotated, rotated.conj())
    return np.real(np.einsum("ix,ij,jx->x", psi, m, psi))


cat = evolve(t_cat)
spread = [np.sum(x**2 * marginal(cat, a)) for a in np.linspace(0, np.pi, 181)]
fringe_angle = np.linspace(0, np.pi, 181)[int(np.argmin(spread))]
lossy = evolve(t_cat, 1.0)
ax.plot(x, marginal(cat, fringe_angle), color=BLUE, label="no loss")
ax.plot(x, marginal(lossy, fringe_angle), color=ORANGE, label="T1 = 1 µs")
ax.set(title="Interference fringes of the cat", xlabel="Quadrature", ylabel="Probability density", xlim=(-4, 4))
ax.legend(loc="upper right")

ax = fig.add_subplot(bottom[1])
ax.semilogx(lifetimes, negative, "-o", color=BLUE)
ax.axhline(negativity(wigners[3]), color=INK2, lw=0.9)
ax.annotate("lossless", (lifetimes[0], negativity(wigners[3])), xytext=(0, -14), textcoords="offset points", color=INK2)
ax.set(title="Cat quality vs photon lifetime", xlabel="T1 (µs)", ylabel="Wigner negativity at T/2", ylim=(0, None))

ax = fig.add_subplot(bottom[2])
times = np.linspace(0, revival, 401)
overlap = [abs(np.sum(np.abs(start.full().ravel()) ** 2 * np.exp(-2j * np.pi * (energies - n * f01) * t))) ** 2 for t in times]
lossless_kerr = [abs(np.sum(np.abs(start.full().ravel()) ** 2 * np.exp(1j * np.pi * kerr * n * (n - 1) * t))) ** 2 for t in times]
ax.plot(times, overlap, color=BLUE, label="netlist levels")
ax.plot(times[::16], lossless_kerr[::16], "o", color=ORANGE, label="ideal Kerr oscillator")
ax.set(title="Return probability to the starting state", xlabel="Time (ns)", ylabel="Overlap", ylim=(0, 1.32))
ax.legend(loc="upper center", ncol=2)
demo.save(fig, "wigner_cats")
demo.table(pd.DataFrame(rows), "cat_fidelities", "Cat states produced by the circuit, and what photon loss does to them")
demo.finish()
