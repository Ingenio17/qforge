"""
Demo 9: the H2 molecule, from Gaussian integrals to microwave pulses.

The STO-3G integrals are computed here, mapped exactly onto two qubits (one per
electron), and the ground state is found by a variational eigensolver whose every
energy is measured on pulse-level executions of vqe_h2.qasm. The ansatz angle enters
only as a virtual Z, so it costs no gate time. Shot noise and T1/T2 are both included.
Full configuration interaction is the reference.
"""

import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
from _common import (AQUA, BLUE, CIRCUITS, DEVICES, INK2, MUTED, ORANGE, Demo, headline, plt, quiet)
from scipy.special import erf

from QubitWeave.config.defaults import NOISE_DEFAULTS, QUBIT_PRESETS
from QubitWeave.core.device_qubit import device_qubit_params
from QubitWeave.core.gate_engine import GateEngine
from QubitWeave.core.qubit_engine import QubitEngine
from QubitWeave.core.workflow_engine import PhysicalWorkflowEngine

NAMES = ["vqe_transmon", "vqe_fluxonium"]
COUPLINGS = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05}]
AMPLITUDES = {NAMES[1]: 0.10}
NOISE = {NAMES[0]: {"T1": NOISE_DEFAULTS["transmon"]["T1_dielectric"], "T2": NOISE_DEFAULTS["transmon"]["T2_echo"]},
         NAMES[1]: {"T1": NOISE_DEFAULTS["fluxonium"]["T1_dielectric"], "T2": NOISE_DEFAULTS["fluxonium"]["T2_echo"]}}
SHOTS = 20000
KCAL = 627.5095  # kcal/mol per hartree; chemical accuracy is 1 kcal/mol = 1.6 mHa


# --- STO-3G integrals for H2 -----------------------------------------------------
ZETA = np.array([3.42525091, 0.62391373, 0.16885540])
COEFF = np.array([0.15432897, 0.53532814, 0.44463454]) * (2 * ZETA / np.pi) ** 0.75


def boys(t):
    return np.where(t < 1e-10, 1.0 - t / 3, 0.5 * np.sqrt(np.pi / np.maximum(t, 1e-12)) * erf(np.sqrt(t)))


def integrals(r_bohr):
    """Overlap, core Hamiltonian and two-electron integrals over the two 1s functions."""
    centres = np.array([0.0, r_bohr])
    s, h = np.zeros((2, 2)), np.zeros((2, 2))
    pairs = {}
    for i in range(2):
        for j in range(2):
            a, b = np.meshgrid(ZETA, ZETA, indexing="ij")
            p = a + b
            rab2 = (centres[i] - centres[j]) ** 2
            k = np.outer(COEFF, COEFF) * np.exp(-a * b / p * rab2)
            rp = (a * centres[i] + b * centres[j]) / p
            s[i, j] = np.sum(k * (np.pi / p) ** 1.5)
            m = a * b / p
            kinetic = m * (3 - 2 * m * rab2) * (np.pi / p) ** 1.5
            nuclear = sum(-2 * np.pi / p * boys(p * (rp - c) ** 2) for c in centres)
            h[i, j] = np.sum(k * (kinetic + nuclear))
            pairs[i, j] = (p.ravel(), rp.ravel(), k.ravel())
    g = np.zeros((2, 2, 2, 2))
    for i, j in pairs:
        for m, n in pairs:
            p, rp, kp = pairs[i, j]
            q, rq, kq = pairs[m, n]
            pp, qq = np.meshgrid(p, q, indexing="ij")
            d2 = (rp[:, None] - rq[None, :]) ** 2
            v = 2 * np.pi**2.5 / (pp * qq * np.sqrt(pp + qq)) * boys(pp * qq / (pp + qq) * d2)
            g[i, j, m, n] = np.einsum("a,b,ab->", kp, kq, v)
    return s, h, g


def hamiltonian(r_angstrom):
    """
    Two-qubit Hamiltonian: qubit 0 is the spin-up electron, qubit 1 the spin-down one,
    |0> the bonding orbital and |1> the antibonding one. Exact, not a reduction: one
    electron of each spin in two orbitals is exactly two qubits. Returns the
    coefficients of I, Z0 + Z1, Z0 Z1 and X0 X1 (hartree), and the Hartree-Fock energy.
    """
    r = r_angstrom / 0.52917721067
    s, h, g = integrals(r)
    c = np.array([[1, 1], [1, -1]]) / np.sqrt(2 * (1 + np.array([1, -1]) * s[0, 1]))
    hm = c.T @ h @ c
    gm = np.einsum("pi,qj,rk,sl,pqrs->ijkl", c, c, c, c, g)
    nuclear = 1 / r
    e00 = 2 * hm[0, 0] + gm[0, 0, 0, 0] + nuclear
    e01 = hm[0, 0] + hm[1, 1] + gm[0, 0, 1, 1] + nuclear
    e11 = 2 * hm[1, 1] + gm[1, 1, 1, 1] + nuclear
    coefficients = np.array([(e00 + 2 * e01 + e11) / 4, (e00 - e11) / 4, (e00 - 2 * e01 + e11) / 4, gm[0, 1, 0, 1]])
    return coefficients, e00


def exact(coefficients):
    z, x, i2 = np.diag([1.0, -1.0]), np.array([[0, 1.0], [1, 0]]), np.eye(2)
    c0, cz, czz, cxx = coefficients
    h = c0 * np.eye(4) + cz * (np.kron(z, i2) + np.kron(i2, z)) + czz * np.kron(z, z) + cxx * np.kron(x, x)
    return float(np.linalg.eigvalsh(h)[0])


# --- pulse-level measurements ------------------------------------------------------
def circuit(theta, basis):
    body = (CIRCUITS / "vqe_h2.qasm").read_text().replace("THETA", f"{theta:.12f}")
    return body + ("h q[0];\nh q[1];\n" if basis == "X" else "")


def engines():
    return PhysicalWorkflowEngine(QubitEngine(), GateEngine(), drive_amplitudes=AMPLITUDES)


def run(job):
    """Computational-state probabilities of one full pulse-level execution."""
    theta, basis, noise = job
    path = f"vqe_{basis}_{theta:.8f}_{'n' if noise else 'u'}.qasm"
    with open(path, "w") as handle:
        handle.write(circuit(theta, basis))
    with quiet():
        result = engines().execute_workflow(NAMES, COUPLINGS, path, noise=noise, steps=10)
    probabilities = np.array([result["populations"][b][-1] for b in ("00", "01", "10", "11")])
    return probabilities, float(result["times"][-1])


def expectations(p_z, p_x):
    """<Z0 + Z1>, <Z0 Z1>, <X0 X1> from the two measurement settings."""
    return np.array([2 * (p_z[0] - p_z[3]), p_z[0] - p_z[1] - p_z[2] + p_z[3], p_x[0] - p_x[1] - p_x[2] + p_x[3]])


def sampled(p, rng):
    p = np.clip(p, 0, None)
    return rng.multinomial(SHOTS, p / p.sum()) / SHOTS


def main():
    demo = Demo("09_vqe_h2", "Demo 9: VQE for the H2 molecule at pulse level")
    q_eng = QubitEngine()
    q_eng.create_qubit("transmon", NAMES[0], {**QUBIT_PRESETS["transmon"]["typical"], "truncated_dim": 3})
    q_eng.create_qubit("device", NAMES[1], device_qubit_params((DEVICES / "fluxonium.qdl").read_text(encoding="utf-8"), 3, "fluxonium"))
    run((0.1, "Z", None))  # fill the calibration cache before the pool reads it

    c, hf = hamiltonian(0.7414)
    demo.check("Hartree-Fock energy at 0.7414 Å vs literature (Ha)", hf, -1.1167, 2e-4)
    demo.check("FCI energy at 0.7414 Å vs literature (Ha)", exact(c), -1.1373, 2e-4)

    # One Rotosolve step. E(theta) = a + b cos(theta) + c sin(theta) holds for any single
    # rotation, so three measured angles locate the minimum exactly, for every molecule.
    probes = [0.0, np.pi / 2, -np.pi / 2]
    with Pool(8) as pool:
        raw = pool.map(run, [(t, b, None) for t in probes for b in "ZX"], chunksize=1)
        probe_values = [expectations(raw[2 * k][0], raw[2 * k + 1][0]) for k in range(3)]
        bonds = np.array([0.40, 0.50, 0.60, 0.70, 0.7414, 0.80, 0.90, 1.00, 1.20, 1.40, 1.70, 2.00, 2.50])
        molecules = [hamiltonian(r) for r in bonds]
        optima = []
        for coefficients, _ in molecules:
            e = [coefficients[0] + coefficients[1:] @ v for v in probe_values]
            a = (e[1] + e[2]) / 2
            b, s = e[0] - a, (e[1] - e[2]) / 2
            optima.append(float(np.arctan2(-s, -b)))
        sweep = np.linspace(-np.pi, np.pi, 17)
        jobs = [(t, b, n) for t in optima for n in (None, NOISE) for b in "ZX"]
        jobs += [(t, b, None) for t in sweep for b in "ZX"]
        out = pool.map(run, jobs, chunksize=1)

    rng = np.random.default_rng(5)
    fine = np.linspace(0.32, 2.6, 240)
    fci_curve = np.array([exact(hamiltonian(r)[0]) for r in fine])
    hf_curve = np.array([hamiltonian(r)[1] for r in fine])
    rows, vqe, noisy, noisy_err = [], [], [], []
    for k, (r, (coefficients, hf_energy)) in enumerate(zip(bonds, molecules)):
        pz, px, nz, nx = (out[4 * k + j][0] for j in range(4))
        ideal_energy = coefficients[0] + coefficients[1:] @ expectations(pz, px)
        samples = [coefficients[0] + coefficients[1:] @ expectations(sampled(nz, rng), sampled(nx, rng)) for _ in range(40)]
        # Repeated experiments: the error bar is the spread of one 2 x 20000-shot measurement.
        one, spread = samples[0], float(np.std(samples))
        reference = exact(coefficients)
        vqe.append(ideal_energy)
        noisy.append(one)
        noisy_err.append(spread)
        rows.append({
            "R (Å)": f"{r:.4f}", "θ* (rad)": f"{optima[k]:+.4f}", "Hartree-Fock (Ha)": f"{hf_energy:.5f}",
            "FCI (Ha)": f"{reference:.5f}", "VQE pulses (Ha)": f"{ideal_energy:.5f}",
            "VQE error (kcal/mol)": f"{(ideal_energy - reference) * KCAL:+.1e}",
            "VQE + T1/T2 + shots (Ha)": f"{one:.4f} ± {spread:.4f}",
            "HF error (kcal/mol)": f"{(hf_energy - reference) * KCAL:+.1f}",
        })
    reference = np.array([exact(m[0]) for m in molecules])
    worst = np.abs(np.array(vqe) - reference).max() * KCAL
    demo.check("worst VQE error over the whole curve (kcal/mol)", worst, 0.0, 1.0)
    demo.check("VQE respects the variational principle (min error, mHa)", max(0.0, -(np.array(vqe) - reference).min() * 1e3), 0.0, 0.3)
    i_min = int(np.argmin(fci_curve))
    fit = np.polyfit(bonds[2:8], np.array(vqe)[2:8], 4)
    grid = np.linspace(0.65, 0.85, 2001)
    bond = float(grid[np.argmin(np.polyval(fit, grid))])
    demo.check("equilibrium bond length (Å)", bond, float(fine[i_min]), 0.015)
    landscape = [expectations(out[4 * len(bonds) + 2 * k][0], out[4 * len(bonds) + 2 * k + 1][0]) for k in range(len(sweep))]
    eq, stretched = list(bonds).index(0.7414), list(bonds).index(2.0)
    duration = out[0][1]

    # --- figure -------------------------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(17, 6.2), gridspec_kw={"width_ratios": [1.3, 1, 1]})
    fig.subplots_adjust(left=0.055, right=0.985, bottom=0.12, top=0.78, wspace=0.28)
    headline(fig, f"H₂ dissociation on simulated pulses, within {worst:.0e} kcal/mol of exact",
             f"Transmon + netlist fluxonium. Each energy is measured on {duration:.0f} ns pulse schedules compiled from QASM; "
             f"with T1/T2 and shot noise the errors are around 1 kcal/mol, the threshold of chemical accuracy. STO-3G.")
    ax = axes[0]
    ax.plot(fine, hf_curve, color=MUTED, label="Hartree-Fock (mean field)")
    ax.plot(fine, fci_curve, color=BLUE, label="Exact (FCI)")
    ax.plot(bonds, vqe, "o", color=ORANGE, ms=8, label="VQE on pulses")
    ax.errorbar(bonds, noisy, yerr=noisy_err, fmt="D", ms=5, color=AQUA, lw=1.2, label=f"VQE with T1/T2 and {SHOTS // 1000}k shots")
    ax.set(title="Dissociation curve", xlabel="H–H distance (Å)", ylabel="Energy (Ha)", xlim=(0.32, 2.6), ylim=(-1.17, -0.55))
    ax.legend(loc="upper right")

    ax = axes[1]
    ax.axhspan(0, 1.0, color=BLUE, alpha=0.10, lw=0)
    ax.semilogy(bonds, [(m[1] - e) * KCAL for m, e in zip(molecules, reference)], "-s", color=MUTED, label="Hartree-Fock")
    ax.semilogy(bonds, np.abs(np.array(noisy) - reference) * KCAL, "-D", ms=6, color=AQUA, label="VQE, T1/T2 + shots")
    ax.semilogy(bonds, np.abs(np.array(vqe) - reference) * KCAL, "-o", color=ORANGE, label="VQE on pulses")
    ax.text(2.55, 1.4e-5, "shaded: chemical accuracy", ha="right", va="bottom", color=INK2)
    ax.set(title="Error against FCI", xlabel="H–H distance (Å)", ylabel="|Error| (kcal/mol)", ylim=(1e-5, 1e4))
    ax.legend(loc="upper left")

    ax = axes[2]
    th = np.linspace(-np.pi, np.pi, 300)
    for index, color, label in ((eq, BLUE, "0.74 Å"), (stretched, ORANGE, "2.00 Å")):
        coefficients = molecules[index][0]
        theory = coefficients[0] + coefficients[1] * 2 * np.cos(th) + coefficients[2] + coefficients[3] * np.sin(th)
        ax.plot(th / np.pi, theory, color=color, label=f"R = {label}, ideal circuit")
        ax.plot(sweep / np.pi, [coefficients[0] + coefficients[1:] @ v for v in landscape], "o", color=color)
        ax.plot(optima[index] / np.pi, vqe[index], "*", color="#0b0b0b", ms=15)
    ax.plot([], [], "o", color=INK2, label="pulse simulation")
    ax.plot([], [], "*", color="#0b0b0b", ms=12, label="optimum found")
    ax.set(title="Energy landscape of the ansatz", xlabel="Ansatz angle θ (π)", ylabel="Energy (Ha)")
    ax.set_ylim(None, ax.get_ylim()[1] + 0.75)
    ax.legend(loc="upper right", fontsize=9)
    demo.save(fig, "h2_dissociation")
    demo.table(pd.DataFrame(rows), "h2_energies", "H₂ ground-state energy: exact, mean field, and pulse-level VQE")
    demo.finish()


if __name__ == "__main__":
    main()
    sys.exit(0)
