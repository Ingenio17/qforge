"""
Demo 6: randomized benchmarking of simulated physical pulses.

Random Clifford sequences are played on the multilevel ladder with T1 and T2 running,
exactly as a lab would do it, and the decay gives an error per Clifford. Because this is
a simulator the true error of the same channels is known, so the benchmarking protocol
itself is put on trial. Three gates on two architectures separate the error budget into
coherent, leakage and coherence-limited parts.
"""

import numpy as np
import pandas as pd
from _common import AQUA, BLUE, INK2, ORANGE, VIOLET, YELLOW, Demo, headline, plt, quiet
from scipy.optimize import minimize

from QubitWeave.config.defaults import NOISE_DEFAULTS, QUBIT_PRESETS
from QubitWeave.core.benchmarking import (_average_error, _rz, _SX, _super, pulse_superoperator,
                                          randomized_benchmarking)
from QubitWeave.core.pulse_optimizer import Ladder, gaussian_pulse
from QubitWeave.core.qubit_engine import QubitEngine

demo = Demo("06_randomized_benchmarking", "Demo 6: pulse-level randomized benchmarking")
engine = QubitEngine()
with quiet():
    engine.create_qubit("transmon", "rb_t", {**QUBIT_PRESETS["transmon"]["typical"], "truncated_dim": 4})
    engine.create_qubit("fluxonium", "rb_f", {**QUBIT_PRESETS["fluxonium"]["typical"], "truncated_dim": 4})
transmon = Ladder.from_qubit(engine.get_qubit("rb_t"), 4)
fluxonium = Ladder.from_qubit(engine.get_qubit("rb_f"), 4)
noise_t = NOISE_DEFAULTS["transmon"]
noise_f = NOISE_DEFAULTS["fluxonium"]


def calibrate(ladder, duration, use_drag):
    """Calibrate a pi/2 pulse: amplitude, detuning, DRAG weight and the virtual Z around it."""
    base = gaussian_pulse(ladder, duration, angle=np.pi / 2).x.max()

    def build(v):
        return gaussian_pulse(ladder, duration, base * v[0], v[1] if use_drag else 0.0, 0.01 * v[2] if use_drag else 0.0)

    def loss(v):
        channel = pulse_superoperator(ladder, build(v))
        z = _rz(v[3], ladder.dim)
        z = _super(z, z.conj().T)
        return np.log10(_average_error(z @ channel @ z, _SX, ladder.dim) + 1e-12)

    found = min((minimize(loss, (1.0, d, 0.0, 0.0), method="Nelder-Mead", options={"maxiter": 260, "fatol": 1e-3, "xatol": 1e-5})
                 for d in ((0.5, 1.0) if use_drag else (0.0,))), key=lambda r: r.fun)
    return build(found.x), found.x[3]


CASES = [
    ("Transmon, 20 ns DRAG", transmon, 20.0, True, noise_t["T1_dielectric"], noise_t["T2_echo"], BLUE, (1, 30, 80, 160, 320, 640, 1200, 2000)),
    ("Transmon, 8 ns Gaussian", transmon, 8.0, False, noise_t["T1_dielectric"], noise_t["T2_echo"], ORANGE, (1, 4, 10, 20, 40, 70, 120, 200)),
    ("Transmon, 4 ns DRAG", transmon, 4.0, True, noise_t["T1_dielectric"], noise_t["T2_echo"], AQUA, (1, 10, 30, 60, 120, 220, 400, 700)),
    ("Fluxonium, 40 ns DRAG", fluxonium, 40.0, True, noise_f["T1_dielectric"], noise_f["T2_echo"], VIOLET, (1, 100, 300, 700, 1400, 2600, 4500, 7000)),
]
results, rows = [], []
for label, ladder, duration, drag, t1, t2, color, lengths in CASES:
    half_pi, z = calibrate(ladder, duration, drag)
    r = randomized_benchmarking(ladder, half_pi, t1, t2, lengths=lengths, sequences=80, z_correction=z)
    bare = randomized_benchmarking(ladder, half_pi, lengths=lengths[:3], sequences=2, z_correction=z)
    results.append(r)
    coherent = bare["true_error"]
    rows.append({
        "Gate": label, "Clifford (ns)": f"{r['clifford_duration']:.0f}", "T1 / T2 (µs)": f"{t1:g} / {t2:g}",
        "True error": f"{r['true_error']:.3e}", "Standard RB": f"{r['error_per_clifford']:.3e}",
        "Leakage-aware RB": f"{r['corrected_error']:.3e}",
        "Aware / true": f"{r['corrected_error'] / r['true_error']:.3f}", "Coherence limit": f"{r['coherence_limit']:.2e}",
        "Coherent error": f"{coherent:.1e}", "True leakage": f"{r['leakage']:.1e}", "RB leakage": f"{r['leakage_rb']:.1e}",
    })
    r["coherent"] = coherent
    demo.check(f"{label}: leakage-aware RB / true error", r["corrected_error"] / r["true_error"], 1.0, 0.10)

demo.check("20 ns DRAG is coherence limited (true / limit)", results[0]["true_error"] / results[0]["coherence_limit"], 1.0, 0.03)
demo.check("number of Cliffords", len(__import__("QubitWeave.core.benchmarking", fromlist=["x"]).clifford_group()), 24, 0)

# --- figure --------------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(16, 6.6), gridspec_kw={"width_ratios": [1.35, 1]})
fig.subplots_adjust(left=0.06, right=0.985, bottom=0.13, top=0.80, wspace=0.24)
headline(fig, "Randomized benchmarking that can check its own answer",
         "80 random sequences per point, simulated pulse by pulse on four levels with T1 and T2. "
         "Lines: standard RB fits. r: leakage-aware error per Clifford.")
ax = axes[0]
for (label, *_rest, color, _), r in zip(CASES, results):
    m = np.linspace(1, r["lengths"][-1], 400)
    ax.plot(np.repeat(r["lengths"], r["survival"].shape[1]), r["survival"].ravel(), ".", color=color, ms=3.5, alpha=0.22, mew=0)
    ax.plot(m, r["A"] * r["p"] ** m + r["B"], color=color)
    ax.plot(r["lengths"], r["mean"], "o", color=color, label=f"{label}: r = {r['corrected_error']:.1e}")
ax.set_xscale("log")
ax.set(title="Survival probability", xlabel="Number of random Cliffords", ylabel="P(|0⟩)", ylim=(0.2, 1.03))
ax.legend(loc="lower left")

ax = axes[1]
y = np.arange(len(CASES))[::-1]
limit = [r["coherence_limit"] for r in results]
ax.hlines(y, limit, [r["true_error"] for r in results], color="#c3c2b7", lw=2)
ax.plot(limit, y, "o", color=YELLOW, ms=10, label="coherence limit (T1, T2)")
ax.plot([r["true_error"] for r in results], y, "o", color=BLUE, ms=13, label="true channel error")
ax.plot([r["error_per_clifford"] for r in results], y, "X", color=AQUA, ms=10, label="standard RB")
ax.plot([r["corrected_error"] for r in results], y, "D", color=ORANGE, ms=7, label="leakage-aware RB")
ax.set_xscale("log")
ax.set_yticks(y, [c[0].replace(", ", "\n") for c in CASES])
ax.set_ylim(-0.6, len(CASES) - 0.1)
ax.set(title="Where the error comes from", xlabel="Error per Clifford")
ax.legend(loc="upper center", bbox_to_anchor=(0.40, -0.09), ncol=4, fontsize=9, handletextpad=0.3, columnspacing=1.0)
ax.xaxis.set_label_coords(0.5, -0.055)
demo.save(fig, "randomized_benchmarking")
demo.table(pd.DataFrame(rows), "error_budget", "Randomized benchmarking vs the exact error of the same simulated channels")
demo.finish()
