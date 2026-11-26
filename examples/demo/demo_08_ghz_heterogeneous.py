"""
Demo 8: a GHZ state across three different kinds of qubit.

A netlist fluxonium, a transmon and a preset fluxonium, joined by two tunable couplers,
run ghz3.qasm through the full pulse-level workflow. Analysis rotations are compiled
and simulated too: parity fringes that oscillate three times per cycle, and a Mermin
inequality no classical model can violate. A second run switches on T1 and T2.
"""

import itertools
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
from _common import (AQUA, BLUE, CIRCUITS, DEVICES, INK, INK2, ORANGE, SEQUENTIAL, SURFACE, Demo, colorbar,
                     headline, heatmap_axes, plt, quiet)
from scipy.optimize import curve_fit

from QubitWeave.config.defaults import NOISE_DEFAULTS, QUBIT_PRESETS
from QubitWeave.core.device_qubit import device_qubit_params
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine

NAMES = ["ghz_netlist_fluxonium", "ghz_transmon", "ghz_fluxonium"]
COUPLINGS = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05},
             {"q1": 1, "q2": 2, "type": "tunable_coupler", "strength": 0.05}]
AMPLITUDES = {NAMES[0]: 0.10, NAMES[2]: 0.10}
NOISE = {name: {"T1": NOISE_DEFAULTS[kind]["T1_dielectric"], "T2": NOISE_DEFAULTS[kind]["T2_echo"]}
         for name, kind in zip(NAMES, ("fluxonium", "transmon", "fluxonium"))}
BODY = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\nh q[1];\ncx q[1],q[0];\ncx q[1],q[2];\n'
BITS = ["".join(b) for b in itertools.product("01", repeat=3)]


def engines():
    q_eng = QubitEngine()
    g_eng = GateEngine()
    return PhysicalWorkflowEngine(q_eng, g_eng, drive_amplitudes=AMPLITUDES)


def register():
    q_eng = QubitEngine()
    source = (DEVICES / "fluxonium.qdl").read_text(encoding="utf-8")
    q_eng.create_qubit("device", NAMES[0], device_qubit_params(source, 3, "fluxonium"))
    q_eng.create_qubit("transmon", NAMES[1], {**QUBIT_PRESETS["transmon"]["typical"], "truncated_dim": 3})
    q_eng.create_qubit("fluxonium", NAMES[2], {**QUBIT_PRESETS["fluxonium"]["high_coherence"], "truncated_dim": 3})


def run(job):
    """One full pulse-level execution. Returns computational density matrix and timeline."""
    tag, body, noise, steps = job
    path = f"{tag}.qasm"
    with open(path, "w") as handle:
        handle.write(body)
    with quiet():
        result = engines().execute_workflow(NAMES, COUPLINGS, path, noise=noise, steps=steps)
    state = result["logical_state"].full()
    dims = result["logical_state"].dims[0]
    keep = [int(np.ravel_multi_index([int(c) for c in b], dims)) for b in BITS]
    rho = np.outer(state, state.conj()) if state.shape[1] == 1 else state
    pops = {b: np.asarray(result["populations"][b]) for b in BITS}
    return rho[np.ix_(keep, keep)], result["times"], pops


def parity(rho):
    signs = np.array([(-1) ** b.count("1") for b in BITS])
    return float(np.real(np.sum(signs * np.diag(rho))))


def analysis(settings):
    """Rotate each qubit so that its X ('X') or Y ('Y') is read out in the Z basis."""
    return "".join(("sdg" if s == "Y" else "id") + f" q[{i}];\nh q[{i}];\n" for i, s in enumerate(settings))


def fringe(phi):
    return "".join(f"rz({phi:.10f}) q[{i}];\nh q[{i}];\n" for i in range(3))


def main():
    demo = Demo("08_ghz_heterogeneous", "Demo 8: GHZ state across three qubit types")
    register()
    with quiet():
        run(("warmup", BODY, None, 10))  # fills the calibration cache once, before the pool reads it

    phases = np.linspace(0, 2 * np.pi, 25)
    settings = ["XXX", "XYY", "YXY", "YYX"]
    jobs = [("state", BODY, None, 400), ("state_noisy", BODY, NOISE, 200)]
    jobs += [(f"m_{s}", BODY + analysis(s), None, 10) for s in settings]
    jobs += [(f"mn_{s}", BODY + analysis(s), NOISE, 10) for s in settings]
    jobs += [(f"f_{k}", BODY + fringe(p), None, 10) for k, p in enumerate(phases)]
    with Pool(8) as pool:
        out = pool.map(run, jobs, chunksize=1)
    (rho, times, pops), (rho_noisy, _, _) = out[0], out[1]
    mermin, mermin_noisy = [parity(o[0]) for o in out[2:6]], [parity(o[0]) for o in out[6:10]]
    fringes = np.array([parity(o[0]) for o in out[10:]])

    ideal = np.zeros(8)
    ideal[[0, 7]] = 1 / np.sqrt(2)
    fidelity = float(np.real(ideal @ rho @ ideal))
    fidelity_noisy = float(np.real(ideal @ rho_noisy @ ideal))
    signs = np.array([1, -1, -1, -1])
    m_value, m_noisy = float(signs @ mermin), float(signs @ mermin_noisy)
    (amplitude, frequency, offset), _ = curve_fit(lambda p, a, f, o: a * np.cos(f * p + o), phases, fringes, p0=(1, 3, 0))

    demo.check("GHZ fidelity, pulse level", fidelity, 1.0, 0.02)
    demo.check("fringe frequency (three times a single qubit's)", frequency, 3.0, 0.02)
    demo.check("fringe visibility equals twice the GHZ coherence", abs(amplitude), 2 * abs(rho[0, 7]), 0.02)
    demo.check("Mermin value vs the quantum maximum", m_value, 4.0, 0.1)
    demo.check("Mermin value recomputed from the density matrix", 8 * abs(rho[0, 7]), m_value, 0.05)
    demo.check("noisy state is a valid density matrix: trace kept", float(np.real(np.trace(rho_noisy))), 1.0, 0.02)
    # First-order estimate of the noise: coherence lost at 1/T2 per qubit over the sequence.
    budget = sum(times[-1] * 1e-3 / NOISE[n]["T2"] for n in NAMES)
    print(f"  noisy fidelity {fidelity_noisy:.4f}, T2 budget {budget:.4f}, Mermin {m_noisy:.3f}")
    demo.check("noisy Mermin still violates the classical bound of 2", float(m_noisy > 2), 1.0, 0)

    # --- figure -------------------------------------------------------------------
    fig = plt.figure(figsize=(17, 10))
    headline(fig, f"Three kinds of qubit, one GHZ state: infidelity {1 - fidelity:.0e}, Mermin {m_value:.3f}",
             "Netlist fluxonium, transmon and preset fluxonium on two tunable couplers. ghz3.qasm compiled to pulses; "
             "every analysis rotation is simulated too.")
    grid = fig.add_gridspec(2, 3, left=0.05, right=0.965, top=0.845, bottom=0.08, hspace=0.40, wspace=0.28)

    ax = fig.add_subplot(grid[0, :2])
    for b, color in (("000", BLUE), ("111", ORANGE), ("010", AQUA)):
        ax.plot(times, pops[b], color=color, label=f"|{b}⟩")
    rest = sum(pops[b] for b in BITS if b not in ("000", "111", "010"))
    ax.plot(times, rest, color="#898781", lw=1.4, label="other computational")
    ax.plot(times, 1 - sum(pops.values()), color="#e34948", lw=1.4, label="|2⟩ levels")
    ax.set(title="Building the state, pulse by pulse", xlabel="Time (ns)", ylabel="Population", ylim=(0, 1.2), xlim=(0, times[-1]))
    ax.legend(loc="upper right", ncol=5)

    ax = fig.add_subplot(grid[0, 2])
    fine = np.linspace(0, 2 * np.pi, 400)
    ax.plot(fine / np.pi, np.cos(fine), color="#c3c2b7", lw=1.4, label="one qubit, ideal")
    ax.plot(fine / np.pi, amplitude * np.cos(frequency * fine + offset), color=BLUE, label=f"fit: cos({frequency:.3f} φ)")
    ax.plot(phases / np.pi, fringes, "o", color=ORANGE, label="simulated GHZ")
    ax.set(title="Parity fringes: three times faster", xlabel="Phase φ on every qubit (π)", ylabel="Parity", ylim=(-1.1, 1.75))
    ax.legend(loc="upper center", fontsize=9, ncol=1)

    for k, (matrix, title) in enumerate(((rho, f"Density matrix, unitary (1 − F = {1 - fidelity:.0e})"),
                                         (rho_noisy, f"With T1 and T2 (F = {fidelity_noisy:.4f})"))):
        ax = fig.add_subplot(grid[1, k])
        image = ax.imshow(np.abs(matrix), cmap=SEQUENTIAL, vmin=0, vmax=0.5)
        heatmap_axes(ax)
        ax.set_xticks(range(8), BITS, fontsize=9)
        ax.set_yticks(range(8), BITS, fontsize=9)
        for i, j in ((0, 0), (0, 7), (7, 0), (7, 7)):
            ax.text(j, i, f"{abs(matrix[i, j]):.3f}", ha="center", va="center", color=SURFACE, fontsize=8.5)
        ax.set_title(title)
        colorbar(fig, image, ax, "|ρ|")

    ax = fig.add_subplot(grid[1, 2])
    x = np.arange(4)
    ax.bar(x - 0.14, mermin, 0.25, color=BLUE, label=f"unitary, M = {m_value:.3f}")
    ax.bar(x + 0.14, mermin_noisy, 0.25, color=ORANGE, label=f"with noise, M = {m_noisy:.3f}")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(x, settings)
    ax.set(title="Mermin test (classical |M| ≤ 2, quantum 4)", ylabel="Measured correlator", ylim=(-1.15, 1.9))
    ax.legend(loc="upper right")
    demo.save(fig, "ghz_state")

    demo.table(pd.DataFrame([
        {"Setting": s, "Ideal": f"{i:+d}", "Pulse level": f"{a:+.4f}", "With T1/T2": f"{b:+.4f}"}
        for s, i, a, b in zip(settings, (1, -1, -1, -1), mermin, mermin_noisy)]
        + [{"Setting": "Mermin M", "Ideal": "+4", "Pulse level": f"{m_value:+.4f}", "With T1/T2": f"{m_noisy:+.4f}"},
           {"Setting": "GHZ fidelity", "Ideal": "1", "Pulse level": f"{fidelity:.5f}", "With T1/T2": f"{fidelity_noisy:.4f}"}]),
        "mermin", "Mermin correlators of the simulated GHZ state (classical bound |M| ≤ 2)")
    wf = engines()
    with quiet():
        transpiled = wf.parse_qasm_circuit(str(CIRCUITS / "ghz3.qasm"))
        schedule, _ = wf.compile_schedule(NAMES, COUPLINGS, transpiled, wf.automate_calibrations(NAMES, COUPLINGS, transpiled))
    short = ["fluxonium (netlist)", "transmon", "fluxonium (preset)"]
    demo.table(pd.DataFrame([{
        "#": i + 1, "Pulse": "coupler modulation" if d["type"] == "coupler_pulse" else "microwave",
        "On": " – ".join(short[t] for t in d["target"]) if isinstance(d["target"], tuple) else short[d["target"]],
        "Start (ns)": f"{d['start_time']:.1f}", "End (ns)": f"{d['end_time']:.1f}", "Frequency (GHz)": f"{d['frequency']:.4f}",
        "Amplitude (MHz)": f"{d.get('amplitude', d.get('strength', 0)) * 1e3:.0f}",
        "Phase (rad)": f"{(d.get('phase', 0.0) + np.pi) % (2 * np.pi) - np.pi:+.3f}"} for i, d in enumerate(schedule)]),
        "pulse_schedule", "Compiled pulse schedule for ghz3.qasm")
    demo.finish()


if __name__ == "__main__":
    main()
    sys.exit(0)
