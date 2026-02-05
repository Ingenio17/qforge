"""
Comparison CLI commands for QForge.
"""

import click
from rich.console import Console
from rich.table import Table

from qforge.comparison.comparator import Comparator

console = Console()
comparator = Comparator()


@click.group()
def compare():
    """Comparison and analysis commands for different qubit types."""
    pass


@compare.command("qubits")
@click.option("--qubits", required=True, help="Comma-separated qubit names or types")
@click.option("--metrics", default="all", help="Metrics to compare (coherence, fidelity, frequency, anharmonicity, all)")
@click.option("--gates", default=None, help="Comma-separated list of gates to simulate (e.g., X,H)")
@click.option("--tag", default=None, help="Tag for the run identification")
@click.option("--output", "-o", type=click.Path(), help="Legacy: Save raw JSON comparison results to file")
def compare_qubits(qubits, metrics, gates, tag, output):
    """
    Compare multiple qubits side-by-side.
    
    Examples:
        qforge compare qubits --qubits transmon,fluxonium --metrics all
        qforge compare qubits --qubits my_transmon,fluxonium --gates X --tag demo
    """
    qubit_list = [q.strip() for q in qubits.split(",")]
    metric_list = [m.strip() for m in metrics.split(",")] if metrics != "all" else ["all"]
    gate_list = [g.strip() for g in gates.split(",")] if gates else []
    
    try:
        console.print(f"\n[bold cyan]Comparing qubits:[/bold cyan] {', '.join(qubit_list)}")
        if tag:
            console.print(f"[dim]Run Tag: {tag}[/dim]")
        
        # Perform comparison with managed run
        results = comparator.compare_qubits(
            qubit_list=qubit_list, 
            metrics=metric_list, 
            gates=gate_list, 
            run_tag=tag
        )
        
        # Display results in a table
        table = Table(title="Qubit Comparison Results", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="yellow")
        
        # Get all qubit names found in results
        all_qubits = set()
        for metric_vals in results.values():
            all_qubits.update(metric_vals.keys())
        all_qubits = sorted(list(all_qubits)) # Sort to be deterministic
        
        for qubit_name in all_qubits:
            table.add_column(qubit_name.capitalize(), style="green")
        
        # Add rows for each metric
        for metric, values in results.items():
            row = [metric]
            
            # Determine best value for highlighting
            best_val = None
            numeric_vals = [v for v in values.values() if isinstance(v, (int, float))]
            if numeric_vals:
                if "Anharmonicity" in metric:
                     # Magnitude matters? Or specific value? Usually magnitude.
                     # Let's assume larger magnitude is "better" for distinctness,
                     # or larger positive for some cases.
                     # Simplistic: Max absolute value
                     best_val = max(numeric_vals, key=abs)
                else:
                    best_val = max(numeric_vals)
            
            for qubit_name in all_qubits:
                value = values.get(qubit_name, "-")
                
                # Format floats
                display_val = str(value)
                if isinstance(value, float):
                    display_val = f"{value:.4f}"
                
                # Add checkmark for best value
                if best_val is not None and isinstance(value, (int, float)) and value == best_val:
                    row.append(f"{display_val} ✓")
                else:
                    row.append(display_val)
                    
            table.add_row(*row)
        
        console.print(table)
        console.print(f"\n[dim]Detailed report generated in outputs/runs/...[/dim]")
        
        # Legacy Save if requested
        if output:
            comparator.save_comparison(results, output)
            console.print(f"\n[green]✓ Raw results saved to {output}[/green]")
        
    except Exception as e:
        # console.print_exception() # For debug
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        raise click.Abort()
