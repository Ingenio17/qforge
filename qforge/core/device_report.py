"""
Rendering for designed devices: schematics, spectra, sweeps and analysis reports.

This is the presentation layer of the "Design Device" workflow. It takes the
structured results produced by :mod:`qforge.core.device_engine` and turns them
into Rich tables, terminal plots and saved figures.

It is kept separate from the engine on purpose: ``device_engine`` never imports
this module, so every simulation stays usable headless, and both the interactive
CLI and the GUI can share one renderer instead of each growing their own. Every
function here takes an already-computed result; none of them run physics.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qforge.config.defaults import OUTPUT_DIRS
from qforge.core.device_netlist import DeviceNetlist, format_si

__all__ = [
    "render_netlist",
    "render_schematic",
    "render_analysis",
    "render_sweep",
    "render_format_reference",
    "plot_spectrum_terminal",
    "plot_sweep_terminal",
    "save_plots",
]

_console = Console()

ACCENT = "bright_cyan"

# Three-column glyphs for the text schematic: two capacitor plates, a coil, the
# cross of a Josephson junction and a resistor's zigzag.
#
# Two rules hold this table together. Every glyph must be exactly three columns
# wide, or the node labels stop lining up down the drawing. And none may contain
# square brackets: Rich treats "[word]" as markup, and so does the GUI console's
# own parser, which silently drops any tag it does not recognise. An earlier
# "[X]" for the junction was swallowed whole there, leaving that row three
# columns short of the rest.
_SCHEMATIC_SYMBOLS = {
    "C": "┤ ├",
    "L": "ᒥᒧᒥ",
    "JJ": "─╳─",
    "R": "╱╲╱",
}

# How a branch type is labelled in a report.
_KIND_LABELS = {
    "C": "capacitor",
    "L": "inductor",
    "JJ": "junction",
    "R": "resistor",
    "ML": "mutual L",
}


def _c(console: Console | None) -> Console:
    return console or _console


def _node_label(netlist: DeviceNetlist, index: int) -> str:
    """Human-facing name for a circuit node index."""
    if index == 0:
        return netlist.ground_labels[0] if netlist.ground_labels else "0"
    for label, mapped in netlist.node_map.items():
        if mapped == index:
            return label
    return str(index)


# ---------------------------------------------------------------------------
# Netlist and schematic
# ---------------------------------------------------------------------------


def render_netlist(netlist: DeviceNetlist, console: Console | None = None) -> None:
    """Print the parsed schematic: elements in both unit systems, plus its settings."""
    out = _c(console)
    heading = netlist.title or netlist.name
    out.print(f"\n[bold {ACCENT}]Device: {heading}[/bold {ACCENT}]")

    table = Table(title="Circuit elements", show_header=True, header_style="bold")
    table.add_column("Element", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Between", style="yellow")
    table.add_column("Energy (GHz)", justify="right", style="green")
    table.add_column("Physical value", justify="right")

    for element in netlist.elements:
        if element.kind == "ML":
            between = f"{element.nodes[0]} <-> {element.nodes[1]}"
        else:
            between = " - ".join(_node_label(netlist, index) for index in element.node_indices)

        if element.kind == "R":
            energy, physical = "-", format_si(element.resistance_ohm, "Ohm")
        else:
            energies, physicals = [], []
            for role in ("EJ", "EJ2", "EJ3", "EJ4", "EC", "EL", "EML"):
                value = element.values.get(role)
                if value is None:
                    continue
                energies.append(f"{role} {value.ghz:.6g}")
                magnitude, unit = value.physical()
                if magnitude is not None:
                    physicals.append(format_si(magnitude, unit))
            energy = "\n".join(energies)
            physical = "\n".join(physicals)
            if element.coupling_coefficient is not None:
                physical += f"\nk = {element.coupling_coefficient:.4g}"

        table.add_row(
            element.name, _KIND_LABELS.get(element.kind, element.kind), between, energy, physical
        )

    out.print(table)

    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="dim")
    facts.add_column()
    ground = ", ".join(netlist.ground_labels) if netlist.ground_labels else "none (floating)"
    facts.add_row("Nodes", f"{netlist.num_nodes} active + ground ({ground})")
    facts.add_row("Branches", str(len(netlist.branches)))
    facts.add_row("Junctions", str(len(netlist.junctions)))
    facts.add_row("Independent loops", str(netlist.num_loops))
    facts.add_row("Levels requested", str(netlist.levels))
    if netlist.params:
        facts.add_row(
            "Parameters",
            ", ".join(f"{p.name} = {p.source_text or p.value}" for p in netlist.params.values()),
        )
    if netlist.fluxes:
        facts.add_row(
            "External flux", ", ".join(f"loop {k} = {v} Phi_0" for k, v in netlist.fluxes.items())
        )
    if netlist.charges:
        facts.add_row(
            "Offset charge", ", ".join(f"n_g{k} = {v}" for k, v in netlist.charges.items())
        )
    if netlist.cutoffs:
        facts.add_row("Cutoffs", ", ".join(f"{k} = {v}" for k, v in netlist.cutoffs.items()))
    if netlist.options:
        facts.add_row("Options", ", ".join(f"{k} = {v}" for k, v in netlist.options.items()))
    out.print(facts)

    if netlist.notes:
        out.print()
        for note in netlist.notes:
            out.print(f"[yellow]  note:[/yellow] [dim]{note}[/dim]")


def render_schematic(netlist: DeviceNetlist, console: Console | None = None) -> None:
    """
    Print a text view of the circuit's connectivity.

    A netlist is a graph, so this shows it as one: every branch as an edge, then
    what each node is attached to. That is more honest, and more readable for an
    arbitrary topology, than trying to draw a schematic in characters.
    """
    out = _c(console)
    lines: list[str] = []

    width = max((len(el.name) for el in netlist.elements), default=4)
    for element in netlist.elements:
        if element.kind == "ML":
            lines.append(
                f"  {element.name:<{width}}  {element.nodes[0]} ≈≈≈ {element.nodes[1]}"
                f"   (mutual inductance, k = {element.coupling_coefficient:.4g})"
            )
            continue
        left = _node_label(netlist, element.node_indices[0])
        right = _node_label(netlist, element.node_indices[1])
        # Every glyph here is exactly three columns wide, so the node labels on
        # either side of the wire line up down the whole schematic.
        symbol = _SCHEMATIC_SYMBOLS.get(element.kind, "───")
        detail = element.value_summary().split(";")[0].strip()
        lines.append(f"  {element.name:<{width}}  {left:>6} ──{symbol}── {right:<6}   {detail}")

    connectivity: dict[str, list[str]] = {}
    for element in netlist.branches + netlist.resistors:
        for index in element.node_indices:
            label = _node_label(netlist, index)
            connectivity.setdefault(label, []).append(element.name)

    body = "\n".join(lines)
    body += "\n\n  Node connectivity\n"
    for label in sorted(connectivity, key=lambda name: (name not in netlist.ground_labels, name)):
        tag = "  (ground)" if label in netlist.ground_labels else ""
        body += f"    {label:>6}{tag}: {', '.join(connectivity[label])}\n"

    out.print(
        Panel(
            body.rstrip(),
            title=f"Schematic: {netlist.title or netlist.name}",
            border_style=ACCENT,
        )
    )


def render_format_reference(console: Console | None = None) -> None:
    """Print the netlist language reference."""
    from qforge.core.device_netlist import FORMAT_REFERENCE

    _c(console).print(Panel(FORMAT_REFERENCE, title="Device netlist format", border_style="yellow"))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def render_analysis(result: dict[str, Any], console: Console | None = None) -> None:
    """Print a full analysis result: spectrum, key metrics, coherence and caveats."""
    out = _c(console)
    circuit = result.get("circuit", {})

    out.print(f"\n[bold {ACCENT}]Analysis: {result.get('name', 'device')}[/bold {ACCENT}]")

    structure = Table.grid(padding=(0, 2))
    structure.add_column(style="dim")
    structure.add_column()
    structure.add_row("Modes", str(circuit.get("num_modes", "?")))
    structure.add_row(
        "Variables",
        f"periodic (charge) {circuit.get('periodic_vars', [])}, "
        f"extended (flux) {circuit.get('extended_vars', [])}"
        + (f", free {circuit['free_vars']}" if circuit.get("free_vars") else ""),
    )
    structure.add_row("Hilbert space", f"{circuit.get('hilbert_dim', 0):,} states")
    structure.add_row(
        "Basis cutoffs", ", ".join(f"{k} = {v}" for k, v in circuit.get("cutoffs", {}).items())
    )
    if circuit.get("external_fluxes"):
        structure.add_row(
            "External flux",
            ", ".join(f"{k} = {v:g} Phi_0" for k, v in circuit["external_fluxes"].items()),
        )
    if circuit.get("offset_charges"):
        structure.add_row(
            "Offset charge",
            ", ".join(f"{k} = {v:g}" for k, v in circuit["offset_charges"].items()),
        )
    if circuit.get("parameters"):
        structure.add_row(
            "Parameters", ", ".join(f"{k} = {v:g} GHz" for k, v in circuit["parameters"].items())
        )
    out.print(structure)

    # -- energy levels
    energies = result.get("energies_ghz", [])
    relative = result.get("relative_ghz", [])
    spacings = result.get("level_spacings_ghz", [])

    levels = Table(title="Energy levels", show_header=True, header_style="bold")
    levels.add_column("Level", justify="right", style="cyan")
    levels.add_column("E (GHz)", justify="right")
    levels.add_column("E - E0 (GHz)", justify="right", style="green")
    levels.add_column("Spacing from previous (GHz)", justify="right", style="magenta")
    for index, energy in enumerate(energies):
        spacing = f"{spacings[index - 1]:.6f}" if index > 0 else "-"
        levels.add_row(str(index), f"{energy:.6f}", f"{relative[index]:.6f}", spacing)
    out.print(levels)

    # -- headline numbers
    metrics = Table(title="Qubit metrics", show_header=True, header_style="bold")
    metrics.add_column("Quantity", style="yellow")
    metrics.add_column("Value", justify="right", style="green")
    metrics.add_row("f01 (0 -> 1 transition)", f"{result.get('f01_ghz', float('nan')):.6f} GHz")
    if result.get("f12_ghz") is not None:
        metrics.add_row("f12 (1 -> 2 transition)", f"{result['f12_ghz']:.6f} GHz")
        metrics.add_row(
            "Anharmonicity  alpha = f12 - f01", f"{result['anharmonicity_mhz']:.3f} MHz"
        )
        relative_anharmonicity = result.get("relative_anharmonicity")
        if relative_anharmonicity is not None:
            metrics.add_row("Relative anharmonicity  alpha/f01", f"{relative_anharmonicity:.4f}")
    out.print(metrics)

    if result.get("anharmonicity_note"):
        style = "dim" if result.get("anharmonicity_meaningful") else "yellow"
        out.print(f"[{style}]  {result['anharmonicity_note']}[/{style}]")
    if result.get("addressable") is False and result.get("anharmonicity_meaningful"):
        out.print(
            "[yellow]  The anharmonicity is under 1 MHz: no realistic pulse can drive "
            "0-1 without also driving 1-2, so this circuit is not addressable as a "
            "qubit.[/yellow]"
        )

    # -- basis convergence
    convergence = result.get("convergence")
    if convergence:
        if convergence.get("converged") is True:
            out.print(
                f"[green]  Basis converged:[/green] [dim]transitions move by "
                f"{convergence['max_transition_shift_mhz']:.4g} MHz when the cutoffs are "
                f"enlarged.[/dim]"
            )
        elif convergence.get("converged") is False:
            out.print(
                f"[bold red]  Not converged:[/bold red] transitions move by "
                f"{convergence['max_transition_shift_mhz']:.4g} MHz when the cutoffs are "
                f"enlarged. Raise them with .cutoff before trusting these numbers."
            )
        elif convergence.get("error"):
            out.print(f"[yellow]  Convergence check failed: {convergence['error']}[/yellow]")

    # -- drive matrix elements
    operators = (result.get("matrix_elements") or {}).get("operators") or {}
    if operators:
        drive = Table(title="Charge matrix elements", show_header=True, header_style="bold")
        drive.add_column("Operator", style="cyan")
        drive.add_column("|<0|Q|1>|", justify="right", style="green")
        drive.add_column("|<1|Q|2>|", justify="right")
        for label, data in operators.items():
            if "error" in data:
                drive.add_row(label, f"[red]{data['error']}[/red]", "-")
                continue
            g12 = data.get("g12")
            drive.add_row(label, f"{data['g01']:.4f}", f"{g12:.4f}" if g12 is not None else "-")
        out.print(drive)
        out.print(f"[dim]  {result['matrix_elements'].get('note', '')}[/dim]")

    # -- coherence
    coherence = result.get("coherence") or {}
    if coherence.get("available") and coherence.get("channels"):
        table = Table(title="Coherence estimates", show_header=True, header_style="bold")
        table.add_column("Channel", style="cyan")
        table.add_column("Mechanism", style="magenta")
        table.add_column("Time", justify="right", style="green")
        for channel, data in sorted(
            coherence["channels"].items(), key=lambda kv: kv[1].get("time_us", float("inf"))
        ):
            if "error" in data:
                continue
            table.add_row(channel, data.get("kind", ""), f"{data['time_us']:.2f} us")
        if coherence.get("t1_effective_us"):
            table.add_row(
                "T1 effective", "all T1 channels", f"{coherence['t1_effective_us']:.2f} us"
            )
        if coherence.get("t2_effective_us"):
            table.add_row(
                "T2 effective", "all T1 + Tphi channels", f"{coherence['t2_effective_us']:.2f} us"
            )
        out.print(table)
        out.print(
            f"[dim]  Order-of-magnitude estimates from scqubits' generic noise amplitudes "
            f"at T = {coherence.get('temperature_k', 0.015)} K, not measurements of a "
            f"fabricated device.[/dim]"
        )
    elif coherence.get("reason"):
        out.print(f"[dim]  Coherence estimates unavailable: {coherence['reason']}[/dim]")

    # -- resistive loading
    dissipation = result.get("dissipation") or []
    if dissipation:
        table = Table(title="Dissipative elements", show_header=True, header_style="bold")
        table.add_column("Resistor", style="cyan")
        table.add_column("Across", style="yellow")
        table.add_column("R", justify="right")
        table.add_column("C in parallel", justify="right")
        table.add_column("tau = RC", justify="right", style="green")
        table.add_column("Q at f01", justify="right", style="magenta")
        for entry in dissipation:
            table.add_row(
                entry["name"],
                " - ".join(entry["nodes"]),
                format_si(entry["resistance_ohm"], "Ohm"),
                format_si(entry.get("parallel_capacitance_f"), "F"),
                f"{entry['tau_rc_ns']:.3g} ns" if entry.get("tau_rc_ns") else "n/a",
                f"{entry['quality_factor']:.4g}" if entry.get("quality_factor") else "n/a",
            )
        out.print(table)
        out.print(
            "[dim]  A classical lumped-element estimate of how the environment loads the "
            "mode. It is not T1: resistors do not enter the circuit Hamiltonian.[/dim]"
        )

    for note in result.get("notes", []):
        out.print(f"[dim]  note: {note}[/dim]")
    for warning in result.get("warnings", []):
        out.print(f"[yellow]  warning:[/yellow] [dim]{warning}[/dim]")

    if result.get("elapsed_s"):
        out.print(f"[dim]  Completed in {result['elapsed_s']:.2f} s.[/dim]")


def render_sweep(sweep: dict[str, Any], console: Console | None = None) -> None:
    """Print a parameter sweep as a table of transition frequencies."""
    out = _c(console)
    values = sweep["values"]
    transitions = sweep["transitions_ghz"]
    levels = min(sweep["levels"], 5)

    table = Table(
        title=f"Spectrum vs {sweep['parameter']} ({sweep['unit']})",
        show_header=True,
        header_style="bold",
    )
    table.add_column(sweep["parameter"], justify="right", style="cyan")
    for index in range(1, levels):
        table.add_column(f"E{index} - E0 (GHz)", justify="right", style="green")

    for row_index, value in enumerate(values):
        row = [f"{value:.5g}"]
        for index in range(1, levels):
            row.append(f"{transitions[row_index][index]:.6f}")
        table.add_row(*row)
    out.print(table)


# ---------------------------------------------------------------------------
# Terminal plots
# ---------------------------------------------------------------------------


def plot_spectrum_terminal(result: dict[str, Any], height: int = 22) -> None:
    """Draw the energy ladder in the terminal, relative to the ground state."""
    try:
        from qforge.utils.terminal_plot import TerminalPlotter
    except Exception:
        return
    relative = result.get("relative_ghz") or []
    if len(relative) < 2:
        return
    TerminalPlotter.plot_spectrum(
        relative,
        title=f"Energy levels (relative to ground): {result.get('name', 'device')}",
        height=height,
    )


def plot_sweep_terminal(sweep: dict[str, Any], height: int = 22) -> None:
    """
    Draw a parameter sweep in the terminal.

    Uses plotext directly rather than ``TerminalPlotter.plot_time_evolution``,
    whose axes are labelled for a time series; a sweep's x-axis is a flux, a
    charge or an energy, and mislabelling it as time would be worse than plain.
    """
    try:
        import plotext as plt
    except Exception:
        return

    values = sweep["values"]
    transitions = sweep["transitions_ghz"]
    levels = min(sweep["levels"], 5)
    if len(values) < 2 or levels < 2:
        return

    plt.clear_figure()
    plt.theme("dark")
    # See qforge.utils.terminal_plot for why both of these are needed: plotext
    # otherwise caps the plot to a mis-detected terminal width, and a vertical
    # gridline collides with the right-hand border.
    plt.limit_size(False, False)
    plt.plotsize(100, height)
    for index in range(1, levels):
        plt.plot(
            list(values),
            [row[index] for row in transitions],
            label=f"E{index} - E0",
        )
    plt.title(f"Spectrum vs {sweep['parameter']}")
    plt.xlabel(f"{sweep['parameter']} ({sweep['unit']})")
    plt.ylabel("Transition (GHz)")
    plt.grid(True, False)
    plt.show()


# ---------------------------------------------------------------------------
# Saved figures
# ---------------------------------------------------------------------------


def save_plots(
    device,
    result: dict[str, Any] | None = None,
    output_dir: str | None = None,
    plots: Sequence[str] = ("levels", "potential", "wavefunctions"),
) -> dict[str, str]:
    """
    Write high-resolution figures for a device to disk.

    Args:
        device: A :class:`~qforge.core.device_engine.QuantumDevice`.
        result: An analysis result to take the spectrum from. Recomputed if omitted.
        output_dir: Where to write. Defaults to qforge's ``outputs/plots``.
        plots: Which figures to attempt. Unsupported ones are skipped rather than
            raising, since a potential plot only makes sense for one or two modes.

    Returns:
        A mapping from plot name to the file written.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination = Path(output_dir or OUTPUT_DIRS["plots"])
    destination.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    name = device.name

    if "levels" in plots:
        data = result or device.spectrum()
        relative = data["relative_ghz"]
        try:
            figure, axis = plt.subplots(figsize=(6, 7))
            for index, energy in enumerate(relative):
                axis.hlines(energy, 0.1, 0.9, linewidth=2)
                axis.text(0.92, energy, f"|{index}>  {energy:.4f} GHz", va="center", fontsize=9)
            for index in range(1, min(4, len(relative))):
                axis.annotate(
                    "",
                    xy=(0.3, relative[index]),
                    xytext=(0.3, relative[index - 1]),
                    arrowprops=dict(arrowstyle="<->", color="tab:red", alpha=0.6),
                )
                axis.text(
                    0.32,
                    (relative[index] + relative[index - 1]) / 2,
                    f"{relative[index] - relative[index - 1]:.4f}",
                    color="tab:red",
                    fontsize=8,
                )
            axis.set_xlim(0, 1.6)
            axis.set_xticks([])
            axis.set_ylabel("Energy above ground state (GHz)")
            axis.set_title(f"Energy levels: {device.netlist.title or name}")
            axis.grid(True, axis="y", alpha=0.3)
            path = destination / f"{name}_levels.png"
            figure.savefig(path, dpi=150, bbox_inches="tight")
            plt.close(figure)
            saved["levels"] = str(path)
        except Exception:
            plt.close("all")

    if "potential" in plots:
        try:
            device.circuit.plot_potential(**_potential_grids(device.circuit))
            plt.suptitle(f"Potential: {device.netlist.title or name}")
            path = destination / f"{name}_potential.png"
            plt.savefig(path, dpi=150, bbox_inches="tight")
            plt.close("all")
            saved["potential"] = str(path)
        except Exception:
            # scqubits can only draw a potential over one or two variables.
            plt.close("all")

    if "wavefunctions" in plots:
        # This scqubits version plots one state per call, so each gets its own file.
        for state in range(3):
            try:
                device.circuit.plot_wavefunction(which=state)
                plt.suptitle(f"|{state}>: {device.netlist.title or name}")
                path = destination / f"{name}_wavefunction_{state}.png"
                plt.savefig(path, dpi=150, bbox_inches="tight")
                plt.close("all")
                saved[f"wavefunction_{state}"] = str(path)
            except Exception:
                plt.close("all")

    return saved


def _potential_grids(circuit, points: int = 200) -> dict[str, Any]:
    """
    Build the ``theta_i`` arguments ``scqubits.Circuit.plot_potential`` requires.

    It wants a value for every variable in the potential, and can only draw over
    two of them at once. The first two dynamical variables get a grid across their
    full range, and any others are pinned at zero so the plot is a cut through the
    potential rather than an error.
    """
    import numpy as np

    categories = circuit.var_categories
    extended = list(categories.get("extended", []))
    periodic = list(categories.get("periodic", []))
    ranges = getattr(circuit, "discretized_phi_range", {}) or {}

    arguments: dict[str, Any] = {}
    for position, index in enumerate(extended + periodic):
        if position < 2:
            if index in extended and index in ranges:
                low, high = ranges[index]
            else:
                low, high = -np.pi, np.pi  # a periodic variable's full period
            arguments[f"θ{index}"] = np.linspace(low, high, points)
        else:
            arguments[f"θ{index}"] = 0.0
    return arguments


def save_sweep_plot(sweep: dict[str, Any], name: str, output_dir: str | None = None) -> str | None:
    """Write a parameter sweep to a PNG. Returns the path, or None if it failed."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination = Path(output_dir or OUTPUT_DIRS["plots"])
    destination.mkdir(parents=True, exist_ok=True)
    try:
        figure, axis = plt.subplots(figsize=(9, 5))
        values = sweep["values"]
        transitions = sweep["transitions_ghz"]
        for index in range(1, min(sweep["levels"], 6)):
            axis.plot(values, [row[index] for row in transitions], label=f"E{index} - E0")
        axis.set_xlabel(f"{sweep['parameter']} ({sweep['unit']})")
        axis.set_ylabel("Transition frequency (GHz)")
        axis.set_title(f"{name}: spectrum vs {sweep['parameter']}")
        axis.grid(True, alpha=0.3)
        axis.legend()
        path = destination / f"{name}_sweep_{_slug(sweep['parameter'])}.png"
        figure.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(figure)
        return str(path)
    except Exception:
        plt.close("all")
        return None


def _slug(text: str) -> str:
    """
    Make a parameter name safe for a filename.

    scqubits names external fluxes with a Greek capital phi, which is alphanumeric
    but not portable across filesystems, so this keeps ASCII only.
    """
    text = str(text).replace("Φ", "Phi").replace("φ", "phi").replace("θ", "theta")
    cleaned = "".join(char if (char.isascii() and char.isalnum()) else "_" for char in text)
    return cleaned.strip("_") or "param"
