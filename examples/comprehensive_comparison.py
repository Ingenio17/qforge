"""
Comprehensive Qubit Comparison Example

This example demonstrates the advanced comparison capabilities of qforge.
It compares Transmon, Fluxonium, and Flux qubits across:
1. Static Metrics: Frequency, Anharmonicity, Coherence (T1/T2)
2. Dynamic Metrics: X-Gate Fidelity, Gate Speed
3. Derived Metrics: Addressability, Coherence Limit

A detailed report with plots will be generated in 'outputs/runs/'.
"""

import sys
import os

# Enable UTF-8 console
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from qforge.utils.console import enable_unicode_console
enable_unicode_console()

from qforge.core.qubit_engine import QubitEngine
from qforge.comparison.comparator import Comparator

def main():
    print("=" * 70)
    print("qforge Example: Comprehensive Qubit Comparison")
    print("=" * 70)

    # Initialize engine
    qubit_engine = QubitEngine()
    
    # 1. Create Candidates
    print("\n1. Defining Qubit Candidates...")
    
    # Transmon (Standard)
    transmon = qubit_engine.create_qubit(
        "transmon", "transmon", 
        {"EJ": 15.0, "EC": 0.3}
    )
    
    # Fluxonium (Heavy)
    fluxonium = qubit_engine.create_qubit(
        "fluxonium", "fluxonium", 
        {"EJ": 8.9, "EC": 2.5, "EL": 0.5, "flux": 0.5}
    )
    
    # Flux Qubit (C-Shunt)
    flux_qubit = qubit_engine.create_qubit(
        "flux", "c_shunt_flux", 
        {"EJ1": 4.0, "EJ2": 4.0, "EJ3": 2.2, "ECJ1": 2.0, "ECJ2": 2.0, "ECJ3": 2.0, "flux": 0.5}
    )

    print("   ✓ Candidates ready: transmon, fluxonium, c_shunt_flux")

    # Initialize comparator (will load the newly created qubits)
    comparator = Comparator()

    # 2. Run Comparison
    print("\n2. Running Comprehensive Comparison...")
    print("   (This includes gate simulations and may take a moment)")
    
    results = comparator.compare_qubits(
        qubit_list=["transmon", "fluxonium", "c_shunt_flux"],
        metrics=["all"], # Includes frequency, anharmonicity, coherence, fidelity
        gates=["X"],     # Simulate X gate dynamics
        run_tag="example_comprehensive"
    )

    # 3. Print Results to Terminal
    from rich.console import Console
    from rich.table import Table
    console = Console()

    print("\n" + "=" * 70)
    print("Comparison Results")
    print("=" * 70)

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="yellow")
    
    # Get all qubit names found in results
    all_qubits = set()
    for metric_vals in results.values():
        all_qubits.update(metric_vals.keys())
    all_qubits = sorted(list(all_qubits))
    
    for qubit_name in all_qubits:
        table.add_column(qubit_name.capitalize(), style="green")
    
    for metric, values in results.items():
        row = [metric]
        best_val = None
        numeric_vals = [v for v in values.values() if isinstance(v, (int, float))]
        if numeric_vals:
            if "Anharmonicity" in metric:
                    best_val = max(numeric_vals, key=abs)
            else:
                best_val = max(numeric_vals)
        
        for qubit_name in all_qubits:
            value = values.get(qubit_name, "-")
            display_val = str(value)
            if isinstance(value, float):
                display_val = f"{value:.4f}"
            
            if best_val is not None and isinstance(value, (int, float)) and value == best_val:
                row.append(f"{display_val} ✓")
            else:
                row.append(display_val)
                
        table.add_row(*row)
    
    console.print(table)

    print("\n" + "=" * 70)
    print("Comparison Run Completed Successfully!")
    print("=" * 70)
    print("\nPlease check the generated report in outputs/runs/ for detailed tables and plots.")

if __name__ == "__main__":
    main()
