"""
Gate simulation CLI commands for qforge.
"""

import click
import numpy as np
from rich.console import Console

from qforge.core.gate_engine import GateEngine
from qforge.utils.terminal_plot import TerminalPlotter
from qforge.config.defaults import OUTPUT_DIRS
from pathlib import Path

console = Console()
engine = GateEngine()


@click.group()
def gate():
    """Gate physics and dynamics simulation commands."""
    pass


@gate.command("simulate")
@click.option("--qubit", required=True, help="Qubit name")
@click.option("--gate", required=True, type=click.Choice(["X", "Y", "Z", "H"]), help="Gate type")
@click.option("--duration", type=float, default=20.0, show_default=True, help="Gate duration (ns)")
@click.option("--noise", type=click.Choice(["none", "realistic"]), default="none", show_default=True, help="Noise model")
@click.option("--save", is_flag=True, help="Save the plot to a file")
@click.option("--steps", type=int, default=100, show_default=True, help="Number of time steps")
def simulate(qubit, gate, duration, noise, save, steps):
    """
    Simulate quantum gate dynamics.
    
    This command simulates the time evolution of a qubit under a specified gate drive.
    It shows real-time state populations in the terminal.
    """
    try:
        console.print(f"\n[bold cyan]Simulating {gate} gate on {qubit}...[/bold cyan]")
        console.print(f"[dim]Duration: {duration} ns | Noise: {noise}[/dim]\n")
        
        with console.status("[cyan]Running dynamics simulation...[/cyan]"):
            result = engine.simulate_dynamics(
                qubit_name=qubit,
                gate_type=gate,
                duration=duration,
                noise_model=noise,
                steps=steps
            )
            
        # Terminal Plot
        TerminalPlotter.plot_time_evolution(
            times=result["times"],
            expectations=result["expectations"],
            labels=result["labels"],
            title=f"Time Evolution during {gate} Gate"
        )
        
        # Save option
        if save:
             _save_plot(result, qubit, gate)
        
        console.print("\n[bold green]✓ Simulation complete![/bold green]")
            
    except Exception as e:
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        raise click.Abort()

def _save_plot(result, qubit, gate):
    """Helper to save the plot using matplotlib."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    times = result["times"]
    expectations = result["expectations"]
    labels = result["labels"]
    
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, expect in enumerate(expectations):
        ax.plot(times, expect, label=labels[i], linewidth=2)
        
    ax.set_title(f"Time Evolution: {qubit} + {gate} Gate")
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Population")
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    base_filename = f"{qubit}_{gate}_dynamics"
    save_path = Path(OUTPUT_DIRS["plots"]) / f"{base_filename}_1.png"
    
    counter = 2
    while save_path.exists():
        save_path = Path(OUTPUT_DIRS["plots"]) / f"{base_filename}_{counter}.png"
        counter += 1
        
    plt.savefig(save_path, dpi=150)
    plt.close()
    
    console.print(f"[green]✓ Plot saved to {save_path}[/green]")
