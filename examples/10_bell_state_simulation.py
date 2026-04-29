"""
10_bell_state_simulation.py

Description:
Simulates Bell state creation (|Φ+⟩ = (|00⟩+|11⟩)/√2) via physical H + CNOT pulse
sequence on two transmon qubits, with and without DRAG pulse correction.

Terminal CLI Equivalents:
-------------------------
qforge qubit create --type transmon --name T1 --EJ 15.0 --EC 0.3
qforge qubit create --type transmon --name T2 --EJ 13.5 --EC 0.2
"""

import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from qforge.utils.terminal_plot import TerminalPlotter
from qforge import QubitEngine
from qforge.core.gate_engine import GateEngine

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# ── Presentation style constants ─────────────────────────────────────────────
TITLE_FS  = 17
LABEL_FS  = 14
TICK_FS   = 12
LEGEND_FS = 12
LW        = 2.5

C = {
    "00":   "#1565C0",  # deep blue
    "01":   "#FF8F00",  # amber
    "10":   "#2E7D32",  # dark green
    "11":   "#C62828",  # dark red  ← Bell target
    "leak": "#7B1FA2",  # purple
    "h_bg": "#E3F2FD",  # light blue  (H-gate phase region)
    "cx_bg":"#FFF3E0",  # light amber (CNOT phase region)
}


# ── Simulation helpers ────────────────────────────────────────────────────────

def _run_bell_sequence(g_eng, use_drag, best_h_dur, best_cnot_dur, w01_t1, couplings):
    """Run H (on T1) then CNOT and return stitched (times, pops, leakage)."""
    h_drives = [{
        "target": 0, "type": "H",
        "amplitude": 0.025, "frequency": w01_t1, "phase": 0.0,
        "start_time": 0.0, "end_time": best_h_dur,
    }]
    res_H = g_eng.simulate_n_qubit_dynamics(
        ["T1", "T2"], "H_Gate", best_h_dur, [], h_drives, "00", steps=50, use_drag=use_drag
    )
    res_CX = g_eng.simulate_n_qubit_dynamics(
        ["T1", "T2"], "CNOT", best_cnot_dur, couplings, [],
        res_H["final_state"], steps=200, use_drag=use_drag
    )

    times = np.concatenate((res_H["times"], res_H["times"][-1] + res_CX["times"][1:]))
    pops  = {s: np.concatenate((res_H["populations"][s], res_CX["populations"][s][1:]))
             for s in res_H["populations"]}
    leakage = np.array([
        max(0.0, 1.0 - min(sum(pops[s][i] for s in ["00","01","10","11"]), 1.0))
        for i in range(len(times))
    ])
    return times, pops, leakage


def _bell_fidelity(pops):
    """Approximate Bell fidelity as P(|00⟩) + P(|11⟩) at the final step."""
    return float(pops["00"][-1] + pops["11"][-1])


# ── Per-panel plot helper ─────────────────────────────────────────────────────

def _draw_panel(ax, times, pops, leakage, h_end, title, xlabel=True):
    """Draw a single Bell-state evolution panel on *ax*."""
    t_end = times[-1]

    # Shaded phase regions
    ax.axvspan(0,     h_end, alpha=0.18, color=C["h_bg"],  zorder=0)
    ax.axvspan(h_end, t_end, alpha=0.18, color=C["cx_bg"], zorder=0)

    # Phase divider
    ax.axvline(h_end, color="gray", lw=1.4, ls=":", alpha=0.8, zorder=1)

    # Target 0.5 reference
    ax.axhline(0.5, color="gray", lw=1.0, ls="--", alpha=0.45, zorder=1)
    ax.text(t_end * 0.99, 0.515, "ideal 0.5", ha="right", va="bottom",
            fontsize=10, color="gray", style="italic")

    # Population curves
    ax.plot(times, pops["00"],  color=C["00"],   lw=LW, label="P(|00⟩)")
    ax.plot(times, pops["10"],  color=C["10"],   lw=LW, label="P(|10⟩)",  ls="--")
    ax.plot(times, pops["11"],  color=C["11"],   lw=LW, label="P(|11⟩)  ← Bell", zorder=3)
    ax.plot(times, leakage,     color=C["leak"], lw=LW, label="Leakage",   ls=":")

    # Phase labels
    ax.text(h_end * 0.50,          0.96, "H Gate\n(superposition)",
            ha="center", va="top", fontsize=11, color="#1565C0", style="italic", zorder=4)
    ax.text(h_end + (t_end-h_end)*0.48, 0.96, "CNOT\n(entanglement)",
            ha="center", va="top", fontsize=11, color="#BF360C", style="italic", zorder=4)

    # Bell fidelity annotation
    f = _bell_fidelity(pops)
    ax.text(0.975, 0.28, f"Bell fidelity ≈ {f:.3f}",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=12, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="gray", alpha=0.92))

    ax.set_title(title, fontsize=TITLE_FS, fontweight="bold", pad=7)
    ax.set_ylabel("Population", fontsize=LABEL_FS)
    if xlabel:
        ax.set_xlabel("Time (ns)", fontsize=LABEL_FS)
    ax.set_ylim(-0.03, 1.10)
    ax.tick_params(labelsize=TICK_FS)
    ax.legend(fontsize=LEGEND_FS, loc="center right", framealpha=0.9)
    ax.grid(True, alpha=0.28)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  Example 10: Bell State Creation — H + CNOT (Physical Pulses)")
    print("=" * 62)

    q_eng = QubitEngine()
    g_eng = GateEngine()

    q_eng.create_qubit("transmon", "T1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 4})
    q_eng.create_qubit("transmon", "T2", {"EJ": 13.5, "EC": 0.2, "truncated_dim": 4})

    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.03}]

    print("\n[CALIBRATION] H gate on T1 ...")
    best_h_dur, _ = g_eng.calibrate_gate("T1", gate_type="H", parameter="duration")
    print(f"  -> H duration: {best_h_dur:.1f} ns")

    print("\n[CALIBRATION] CNOT (T1 → T2) ...")
    best_cnot_dur, _ = g_eng.calibrate_gate(
        "T1", "T2", "CNOT", "tunable_coupler", 0.03,
        parameter="duration", range_vals=np.linspace(20, 100, 20),
    )
    print(f"  -> CNOT duration: {best_cnot_dur:.1f} ns")

    evals_t1 = q_eng.get_qubit("T1").eigensys(evals_count=2)[0]
    w01_t1   = float(np.real(evals_t1[1] - evals_t1[0]))

    print("\n[THEORY]  |00⟩  →[H⊗I]→  (|00⟩+|10⟩)/√2  →[CNOT]→  (|00⟩+|11⟩)/√2  =  |Φ+⟩")

    results = {}
    for use_drag, label in [(False, "without"), (True, "with")]:
        print(f"\n[SIMULATING]  {label.upper()} DRAG ...")
        times, pops, leakage = _run_bell_sequence(
            g_eng, use_drag, best_h_dur, best_cnot_dur, w01_t1, couplings
        )
        results[label] = (times, pops, leakage)

        print(f"\n   {'Time (ns)':>10} | {'P(|00>)':>7} | {'P(|01>)':>7} | "
              f"{'P(|10>)':>7} | {'P(|11>)':>7} | {'Leak':>7}")
        print("   " + "-" * 60)
        step = max(1, len(times) // 12)
        for i in list(range(0, len(times), step)) + [len(times)-1]:
            print(f"   {times[i]:10.1f} |  {pops['00'][i]:.3f}  |  {pops['01'][i]:.3f}  |"
                  f"  {pops['10'][i]:.3f}  |  {pops['11'][i]:.3f}  |  {leakage[i]:.3f}")

        TerminalPlotter.plot_time_evolution(
            times=times,
            expectations=[pops["00"], pops["10"], pops["11"], leakage],
            labels=["P(|00>)", "P(|10>)", "P(|11>) Bell", "Leakage"],
            title=f"Bell State Evolution {label} DRAG",
            ylim=(0, 1.05),
        )

    os.makedirs(os.path.join("outputs", "plots"), exist_ok=True)

    # ── Figure 1: stacked comparison (2 rows) ────────────────────────────────
    fig1, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(14, 11), sharex=True)
    fig1.suptitle(
        "Bell State Creation: Physical Simulation on Transmon Qubits\n"
        r"$|00\rangle \;\xrightarrow{\;H \otimes I\;}\; "
        r"\tfrac{|00\rangle+|10\rangle}{\sqrt{2}} \;\xrightarrow{\;\text{CNOT}\;}\; "
        r"\tfrac{|00\rangle+|11\rangle}{\sqrt{2}} = |\Phi^+\rangle$",
        fontsize=15, fontweight="bold", y=0.99,
    )
    t_nd, p_nd, l_nd = results["without"]
    t_wd, p_wd, l_wd = results["with"]
    _draw_panel(ax_top, t_nd, p_nd, l_nd, best_h_dur, "Without DRAG Correction", xlabel=False)
    _draw_panel(ax_bot, t_wd, p_wd, l_wd, best_h_dur, "With DRAG Correction",    xlabel=True)
    fig1.tight_layout(rect=[0, 0, 1, 0.94])
    path1 = os.path.join("outputs", "plots", "10_bell_state_comparison.png")
    fig1.savefig(path1, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig1)
    print(f"\n[SAVED] Comparison plot → {path1}")

    # ── Figure 2: final-state bar chart ──────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    xlabels = ["|00⟩", "|01⟩", "|10⟩", "|11⟩"]
    states  = ["00", "01", "10", "11"]
    x       = np.arange(len(states))
    w       = 0.34

    bar_colors_nd = ["#90CAF9", "#90CAF9", "#90CAF9", "#1565C0"]
    bar_colors_wd = ["#FFCC80", "#FFCC80", "#FFCC80", "#E65100"]

    b1 = ax2.bar(x - w/2, [p_nd[s][-1] for s in states], w,
                 color=bar_colors_nd, edgecolor="white", lw=1.5, label="Without DRAG")
    b2 = ax2.bar(x + w/2, [p_wd[s][-1] for s in states], w,
                 color=bar_colors_wd, edgecolor="white", lw=1.5, label="With DRAG")

    ax2.axhline(0.5, color="black", lw=1.6, ls="--", alpha=0.55, label="Ideal Bell (0.5)")

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            if h > 0.015:
                ax2.text(bar.get_x() + bar.get_width()/2, h + 0.012,
                         f"{h:.3f}", ha="center", va="bottom",
                         fontsize=11, fontweight="bold")

    ax2.set_xticks(x)
    ax2.set_xticklabels(xlabels, fontsize=LABEL_FS)
    ax2.set_xlabel("Computational Basis State", fontsize=LABEL_FS)
    ax2.set_ylabel("Final Population",          fontsize=LABEL_FS)
    ax2.set_title(
        "Final State Populations after Bell State Creation\n"
        "Ideal: P(|00⟩) = P(|11⟩) = 0.5, all others = 0",
        fontsize=TITLE_FS, fontweight="bold",
    )
    ax2.set_ylim(0, 0.72)
    ax2.tick_params(labelsize=TICK_FS)
    ax2.legend(fontsize=LEGEND_FS)
    ax2.grid(True, axis="y", alpha=0.35)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig2.tight_layout()
    path2 = os.path.join("outputs", "plots", "10_bell_state_final_populations.png")
    fig2.savefig(path2, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig2)
    print(f"[SAVED] Final populations bar chart → {path2}")

    # ── Figure 3 & 4: individual high-res panels ─────────────────────────────
    for label, (times, pops, leakage) in results.items():
        fig3, ax3 = plt.subplots(figsize=(12, 7))
        _draw_panel(ax3, times, pops, leakage, best_h_dur,
                    f"Bell State Creation {label.title()} DRAG — Transmon Qubits")
        fig3.tight_layout()
        path3 = os.path.join("outputs", "plots", f"10_bell_state_{label}_DRAG.png")
        fig3.savefig(path3, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig3)
        print(f"[SAVED] Individual plot ({label} DRAG) → {path3}")

    print("\n[COMPLETE] All presentation figures saved to outputs/plots/")


if __name__ == "__main__":
    main()
