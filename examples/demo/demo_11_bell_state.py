"""
Demo 11: one Bell state, with and without error correction.

Q1 is a transmon and Q2 a fluxonium, both with QubitWeave's typical presets. The same
two-gate circuit (bell_state.qasm: H on Q1, then CNOT) is run

* on the bare qubits, as microwave and coupler pulses integrated in time, and
* encoded in each error-correcting code, once clean and once with an error injected
  that the code then has to find and remove.

Equal populations do not make a Bell state: a classical mixture, or |00> - |11>, has the
same ones. Every result is therefore judged by its fidelity to (|00> + |11>)/sqrt(2),
which needs the correlations <XX> and <YY> as well as <ZZ>.
"""

import numpy as np
import pandas as pd
from _common import (AQUA, BLUE, CIRCUITS, INK, INK2, MUTED, ORANGE, RED, SURFACE, VIOLET, Demo, headline,
                     plt, quiet)

from QubitWeave.config.defaults import QUBIT_PRESETS
from QubitWeave.core.error_correction_engine import ErrorCorrectionEngine
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.register_ops import pauli_string
from QubitWeave.core.stabilizer_codes import REPETITION_3, SHOR_9, STEANE_7, SURFACE_9
from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine

demo = Demo("11_bell_state", "Demo 11: Bell state, with and without error correction")
QASM = str(CIRCUITS / "bell_state.qasm")
NAMES = ["Q1", "Q2"]
STATES = ["00", "01", "10", "11"]
COLOURS = {"00": BLUE, "01": VIOLET, "10": AQUA, "11": ORANGE}

with quiet():
    qubits = QubitEngine()
    qubits.create_qubit("transmon", "Q1", dict(QUBIT_PRESETS["transmon"]["typical"]))
    qubits.create_qubit("fluxonium", "Q2", dict(QUBIT_PRESETS["fluxonium"]["typical"]))
    gates = GateEngine()


def bell_fidelity(zz, xx, yy):
    """<Phi+| rho |Phi+> from the three two-qubit correlations."""
    return (1 + zz + xx - yy) / 4


# --- without error correction: pulses in time ------------------------------------------
with quiet():
    workflow = PhysicalWorkflowEngine(qubits, gates)
    coupling = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05}]
    bare = workflow.execute_workflow(NAMES, coupling, QASM)
    transpiled = workflow.parse_qasm_circuit(QASM)
    schedule, total = workflow.compile_schedule(
        NAMES, coupling, transpiled, workflow.automate_calibrations(NAMES, coupling, transpiled)
    )
times, pops = bare["times"], bare["populations"]
leaked = 1 - sum(pops[s] for s in STATES)
state = bare["logical_state"].full().ravel()
d2 = bare["logical_state"].dims[0][1]
amplitudes = state[[0, 1, d2, d2 + 1]]
rho = np.outer(amplitudes, amplitudes.conj())
X, Z = np.array([[0, 1], [1, 0]]), np.diag([1, -1])
Y = 1j * X @ Z
zz, xx, yy = (float(np.real(np.trace(rho @ np.kron(p, p)))) for p in (Z, X, Y))
fidelity = float(abs(np.vdot([1 / np.sqrt(2), 0, 0, 1 / np.sqrt(2)], amplitudes)) ** 2)

rows = [{
    "Method": "No error correction (pulses)", "Physical qubits": "2", "Injected error": "none",
    "Syndrome Q1": "–", **{f"P({s})": f"{pops[s][-1]:.4f}" for s in STATES},
    "⟨ZZ⟩": f"{zz:+.4f}", "⟨XX⟩": f"{xx:+.4f}", "⟨YY⟩": f"{yy:+.4f}", "Bell fidelity": f"{fidelity:.5f}",
}]
demo.check("no EC: P(00)", pops["00"][-1], 0.5, 0.005)
demo.check("no EC: P(11)", pops["11"][-1], 0.5, 0.005)
demo.check("no EC: Bell-state fidelity", fidelity, 1.0, 1e-3)

# --- encoded ------------------------------------------------------------------------------
CODES = [
    ("3-qubit repetition", REPETITION_3, "execute_3q_repetition_workflow", "X", "Z0Z1, Z1Z2"),
    ("7-qubit Steane", STEANE_7, "execute_steane7_workflow", "Y", "3 Z + 3 X checks"),
    ("9-qubit Shor", SHOR_9, "execute_shor9_workflow", "Y", "6 Z + 2 X checks"),
    ("9-qubit surface (d = 3)", SURFACE_9, "execute_surface9_workflow", "Y", "4 Z + 4 X checks"),
]
PREFIXES = [("Encode", ""), ("H", "h q[0];\n"), ("CNOT", "h q[0];\ncx q[0],q[1];\n")]
engine = ErrorCorrectionEngine(qubits, gates)


def correlations(result, code):
    """Logical <ZZ>, <XX>, <YY> of the final physical state."""
    ket = result["final_physical_state"]
    array = ket.full().reshape(ket.dims[0])

    def act(vector, pauli, support):
        for name in NAMES:
            vector = pauli_string(vector, [result["data_axes"][name][q] for q in support], pauli)
        return vector

    z = act(array, code.logical_z_pauli, code.logical_z_qubits)
    x = act(array, code.logical_x_pauli, code.logical_x_qubits)
    # Y_L Y_L = (i X_L Z_L)(i X_L Z_L) = -(XX)(ZZ)
    both = act(z, code.logical_x_pauli, code.logical_x_qubits)
    return (float(np.vdot(array, z).real), float(np.vdot(array, x).real), -float(np.vdot(array, both).real))


def in_codespace(result, code):
    """Smallest stabilizer expectation over both blocks: 1 means a valid codeword."""
    ket = result["final_physical_state"]
    array = ket.full().reshape(ket.dims[0])
    return min(
        float(np.vdot(array, pauli_string(array, [result["data_axes"][n][q] for q in g.data_qubits], g.basis)).real)
        for n in NAMES for g in code.generators
    )


def encoded(method, body, errors=None):
    with open("encoded.qasm", "w") as handle:
        handle.write("OPENQASM 2.0;\nqreg q[2];\n" + body)
    with quiet():
        # A syndrome round after every gate. The repetition code needs it here: its
        # transversal H leaves the code until the next round, and an error arriving
        # before that round can be mistaken for part of the H.
        return getattr(engine, method)(NAMES, "encoded.qasm", ec_every_n_gates=1, inject_errors=errors)


def raw_fidelity(method, body, code, error):
    """Overlap with the clean codeword when the same error is left uncorrected."""
    clean = encoded(method, body)
    ket = clean["final_physical_state"]
    array = ket.full().reshape(ket.dims[0])
    name, qubit, pauli = error
    broken = array
    for factor in ("Z", "X") if pauli == "Y" else (pauli,):
        broken = pauli_string(broken, [clean["data_axes"][name][qubit]], factor)
    return float(abs(np.vdot(array, broken)) ** 2)


np.random.seed(1)
evolution, summary = {}, []
for label, code, method, pauli, checks in CODES:
    stages = []
    for _, body in PREFIXES:
        r = encoded(method, body)
        stages.append([r["logical_populations"].get(s, 0.0) for s in STATES])
    evolution[label] = np.array(stages)

    body = PREFIXES[-1][1]
    error = ("Q1", 1, pauli)
    broken = raw_fidelity(method, body, code, error)
    for injected in (None, [error]):
        r = encoded(method, body, injected)
        czz, cxx, cyy = correlations(r, code)
        f = bell_fidelity(czz, cxx, cyy)
        valid = in_codespace(r, code)
        rows.append({
            "Method": label, "Physical qubits": str(2 * (code.num_data + code.num_ancilla)),
            "Injected error": f"{pauli} on Q1 data 1" if injected else "none",
            "Syndrome Q1": "".join(map(str, r["syndromes"]["Q1"])),
            **{f"P({s})": f"{r['logical_populations'].get(s, 0.0):.4f}" for s in STATES},
            "⟨ZZ⟩": f"{czz:+.4f}", "⟨XX⟩": f"{cxx:+.4f}", "⟨YY⟩": f"{cyy:+.4f}", "Bell fidelity": f"{f:.5f}",
        })
        tag = f"{label}, {'with ' + pauli + ' error' if injected else 'clean'}"
        demo.check(f"{tag}: logical Bell fidelity", f, 1.0, 1e-9)
        demo.check(f"{tag}: every stabilizer is +1", valid, 1.0, 1e-9)
    # Every correctable error, on every data qubit of both blocks. The repetition code's
    # syndrome after H is random, so it is repeated over many outcomes.
    worst, trials = 1.0, 0
    for seed in range(20 if code is REPETITION_3 else 1):
        for name in NAMES:
            for qubit in range(code.num_data):
                for p in ("X",) if code is REPETITION_3 else ("X", "Y", "Z"):
                    np.random.seed(seed)
                    r = encoded(method, body, [(name, qubit, p)])
                    worst = min(worst, bell_fidelity(*correlations(r, code)))
                    trials += 1
    summary.append((label, broken, worst, trials, "X" if code is REPETITION_3 else "X, Y, Z"))
    demo.check(f"{label}: worst fidelity over {trials} single-error runs", worst, 1.0, 1e-9)
    demo.check(f"{label}: P(00) and P(11) after the circuit", abs(evolution[label][-1][[0, 3]] - 0.5).max(), 0.0, 1e-9)
    demo.check(f"{label}: an uncorrected error destroys the state", broken, 0.0, 1e-9)

# --- figure -------------------------------------------------------------------------------
fig = plt.figure(figsize=(17, 10.4))
headline(fig, "Transmon + fluxonium Bell state, bare and in four error-correcting codes",
         "H on Q1 (transmon), then CNOT onto Q2 (fluxonium). Target (|00⟩ + |11⟩)/√2, judged by fidelity, "
         "not populations alone. No T1/T2; encoded gates are ideal logical operations.")
grid = fig.add_gridspec(2, 5, left=0.05, right=0.985, top=0.85, bottom=0.085, hspace=0.42, wspace=0.28,
                        height_ratios=[1.25, 1])

ax = fig.add_subplot(grid[0, :])
for s in STATES:
    ax.plot(times, pops[s], color=COLOURS[s], label=f"|{s}⟩", zorder=3 if s in ("00", "11") else 2)
ax.plot(times, leaked, color=RED, lw=1.4, label="|2⟩ levels")
LABELS = {0: "H on Q1", 1: "CNOT: Ry(−π/2) on Q2", 2: "CZ", 3: "CNOT: Ry(π/2) on Q2"}
for k, pulse in enumerate(schedule):
    a, b = pulse["start_time"], pulse["end_time"]
    ax.axvspan(a, b, color=MUTED, alpha=0.10 if k % 2 else 0.04, lw=0)
    narrow = (b - a) < 0.08 * total
    ax.annotate(LABELS[k], ((a + b) / 2, 1.06), ha="left" if narrow and k == 0 else "center", va="bottom",
                color=INK2, fontsize=10, xytext=(-8 if k == 0 else 0, 0), textcoords="offset points")
ax.axhline(0.5, color=INK2, lw=0.8)
ax.set(title=f"Without error correction: pulse-level evolution (final fidelity {fidelity:.5f})", xlabel="Time (ns)",
       ylabel="Population", xlim=(0, times[-1]), ylim=(0, 1.22))
ax.legend(loc="upper right", bbox_to_anchor=(0.995, 0.87), ncol=5)

for k, (label, code, *_rest) in enumerate(CODES):
    ax = fig.add_subplot(grid[1, k])
    x = np.arange(len(PREFIXES))
    bottom = np.zeros(len(PREFIXES))
    for column, s in enumerate(STATES):
        values = evolution[label][:, column]
        bars = ax.bar(x, values, 0.42, bottom=bottom, color=COLOURS[s], edgecolor=SURFACE, linewidth=2, label=f"|{s}⟩")
        for bar, v, b0 in zip(bars, values, bottom):
            if v > 0.05:
                ax.text(bar.get_x() + bar.get_width() / 2, b0 + v / 2, f"{s}\n{v:.2f}", ha="center", va="center",
                        color=SURFACE, fontsize=9)
        bottom += values
    ax.set_xticks(x, [n for n, _ in PREFIXES])
    ax.set_yticks([0, 0.5, 1.0])
    ax.grid(axis="x", visible=False)
    ax.set(ylim=(0, 1.05), ylabel="Logical population" if k == 0 else "")
    ax.set_title(f"{label}\n{2 * (code.num_data + code.num_ancilla)} physical qubits", fontsize=11.5)

ax = fig.add_subplot(grid[1, 4])
y = np.arange(len(summary))[::-1]
ax.hlines(y, [s[1] for s in summary], [s[2] for s in summary], color="#c3c2b7", lw=2)
ax.plot([s[1] for s in summary], y, "o", color=RED, ms=10, label="error left in")
ax.plot([s[2] for s in summary], y, "o", color="#008300", ms=10, label="corrected (worst case)")
ax.set_yticks(y, [s[0].replace(" (d = 3)", "").split(" ")[-1].capitalize() for s in summary])
ax.set(xlim=(-0.08, 1.08), ylim=(-0.6, len(summary) + 0.35), xlabel="Bell-state fidelity")
for position, entry in zip(y, summary):
    ax.text(0.5, position + 0.10, f"{entry[4]} errors, {entry[3]} runs", ha="center", color=INK2, fontsize=9)
ax.set_title("Any single error, either block\n(repetition: bit flips only)", fontsize=11.5)
ax.legend(loc="upper center", ncol=2, fontsize=8.5, handletextpad=0.1, columnspacing=0.6)
demo.save(fig, "bell_state_all_methods")

demo.table(pd.DataFrame(rows), "bell_results", "Bell state of Q1 (transmon) and Q2 (fluxonium): every method, with and without an injected error")
demo.table(pd.DataFrame([{
    "Code": label, "Errors tried": f"{paulis} on every data qubit of Q1 and Q2", "Runs": str(trials),
    "Fidelity, error left in": f"{left:.4f}", "Worst fidelity after correction": f"{worst:.6f}",
} for label, left, worst, trials, paulis in summary]), "error_recovery", "Recovery of the encoded Bell state from every correctable single-qubit error")
demo.table(pd.DataFrame([{
    "#": i + 1, "Step": LABELS[i], "Pulse": "coupler modulation" if p["type"] == "coupler_pulse" else "microwave",
    "Start (ns)": f"{p['start_time']:.1f}", "End (ns)": f"{p['end_time']:.1f}", "Frequency (GHz)": f"{p['frequency']:.4f}",
} for i, p in enumerate(schedule)]), "pulse_schedule", "Pulses of the uncorrected run")
demo.finish()
