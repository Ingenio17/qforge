"""
Demo 2: circuit QED straight from a netlist.

tunable_transmon_readout.qdl has two modes. Sweeping flux through the SQUID moves the
transmon through the resonator and the two transitions repel: the vacuum Rabi
splitting. Far from resonance the same spectrum gives the dispersive shift used for
readout. The reference is the textbook model, with every parameter computed from the
capacitance matrix and nothing fitted.
"""

import numpy as np
import pandas as pd
import scqubits as scq
from _common import (AQUA, BLUE, DEVICES, INK, INK2, ORANGE, SEQUENTIAL, SURFACE, Demo, colorbar, headline,
                     heatmap_axes, plt)
from scipy.optimize import minimize_scalar

from QubitWeave.core.device_engine import QuantumDevice
from QubitWeave.core.device_netlist import parse_netlist_file

demo = Demo("02_vacuum_rabi", "Demo 2: vacuum Rabi splitting and readout from a netlist")
device = QuantumDevice(parse_netlist_file(str(DEVICES / "tunable_transmon_readout.qdl")))

flux = np.linspace(0.0, 0.40, 401)
table = np.array(device.sweep("flux1", flux, levels=6)["transitions_ghz"])

# --- what a spectrometer sees: transmission through the resonator --------------
probe = np.linspace(6.70, 7.45, 420)
kappa = 0.012  # GHz, resonator linewidth used to draw the spectrum
spectrum = np.zeros((len(probe), len(flux)))
for i, phi in enumerate(flux):
    device.set_parameter("flux1", phi)
    operators = device.effective_operators(levels=4)
    q2 = operators["charge_operators"]["Q2"].full()
    for k in range(1, 4):
        weight = abs(q2[0, k]) ** 2
        spectrum[:, i] += weight / (1 + (2 * (probe - operators["energies_ghz"][k]) / kappa) ** 2)
device.set_parameter("flux1", 0.0)
spectrum = np.sqrt(spectrum / spectrum.max())


def gap(phi):
    e = device.sweep("flux1", [float(phi)], levels=3)["transitions_ghz"][0]
    return e[2] - e[1]


found = minimize_scalar(gap, bounds=(0.05, 0.3), method="bounded", options={"xatol": 1e-6})
g_measured = found.fun / 2

# --- textbook model from the capacitance matrix, no fitting --------------------
E2_OVER_2H = 19.3702  # e^2 / (2 h * 1 fF), GHz
PHI0_OVER = 163.4615  # EL (GHz) = 163.4615 / L(nH)
EJ_PER_NA = 0.4966787
c = np.array([[74.0 + 6.0, -6.0], [-6.0, 250.0 + 6.0]])  # fF: shunt + 2 Cj + Cc, C2 + Cc
inverse = np.linalg.inv(c)
ec_q, ec_r = E2_OVER_2H * inverse[0, 0], E2_OVER_2H * inverse[1, 1]
el_r = PHI0_OVER / 2.0
f_res = np.sqrt(8 * ec_r * el_r)
n_zpf_r = (el_r / (32 * ec_r)) ** 0.25
coupling = 8 * E2_OVER_2H * inverse[0, 1]  # GHz per Cooper-pair product, n_q n_r


def bare_transmon(phi, levels=4):
    ic = np.array([40.0, 28.0])
    ej = EJ_PER_NA * abs(ic[0] + ic[1] * np.exp(2j * np.pi * phi))
    qubit = scq.Transmon(EJ=ej, EC=ec_q, ng=0, ncut=30)
    return qubit.eigenvals(levels), np.abs(qubit.matrixelement_table("n_operator", evals_count=levels))


def model(phi, photons=8, levels=6):
    """Transmon times oscillator with the computed coupling, diagonalized exactly."""
    e, n = bare_transmon(phi, levels)
    a = np.diag(np.sqrt(np.arange(1, photons)), 1)
    h = np.kron(np.diag(e - e[0]), np.eye(photons))
    h = h + np.kron(np.eye(levels), f_res * np.diag(np.arange(photons)))
    h = h.astype(complex) + coupling * n_zpf_r * np.kron(n, 1j * (a.T - a))
    values = np.linalg.eigvalsh(h)
    return values - values[0]


reference = np.array([model(p)[1:4] for p in flux])
theory = minimize_scalar(lambda p: model(p)[2] - model(p)[1], bounds=(0.05, 0.3), method="bounded",
                         options={"xatol": 1e-6})
g_theory = theory.fun / 2
n01 = bare_transmon(theory.x)[1][0, 1]
g_formula = abs(coupling) * n_zpf_r * n01


# --- dispersive shift: how far the resonator moves when the qubit is excited ---
def dispersive(phi, e):
    qubit = bare_transmon(phi)[0]
    f_q = qubit[1] - qubit[0]
    resonator = 1 + int(np.argmin(np.abs(e[1:] - f_res)))
    excited = 1 + int(np.argmin([abs(v - f_q) if k + 1 != resonator else 9 for k, v in enumerate(e[1:])]))
    both = 1 + int(np.argmin(np.abs(e[1:] - (e[resonator] + e[excited]))))
    return e[both] - e[excited] - e[resonator]


rows = []
for phi in (0.26, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33, 0.34):
    two_chi = dispersive(phi, np.array(device.sweep("flux1", [phi], levels=6)["transitions_ghz"][0]))
    exact = dispersive(phi, model(phi)[:6])
    levels, n = bare_transmon(phi)
    f01, f12 = levels[1] - levels[0], levels[2] - levels[1]
    g01, g12 = abs(coupling) * n_zpf_r * n[0, 1], abs(coupling) * n_zpf_r * n[1, 2]
    # Koch et al. 2007 with the counter-rotating (Bloch-Siegert) terms kept.
    chi01 = g01**2 * (1 / (f01 - f_res) + 1 / (f01 + f_res))
    chi12 = g12**2 * (1 / (f12 - f_res) + 1 / (f12 + f_res))
    formula = 2 * chi01 - chi12
    rows.append({
        "Flux (Φ0)": f"{phi:.2f}", "Qubit f01 (GHz)": f"{f01:.4f}", "Detuning (GHz)": f"{f01 - f_res:+.3f}",
        "g (MHz)": f"{g01 * 1e3:.2f}", "2χ netlist (MHz)": f"{two_chi * 1e3:+.3f}",
        "2χ exact model (MHz)": f"{exact * 1e3:+.3f}", "2χ Koch formula (MHz)": f"{formula * 1e3:+.3f}",
        "Formula error (%)": f"{100 * abs(two_chi - formula) / abs(two_chi):.1f}",
    })
    demo.check(f"dispersive shift 2χ at flux {phi} (MHz)", two_chi * 1e3, exact * 1e3, 0.05)
demo.check("Koch formula at the largest detuning, relative error", formula / two_chi, 1.0, 0.05)

demo.check("basis-truncation error (MHz)", device.check_convergence(6)["max_transition_shift_mhz"], 0, 0.01)
demo.check("vacuum Rabi splitting 2g (MHz)", 2e3 * g_measured, 2e3 * g_theory, 1.0)
demo.check("resonance flux", found.x, theory.x, 0.002)
demo.check("worst transition vs model over the sweep (MHz)", 1e3 * np.abs(table[:, 1:4] - reference)[:, :2].max(), 0, 5.0)

# --- figure -------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(17, 6), gridspec_kw={"width_ratios": [1.35, 1, 1]})
fig.subplots_adjust(left=0.05, right=0.985, bottom=0.12, top=0.78, wspace=0.30)
headline(fig, f"Vacuum Rabi splitting of {2e3 * g_measured:.0f} MHz, from a 6 fF capacitor",
         "Two-mode circuit quantized from tunable_transmon_readout.qdl. The netlist contains no coupling "
         "strength: the anticrossing and the readout shift both follow from the geometry.")
ax = axes[0]
image = ax.pcolormesh(flux, probe, spectrum, cmap=SEQUENTIAL, shading="gouraud", vmax=0.9)
heatmap_axes(ax)
bare = [bare_transmon(p)[0] for p in flux]
ax.plot(flux, [b[1] - b[0] for b in bare], color=ORANGE, lw=1.2, label="bare qubit")
ax.axhline(f_res, color=INK2, lw=1.0, label="bare resonator")
ax.annotate("", (found.x, f_res + g_measured), (found.x, f_res - g_measured),
            arrowprops={"arrowstyle": "<->", "color": INK, "lw": 1.2})
ax.text(0.055, f_res + 0.045, f"2g = {2e3 * g_measured:.1f} MHz", color=INK, fontsize=10.5,
        bbox={"fc": SURFACE, "ec": "none", "alpha": 0.85, "pad": 1.5})
ax.set(title="Resonator transmission", xlabel="SQUID flux (Φ$_0$)", ylabel="Probe frequency (GHz)",
       xlim=(0, 0.4), ylim=(probe[0], probe[-1]))
ax.legend(loc="lower left")
colorbar(fig, image, ax, "Transmission amplitude (normalised)")

ax = axes[1]
ax.plot(flux, (table[:, 2] - table[:, 1]) * 1e3, color=BLUE, label="netlist")
every = slice(None, None, 25)
ax.plot(flux[every], (reference[every, 1] - reference[every, 0]) * 1e3, "o", color=ORANGE,
        label="textbook model, no fit")
ax.axhline(2e3 * g_measured, color=INK2, lw=0.9)
ax.set(title="Gap between the two branches", xlabel="SQUID flux (Φ$_0$)", ylabel="Splitting (MHz)",
       xlim=(0, 0.3), ylim=(0, 1300))
ax.annotate(f"minimum = 2g = {2e3 * g_measured:.1f} MHz", (0.005, 2e3 * g_measured), xytext=(0, 6),
            textcoords="offset points", color=INK2)
ax.legend(loc="upper left")

ax = axes[2]
frame = pd.DataFrame(rows)
x = frame["Detuning (GHz)"].astype(float)
ax.plot(x, frame["2χ netlist (MHz)"].astype(float), color=BLUE, label="netlist")
ax.plot(x, frame["2χ exact model (MHz)"].astype(float), "o", color=AQUA, ms=8, label="textbook model, exact")
ax.plot(x, frame["2χ Koch formula (MHz)"].astype(float), "s", color=ORANGE, ms=7, label="2nd-order formula (Koch 2007)")
ax.set(title="Readout shift when the qubit is excited", xlabel="Qubit − resonator detuning (GHz)",
       ylabel="2χ (MHz)")
ax.legend(loc="lower left")
demo.save(fig, "vacuum_rabi_splitting")
demo.table(frame, "dispersive_shift", "Dispersive readout shift: netlist spectrum vs perturbation theory")
demo.table(pd.DataFrame([
    {"Quantity": "Resonator at flux 0.40, qubit far below (GHz)", "Netlist": f"{table[-1, 2]:.4f}", "Model from C matrix": f"{reference[-1, 1]:.4f}"},
    {"Quantity": "Vacuum Rabi splitting 2g (MHz)", "Netlist": f"{2e3 * g_measured:.2f}", "Model from C matrix": f"{2e3 * g_theory:.2f}"},
    {"Quantity": "2g from g·n01 formula (MHz)", "Netlist": f"{2e3 * g_measured:.2f}", "Model from C matrix": f"{2e3 * g_formula:.2f}"},
    {"Quantity": "Flux at resonance (Φ0)", "Netlist": f"{found.x:.4f}", "Model from C matrix": f"{theory.x:.4f}"},
]), "coupling", "Coupling extracted from the spectrum vs computed from the capacitance matrix")
demo.finish()
