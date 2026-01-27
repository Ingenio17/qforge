"""
Qubit CLI commands for QForge.
"""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from qforge.core.qubit_engine import QubitEngine
from qforge.config.defaults import QUBIT_PRESETS

console = Console()
engine = QubitEngine()


@click.group()
def qubit():
    """Qubit modeling and physics commands."""
    pass


@qubit.command("create")
@click.option("--type", "-t", "qubit_type", required=True, 
              type=click.Choice(["transmon", "fluxonium", "flux", "zeropi"], case_sensitive=False),
              help="Type of qubit to create")
@click.option("--name", "-n", required=True, help="Name for the qubit")
@click.option("--EJ", type=float, show_default=True, help="Josephson energy (GHz)")
@click.option("--EC", type=float, show_default=True, help="Charging energy (GHz)")
@click.option("--EL", type=float, show_default=True, help="Inductive energy (GHz) - required for fluxonium")
@click.option("--flux", type=float, default=0.0, show_default=True, help="External flux in Φ₀ units")
@click.option("--preset", "-p", type=click.Choice(["typical", "high_coherence", "fast_gates"]),
              help="Use preset parameters")
@click.option("--output", "-o", type=click.Path(), help="Save qubit configuration to file")
@click.option("--relative", is_flag=True, help="Display energies relative to ground state")
def create(qubit_type, name, ej, ec, el, flux, preset, output, relative):
    """Create a new qubit with specified parameters."""
    
    # Build parameters dictionary
    params = {}
    if preset:
        params = QUBIT_PRESETS.get(qubit_type, {}).get(preset, {}).copy()
        console.print(f"[cyan]Using {preset} preset for {qubit_type}[/cyan]")
    
    # Override with explicit parameters
    if ej is not None:
        params["EJ"] = ej
    if ec is not None:
        params["EC"] = ec
    if el is not None and qubit_type == "fluxonium":
        params["EL"] = el
    if flux is not None:
        params["flux"] = flux
    
    # Call the creation function
    _create_qubit(qubit_type, name, params, output, relative)


def _create_qubit(qubit_type, name, params, output=None, relative=False):
    """Internal function to create qubit (used by interactive mode too)."""
    try:
        qubit_obj = engine.create_qubit(qubit_type, name, params)
        
        # Display qubit information
        table = Table(title=f"Qubit Created: {name}", show_header=True, header_style="bold cyan")
        table.add_column("Property", style="yellow")
        table.add_column("Value", style="green")
        
        table.add_row("Type", qubit_type.capitalize())
        table.add_row("Name", name)
        for key, value in params.items():
            if isinstance(value, float):
                table.add_row(key, f"{value:.3f} GHz")
            else:
                table.add_row(key, str(value))
        
        console.print(table)
        
        # Compute basic properties
        with console.status("[cyan]Computing energy spectrum...[/cyan]"):
            spectrum = engine.compute_spectrum(qubit_obj, n_levels=5, subtract_ground=relative)
        
        # Display spectrum
        spec_table = Table(title=f"Energy Spectrum (first 5 levels){' - Relative' if relative else ''}", show_header=True)
        spec_table.add_column("Level", justify="center")
        spec_table.add_column("Energy (GHz)", justify="right")
        spec_table.add_column("Transition (GHz)", justify="right")
        
        for i, energy in enumerate(spectrum[:5]):
            transition = spectrum[i] - spectrum[0] if i > 0 else 0.0
            spec_table.add_row(
                f"|{i}⟩",
                f"{energy:.4f}",
                f"{transition:.4f}" if i > 0 else "—"
            )
        
        console.print(spec_table)
        
        # Calculate anharmonicity if applicable
        if len(spectrum) >= 3:
            omega_01 = spectrum[1] - spectrum[0]
            omega_12 = spectrum[2] - spectrum[1]
            anharmonicity = omega_12 - omega_01
            console.print(f"\n[yellow]Anharmonicity (α):[/yellow] [bold]{anharmonicity*1000:.1f} MHz[/bold]")
            console.print(f"[yellow]Qubit Frequency (ω₀₁):[/yellow] [bold]{omega_01:.4f} GHz[/bold]")
        
        # Save if requested
        if output:
            engine.save_qubit(qubit_obj, output)
            console.print(f"\n[green]✓ Qubit saved to {output}[/green]")
        
        console.print(f"\n[bold green]✓ Qubit '{name}' created successfully![/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]✗ Error creating qubit:[/bold red] {str(e)}")
        raise click.Abort()


@qubit.command("list")
def list_qubits():
    """List all created qubits."""
    qubits = engine.list_qubits()
    
    if not qubits:
        console.print("[yellow]No qubits created yet. Use 'qforge qubit create' to get started.[/yellow]")
        return
    
    table = Table(title="Created Qubits", show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Frequency (GHz)")
    table.add_column("Anharmonicity (MHz)")
    
    for qubit in qubits:
        table.add_row(
            qubit["name"],
            qubit["type"],
            f"{qubit.get('frequency', 0):.3f}",
            f"{qubit.get('anharmonicity', 0)*1000:.1f}"
        )
    
    console.print(table)


@qubit.command("delete")
@click.argument("name")
def delete(name):
    """Delete a qubit."""
    try:
        engine.delete_qubit(name)
        console.print(f"[bold green]✓ Qubit '{name}' deleted successfully.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        raise click.Abort()


@qubit.command("analyze")
@click.argument("name")
@click.option("--plot", is_flag=True, help="Generate and save visualization plots")
@click.option("--coherence", is_flag=True, help="Estimate coherence times (T1, T2)")
@click.option("--relative", is_flag=True, help="Display energies relative to ground state")
def analyze(name, plot, coherence, relative):
    """Analyze qubit properties in detail."""
    try:
        qubit_obj = engine.get_qubit(name)
        
        console.print(f"\n[bold cyan]Analyzing qubit: {name}[/bold cyan]\n")
        
        # Detailed spectrum
        with console.status("[cyan]Computing detailed spectrum...[/cyan]"):
            spectrum = engine.compute_spectrum(qubit_obj, n_levels=10, subtract_ground=relative)
        
        if plot:
            console.print("[yellow]Generating plots...[/yellow]")
            engine.visualize(qubit_obj, plot_type="spectrum", subtract_ground=relative)
            console.print("[green]✓ Plots saved to outputs/[/green]")
        
        if coherence:
            with console.status("[cyan]Estimating coherence times...[/cyan]"):
                coherence_data = engine.estimate_coherence(qubit_obj)
            
            coh_table = Table(title="Coherence Times (Estimates)", show_header=True)
            coh_table.add_column("Parameter")
            coh_table.add_column("Value")
            coh_table.add_column("Limit")
            
            for param, data in coherence_data.items():
                coh_table.add_row(param, f"{data['value']:.2f} μs", data['limit'])
            
            console.print(coh_table)
        
    except Exception as e:
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        raise click.Abort()


@qubit.command("export")
@click.argument("name")
@click.option("--format", "-f", type=click.Choice(["json", "qutip", "qiskit"]),
              default="json", show_default=True, help="Export format")
@click.option("--output", "-o", type=click.Path(), required=True, help="Output file path")
def export(name, format, output):
    """Export qubit to various formats."""
    try:
        qubit_obj = engine.get_qubit(name)
        
        if format == "qutip":
            engine.export_to_qutip(qubit_obj, output)
        elif format == "qiskit":
            engine.export_to_qiskit(qubit_obj, output)
        else:
            engine.save_qubit(qubit_obj, output)
        
        console.print(f"[green]✓ Qubit exported to {output} ({format} format)[/green]")
        
    except Exception as e:
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        raise click.Abort()
