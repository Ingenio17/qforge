"""
Workflow CLI commands for QForge.
"""

import click
from rich.console import Console

console = Console()


@click.group()
def workflow():
    """End-to-end workflow orchestration commands."""
    pass


@workflow.command("run")
@click.option("--qubit-type", type=click.Choice(["transmon", "fluxonium"]))
@click.option("--interactive", is_flag=True, help="Run in interactive mode")
def run(qubit_type, interactive):
    """Run end-to-end quantum workflow."""
    console.print(f"[yellow]Running workflow for {qubit_type or 'default'}[/yellow]")
    console.print("[dim]Full implementation coming soon. See qforge workflow --help[/dim]")
