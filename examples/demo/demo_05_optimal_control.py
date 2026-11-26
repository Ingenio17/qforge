"""
Demo 5: GRAPE optimal control against DRAG and a plain Gaussian.

All three are calibrated on the same four-level transmon registered in QubitEngine. The
optimiser works in the rotating frame; every pulse is then replayed in the lab frame
with its carrier and the full charge operator, so the plotted errors are not the ones
the optimiser believed but the ones the Hamiltonian delivers.
"""

import numpy as np
import pandas as pd
import qutip as qt
from _common import AQUA, BLUE, INK2, MUTED, ORANGE, Demo, headline, plt, quiet

from QubitWeave.core.pulse_optimizer import (Ladder, gate_metrics, lab_frame_unitary, optimize_drag,
                                             optimize_gaussian, optimize_grape, rotating_frame_unitary)
from QubitWeave.core.qubit_engine import QubitEngine

demo = Demo("05_optimal_control", "Demo 5: GRAPE vs DRAG vs Gaussian")
engine = QubitEngine()
with quiet():
    engine.create_qubit("transmon", "oc_transmon", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 5})
ladder = Ladder.from_qubit(engine.get_qubit("oc_transmon"), 5)

DURATIONS = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 16.0, 20.0]
METHODS = (("Gaussian", BLUE, "o"), ("DRAG", ORANGE, "s"), ("GRAPE", AQUA, "D"))
results, pulses, histories = {m: [] for m, *_ in METHODS}, {}, {}
for duration in DURATIONS:
    grape = optimize_grape(ladder, duration)
    candidates = {"Gaussian": optimize_gaussian(ladder, duration), "DRAG": optimize_drag(ladder, duration),
                  "GRAPE": grape["pulse"]}
    histories[duration] = grape["history"]
    for name, pulse in candidates.items():
        pulses[name, duration] = pulse
        rwa, lab = gate_metrics(rotating_frame_unitary(ladder, pulse)), gate_metrics(lab_frame_unitary(ladder, pulse))
        results[name].append({"rwa": rwa["error"], "lab": lab["error"], "leak": lab["leakage"]})


def at(name, duration, key="lab"):
    return results[name][DURATIONS.index(duration)][key]


# --- checks --------------------------------------------------------------------
demo.check("5 ns: GRAPE beats DRAG by at least 100x in the lab frame (log10 ratio)",
           min(np.log10(at("DRAG", 5.0) / at("GRAPE", 5.0)), 2.0), 2.0, 1e-9)
demo.check("5 ns GRAPE error below 1e-4 in the lab frame (1 = yes)", float(at("GRAPE", 5.0) < 1e-4), 1.0, 0)

pulse = pulses["GRAPE", 5.0]
op_x, op_y = ladder.rotating_drives()
h = [qt.Qobj(ladder.rotating_drift()),
     [qt.Qobj(op_x), pulse.x.astype(float)], [qt.Qobj(op_y), pulse.y.astype(float)]]
edges = np.arange(len(pulse.x) + 1) * pulse.dt
u = qt.qeye(ladder.dim)
for k in range(len(pulse.x)):
    step = qt.Qobj(ladder.rotating_drift() + pulse.x[k] * op_x + pulse.y[k] * op_y)
    u = (-1j * step * pulse.dt).expm() * u
demo.check("5 ns GRAPE propagator vs QuTiP (max element)", np.abs(u.full() - rotating_frame_unitary(ladder, pulse)).max(), 0, 1e-10)

# Full lab-frame Schroedinger integration with QuTiP, from |0>.
w = 2 * np.pi * ladder.f01


def voltage(t, args=None):
    k = min(int(t / pulse.dt), len(pulse.x) - 1)
    return 2 * np.pi * (pulse.x[k] * np.cos(w * t) + pulse.y[k] * np.sin(w * t)) / abs(ladder.charge[1, 0])


times = np.linspace(0, pulse.duration, 301)
run = qt.sesolve([qt.Qobj(np.diag(2 * np.pi * ladder.energies)), [qt.Qobj(ladder.charge), voltage]], qt.basis(5, 0), times,
                 options={"atol": 1e-10, "rtol": 1e-8, "max_step": 0.005, "nsteps": 10**7, "progress_bar": ""})
populations = np.array([np.abs(s.full().ravel()) ** 2 for s in run.states])
ours = np.abs(lab_frame_unitary(ladder, pulse)[:, 0]) ** 2
demo.check("lab-frame P(1) vs QuTiP sesolve", populations[-1, 1], ours[1], 2e-5)

drag_run = pulses["DRAG", 5.0]


def lab_populations(p):
    _, history = rotating_frame_unitary(ladder, p, trajectory=True)
    return p.times + p.dt / 2, np.abs(history[:, :, 0]) ** 2


# --- figure --------------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(15, 10.2))
fig.subplots_adjust(left=0.065, right=0.985, bottom=0.075, top=0.855, hspace=0.36, wspace=0.20)
ratio = at("DRAG", 5.0) / at("GRAPE", 5.0)
headline(fig, f"A 5 ns X gate, {ratio:,.0f} times better than DRAG",
         f"Transmon, f01 = {ladder.f01:.3f} GHz, anharmonicity −{-ladder.anharmonicity * 1e3:.0f} MHz, five levels. "
         "Errors are lab-frame: full carrier, full charge operator, no RWA, no decoherence.")
ax = axes[0, 0]
for name, color, marker in METHODS:
    ax.semilogy(DURATIONS, [r["lab"] for r in results[name]], "-" + marker, color=color, label=name)
ax.axhline(1e-4, color=INK2, lw=0.8)
ax.text(20, 1.15e-4, "10⁻⁴", ha="right", va="bottom", color=INK2)
ax.set(title="Gate error vs gate time", xlabel="X gate duration (ns)", ylabel="Average gate error")
ax.legend(loc="upper right")

ax = axes[0, 1]
for p, color, name in ((drag_run, ORANGE, "DRAG"), (pulse, AQUA, "GRAPE")):
    t = np.concatenate([[0], np.arange(1, len(p.x) + 1) * p.dt])
    ax.stairs(p.x * 1e3, t, color=color, lw=2, label=f"{name}, in phase")
    ax.stairs(p.y * 1e3, t, color=color, lw=1.2, alpha=0.55, label=f"{name}, quadrature")
ax.axhline(0, color=MUTED, lw=0.8)
ax.set(title="The 5 ns pulses", xlabel="Time (ns)", ylabel="Rabi rate (MHz)", xlim=(0, 5))
ax.legend(loc="upper right", fontsize=9)

ax = axes[1, 0]
for p, color, name in ((drag_run, ORANGE, "DRAG"), (pulse, AQUA, "GRAPE")):
    t, pop = lab_populations(p)
    ax.semilogy(t, np.maximum(pop[:, 2:].sum(axis=1), 1e-9), color=color, label=name)
ax.set(title="Leakage out of the qubit during the 5 ns gate", xlabel="Time (ns)",
       ylabel="P(|2⟩ and above), from |0⟩", xlim=(0, 5), ylim=(1e-7, 1))
ax.legend(loc="lower center")

ax = axes[1, 1]
for duration, color in ((4.0, BLUE), (5.0, AQUA), (8.0, ORANGE)):
    ax.semilogy(np.arange(1, len(histories[duration]) + 1), np.minimum.accumulate(np.maximum(histories[duration], 1e-13)), color=color,
                label=f"{duration:g} ns")
ax.set(title="GRAPE convergence (rotating frame)", xlabel="Iteration", ylabel="Best gate error so far", xscale="log")
ax.legend(loc="upper right", title=None)
demo.save(fig, "grape_vs_drag")
demo.table(pd.DataFrame([{
    "Gate time (ns)": f"{d:g}", **{f"{m} error": f"{results[m][i]['lab']:.1e}" for m, *_ in METHODS},
    **{f"{m} leakage": f"{results[m][i]['leak']:.1e}" for m, *_ in METHODS},
    "GRAPE error in RWA": f"{results['GRAPE'][i]['rwa']:.0e}"} for i, d in enumerate(DURATIONS)]),
    "errors", "X-gate error and leakage, replayed in the lab frame")
demo.finish()
