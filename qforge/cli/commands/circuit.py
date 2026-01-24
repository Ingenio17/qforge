"""
Circuit simulation CLI commands for QForge.
"""

import click
from rich.console import Console

console = Console()


@click.group()
def circuit():
    """Circuit-level quantum simulation commands."""
    pass


@circuit.command("build")
@click.option("--qubits", required=True, help="Comma-separated qubit names")
@click.option("--gates", required=True, help="Comma-separated gate sequence")
@click.option("--shots", type=int, default=1024, help="Number of shots")
def build(qubits, gates, shots):
    """Build and simulate a quantum circuit."""
    console.print(f"[yellow]Circuit simulation: {gates} on {qubits}[/yellow]")
    console.print("[dim]Full implementation coming soon. See qforge circuit --help[/dim]")
