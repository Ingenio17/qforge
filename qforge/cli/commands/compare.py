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
@click.option("--metrics", default="all", help="Metrics to compare (coherence,fidelity,frequency,anharmonicity,all)")
@click.option("--output", "-o", type=click.Path(), help="Save comparison to file")
def compare_qubits(qubits, metrics, output):
    """
    Compare multiple qubits side-by-side.
    
    Examples:
        qforge compare qubits --qubits transmon,fluxonium
        qforge compare qubits --qubits my_qubit1,my_qubit2 --metrics coherence,frequency
    """
    qubit_list = [q.strip() for q in qubits.split(",")]
    metric_list = [m.strip() for m in metrics.split(",")] if metrics != "all" else ["all"]
    
    try:
        console.print(f"\n[bold cyan]Comparing qubits:[/bold cyan] {', '.join(qubit_list)}")
        
        # Perform comparison
        results = comparator.compare_qubits(qubit_list, metric_list)
        
        # Display results in a table
        table = Table(title="Qubit Comparison", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="yellow")
        
        for qubit_name in qubit_list:
            table.add_column(qubit_name.capitalize(), style="green")
        
        # Add rows for each metric
        for metric, values in results.items():
            row = [metric]
            for qubit_name in qubit_list:
                value = values.get(qubit_name, "N/A")
                # Add checkmark for best value
                if isinstance(value, (int, float)) and value == max([v for v in values.values() if isinstance(v, (int, float))]):
                    row.append(f"{value} ✓")
                else:
                    row.append(str(value))
            table.add_row(*row)
        
        console.print(table)
        
        # Save if requested
        if output:
            comparator.save_comparison(results, output)
            console.print(f"\n[green]✓ Comparison saved to {output}[/green]")
        
    except Exception as e:
        console.print(f"[bold red]✗ Error:[/bold red] {str(e)}")
        raise click.Abort()
