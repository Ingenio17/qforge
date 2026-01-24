"""
Enhanced CLI analyze command with comprehensive visualization and analysis.
"""

import click
import numpy as np
from pathlib import Path
from rich.console import Console
from rich.table import Table

# This will be inserted into qubit.py

# Add these imports at the top
# from qforge.config.defaults import OUTPUT_DIRS

analyze_enhanced_code = '''
@qubit.command("analyze")
@click.argument("name")
@click.option("--plot", is_flag=True, help="Generate all visualizations")
@click.option("--coherence", is_flag=True, help="Estimate coherence times")
@click.option("--spectrum", is_flag=True, help="Plot energy spectrum")
@click.option("--wavefunctions", is_flag=True, help="Plot wavefunctions")
@click.option("--potential", is_flag=True, help="Plot potential energy")
@click.option("--sweep", type=str, help="Parameter sweep: 'param:start:end:steps' (e.g., 'EJ:10:20:50')")
@click.option("--sweep-property", type=click.Choice(["frequency", "anharmonicity", "T1", "T2"]),
              default="frequency", help="Property to plot during sweep")
def analyze(name, plot, coherence, spectrum, wavefunctions, potential, sweep, sweep_property):
    """Analyze qubit properties with visualizations and parameter sweeps."""
    import numpy as np
    from pathlib import Path
    from qforge.config.defaults import OUTPUT_DIRS
    
    try:
        qubit_obj = engine.get_qubit(name)
        qubit_data = None
        for qname, data in engine._qubits.items():
            if qname == name:
                qubit_data = data
                break
        
        console.print(f"\\n[bold cyan]✨ Analyzing qubit: {name}[/bold cyan]\\n")
        
        # Basic properties table
        with console.status("[cyan]Computing properties...[/cyan]"):
            evals = engine.compute_spectrum(qubit_obj, n_levels=10)
            omega_01 = evals[1] - evals[0]
            omega_12 = evals[2] - evals[1] if len(evals) > 2 else 0
            anharmonicity = omega_12 - omega_01 if len(evals) > 2 else 0
        
        info_table = Table(title="Qubit Properties", show_header=True, header_style="bold cyan")
        info_table.add_column("Property", style="yellow")
        info_table.add_column("Value", style="green")
        
        info_table.add_row("Type", qubit_data["type"].capitalize())
        info_table.add_row("Frequency (ω₀₁)", f"{omega_01:.4f} GHz")
        if len(evals) > 2:
            info_table.add_row("Anharmonicity (α)", f"{anharmonicity*1000:.1f} MHz")
            info_table.add_row("ω₁₂", f"{omega_12:.4f} GHz")
        
        console.print(info_table)
        
        # Coherence analysis
        if coherence:
            with console.status("[cyan]Estimating coherence times...[/cyan]"):
                coherence_data = engine.estimate_coherence(qubit_obj)
            
            coh_table = Table(title="Coherence Times", show_header=True, header_style="bold green")
            coh_table.add_column("Parameter", style="yellow")
            coh_table.add_column("Value", style="cyan")
            coh_table.add_column("Limiting Mechanism", style="dim")
            
            for param, data in coherence_data.items():
                coh_table.add_row(param, f"{data['value']:.2f} μs", data['limit'])
            
            console.print(coh_table)
        
        # Visualizations
        plot_types = []
        if plot:
            plot_types = ["spectrum", "wavefunctions", "potential"]
        else:
            if spectrum:
                plot_types.append("spectrum")
            if wavefunctions:
                plot_types.append("wavefunctions")
            if potential:
                plot_types.append("potential")
        
        if plot_types:
            console.print("\\n[yellow]📊 Generating visualizations...[/yellow]")
            saved_plots = engine.visualize_enhanced(qubit_obj, plot_types=plot_types, save=True)
            
            for plot_type, path in saved_plots.items():
                console.print(f"  [green]✓ {plot_type.capitalize()}:[/green] {path}")
        
        # Parameter sweep
        if sweep:
            try:
                parts = sweep.split(":")
                if len(parts) == 4:
                    param_name, start, end, steps = parts
                    param_range = np.linspace(float(start), float(end), int(steps))
                    
                    console.print(f"\\n[yellow]📈 Running parameter sweep...[/yellow]")
                    console.print(f"   Parameter: [cyan]{param_name}[/cyan] from [cyan]{start}[/cyan] to [cyan]{end}[/cyan] GHz")
                    console.print(f"   Property: [cyan]{sweep_property}[/cyan]")
                    
                    fixed_params = {k: v for k, v in qubit_data["params"].items() if k != param_name}
                    
                    with console.status("[cyan]Computing sweep...[/cyan]"):
                        results = engine.parameter_sweep(
                            qubit_data["type"],
                            param_name,
                            param_range,
                            fixed_params,
                            sweep_property
                        )
                    
                    # Plot
                    from qforge.utils.analysis import plot_parameter_sweep
                    save_path = str(Path(OUTPUT_DIRS["plots"]) / f"{name}_sweep_{param_name}_{sweep_property}.png")
                    Path(OUTPUT_DIRS["plots"]).mkdir(parents=True, exist_ok=True)
                    
                    plot_parameter_sweep(
                        qubit_data["type"],
                        param_name,
                        np.array(results["parameter_values"]),
                        fixed_params,
                        sweep_property,
                        save_path=save_path
                    )
                    
                    console.print(f"  [green]✓ Sweep plot:[/green] {save_path}")
                    
                    # Summary
                    p_vals = results["parameter_values"]
                    prop_vals = results["property_values"]
                    console.print(f"\\n[cyan]Sweep Summary:[/cyan]")
                    console.print(f"  Range: {min(prop_vals):.3f} - {max(prop_vals):.3f}")
                    console.print(f"  Variation: {(max(prop_vals) - min(prop_vals)):.3f}")
                else:
                    console.print("[red]Invalid sweep format. Use: 'param:start:end:steps'[/red]")
                    console.print("[yellow]Example: --sweep 'EJ:10:20:50'[/yellow]")
            except Exception as e:
                console.print(f"[red]Sweep error: {e}[/red]")
        
        console.print(f"\\n[bold green]✓ Analysis complete![/bold green]\\n")
        
    except Exception as e:
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        import traceback
        traceback.print_exc()
        raise click.Abort()
'''

# Instructions for manual integration:
# Replace the existing analyze command in qubit.py (lines ~144-180) with the analyze_enhanced_code above
