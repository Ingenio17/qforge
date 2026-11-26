"""
Demo 12: a Toffoli gate on three different qubits, as pulses, without error correction.

Control 1 is a transmon, control 2 a fluxonium and the target a three-junction flux
qubit built from a netlist. The gate is compiled from toffoli_only.qasm to microwave and
coupler pulses and integrated in time. Starting from |110> the target must flip, starting
from |100> it must not. All eight inputs are then run, so that the whole gate, phases
included, is compared with the ideal Toffoli and not just one transition.
"""

import itertools
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
from _common import (AQUA, BLUE, CIRCUITS, INK2, MUTED, ORANGE, RED, SEQUENTIAL, SURFACE, VIOLET, Demo, colorbar,
                     headline, heatmap_axes, plt, quiet)

from QubitWeave.config.defaults import QUBIT_PRESETS
from QubitWeave.core.device_library import template_source
from QubitWeave.core.device_qubit import device_qubit_params
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine

NAMES = ["tof_transmon", "tof_fluxonium", "tof_flux_qubit"]
KINDS = ["transmon (control 1)", "fluxonium (control 2)", "flux qubit (target)"]
SHORT = ["transmon", "fluxonium", "flux qubit"]
COUPLINGS = [
    {"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05},
    {"q1": 1, "q2": 2, "type": "tunable_coupler", "strength": 0.05},
    # |11> and |02> are only 263 MHz apart here, so a gentler coupler keeps it selective.
    {"q1": 0, "q2": 2, "type": "tunable_coupler", "strength": 0.01},
]
AMPLITUDES = {NAMES[1]: 0.10}
BITS = ["".join(b) for b in itertools.product("01", repeat=3)]
STEPS = 900


def compiled():
    engine = GateEngine()
    flow = PhysicalWorkflowEngine(QubitEngine(), engine, drive_amplitudes=AMPLITUDES)
    circuit = flow.parse_qasm_circuit(str(CIRCUITS / "toffoli_only.qasm"))
    schedule, total = flow.compile_schedule(NAMES, COUPLINGS, circuit, flow.automate_calibrations(NAMES, COUPLINGS, circuit))
    return engine, flow, circuit, schedule, total


def run(bits):
    """Full pulse-level evolution of the Toffoli from one basis state."""
    with quiet():
        engine, flow, _, schedule, total = compiled()
        result = engine.simulate_n_qubit_dynamics(NAMES, "Compiled_Algorithm", total, COUPLINGS, schedule, bits, steps=STEPS)
        logical = flow._logical_state(NAMES, result["final_state"], total)
    dims = logical.dims[0]
    keep = [int(np.ravel_multi_index([int(c) for c in b], dims)) for b in BITS]
    return (logical.full().ravel()[keep], result["times"],
            {b: np.asarray(result["populations"][b]) for b in BITS})


def label_schedule(circuit, schedule):
    """Which logical gate each pulse belongs to: 1 pulse per H, 3 per CNOT, none per RZ."""
    labels = []
    for gate in circuit:
        kind, target = gate["type"], gate["target"]
        if kind == "H":
            labels.append(f"H q{target}")
        elif kind == "CX":
            labels += [f"CX {target[0]}→{target[1]}"] * 3
    assert len(labels) == len(schedule)
    return labels


def main():
    demo = Demo("12_toffoli", "Demo 12: Toffoli on three different qubits")
    with quiet():
        qubits = QubitEngine()
        qubits.create_qubit("transmon", NAMES[0], {**QUBIT_PRESETS["transmon"]["typical"], "truncated_dim": 3})
        qubits.create_qubit("fluxonium", NAMES[1], {**QUBIT_PRESETS["fluxonium"]["typical"], "truncated_dim": 3})
        qubits.create_qubit("device", NAMES[2], device_qubit_params(template_source("flux_qubit"), 3, "flux_qubit"))
        engine, flow, circuit, schedule, total = compiled()  # fills the caches before the pool reads them
    labels = label_schedule(circuit, schedule)

    with Pool(8) as pool:
        out = pool.map(run, BITS, chunksize=1)
    unitary = np.array([o[0] for o in out]).T  # columns are inputs
    times = out[0][1]
    evolution = {b: o[2] for b, o in zip(BITS, out)}

    ideal = np.eye(8)[[0, 1, 2, 3, 4, 5, 7, 6]]
    truth = np.abs(unitary) ** 2
    d = 8
    average = float((abs(np.trace(ideal.conj().T @ unitary)) ** 2 + np.sum(np.abs(unitary) ** 2)) / (d * (d + 1)))
    leakage = float(1 - np.sum(np.abs(unitary) ** 2) / d)
    expected = {b: b[:2] + str(int(b[2]) ^ (int(b[0]) & int(b[1]))) for b in BITS}

    demo.check("|110⟩ → |111⟩: final population", evolution["110"]["111"][-1], 1.0, 0.02)
    demo.check("|100⟩ stays: final population", evolution["100"]["100"][-1], 1.0, 0.02)
    worst = min(truth[BITS.index(expected[b]), BITS.index(b)] for b in BITS)
    demo.check("worst entry of the truth table, all 8 inputs", worst, 1.0, 0.02)
    demo.check("average gate fidelity to the ideal Toffoli, phases included", average, 1.0, 0.02)
    demo.check("leakage out of the computational states", leakage, 0.0, 0.01)
    # An independent handle on the phases: a superposed control must leave a Bell-like state.
    plus = (unitary[:, BITS.index("010")] + unitary[:, BITS.index("110")]) / np.sqrt(2)
    target = np.zeros(8)
    target[[BITS.index("010"), BITS.index("111")]] = 1 / np.sqrt(2)
    demo.check("(|0⟩+|1⟩)|10⟩ → (|010⟩+|111⟩)/√2: fidelity", abs(np.vdot(target, plus)) ** 2, 1.0, 0.02)
    demo.check("columns stay orthonormal (largest deviation)", np.abs(unitary.conj().T @ unitary - np.eye(8)).max(), 0.0, 0.01)

    # --- figure -------------------------------------------------------------------
    fig = plt.figure(figsize=(17, 11.6))
    headline(fig, f"Toffoli on a transmon, a fluxonium and a flux qubit: {average * 100:.2f}% gate fidelity",
             f"toffoli_only.qasm compiled to {len(schedule)} pulses over {total:,.0f} ns. Labels are |control 1, control 2, target⟩. "
             "No error correction, no T1/T2.")
    grid = fig.add_gridspec(3, 2, left=0.05, right=0.97, top=0.87, bottom=0.06, hspace=0.42, wspace=0.24,
                            height_ratios=[1.15, 1, 1.45])
    # Highlight the input, its Toffoli partner, and the two states the route passes through most.
    palette = {"110": BLUE, "111": ORANGE, "100": AQUA, "101": VIOLET}
    for row, (start, title) in enumerate((
        ("110", "Both controls are 1: the target flips, |110⟩ → |111⟩"),
        ("100", "Only one control is 1: the target must not flip, |100⟩ → |100⟩"),
    )):
        ax = fig.add_subplot(grid[row, :])
        pops = evolution[start]
        edges = [(p["start_time"], p["end_time"]) for p in schedule]
        k, shade = 0, 0
        while k < len(schedule):
            width = 3 if labels[k].startswith("CX") else 1
            a, b = edges[k][0], edges[k + width - 1][1]
            ax.axvspan(a, b, color=MUTED, alpha=0.11 if shade % 2 else 0.03, lw=0)
            if row == 0:
                ax.text((a + b) / 2, 1.05, labels[k], ha="center", va="bottom", color=INK2, fontsize=9)
            k, shade = k + width, shade + 1
        for s, color in palette.items():
            ax.plot(times, pops[s], color=color, label=f"|{s}⟩", zorder=3)
        ax.plot(times, sum(pops[s] for s in BITS if s not in palette), color=MUTED, lw=1.4, label="other |0⟩/|1⟩ states")
        ax.plot(times, 1 - sum(pops.values()), color=RED, lw=1.2, label="|2⟩ levels")
        final = expected[start]
        ax.set(title=f"{title}  (ends at {pops[final][-1]:.4f})", ylabel="Population", xlim=(0, times[-1]), ylim=(0, 1.20 if row == 0 else 1.06),
               xlabel="Time (ns)" if row else "")
        if row == 0:
            ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.985), ncol=6, fontsize=9.5)

    ax = fig.add_subplot(grid[2, 0])
    image = ax.imshow(truth, cmap=SEQUENTIAL, vmin=0, vmax=1)
    heatmap_axes(ax)
    ax.set_xticks(range(8), [f"|{b}⟩" for b in BITS], fontsize=9)
    ax.set_yticks(range(8), [f"|{b}⟩" for b in BITS], fontsize=9)
    for column, b in enumerate(BITS):
        ax.text(column, BITS.index(expected[b]), f"{truth[BITS.index(expected[b]), column]:.3f}", ha="center", va="center",
                color=SURFACE, fontsize=8)
    ax.set(xlabel="Input", ylabel="Output", title="Truth table from pulse simulation, all 8 inputs")
    colorbar(fig, image, ax, "Probability")

    ax = fig.add_subplot(grid[2, 1])
    pair = [BITS.index("110"), BITS.index("111")]
    phases = [np.angle(unitary[BITS.index(expected[b]), i] / unitary[0, 0]) / np.pi for i, b in enumerate(BITS)]
    ax.axhline(0, color=INK2, lw=0.9)
    ax.vlines(range(8), 0, phases, color="#c3c2b7", lw=2)
    ax.plot([i for i in range(8) if i not in pair], [phases[i] for i in range(8) if i not in pair], "o", color=BLUE, ms=9,
            label="input unchanged")
    ax.plot(pair, [phases[i] for i in pair], "o", color=ORANGE, ms=9, label="target flipped")
    limit = max(0.02, 1.4 * np.abs(phases).max())
    ax.set(xlabel="Input", ylabel="Output phase error (π)", title="Phase of each output (ideal: all 0)", ylim=(-limit, 1.5 * limit))
    ax.set_xticks(range(8), [f"|{b}⟩" for b in BITS], fontsize=9)
    ax.legend(loc="upper left", ncol=2)
    demo.save(fig, "toffoli_evolution")

    demo.table(pd.DataFrame([{
        "Input": f"|{b}⟩", "Ideal output": f"|{expected[b]}⟩", "Target flips": "yes" if expected[b] != b else "no",
        "P(ideal output)": f"{truth[BITS.index(expected[b]), i]:.5f}",
        "Largest wrong output": f"{max(truth[j, i] for j in range(8) if BITS[j] != expected[b]):.1e}",
        "Leakage": f"{1 - truth[:, i].sum():.1e}", "Phase error (π)": f"{phases[i]:+.4f}",
    } for i, b in enumerate(BITS)]), "truth_table", "Toffoli truth table from pulse-level simulation")
    rows = []
    for i, (name, kind) in enumerate(zip(NAMES, KINDS)):
        energies = np.real(engine._get_qubit_hamiltonian(name)[0].diag()) / (2 * np.pi)
        f01, f12 = energies[1] - energies[0], energies[2] - energies[1]
        half_pi = flow.g_eng.calibrate_half_pi(name, flow._drive_amplitude(name))[0]
        rows.append({"Qubit": f"q{i}: {kind}", "Built from": ["preset", "preset", "netlist (3 junctions)"][i],
                     "f01 (GHz)": f"{f01:.4f}", "Anharmonicity (GHz)": f"{f12 - f01:+.4f}", "π/2 pulse (ns)": f"{half_pi:.1f}"})
    demo.table(pd.DataFrame(rows), "qubits", "The three qubits")
    demo.table(pd.DataFrame([{
        "Pair": f"{SHORT[c['q1']]} – {SHORT[c['q2']]}", "g (MHz)": f"{c['strength'] * 1e3:.0f}",
        "Modulation (GHz)": f"{s['frequency']:.4f}", "CZ (ns)": f"{s['duration']:.1f}", "CZ error": f"{1 - s['fidelity']:.1e}",
    } for c in COUPLINGS for s in [engine._parametric_cphase_schedule(NAMES[c["q1"]], NAMES[c["q2"]], c["strength"])]]),
        "couplings", "The three tunable-coupler CZ gates")
    demo.table(pd.DataFrame([{
        "#": i + 1, "Gate": l, "Pulse": "coupler modulation" if p["type"] == "coupler_pulse" else "microwave",
        "On": " – ".join(SHORT[t] for t in p["target"]) if isinstance(p["target"], tuple) else SHORT[p["target"]],
        "Start (ns)": f"{p['start_time']:.1f}", "End (ns)": f"{p['end_time']:.1f}", "Frequency (GHz)": f"{p['frequency']:.4f}",
    } for i, (l, p) in enumerate(zip(labels, schedule))]), "pulse_schedule", "Compiled pulses of the Toffoli")
    demo.finish()


if __name__ == "__main__":
    main()
    sys.exit(0)
