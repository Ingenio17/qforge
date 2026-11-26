"""
Demo 1: a qubit designed from a netlist whose anharmonicity changes sign with flux.

examples/device_files/csfq.qdl describes three junctions and a capacitor. The device
engine quantizes it, sweeps flux and junction ratio, and finds the operating points
where the ladder is exactly harmonic. scqubits' hand-written FluxQubit class, which
shares no code with the netlist path, is the independent reference.
"""

import numpy as np
import pandas as pd
import scqubits as scq
from _common import (AQUA, BLUE, DEVICES, DIVERGING, INK, INK2, ORANGE, SURFACE, Demo, colorbar,
                     headline, heatmap_axes, plt)
from scipy.optimize import brentq

from QubitWeave.core.device_engine import QuantumDevice
from QubitWeave.core.device_netlist import parse_netlist

demo = Demo("01_sign_flipping_qubit", "Demo 1: custom netlist, anharmonicity that changes sign")
SOURCE = (DEVICES / "csfq.qdl").read_text(encoding="utf-8")
LEVELS = 4


def build(alpha=0.43):
    return QuantumDevice(parse_netlist(SOURCE.replace("ALPHA = 0.43", f"ALPHA = {alpha}"), name="csfq"))


def ladder(device, fluxes):
    e = np.array(device.sweep("flux1", fluxes, levels=LEVELS)["transitions_ghz"])
    return e, e[:, 2] - 2 * e[:, 1]


device = build()
flux = np.linspace(0.0, 1.0, 161)
levels, alpha_ghz = ladder(device, flux)


def anharmonicity(phi):
    return ladder(device, [phi])[1][0]


crossing = brentq(anharmonicity, 0.46, 0.5, xtol=1e-5)
deepest_grid = np.linspace(0.40, crossing, 60)
deepest = deepest_grid[np.argmin(ladder(device, deepest_grid)[1])]

ratios = np.linspace(0.30, 0.48, 25)
map_flux = np.linspace(0.42, 0.58, 61)
grid = np.array([ladder(build(round(a, 4)), map_flux)[1] for a in ratios]) * 1e3

# --- independent reference: scqubits' dedicated flux-qubit class ---------------
reference = scq.FluxQubit(
    EJ1=80, EJ2=80, EJ3=80 * 0.43, ECJ1=4, ECJ2=4, ECJ3=1 / (1 / (4 / 0.43) + 1 / 0.30),
    ECg1=1e5, ECg2=1e5, ng1=0, ng2=0, flux=0.5, ncut=14,
)
rows = []
for label, phi in (("Zero flux (transmon-like)", 0.0), ("Most negative", deepest),
                   ("Harmonic point", crossing), ("Half flux (sweet spot)", 0.5)):
    ours, a = ladder(device, [phi])
    reference.flux = phi
    theirs = reference.eigenvals(LEVELS)
    theirs = theirs - theirs[0]
    worst = 1e3 * np.abs(ours[0] - theirs).max()
    rows.append({
        "Operating point": label, "Flux (Φ0)": f"{phi:.4f}", "f01 (GHz)": f"{ours[0, 1]:.4f}",
        "f12 (GHz)": f"{ours[0, 2] - ours[0, 1]:.4f}", "Anharmonicity (MHz)": f"{a[0] * 1e3:+.2f}",
        "FluxQubit class f01 (GHz)": f"{theirs[1]:.4f}", "Max level error (MHz)": f"{worst:.3f}",
    })
    demo.check(f"levels vs scqubits.FluxQubit at flux {phi:.3f} (MHz)", worst, 0.0, 1.0)
demo.check("anharmonicity at the harmonic point (MHz)", anharmonicity(crossing) * 1e3, 0.0, 0.05)
demo.check("spectrum is symmetric about half flux (MHz)",
           1e3 * np.abs(levels - levels[::-1]).max(), 0.0, 0.01)
convergence = device.check_convergence(LEVELS)
demo.check("basis-truncation error (MHz)", convergence["max_transition_shift_mhz"], 0.0, 0.5)

# --- figure -------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(17, 6), gridspec_kw={"width_ratios": [1, 1, 1.15]})
fig.subplots_adjust(left=0.05, right=0.94, bottom=0.12, top=0.78, wspace=0.27)
headline(fig, "One netlist, two kinds of qubit",
         "Capacitively shunted flux qubit quantized from csfq.qdl. Flux turns a negative-anharmonicity "
         "qubit into a strongly positive one, through a point where f01 = f12.")

ax = axes[0]
for k, color in zip((1, 2, 3), (BLUE, ORANGE, AQUA)):
    ax.plot(flux, levels[:, k], color=color)
    ax.annotate(f"0→{k}", (flux[-1], levels[-1, k]), xytext=(-4, 6), textcoords="offset points",
                ha="right", color=INK2, fontsize=10)
sample = np.linspace(0, 1, 9)
independent = []
for phi in sample:
    reference.flux = phi
    independent.append(reference.eigenvals(LEVELS))
independent = np.array(independent) - np.array(independent)[:, :1]
for k, color in zip((1, 2, 3), (BLUE, ORANGE, AQUA)):
    ax.plot(sample, independent[:, k], "o", color=color)
ax.set(title="Transition spectrum", xlabel="External flux (Φ$_0$)", ylabel="Frequency (GHz)", ylim=(0, 47))
ax.plot([], [], color=INK2, label="QubitWeave netlist")
ax.plot([], [], "o", color=INK2, label="scqubits.FluxQubit")
ax.legend(loc="upper center", ncol=2)

ax = axes[1]
ax.axhline(0, color=INK2, lw=0.9)
ax.fill_between(flux, 0, alpha_ghz * 1e3, where=alpha_ghz >= 0, color=ORANGE, alpha=0.12, lw=0)
ax.fill_between(flux, 0, alpha_ghz * 1e3, where=alpha_ghz <= 0, color=BLUE, alpha=0.12, lw=0)
ax.plot(flux, alpha_ghz * 1e3, color=BLUE)
for phi in (crossing, 1 - crossing):
    ax.plot(phi, 0, "o", color=INK, ms=8)
ax.annotate(f"harmonic at Φ = {crossing:.3f}", (crossing, 0), xytext=(-14, 34),
            textcoords="offset points", ha="right", color=INK2,
            arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.8})
peak = alpha_ghz.max() * 1e3
ax.annotate(f"+{peak:.0f} MHz", (0.5, peak), xytext=(8, -2), textcoords="offset points", color=INK2)
ax.set(title="Anharmonicity", xlabel="External flux (Φ$_0$)", ylabel="f12 − f01 (MHz)")

ax = axes[2]
limit = np.abs(grid).max()
image = ax.pcolormesh(map_flux, ratios, grid, cmap=DIVERGING, vmin=-limit, vmax=limit, shading="gouraud")
contour = ax.contour(map_flux, ratios, grid, levels=[0], colors=INK, linewidths=1.6)
ax.clabel(contour, fmt={0: "harmonic"}, fontsize=9)
ax.axhline(0.43, color=SURFACE, lw=1.2)
ax.text(0.423, 0.433, "panels 1–2", color=INK, fontsize=9)
heatmap_axes(ax)
ax.set(title="Design map", xlabel="External flux (Φ$_0$)", ylabel="Small-junction ratio α")
colorbar(fig, image, ax, "Anharmonicity (MHz)")
demo.save(fig, "anharmonicity_sign_flip")
demo.table(pd.DataFrame(rows), "operating_points", "CSFQ operating points, netlist vs independent FluxQubit class")
demo.finish()
