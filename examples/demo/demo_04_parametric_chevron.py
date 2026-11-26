"""
Demo 4: one gate mechanism, every architecture.

The parametric CZ modulates a tunable coupler at the |11> to |02>/|20> frequency. The
chevron maps where that exchange is resonant; the same calibration routine then finds a
CZ, and arbitrary controlled phases, for fluxonium, transmon and mixed pairs, and for a
custom netlist device. QuTiP integrates the full time-dependent Hamiltonian as the
independent reference.
"""

import numpy as np
import pandas as pd
import qutip as qt
import scqubits as scq
from _common import (BLUE, DEVICES, INK, INK2, ORANGE, SEQUENTIAL, SURFACE, Demo, colorbar, headline,
                     heatmap_axes, plt)

from QubitWeave.core.device_qubit import build_device_qubit, device_qubit_params
from QubitWeave.core.parametric_gate import _Pair, calibrate_parametric_cphase, parametric_envelope

demo = Demo("04_parametric_chevron", "Demo 4: parametric CZ across architectures")


def levels(qubit, dim):
    e = np.real(qubit.eigenvals(evals_count=dim))
    return e, np.asarray(qubit.matrixelement_table("n_operator", evals_count=dim))


def fluxonium(dim=4, **kw):
    p = {"EJ": 8.9, "EC": 2.5, "EL": 0.5, "flux": 0.5, "cutoff": 110, **kw}
    return levels(scq.Fluxonium(truncated_dim=dim, **p), dim)


def transmon(ej, ec=0.3, dim=4):
    return levels(scq.Transmon(EJ=ej, EC=ec, ng=0, ncut=30, truncated_dim=dim), dim)


def netlist(name, dim=4):
    source = (DEVICES / f"{name}.qdl").read_text(encoding="utf-8")
    return levels(build_device_qubit(device_qubit_params(source, dim, name)), dim)


PAIRS = [
    ("Fluxonium + fluxonium (presets)", fluxonium(), fluxonium(), 0.05),
    ("Netlist fluxonium + preset high-coherence fluxonium", netlist("fluxonium"), fluxonium(EJ=10.0, EC=2.0, EL=0.4), 0.05),
    ("Fluxonium fast + fluxonium typical", fluxonium(EJ=7.0, EC=3.0, EL=0.6), fluxonium(), 0.10),
    ("Transmon + fluxonium", transmon(15.0), fluxonium(), 0.05),
    ("Netlist transmon + fluxonium", netlist("transmon"), fluxonium(), 0.05),
    ("Netlist CSFQ + transmon", netlist("csfq"), transmon(18.0, 0.25), 0.02),
]
rows, schedules = [], []
for label, (e1, n1), (e2, n2), g in PAIRS:
    s = calibrate_parametric_cphase(e1, n1, e2, n2, g)
    schedules.append(s)
    rows.append({
        "Pair": label, "g (MHz)": f"{g * 1e3:.0f}", "Transition": s["transition"],
        "Modulation (GHz)": f"{s['frequency']:.4f}", "Duration (ns)": f"{s['duration']:.1f}",
        "Phase / π": f"{s['conditional_phase'] / np.pi:.4f}", "Coherent gate error": f"{1 - s['fidelity']:.1e}",
        "Leakage": f"{s['leakage']:.1e}",
    })
    demo.check(f"CZ fidelity, {label}", s["fidelity"], 1.0, 0.01)

# --- chevron -------------------------------------------------------------------
(e1, n1), (e2, n2), strength = PAIRS[0][1], PAIRS[0][2], PAIRS[0][3]
pair = _Pair(e1, n1, e2, n2, strength)
best = schedules[0]
d2 = len(e2)
centre, rabi = pair.transition()["frequency"], pair.transition()["rabi"]
freqs = centre + np.linspace(-5, 5, 121) * rabi
times = np.linspace(0, 1400, 240)
start = d2 + 1
targets = [2 * d2, 2]  # |20>, |02>
chevron = np.zeros((len(times), len(freqs)))
for i, f in enumerate(freqs):
    period = 1 / f
    samples = 48
    carrier = np.cos(2 * np.pi * f * (np.arange(samples) + 0.5) * period / samples)
    one = pair._propagate(carrier, period / samples)
    w, v = np.linalg.eig(one)
    coeff = np.linalg.solve(v, np.eye(len(w))[:, start])
    powers = np.exp(1j * np.outer(np.round(times / period), np.angle(w)))
    states = (powers * coeff) @ v.T
    chevron[:, i] = np.sum(np.abs(states[:, targets]) ** 2, axis=1)

detuning = (freqs - centre) * 1e3
analytic = lambda t, f: rabi**2 / (rabi**2 + (f - centre) ** 2) * np.sin(np.pi * t * np.sqrt(rabi**2 + (f - centre) ** 2)) ** 2
reference = np.array([[analytic(t, f) for f in freqs] for t in times])
demo.check("chevron vs analytic Rabi formula, worst pixel", np.abs(chevron - reference).max(), 0.0, 0.05)

# --- independent QuTiP integration of the calibrated pulse ----------------------
h0 = qt.Qobj(np.diag(2 * np.pi * pair.energies))
v = qt.Qobj(2 * np.pi * strength * np.kron(n1, n2))
coeff = lambda t, args=None: parametric_envelope(t, best["duration"], best["rise_time"]) * np.cos(2 * np.pi * best["frequency"] * t)
outputs = []
for k in pair.comp:
    out = qt.sesolve([h0, [v, coeff]], qt.basis(len(pair.energies), int(k)), [0, best["duration"]],
                     options={"atol": 1e-11, "rtol": 1e-9, "nsteps": 10**7, "progress_bar": ""}).states[-1]
    outputs.append(np.exp(2j * np.pi * pair.energies * best["duration"]) * out.full().ravel())
block = np.array(outputs).T[pair.comp]
angles = np.angle(np.diag(block))
a, b = angles[2] - angles[0], angles[1] - angles[0]
corrected = np.exp(-1j * (angles[0] + np.array([0, b, a, a + b])))[:, None] * block
phase = float(np.angle(corrected[3, 3]) % (2 * np.pi))
fidelity = float((abs(np.sum(np.conj([1, 1, 1, -1]) * np.diag(corrected))) ** 2 + np.sum(abs(block) ** 2)) / 20)
demo.check("CZ fidelity re-integrated with QuTiP", fidelity, best["fidelity"], 1e-4)
demo.check("conditional phase re-integrated with QuTiP (π)", phase / np.pi, 1.0, 0.005)

# --- continuous controlled phases ------------------------------------------------
angles_wanted = np.linspace(0.25, 1.75, 13) * np.pi
cphase = [calibrate_parametric_cphase(e1, n1, e2, n2, strength, th) for th in angles_wanted]
for th, s in zip(angles_wanted[::4], cphase[::4]):
    demo.check(f"CPHASE({th / np.pi:.2f}π): phase (π)", s["conditional_phase"] / np.pi, th / np.pi, 0.01)

# --- figure -----------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(17, 6), gridspec_kw={"width_ratios": [1.35, 1, 0.95]})
fig.subplots_adjust(left=0.05, right=0.985, bottom=0.12, top=0.78, wspace=0.30)
headline(fig, f"Fluxonium CZ in {best['duration']:.0f} ns, coherent error {1 - best['fidelity']:.0e}",
         "Modulating a 50 MHz tunable coupler at 8.66 GHz swaps |11⟩ with |20⟩ and |02⟩. "
         "One full cycle is a CZ. Both fluxonia stay at their flux sweet spot. (No T1/T2 in this demo.)")
ax = axes[0]
image = ax.pcolormesh(detuning, times, chevron, cmap=SEQUENTIAL, vmin=0, vmax=1, shading="gouraud")
heatmap_axes(ax)
ax.plot((best["frequency"] - centre) * 1e3, 1 / rabi, "o", color=ORANGE, ms=11)
ax.annotate("one full cycle = CZ\n(square pulse)", ((best["frequency"] - centre) * 1e3, 1 / rabi), xytext=(16, 12),
            textcoords="offset points", color=INK, fontsize=10.5,
            bbox={"fc": SURFACE, "ec": "none", "alpha": 0.85, "pad": 1.5})
ax.set(title="Chevron: population outside |11⟩", xlabel=f"Modulation − {centre:.4f} GHz (MHz)",
       ylabel="Coupler pulse (ns)")
colorbar(fig, image, ax, "P(|20⟩) + P(|02⟩)")

ax = axes[1]
ax.plot(angles_wanted / np.pi, [s["conditional_phase"] / np.pi for s in cphase], "o", color=BLUE, label="simulated phase")
ax.plot([0.2, 1.8], [0.2, 1.8], color=INK2, lw=0.9, label="requested = delivered")
worst = min(s["fidelity"] for s in cphase)
ax.set(title="Any controlled phase, not just CZ", xlabel="Requested phase (π)", ylabel="Delivered phase (π)")
ax.text(0.97, 0.06, f"worst coherent error {1 - worst:.0e}", transform=ax.transAxes, ha="right", color=INK2)
ax.legend(loc="upper left")

ax = axes[2]
magnitude = np.abs(block)
image = ax.imshow(magnitude, cmap=SEQUENTIAL, vmin=0, vmax=1)
heatmap_axes(ax)
names = ["00", "01", "10", "11"]
ax.set_xticks(range(4), [f"|{s}⟩" for s in names])
ax.set_yticks(range(4), [f"|{s}⟩" for s in names])
for i in range(4):
    z = np.angle(corrected[i, i]) / np.pi
    ax.text(i, i, f"{abs(corrected[i, i]):.4f}\nphase {abs(z):.3f}π", ha="center", va="center", color=SURFACE, fontsize=10)
ax.set(title="CZ unitary, independent QuTiP run", xlabel="Input", ylabel="Output")
demo.save(fig, "chevron_and_cz")
demo.table(pd.DataFrame(rows), "cz_by_architecture", "Parametric CZ calibrated for six qubit pairings")
demo.table(pd.DataFrame([{
    "Requested phase (π)": f"{th / np.pi:.3f}", "Delivered phase (π)": f"{s['conditional_phase'] / np.pi:.4f}",
    "Modulation (GHz)": f"{s['frequency']:.5f}", "Duration (ns)": f"{s['duration']:.1f}",
    "Coherent gate error": f"{1 - s['fidelity']:.1e}", "Leakage": f"{s['leakage']:.1e}"}
    for th, s in zip(angles_wanted, cphase)]), "controlled_phases", "Continuous controlled-phase family on the fluxonium pair")
demo.finish()
