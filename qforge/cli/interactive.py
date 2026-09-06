"""
Interactive terminal interface for qforge.
"""

import glob
import os
import subprocess
import sys

from prompt_toolkit import prompt
from prompt_toolkit.application import Application
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from qforge import __version__
from qforge.cli.commands.example import get_examples_dir, list_example_files
from qforge.core import device_report
from qforge.core.device_engine import DeviceEngine, DeviceError
from qforge.core.device_library import (
    NETLIST_EXTENSIONS,
    list_templates,
    write_template,
)
from qforge.core.device_netlist import NetlistError
from qforge.core.error_correction_engine import ErrorCorrectionEngine
from qforge.core.gate_engine import GateEngine
from qforge.core.qubit_engine import QubitEngine
from qforge.core.stabilizer_codes import REPETITION_3, SHOR_9, STEANE_7
from qforge.core.workflow_engine import PhysicalWorkflowEngine

console = Console()
engine = QubitEngine()

# Created on first use rather than at import: building it touches the filesystem,
# and most sessions never open the device designer.
_device_engine = None


def _devices():
    """The session's DeviceEngine, created on first use."""
    global _device_engine
    if _device_engine is None:
        _device_engine = DeviceEngine()
    return _device_engine

ACCENT = "bright_cyan"

MENU_STYLE = PTStyle.from_dict(
    {
        "title": "bold ansibrightcyan",
        "subtitle": "ansibrightblack italic",
        "header": "bold ansibrightmagenta",
        "selected": "bold ansibrightcyan",
        "item": "",
        "desc": "ansibrightblack italic",
        "hint": "ansibrightblack",
    }
)


# ---------------------------------------------------------------------------
# Low-level UI helpers
# ---------------------------------------------------------------------------


class _MenuUnavailableError(Exception):
    """Raised when the arrow-key menu can't run in this terminal."""


def _arrow_menu(sections, title=None, subtitle=None):
    """
    A small inline, arrow-key driven picker built on prompt_toolkit.

    `sections` is a list of (header, items) where items is a list of
    (key, label, description) tuples. Returns the chosen key, or None if
    the user cancelled (q / Esc / Ctrl-C).

    Raises `_MenuUnavailableError` if this terminal can't host a prompt_toolkit
    Application at all (e.g. output isn't a real console), so callers can
    fall back to a plain numbered prompt.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise _MenuUnavailableError("not an interactive terminal")

    rows = []  # ("header", text) | ("item", key, label, desc)
    item_rows = []  # indices into `rows` that are selectable
    for header, items in sections:
        if header:
            rows.append(("header", header))
        for key, label, desc in items:
            rows.append(("item", key, label, desc))
            item_rows.append(len(rows) - 1)

    if not item_rows:
        return None

    cursor = [0]  # index into item_rows

    def move(delta):
        cursor[0] = (cursor[0] + delta) % len(item_rows)

    def get_text():
        out = []
        if title:
            out.append(("class:title", f" {title}\n"))
        if subtitle:
            out.append(("class:subtitle", f" {subtitle}\n"))
        out.append(("", "\n"))
        selected_desc = ""
        for i, row in enumerate(rows):
            if row[0] == "header":
                out.append(("class:header", f" {row[1]}\n"))
            else:
                _, key, label, desc = row
                if item_rows[cursor[0]] == i:
                    out.append(("class:selected", f"   > {label}\n"))
                    selected_desc = desc or ""
                else:
                    out.append(("class:item", f"     {label}\n"))
        out.append(("class:desc", f"\n     {selected_desc}\n" if selected_desc else "\n"))
        out.append(("class:hint", "\n  up/down move    enter select    q cancel\n"))
        return out

    n_lines = 4 + len(rows) + sum(1 for h, _ in sections if h) + 3

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        move(-1)

    @kb.add("down")
    @kb.add("j")
    def _(event):
        move(1)

    @kb.add("enter")
    def _(event):
        row = rows[item_rows[cursor[0]]]
        event.app.exit(result=row[1])

    @kb.add("c-c")
    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    control = FormattedTextControl(get_text, focusable=True)
    window = Window(content=control, height=Dimension(preferred=n_lines, max=n_lines))
    app = Application(
        layout=Layout(window),
        key_bindings=kb,
        style=MENU_STYLE,
        full_screen=False,
        mouse_support=False,
    )

    try:
        return app.run()
    except _MenuUnavailableError:
        raise
    except Exception as exc:
        raise _MenuUnavailableError(str(exc))


def _text_menu(sections, title=None):
    """Plain numbered-list fallback for terminals that can't render the arrow menu."""
    if title:
        console.print(f"\n[bold]{title}[/bold]")

    numbered = []
    for header, items in sections:
        if header:
            console.print(f"[dim]{header}[/dim]")
        for key, label, _desc in items:
            numbered.append((key, label))
            console.print(f"  {len(numbered)}. {label}")

    words = [label for _key, label in numbered] + [key for key, _label in numbered]
    choice = prompt(
        "\n> Choice (number or name): ",
        completer=WordCompleter(words, ignore_case=True, sentence=True),
    ).strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(numbered):
            return numbered[idx][0]
        return None

    choice_l = choice.lower()
    for key, label in numbered:
        if choice_l == key.lower() or choice_l == label.lower():
            return key
    return None


def _choose(sections, title=None, subtitle=None):
    """Try the arrow-key menu, falling back to a numbered prompt if the terminal can't host it."""
    try:
        return _arrow_menu(sections, title=title, subtitle=subtitle)
    except _MenuUnavailableError:
        return _text_menu(sections, title=title)


def _flat_choose(items, title=None, subtitle=None):
    """Convenience wrapper for a single, header-less list of (key, label, desc)."""
    return _choose([(None, items)], title=title, subtitle=subtitle)


def _pause():
    console.print()
    console.input("[dim]Press enter to return to the menu...[/dim]")


def _section(title):
    console.print(f"\n[bold {ACCENT}]{title}[/bold {ACCENT}]")


def _qubit_names():
    return [q["name"] for q in engine.list_qubits()]


def _completer(words):
    return WordCompleter(words, ignore_case=True, sentence=True)


def _prompt_params(defaults):
    """Ask for each parameter in `defaults`, keeping its default on an empty reply."""
    params = {}
    for key, default_val in defaults.items():
        val_str = prompt(f"  {key} [{default_val}]: ").strip()
        if not val_str:
            params[key] = default_val
            continue
        try:
            if isinstance(default_val, bool):
                params[key] = val_str.lower() in ("y", "yes", "true", "1")
            elif isinstance(default_val, int):
                params[key] = int(val_str)
            elif isinstance(default_val, float):
                params[key] = float(val_str)
            else:
                params[key] = val_str
        except ValueError:
            console.print(
                f"[yellow]Couldn't parse '{val_str}' for {key}, keeping default.[/yellow]"
            )
            params[key] = default_val
    return params


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _menu_sections():
    return [
        (
            "QUBITS",
            [
                (
                    "create",
                    "Create a qubit",
                    "Define a new physical qubit from EJ/EC/EL and friends",
                ),
                ("list", "List qubits", "Show every qubit registered in this session"),
                ("analyze", "Analyze a qubit", "Spectrum, anharmonicity, coherence estimates"),
                ("compare", "Compare qubits", "Side-by-side metrics across qubits"),
                ("delete", "Delete a qubit", "Remove a qubit and its cached calibrations"),
            ],
        ),
        (
            "GATES & CIRCUITS",
            [
                (
                    "gate",
                    "Simulate a gate",
                    "Drive a 1- or 2-qubit gate and watch populations evolve",
                ),
                ("multi", "Analyze multi-qubit gates", "Compare coupling types for CNOT / CZ"),
                ("circuit", "Build a circuit", "Multi-gate circuit construction"),
            ],
        ),
        (
            "WORKFLOWS",
            [
                (
                    "workflow",
                    "Run full workflow",
                    "QASM to physical execution, with optional error correction",
                ),
            ],
        ),
        (
            "DEVICE DESIGN",
            [
                (
                    "device",
                    "Design a device",
                    "Build a circuit from C, L, JJ and R, then solve for its energy levels",
                ),
            ],
        ),
        (
            "HARDWARE",
            [
                ("hardware", "Design hardware", "Chip layout from qubit and coupling choices"),
            ],
        ),
        (
            "LEARN",
            [
                ("example", "Run an example", "Execute a bundled example script"),
                ("help", "Help", "Guide to interactive mode"),
            ],
        ),
        (
            None,
            [
                ("exit", "Exit", "Quit qforge interactive mode"),
            ],
        ),
    ]


def _print_banner():
    console.print(
        Panel.fit(
            f"[bold {ACCENT}]qforge[/bold {ACCENT}] [dim]v{__version__}[/dim] — interactive mode\n\n"
            "A guided, physics-first path from qubit parameters to calibrated gates,\n"
            "circuits, and error correction. Built for quick prototyping in the terminal.\n\n"
            "[yellow]Tip:[/yellow] use the arrow keys and enter to pick an option, or type its name.",
            border_style=ACCENT,
        )
    )
    console.print(
        "[dim]Powered by scqubits and QuTiP. Please cite these libraries in your research.[/dim]"
    )


HANDLERS = {}


def run_interactive():
    """Run qforge in interactive mode with guided workflows."""
    _print_banner()

    while True:
        try:
            engine.load_session()
            n_qubits = len(_qubit_names())
            subtitle = (
                f"{n_qubits} qubit(s) registered"
                if n_qubits
                else "no qubits yet - start with 'Create a qubit'"
            )
            choice = _choose(
                _menu_sections(), title="What would you like to do?", subtitle=subtitle
            )

            if choice is None or choice == "exit":
                console.print(f"\n[{ACCENT}]Thanks for using qforge. Goodbye![/{ACCENT}]\n")
                break

            handler = HANDLERS.get(choice)
            if handler is None:
                console.print(f"[red]Unknown option: {choice}[/red]")
                continue

            handler()

        except (KeyboardInterrupt, EOFError):
            console.print(f"\n\n[{ACCENT}]Exiting qforge. Goodbye![/{ACCENT}]\n")
            break


# ---------------------------------------------------------------------------
# Wizards: qubits
# ---------------------------------------------------------------------------


def _wizard_create_qubit():
    _section("Create a qubit")

    from qforge.config.defaults import QUBIT_PRESETS

    type_items = []
    for qtype, presets in QUBIT_PRESETS.items():
        info = presets.get("_info", {})
        bits = [b for b in (info.get("freq"), info.get("best_for")) if b]
        type_items.append((qtype, qtype.capitalize(), "  ·  ".join(bits)))

    qubit_type = _flat_choose(type_items, title="Choose a qubit type")
    if not qubit_type:
        return

    preset_keys = [k for k in QUBIT_PRESETS[qubit_type] if k != "_info"]
    preset_items = [(k, k.replace("_", " ").title(), "") for k in preset_keys]
    preset_items.append(("custom", "Custom", "Enter every parameter yourself"))
    preset = _flat_choose(preset_items, title=f"Starting point for this {qubit_type}")
    if not preset:
        return

    name = prompt("Name for this qubit: ").strip()
    if not name:
        return

    if preset == "custom":
        defaults = QUBIT_PRESETS[qubit_type].get("typical", {})
        console.print(f"\n[yellow]Configuring {qubit_type} (blank keeps the default):[/yellow]")
        params = _prompt_params(defaults)
    else:
        params = QUBIT_PRESETS[qubit_type][preset].copy()
        table = Table(
            title=f"{preset.replace('_', ' ').title()} {qubit_type} parameters", show_header=True
        )
        table.add_column("Parameter", style="yellow")
        table.add_column("Value", style="green")
        for key, value in params.items():
            table.add_row(key, str(value))
        console.print(table)
        if not Confirm.ask("Use these values as-is?", default=True):
            console.print(
                f"\n[yellow]Editing {qubit_type} parameters (blank keeps the shown value):[/yellow]"
            )
            params = _prompt_params(params)

    console.print(f"\n[green]Creating {qubit_type} '{name}'...[/green]")

    cmd_str = f"qforge qubit create -t {qubit_type} -n {name}"
    for k, v in params.items():
        cmd_str += f" --{k} {v}"
    console.print(f"[dim]Equivalent command: {cmd_str}[/dim]")

    from qforge.cli.commands.qubit import _create_qubit

    _create_qubit(qubit_type, name, params)

    console.print("\n[bold green]Qubit created successfully.[/bold green]")
    _pause()


def _wizard_list_qubits():
    _section("Registered qubits")
    from qforge.cli.commands.qubit import list_qubits

    try:
        list_qubits.callback()
    except Exception as e:
        console.print(f"[red]Error listing qubits: {e}[/red]")
    _pause()


def _wizard_analyze_qubit():
    _section("Analyze a qubit")
    from qforge.cli.commands.qubit import analyze

    qubits = _qubit_names()
    if not qubits:
        console.print("[yellow]No qubits found. Create one first.[/yellow]")
        _pause()
        return

    name = prompt("Qubit name: ", completer=_completer(qubits)).strip()
    if not name:
        return

    do_plot = Confirm.ask("Generate plots?", default=True)
    do_coherence = Confirm.ask("Estimate coherence?", default=True)
    do_relative = Confirm.ask("Display energies relative to the ground state?", default=False)

    try:
        analyze.callback(name=name, plot=do_plot, coherence=do_coherence, relative=do_relative)
    except Exception as e:
        if "Abort" not in str(type(e)):
            console.print(f"[red]Error: {e}[/red]")

    _pause()


def _wizard_delete_qubit():
    _section("Delete a qubit")
    from qforge.cli.commands.qubit import delete

    qubits = _qubit_names()
    if not qubits:
        console.print("[yellow]No qubits to delete.[/yellow]")
        _pause()
        return

    name = prompt("Qubit name to delete: ", completer=_completer(qubits)).strip()
    if not name:
        return

    if not Confirm.ask(f"Delete '{name}'? This cannot be undone", default=False):
        return

    try:
        delete.callback(name=name)

        g_eng = GateEngine()
        stale = [key for key in GateEngine._calib_cache if name in (key[0], key[1])]
        if stale:
            for key in stale:
                del GateEngine._calib_cache[key]
            g_eng._save_cache_to_disk()
            console.print(
                f"[dim green]Cleared {len(stale)} cached calibration(s) involving '{name}'.[/dim green]"
            )
    except Exception as e:
        if "Abort" not in str(type(e)):
            console.print(f"[red]Error: {e}[/red]")

    _pause()


def _wizard_compare_qubits():
    _section("Compare qubits")
    from qforge.cli.commands.compare import compare_qubits

    qubits = _qubit_names()
    if len(qubits) < 2:
        console.print("[yellow]Need at least 2 qubits to compare.[/yellow]")
        _pause()
        return

    console.print("[dim]Tab-complete qubit names; separate several with commas.[/dim]")
    qubit_str = prompt("Qubits to compare: ", completer=_completer(qubits)).strip()
    if not qubit_str:
        return

    metric_items = [
        ("all", "All metrics", ""),
        ("frequency", "Frequency", ""),
        ("anharmonicity", "Anharmonicity", ""),
        ("t1", "T1", ""),
        ("t2", "T2", ""),
    ]
    metrics = _flat_choose(metric_items, title="Which metrics?") or "all"

    try:
        compare_qubits.callback(
            qubits=qubit_str, metrics=metrics, gates=None, tag=None, output=None
        )
    except Exception as e:
        if "Abort" not in str(type(e)):
            console.print(f"[red]Error: {e}[/red]")

    _pause()


# ---------------------------------------------------------------------------
# Wizards: gates
# ---------------------------------------------------------------------------


def _wizard_simulate_gate():
    _section("Simulate a gate")

    qubits = _qubit_names()
    if not qubits:
        console.print("[yellow]No qubits found. Create one first.[/yellow]")
        _pause()
        return

    gate_items = [
        ("X", "X  (bit flip)", "Single-qubit, pi rotation"),
        ("Y", "Y", "Single-qubit, pi rotation"),
        ("Z", "Z  (phase flip)", "Single-qubit, pi rotation"),
        ("H", "H  (Hadamard)", "Single-qubit, pi/2 rotation"),
        ("CNOT", "CNOT", "Two-qubit, controlled bit flip"),
        ("CZ", "CZ", "Two-qubit, controlled phase"),
    ]
    gate = _flat_choose(gate_items, title="Which gate?")
    if not gate:
        return

    qubit = prompt("Qubit (control, for a two-qubit gate): ", completer=_completer(qubits)).strip()
    if not qubit:
        return

    if gate in ("CNOT", "CZ"):
        remaining = [q for q in qubits if q != qubit]
        if not remaining:
            console.print("[yellow]Need a second qubit for a two-qubit gate.[/yellow]")
            _pause()
            return

        qubit2 = prompt("Target qubit: ", completer=_completer(remaining)).strip()
        if not qubit2:
            return

        duration = Prompt.ask("Duration (ns)", default="50.0")

        coupling_items = [
            ("capacitive", "Capacitive", "g(a1_dag a2 + a1 a2_dag), exchange-like"),
            ("inductive", "Inductive / ZZ", "g * n1 * n2, dispersive / phase-type"),
            (
                "tunable_coupler",
                "Tunable coupler",
                "Time-dependent g_max f(t)(a1_dag a2 + a1 a2_dag)",
            ),
        ]
        c_type = _flat_choose(coupling_items, title="Coupling type") or "tunable_coupler"
        g_val = Prompt.ask("Coupling strength (GHz)", default="0.05")

        console.print(
            f"\n[green]Simulating {gate} on {qubit} -> {qubit2} ({c_type}, g={g_val} GHz)...[/green]"
        )

        ge = GateEngine()
        try:
            with console.status("[cyan]Running two-qubit dynamics...[/cyan]"):
                res = ge.simulate_two_qubit_dynamics(
                    qubit,
                    qubit2,
                    gate,
                    coupling_type=c_type,
                    coupling_strength=float(g_val),
                    duration=float(duration),
                    steps=100,
                )

            times = res["times"]
            pops = res["populations"]

            console.print("\n[bold]Final populations[/bold]")
            for state, p_arr in pops.items():
                console.print(f"  |{state}>: {p_arr[-1]:.4f}")

            from qforge.utils.terminal_plot import TerminalPlotter

            data = [pops[k] for k in ["00", "01", "10", "11"]]
            labels = ["|00>", "|01>", "|10>", "|11>"]
            TerminalPlotter.plot_time_evolution(times, data, labels, title=f"{gate} Dynamics")

        except Exception as e:
            console.print(f"[red]Simulation error: {e}[/red]")

    else:
        duration = Prompt.ask("Duration (ns)", default="20.0")

        noise_items = [
            ("none", "None", "Ideal, coherent evolution"),
            ("realistic", "Realistic", "Includes T1/T2-type decoherence"),
        ]
        noise = _flat_choose(noise_items, title="Noise model") or "none"

        console.print(f"\n[green]Simulating {gate} on {qubit}...[/green]")

        from qforge.cli.commands.gate import simulate

        try:
            simulate.callback(
                qubit=qubit, gate=gate, duration=float(duration), noise=noise, save=False, steps=100
            )

            if Confirm.ask("\nSave a high-resolution plot to file?", default=False):
                console.print("[dim]Re-running to save the plot...[/dim]")
                simulate.callback(
                    qubit=qubit,
                    gate=gate,
                    duration=float(duration),
                    noise=noise,
                    save=True,
                    steps=100,
                )

        except Exception as e:
            if "Abort" not in str(type(e)):
                console.print(f"[red]Error: {e}[/red]")

    _pause()


def _wizard_analyze_multi_qubit():
    _section("Analyze multi-qubit gates")
    from rich.table import Table as RichTable

    gate_engine = GateEngine()
    qubits = _qubit_names()
    if len(qubits) < 2:
        console.print("[yellow]Need at least 2 qubits for multi-qubit analysis.[/yellow]")
        _pause()
        return

    q1 = prompt("Control qubit: ", completer=_completer(qubits)).strip()
    if not q1:
        return

    remaining = [q for q in qubits if q != q1]
    q2 = prompt("Target qubit: ", completer=_completer(remaining)).strip()
    if not q2:
        return

    gate = _flat_choose([("CNOT", "CNOT", ""), ("CZ", "CZ", "")], title="Gate to compare") or "CNOT"

    console.print(f"\n[green]Comparing coupling types for {gate} on {q1} -> {q2}...[/green]")

    try:
        results = gate_engine.compare_couplings(q1, q2, gate=gate)

        table = RichTable(title=f"Coupling comparison: {gate} ({q1} -> {q2})")
        table.add_column("Coupling type", style="cyan")
        table.add_column("Target population (fidelity proxy)", justify="right", style="green")
        if gate == "CZ":
            table.add_column("Phase (pi)", justify="right", style="magenta")

        for coupling, metrics in results.items():
            pop = metrics.get("population", 0.0)
            phase = metrics.get("phase", None)
            row = [coupling, f"{pop:.4f}"]
            if gate == "CZ":
                row.append(f"{phase:.4f}" if phase is not None else "n/a")
            table.add_row(*row)

        console.print(table)

        if gate == "CNOT":
            console.print(
                "[dim]Note: target population is |11>, i.e. the bit-flip success probability.[/dim]"
            )
        else:
            console.print(
                "[dim]Note: target population is |11> population retention (leakage shows up as a drop here).[/dim]"
            )

    except Exception as e:
        console.print(f"[red]Error during analysis: {e}[/red]")

    _pause()


def _wizard_build_circuit():
    _section("Build a circuit")
    console.print(
        "[yellow]A dedicated circuit builder isn't wired up yet in interactive mode.[/yellow]\n"
        "[dim]For a full QASM-to-physical circuit run today, use 'Run full workflow' from the "
        "main menu, or `qforge circuit build --help` on the command line.[/dim]"
    )
    _pause()


# ---------------------------------------------------------------------------
# Wizards: device design (netlist -> quantized circuit -> spectrum)
# ---------------------------------------------------------------------------


def _device_names():
    return [entry["name"] for entry in _devices().list_devices()]


def _netlist_completer():
    """Complete netlist paths from the working directory and any examples folder."""
    found = []
    search_dirs = [
        os.getcwd(),
        os.path.join(os.getcwd(), "netlists"),
        os.path.join(os.getcwd(), "device_files"),
    ]
    examples_dir = get_examples_dir()
    if examples_dir:
        search_dirs += [
            examples_dir,
            os.path.join(examples_dir, "netlists"),
            os.path.join(examples_dir, "device_files"),
        ]
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for extension in NETLIST_EXTENSIONS:
            found.extend(
                os.path.relpath(path) for path in glob.glob(os.path.join(directory, f"*{extension}"))
            )
    return WordCompleter(sorted(set(found)), ignore_case=True)


def _pick_device(title="Which device?"):
    """Choose one registered device, or None if there are none or the user backs out."""
    names = _device_names()
    if not names:
        console.print(
            "[yellow]No devices yet. Load a netlist file or start from a template first.[/yellow]"
        )
        return None
    items = []
    for entry in _devices().list_devices():
        detail = (
            f"{entry['num_nodes']} node(s), {entry['num_branches']} branches, "
            f"{entry['num_junctions']} junction(s), {entry['num_loops']} loop(s)"
        )
        items.append((entry["name"], entry["title"] or entry["name"], detail))
    key = _flat_choose(items, title=title)
    if not key:
        return None
    try:
        return _devices().get_device(key)
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        return None


def _register_netlist(source_path=None, source_text=None, name=None):
    """Parse a netlist, register it, and show what was understood."""
    try:
        with console.status("[cyan]Parsing netlist...[/cyan]"):
            if source_path:
                device = _devices().create_device_from_file(
                    source_path, name=name, overwrite=True
                )
            else:
                device = _devices().create_device(source_text, name=name, overwrite=True)
    except NetlistError as exc:
        console.print(f"\n[bold red]Netlist error[/bold red]\n[red]{exc}[/red]")
        console.print(
            "[dim]Pick 'Netlist format reference' from the device menu for the full syntax.[/dim]"
        )
        return None
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        return None

    device_report.render_netlist(device.netlist, console=console)
    device_report.render_schematic(device.netlist, console=console)
    console.print(f"[green]Registered device '{device.name}'.[/green]")
    return device


def _analyze_device(device):
    """Quantize a device, print the full report, and offer plots."""
    console.print(
        f"\n[green]Quantizing '{device.name}' and solving for its energy levels...[/green]"
    )
    try:
        with console.status("[cyan]Building the circuit Hamiltonian...[/cyan]"):
            hilbert_dim = device.hilbert_dim
        console.print(
            f"[dim]Truncated Hilbert space: {hilbert_dim:,} states.[/dim]"
        )
        with console.status("[cyan]Diagonalizing and analyzing...[/cyan]"):
            result = device.analyze()
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        return None
    except Exception as exc:
        console.print(f"[red]Analysis failed: {type(exc).__name__}: {exc}[/red]")
        return None

    device_report.render_analysis(result, console=console)
    device_report.plot_spectrum_terminal(result)

    if Confirm.ask("\nSave high-resolution plots to file?", default=False):
        with console.status("[cyan]Rendering figures...[/cyan]"):
            saved = device_report.save_plots(device, result)
        if saved:
            for kind, path in saved.items():
                console.print(f"[green]  {kind}:[/green] [dim]{path}[/dim]")
        else:
            console.print("[yellow]  No figures could be produced for this circuit.[/yellow]")

    if Confirm.ask("Save the analysis as JSON?", default=False):
        path = _devices().save_result(device.name, result)
        console.print(f"[green]  Written to[/green] [dim]{path}[/dim]")

    return result


def _wizard_device_from_file():
    console.print(
        "\n[dim]A device netlist describes a circuit as capacitors, inductors, "
        "Josephson junctions, resistors and a ground node.[/dim]"
    )
    path = (
        prompt("Path to the netlist file: ", completer=_netlist_completer()).strip().strip("\"'")
    )
    if not path:
        return
    if not os.path.exists(path):
        console.print(f"[red]No such file: {path}[/red]")
        return

    device = _register_netlist(source_path=path)
    if device and Confirm.ask("\nAnalyze it now?", default=True):
        _analyze_device(device)


def _wizard_device_from_template():
    items = [
        (template.key, template.title, f"{template.description}  [{template.cost}]")
        for template in list_templates()
    ]
    key = _flat_choose(items, title="Start from which circuit?")
    if not key:
        return

    default_path = f"{key}.qdl"
    path = Prompt.ask("Save the netlist as", default=default_path).strip().strip("\"'")
    if not path:
        return
    if os.path.exists(path) and not Confirm.ask(f"'{path}' exists. Overwrite?", default=False):
        return

    written = write_template(key, path=path)
    console.print(f"[green]Wrote {written}.[/green] [dim]Edit it and reload to try variations.[/dim]")

    device = _register_netlist(source_path=written)
    if device and Confirm.ask("\nAnalyze it now?", default=True):
        _analyze_device(device)


def _wizard_device_list():
    entries = _devices().list_devices()
    if not entries:
        console.print("[yellow]No devices designed yet.[/yellow]")
        return
    table = Table(title="Designed devices", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Title", style="yellow")
    table.add_column("Nodes", justify="right")
    table.add_column("Branches", justify="right")
    table.add_column("Junctions", justify="right")
    table.add_column("Loops", justify="right")
    table.add_column("Source", style="dim")
    for entry in entries:
        table.add_row(
            entry["name"],
            entry["title"] or "-",
            str(entry["num_nodes"]),
            str(entry["num_branches"]),
            str(entry["num_junctions"]),
            str(entry["num_loops"]),
            entry["source_path"] or "(inline)",
        )
    console.print(table)


def _wizard_device_sweep():
    device = _pick_device("Sweep which device?")
    if device is None:
        return

    try:
        with console.status("[cyan]Building the circuit...[/cyan]"):
            knobs = device.sweepable_parameters()
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    if not knobs:
        console.print(
            "[yellow]This circuit has nothing to sweep: no external flux, no offset "
            "charge, and no named .param values.[/yellow]\n"
            "[dim]Add a '.param NAME = value' to the netlist and reference it from an "
            "element to make that quantity sweepable.[/dim]"
        )
        return

    flux_names = device.external_flux_names()
    charge_names = device.offset_charge_names()
    items = []
    for name, value in knobs.items():
        if name in flux_names:
            kind = "external flux, in flux quanta"
        elif name in charge_names:
            kind = "offset charge, in Cooper pairs"
        else:
            kind = "branch energy, in GHz"
        items.append((name, name, f"{kind}  ·  currently {value:g}"))
    parameter = _flat_choose(items, title="Sweep which parameter?")
    if not parameter:
        return

    current = knobs[parameter]
    is_flux = parameter in flux_names
    is_charge = parameter in charge_names
    if is_flux:
        low_default, high_default = "0.0", "1.0"
    elif is_charge:
        low_default, high_default = "-1.0", "1.0"
    else:
        low_default = f"{current * 0.5:g}"
        high_default = f"{current * 1.5:g}"

    try:
        low = float(Prompt.ask("  From", default=low_default))
        high = float(Prompt.ask("  To", default=high_default))
        points = int(Prompt.ask("  Points", default="21"))
        levels = int(Prompt.ask("  Levels to track", default="4"))
    except ValueError:
        console.print("[red]Those need to be numbers.[/red]")
        return
    if points < 2:
        console.print("[red]A sweep needs at least 2 points.[/red]")
        return

    import numpy as np

    console.print(f"\n[green]Sweeping {parameter} over {points} points...[/green]")
    try:
        with console.status("[cyan]Re-diagonalizing at each point...[/cyan]"):
            sweep = device.sweep(parameter, np.linspace(low, high, points), levels=levels)
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    device_report.render_sweep(sweep, console=console)
    device_report.plot_sweep_terminal(sweep)

    if Confirm.ask("\nSave the sweep as a plot?", default=False):
        path = device_report.save_sweep_plot(sweep, device.name)
        if path:
            console.print(f"[green]  Written to[/green] [dim]{path}[/dim]")
        else:
            console.print("[yellow]  Could not render the figure.[/yellow]")


def _wizard_device_delete():
    device = _pick_device("Delete which device?")
    if device is None:
        return
    if not Confirm.ask(f"Delete '{device.name}'?", default=False):
        return
    try:
        _devices().delete_device(device.name)
        console.print(f"[green]Deleted '{device.name}'.[/green]")
        console.print("[dim]The netlist file on disk, if any, was left alone.[/dim]")
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")


def _device_menu_sections():
    return [
        (
            "NEW DEVICE",
            [
                ("template", "Start from a template", "Transmon, fluxonium, flux qubit, zero-pi..."),
                ("file", "Load a netlist file", "Read a circuit you have written yourself"),
                ("format", "Netlist format reference", "The full syntax, with examples"),
            ],
        ),
        (
            "DESIGNED DEVICES",
            [
                ("list", "List devices", "Everything designed in this session"),
                ("analyze", "Analyze a device", "Energy levels, anharmonicity, coherence"),
                ("schematic", "Show the schematic", "Elements, values and connectivity"),
                ("sweep", "Sweep a parameter", "Flux, offset charge or a named .param"),
                ("export", "Export a netlist", "Write a device's netlist back out to a file"),
                ("delete", "Delete a device", "Remove it from the session"),
            ],
        ),
        (
            None,
            [("back", "Back to the main menu", "")],
        ),
    ]


def _wizard_device_schematic():
    device = _pick_device("Show which device?")
    if device is None:
        return
    device_report.render_netlist(device.netlist, console=console)
    device_report.render_schematic(device.netlist, console=console)
    if Confirm.ask("\nShow the circuit description handed to scqubits?", default=False):
        console.print(Panel(device.scqubits_yaml, title="scqubits circuit", border_style="dim"))


def _wizard_device_export():
    device = _pick_device("Export which device?")
    if device is None:
        return
    path = Prompt.ask("Write the netlist to", default=f"{device.name}.qdl").strip().strip("\"'")
    if not path:
        return
    if os.path.exists(path) and not Confirm.ask(f"'{path}' exists. Overwrite?", default=False):
        return
    written = _devices().save_netlist(device.name, path)
    console.print(f"[green]Wrote {written}.[/green]")


def _wizard_design_device():
    _section("Design a device")
    console.print(
        "[dim]Describe a circuit in an ngspice-style netlist, and qforge quantizes it: "
        "energy levels, transition frequencies, anharmonicity and coherence for any "
        "topology you can build out of C, L, JJ and R.[/dim]"
    )

    def _analyze_chosen():
        device = _pick_device("Analyze which device?")
        if device is not None:
            _analyze_device(device)

    handlers = {
        "template": _wizard_device_from_template,
        "file": _wizard_device_from_file,
        "format": lambda: device_report.render_format_reference(console=console),
        "list": _wizard_device_list,
        "analyze": _analyze_chosen,
        "schematic": _wizard_device_schematic,
        "sweep": _wizard_device_sweep,
        "export": _wizard_device_export,
        "delete": _wizard_device_delete,
    }

    while True:
        count = len(_device_names())
        subtitle = (
            f"{count} device(s) designed"
            if count
            else "nothing designed yet - try 'Start from a template'"
        )
        choice = _choose(_device_menu_sections(), title="Device design", subtitle=subtitle)
        if choice is None or choice == "back":
            return

        handler = handlers.get(choice)
        if handler is None:
            console.print(f"[red]Unknown option: {choice}[/red]")
            continue

        handler()
        _pause()


def _wizard_design_hardware():
    _section("Design hardware")
    console.print(
        "[yellow]Hardware layout design isn't wired up yet in interactive mode.[/yellow]\n"
        "[dim]Use `qforge hardware design --help` on the command line to track progress on this.[/dim]"
    )
    _pause()


# ---------------------------------------------------------------------------
# Wizards: examples
# ---------------------------------------------------------------------------


def _wizard_run_example():
    _section("Run an example")

    examples = list_example_files()
    if not examples:
        console.print("[yellow]No examples found.[/yellow]")
        _pause()
        return

    examples_dir = get_examples_dir()
    items = []
    for ex in examples:
        desc = ""
        try:
            with open(os.path.join(examples_dir, ex), encoding="utf-8") as f:
                content = f.read()
            if '"""' in content:
                desc = content.split('"""')[1].strip().split("\n")[0]
        except Exception:
            pass
        items.append((ex, ex.replace(".py", ""), desc))

    name = _flat_choose(items, title="Choose an example to run")
    if not name:
        return

    script_path = os.path.join(examples_dir, name)
    if not os.path.exists(script_path):
        console.print(f"[red]Example '{name}' not found.[/red]")
        return

    console.print(f"\n[green]Running {name}...[/green]")
    try:
        subprocess.run([sys.executable, script_path], check=True)
    except Exception as e:
        console.print(f"[red]Error running example: {e}[/red]")

    _pause()


# ---------------------------------------------------------------------------
# Wizard: full workflow (QASM -> physical execution, with optional QEC)
# ---------------------------------------------------------------------------

EC_CODES = {
    "none": None,
    "repetition": REPETITION_3,
    "steane": STEANE_7,
    "shor": SHOR_9,
}

EC_METHODS = {
    "repetition": "execute_3q_repetition_workflow",
    "steane": "execute_steane7_workflow",
    "shor": "execute_shor9_workflow",
}


def _qasm_completer():
    examples_dir = get_examples_dir()
    files = []
    if examples_dir:
        qasm_dir = os.path.join(examples_dir, "qasm_files")
        if os.path.isdir(qasm_dir):
            files = [
                os.path.join("examples", "qasm_files", os.path.basename(f))
                for f in glob.glob(os.path.join(qasm_dir, "*.qasm"))
            ]
    return WordCompleter(files, ignore_case=True)


def _wizard_full_workflow():
    _section("Run full workflow")
    console.print("[dim]Logical OpenQASM in, physical hardware execution out.[/dim]\n")

    available_qubits = _qubit_names()
    if not available_qubits:
        console.print("[red]No qubits exist yet. Create some first.[/red]")
        _pause()
        return

    console.print(f"[bold]Available qubits:[/bold] {', '.join(available_qubits)}")
    q_str = prompt(
        "Qubit names to use, in order (comma-separated): ", completer=_completer(available_qubits)
    ).strip()
    if not q_str:
        return

    qubit_names = [q.strip() for q in q_str.split(",")]
    for q in qubit_names:
        if q not in available_qubits:
            console.print(f"[red]Qubit '{q}' does not exist.[/red]")
            return

    console.print("\n[bold]Native coupling topology[/bold]")
    console.print(
        "[dim]Add an edge for each pair of qubits that can talk to each other directly (each pair only once).[/dim]"
    )
    couplings = []
    qname_completer = _completer(qubit_names)
    coupling_items = [
        ("capacitive", "Capacitive", "g(a1_dag a2 + a1 a2_dag)"),
        ("inductive", "Inductive / ZZ", "g * n1 * n2"),
        ("tunable_coupler", "Tunable coupler", "Time-dependent g_max f(t)(a1_dag a2 + a1 a2_dag)"),
    ]

    while True:
        console.print("\n  [New coupling edge]")
        q1_input = prompt("  First qubit (blank to finish): ", completer=qname_completer).strip()
        if not q1_input:
            break
        q2_input = prompt("  Second qubit: ", completer=qname_completer).strip()
        if not q2_input:
            break
        if q1_input not in qubit_names or q2_input not in qubit_names:
            console.print("[red]Use one of the qubit names chosen above.[/red]")
            continue

        ctype = _flat_choose(coupling_items, title="  Coupling type") or "tunable_coupler"
        cstren = Prompt.ask("  Strength (GHz)", default="0.05")

        try:
            couplings.append(
                {
                    "q1": qubit_names.index(q1_input),
                    "q2": qubit_names.index(q2_input),
                    "type": ctype,
                    "strength": float(cstren),
                }
            )
            console.print(
                f"  [green]Added {ctype} edge between {q1_input} and {q2_input} ({cstren} GHz).[/green]"
            )
        except ValueError:
            console.print("[red]Couldn't parse that strength as a number.[/red]")

    ec_items = [
        ("none", "No error correction", "Run the QASM circuit directly on the physical qubits"),
        (
            "repetition",
            "3-qubit repetition code",
            "5 physical qubits/logical qubit, corrects a single bit flip",
        ),
        (
            "steane",
            "7-qubit Steane code",
            "13 physical qubits/logical qubit, corrects any single-qubit Pauli error",
        ),
        (
            "shor",
            "9-qubit Shor code",
            "17 physical qubits/logical qubit, corrects any single-qubit error",
        ),
    ]
    ec_choice = _flat_choose(ec_items, title="Error correction") or "none"

    qasm_completer = _qasm_completer()
    examples_dir = get_examples_dir()
    if examples_dir and os.path.isdir(os.path.join(examples_dir, "qasm_files")):
        console.print(
            f"\n[dim]Bundled circuits live under {os.path.join(examples_dir, 'qasm_files')} (tab to complete).[/dim]"
        )

    if ec_choice == "none":
        _run_plain_workflow(qubit_names, couplings, qasm_completer)
    else:
        _run_ec_workflow(qubit_names, ec_choice, qasm_completer)


def _run_plain_workflow(qubit_names, couplings, qasm_completer):
    path = prompt("Path to OpenQASM (.qasm) file: ", completer=qasm_completer).strip().strip("\"'")
    if not path or not os.path.exists(path):
        console.print(f"[red]QASM file '{path}' not found.[/red]")
        _pause()
        return

    console.print("\n[green]Building physical schedule and simulating...[/green]")
    try:
        g_eng = GateEngine()
        wf_eng = PhysicalWorkflowEngine(engine, g_eng)

        with console.status("[cyan]Running workflow...[/cyan]"):
            res = wf_eng.execute_workflow(qubit_names, couplings, path)

        console.print("\n[bold]Final physical populations[/bold]")
        final_pops = {k: v[-1] for k, v in res["populations"].items()}
        sorted_pops = sorted(final_pops.items(), key=lambda x: -x[1])
        top_keys = [k for k, _v in sorted_pops[:4]]

        for state, p in sorted_pops[:8]:
            if p > 0.01:
                console.print(f"  |{state}>: {p * 100:5.2f}%")

        from qforge.utils.terminal_plot import TerminalPlotter

        console.print("\n[bold]Hardware execution timeline[/bold]")
        TerminalPlotter.plot_time_evolution(
            times=res["times"],
            expectations=[res["populations"][k] for k in top_keys],
            labels=[f"P(|{k}>)" for k in top_keys],
            title="Physical Workflow Hardware Execution Timeline",
        )
    except Exception as e:
        console.print(f"[red]Workflow execution failed: {e}[/red]")

    _pause()


def _run_ec_workflow(qubit_names, ec_choice, qasm_completer):
    code = EC_CODES[ec_choice]
    n_physical = len(qubit_names) * (code.num_data + code.num_ancilla)
    console.print(
        f"\n[dim]{code.name}: each logical qubit expands to {code.num_data + code.num_ancilla} "
        f"physical qubits ({code.num_data} data + {code.num_ancilla} ancilla). "
        f"{len(qubit_names)} logical qubit(s) -> {n_physical} physical qubits total.[/dim]"
    )
    if n_physical > 20:
        console.print(
            f"[yellow]That's a {2 ** n_physical:,}-dimensional state vector. "
            "This may be slow or memory-heavy.[/yellow]"
        )
        if not Confirm.ask("Continue anyway?", default=True):
            return

    path = (
        prompt("Path to logical OpenQASM (.qasm) file: ", completer=qasm_completer)
        .strip()
        .strip("\"'")
    )
    if not path or not os.path.exists(path):
        console.print(f"[red]QASM file '{path}' not found.[/red]")
        _pause()
        return

    coupling_items = [
        ("capacitive", "Capacitive", "Default for syndrome-extraction CNOTs"),
        ("inductive", "Inductive / ZZ", ""),
        ("tunable_coupler", "Tunable coupler", ""),
    ]
    c_type = (
        _flat_choose(coupling_items, title="Coupling type for syndrome extraction") or "capacitive"
    )
    g_val = Prompt.ask("Coupling strength (GHz)", default="0.010")
    ec_every = Prompt.ask(
        "Run a syndrome cycle every N gates (0 = only a final pass, safest for circuits with H gates)",
        default="0",
    )

    console.print(f"\n[green]Initializing ErrorCorrectionEngine ({code.name})...[/green]")
    try:
        g_eng = GateEngine()
        ec_eng = ErrorCorrectionEngine(engine, g_eng)
        method = getattr(ec_eng, EC_METHODS[ec_choice])

        with console.status(f"[cyan]Running {code.name} workflow...[/cyan]"):
            res = method(
                qubit_names,
                path,
                coupling_type=c_type,
                coupling_strength=float(g_val),
                ec_every_n_gates=int(ec_every),
            )

        logical_results = res["logical_populations"]
        console.print(
            "\n[bold]Decoded logical populations (feed-forward correction applied)[/bold]"
        )
        for l_state, prob in sorted(logical_results.items(), key=lambda x: -x[1]):
            if prob > 0.001:
                console.print(f"  |{l_state}>_L: {prob * 100:5.2f}%")

        console.print(
            "\n[dim]Continuous timeline plotting is skipped during active error correction, "
            "since mid-circuit syndrome measurement collapses the wavefunction.[/dim]"
        )
    except Exception as e:
        console.print(f"[red]Error-correction workflow failed: {e}[/red]")

    _pause()


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def _show_help():
    help_md = f"""
# qforge interactive mode

## Navigation
- Use the **arrow keys** and **enter** to pick a menu option, or start typing its name
- **q**, **Esc**, or **Ctrl-C** backs out of a menu
- Tab completion is available wherever you type a qubit name or file path

## Workflow stages

1. **Create a qubit** - define the physical parameters of a superconducting qubit
2. **Simulate a gate** - drive a calibrated single- or two-qubit gate and watch it evolve
3. **Analyze multi-qubit gates** - compare capacitive, inductive, and tunable-coupler CNOT/CZ
4. **Run full workflow** - take an OpenQASM circuit all the way to a physical execution,
   optionally protected by the 3-qubit repetition, 7-qubit Steane, or 9-qubit Shor code
5. **Compare qubits** - side-by-side metrics across qubit types or instances

## Design a device

The four built-in qubit types are not the only circuits you can study. **Design a
device** takes an ngspice-style netlist of capacitors, inductors, Josephson
junctions and resistors, quantizes whatever topology it describes, and reports the
energy levels, transition frequencies, anharmonicity and coherence estimates.

```
.title  Transmon
J1  1  0  Ic=30nA  Cj=2fF     ; junction, in physical units
C1  1  0  90fF                ; shunt capacitor
.cutoff n1 = 30
.levels 6
```

Values may be written either as circuit quantities (`90fF`, `100nH`, `30nA`,
`1MOhm`) or as the energies used internally (`EJ=15`, `EC=0.3`, all GHz). Start
from a bundled template - transmon, fluxonium, flux qubit, zero-pi and more - or
load a file of your own, then sweep flux, offset charge or any named `.param`.

## Tips
- Start with "Create a qubit" if this is your first time
- Presets (typical / high coherence / fast gates) are a fast way to get a working qubit
- Bundled example circuits live in `examples/qasm_files/`
- "Design a device" -> "Netlist format reference" documents the netlist language in full
- The full CLI reference is available with `qforge --help`

qforge v{__version__} - built on scqubits and QuTiP.
    """
    console.print(Panel(Markdown(help_md), title="Help", border_style="yellow"))
    _pause()


# ---------------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------------

HANDLERS.update(
    {
        "create": _wizard_create_qubit,
        "list": _wizard_list_qubits,
        "analyze": _wizard_analyze_qubit,
        "compare": _wizard_compare_qubits,
        "delete": _wizard_delete_qubit,
        "gate": _wizard_simulate_gate,
        "multi": _wizard_analyze_multi_qubit,
        "circuit": _wizard_build_circuit,
        "workflow": _wizard_full_workflow,
        "device": _wizard_design_device,
        "hardware": _wizard_design_hardware,
        "example": _wizard_run_example,
        "help": _show_help,
    }
)
