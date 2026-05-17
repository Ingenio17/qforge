"""
Hardware design CLI commands for qforge.
"""

import click
from rich.console import Console

console = Console()


@click.group()
def hardware():
    """Quantum hardware chip design commands."""
    pass


@hardware.command("design")
@click.option("--qubit", required=True, help="Qubit name")
@click.option("--layout", type=click.Choice(["grid", "linear", "custom"]), default="grid")
@click.option("--export", type=click.Path(), help="Export GDS file")
def design(qubit, layout, export):
    """Design quantum hardware layout."""
    console.print(f"[yellow]Hardware design: {layout} layout for {qubit}[/yellow]")
    console.print("[dim]Full implementation coming soon. See qforge hardware --help[/dim]")
