"""
Main CLI entry point for qforge.
"""

import click
from rich.console import Console
from rich.panel import Panel

from qforge.cli.commands.cache import cache_group

# Enable UTF-8 console for beautiful Unicode output
from qforge.utils.console import enable_unicode_console
enable_unicode_console()

from qforge.cli.commands import qubit, gate, circuit, hardware, compare, workflow, example, clean
from qforge.cli.interactive import run_interactive
from qforge import __version__

from pathlib import Path

console = Console()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="qforge", message="%(prog)s %(version)s")
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    help="Launch interactive mode with guided workflows",
)
@click.option(
    "--gui",
    is_flag=True,
    help="Launch the qforge graphical interface",
)
@click.option(
    "--cache-clear",
    is_flag=True,
    help="Clear the calibration cache.",
)
@click.pass_context
def cli(ctx, interactive, gui, cache_clear):
    """
    qforge: Quantum Simulation Toolkit
    
    End-to-end quantum simulation from qubit physics to hardware design.
    
    \b
    Quick Start:
      qforge qubit create transmon --name my_transmon
      qforge gate simulate --qubit my_transmon --gate X
      qforge circuit build --qubits my_transmon --gates H,X
      qforge compare --qubits transmon,fluxonium
      qforge workflow run --interactive
    
    For guided experience, use: qforge --interactive
    For graphical interface, use: qforge --gui
    """
    if cache_clear:
        # qforge/cli/main.py -> qforge -> project root
        project_root = Path(__file__).resolve().parents[2]
        cache_file = project_root / "outputs" / "calib_cache.json"

        cache_file.parent.mkdir(parents=True, exist_ok=True)

        with open(cache_file, "w", encoding="utf-8") as f:
            f.write("{}")

        click.echo(f"Cache cleared: {cache_file}")
        ctx.exit()
    if gui:
        from qforge.cli.gui import QForgeGUI
        app = QForgeGUI()
        app.protocol("WM_DELETE_WINDOW", app._safe_quit)
        app.mainloop()
        ctx.exit()

    if interactive:
        run_interactive()
        ctx.exit()
    
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Register subcommands
cli.add_command(qubit.qubit)
cli.add_command(gate.gate)
cli.add_command(circuit.circuit)
cli.add_command(hardware.hardware)
cli.add_command(compare.compare)
cli.add_command(workflow.workflow)
cli.add_command(example.example)
cli.add_command(cache_group)
cli.add_command(clean.clean)

from qforge.cli.commands import dev
cli.add_command(dev.dev)


@cli.command()
def citations():
    """Display BibTeX citations for underlying libraries."""
    console.print("[bold cyan]Please cite the following references in your research:[/bold cyan]\n")
    
    citations_map = {
        "scqubits": """@article{Groszkowski2021,
  title = {scqubits: a Python package for superconducting qubits},
  author = {Groszkowski, Peter and Koch, Jens},
  journal = {Quantum},
  volume = {5},
  pages = {583},
  year = {2021},
  doi = {10.22331/q-2021-11-17-583},
  url = {https://doi.org/10.22331/q-2021-11-17-583}
}""",
        "qutip": """@article{Johansson2013,
  title = {QuTiP 2: A Python framework for the dynamics of open quantum systems},
  author = {Johansson, J.R. and Nation, P.D. and Nori, F.},
  journal = {Comp. Phys. Comm.},
  volume = {184},
  pages = {1234},
  year = {2013},
  doi = {10.1016/j.cpc.2012.11.019}
}""",
        "qiskit": """@misc{Qiskit,
    author = {{Qiskit contributors}},
    title = {Qiskit: An Open-source Framework for Quantum Computing},
    year = {2023},
    doi = {10.5281/zenodo.2573505}
}"""
    }
    
    for name, bib in citations_map.items():
        console.print(f"[green]{name}[/green]")
        console.print(Panel(bib, expand=False, border_style="green"))


@cli.command()
def info():
    """Display qforge system information."""
    info_text = f"""
[bold cyan]qforge Quantum Simulation Toolkit[/bold cyan]
[green]Version:[/green] {__version__}

[yellow]Installed Components:[/yellow]
• Qubit Physics Engine (scqubits)
• Gate Physics Engine (QuTiP)
• Circuit Simulation Engine (Qiskit)
• Hardware Design Engine (Qiskit Metal)
• Comparison Framework
• Interactive CLI

[blue]Supported Qubits:[/blue]
• Transmon
• Fluxonium
• Flux Qubit
• Zero-π (0-π) Qubit
• Custom (via plugins)

[magenta]Quick Start:[/magenta]
  qforge --interactive    # Launch guided mode
  qforge --gui            # Launch GUI
  qforge qubit --help     # View qubit commands
  qforge workflow run     # Run end-to-end workflow
"""
    console.print(Panel(info_text, title="System Info", border_style="cyan"))


if __name__ == "__main__":
    cli()