"""
Comparison Engine for QForge.
"""

import json
import os
import numpy as np
import qutip as qt
from typing import List, Dict, Any, Optional
from pathlib import Path

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.core.run_manager import RunManager
from qforge.config.defaults import QUBIT_PRESETS
from qforge.utils.terminal_plot import TerminalPlotter  # Can use for generating report plots

class Comparator:
    """Engine for comparing different qubits and quantum systems."""
    
    def __init__(self):
        """Initialize the comparator."""
        self.qubit_engine = QubitEngine()
        self.gate_engine = GateEngine()
        self.run_manager = RunManager()
    
    def compare_qubits(self, 
                       qubit_list: List[str], 
                       metrics: List[str] = ["all"], 
                       gates: List[str] = [],
                       run_tag: str = "comparison") -> Dict[str, Any]:
        """
        Compare multiple qubits across various metrics within a managed run.
        
        Args:
            qubit_list: List of qubit names or types
            metrics: List of metrics to compare
            gates: List of gates to simulate for dynamic comparison
            run_tag: Tag for the run directory
        
        Returns:
            Dictionary mapping metrics to qubit values
        """
        # Start a managed run
        with self.run_manager.create_run(tag=run_tag, parameters={"qubits": qubit_list, "metrics": metrics, "gates": gates}) as (run_id, run_dir):
            results = {}
            
            # 1. Prepare Qubits
            qubit_objects = self._prepare_qubits(qubit_list)
            
            # 2. Static Metrics (Frequency, Anharmonicity, Coherence)
            static_results = self._compute_static_metrics(qubit_objects, metrics)
            results.update(static_results)
            
            # 3. Dynamic Metrics (Gate Fidelity, Speed)
            if gates or "gate_fidelity" in metrics or "all" in metrics:
                # Default to X gate if no specific gates requested but fidelity metric is
                gates_to_run = gates if gates else ["X"]
                dynamic_results = self._compute_dynamic_metrics(qubit_objects, gates_to_run, run_dir)
                results.update(dynamic_results)
            
            # 4. Derived Metrics (Addressability, Coherence Limit)
            derived_results = self._compute_derived_metrics(results, qubit_objects)
            results.update(derived_results)
            
            # 5. Generate Report
            self.generate_report(results, run_id, run_dir)
            
            return results
    
    def _prepare_qubits(self, qubit_list: List[str]) -> Dict[str, Any]:
        """Resolve qubit names to objects, creating temporary ones if needed."""
        qubit_objects = {}
        for qubit_id in qubit_list:
            try:
                qubit_objects[qubit_id] = self.qubit_engine.get_qubit(qubit_id)
            except:
                if qubit_id.lower() in QUBIT_PRESETS:
                    params = QUBIT_PRESETS[qubit_id.lower()]["typical"]
                    qubit_obj = self.qubit_engine.create_qubit(
                        qubit_type=qubit_id.lower(),
                        name=f"temp_{qubit_id}_{self.run_manager.current_run_id[:4]}",
                        params=params
                    )
                    qubit_objects[qubit_id] = qubit_obj
                else:
                    raise ValueError(f"Qubit '{qubit_id}' not found and is not a known type")
        return qubit_objects

    def _compute_static_metrics(self, qubit_objects: Dict[str, Any], metrics: List[str]) -> Dict[str, Dict]:
        """Compute static physical properties."""
        results = {}
        
        # Frequency
        if "all" in metrics or "frequency" in metrics or "operational_frequency" in metrics:
            freq_values = {}
            for name, qubit in qubit_objects.items():
                evals = qubit.eigenvals(evals_count=2)
                freq_values[name] = evals[1] - evals[0]
            results["Frequency (GHz)"] = freq_values

        # Anharmonicity
        if "all" in metrics or "anharmonicity" in metrics:
            anharm_values = {}
            for name, qubit in qubit_objects.items():
                evals = qubit.eigenvals(evals_count=3)
                anharmonicity = (evals[2] - evals[1]) - (evals[1] - evals[0])
                anharm_values[name] = anharmonicity * 1000 # MHz
            results["Anharmonicity (MHz)"] = anharm_values
            
        # Coherence
        if "all" in metrics or "coherence" in metrics or "t1" in metrics:
            t1_values = {}
            t2_values = {}
            for name, qubit in qubit_objects.items():
                coherence = self.qubit_engine.estimate_coherence(qubit)
                t1_values[name] = coherence.get('T1 (dielectric)', {}).get('value', 0)
                t2_values[name] = coherence.get('T2 (echo)', {}).get('value', 0)
            results["T1 (μs)"] = t1_values
            results["T2 (μs)"] = t2_values
            
        return results

    def _compute_dynamic_metrics(self, qubit_objects: Dict[str, Any], gates: List[str], run_dir: Path) -> Dict[str, Dict]:
        """Compute metrics requiring simulation."""
        results = {}
        fidelity_results = {}
        speed_results = {}
        
        plotting_dir = run_dir / "plots"
        
        for name, qubit in qubit_objects.items():
            for gate in gates:
                # Determine gate duration based on qubit type/anharmonicity?
                # For fair comparison, we optimize duration or use a standard?
                # Simplification: Use standard 40ns for Transmon, maybe longer for others?
                # Actually, we should probably let GateEngine decide or use a heuristic.
                # Let's use a fixed reasonable duration for now: 40ns
                duration = 40.0
                if "fluxonium" in name.lower():
                    duration = 60.0 # Often slower
                
                # Simulate
                try:
                    sim_result = self.gate_engine.simulate_dynamics(
                        qubit_name=qubit.name if hasattr(qubit, 'name') else name, # Use internal name if strictly needed
                        # Wait, qubit_objects has mapping from user_name -> object.
                        # GateEngine needs name to look up in QubitEngine.
                        # If we created temp qubits, they are already in QubitEngine.
                        gate_type=gate,
                        duration=duration,
                        noise_model="realistic",
                        steps=200
                    )
                    
                    # Calculate Fidelity vs Ideal |1> (assuming X gate)
                    # Ideal X|0> -> -i|1> (in RWA with our Hamiltonian convention usually)
                    # Let's use population validity: P(1)
                    final_state = sim_result["final_state"]
                    # Project onto |1>
                    # Assuming we started in |0>
                    dim = final_state.shape[0]
                    target = qt.basis(dim, 1)
                    fidelity = qt.fidelity(final_state, target)**2 # Overlap squared usually
                    
                    key = f"{gate} Gate Fidelity"
                    if key not in fidelity_results: fidelity_results[key] = {}
                    fidelity_results[key][name] = fidelity
                    
                    spd_key = f"{gate} Gate Speed (MHz)"
                    if spd_key not in speed_results: speed_results[spd_key] = {}
                    speed_results[spd_key][name] = 1000.0 / duration
                    
                    # Save plot for report
                    self._save_dynamics_plot(sim_result, name, gate, plotting_dir)
                    
                except Exception as e:
                    print(f"Simulation failed for {name}: {e}")
        
        results.update(fidelity_results)
        results.update(speed_results) # Aggregate directly
        return results

    def _compute_derived_metrics(self, current_results: Dict[str, Dict], qubit_objects: Dict[str, Any]) -> Dict[str, Dict]:
        """Compute metrics derived from others."""
        results = {}
        
        # Addressability = |Anharmonicity| * T1
        # Measures how many linewidths the non-computational state is separated by
        # Or proportional to max number of gates (speed limit ~ alpha)
        if "Anharmonicity (MHz)" in current_results and "T1 (μs)" in current_results:
            addr_values = {}
            for name in qubit_objects.keys():
                alpha = current_results["Anharmonicity (MHz)"].get(name, 0)
                t1 = current_results["T1 (μs)"].get(name, 0)
                # Use absolute value of anharmonicity
                addr_values[name] = abs(alpha) * t1
            results["Spectral Addressability (α·T1)"] = addr_values
            
        return results

    def _save_dynamics_plot(self, result: Dict, qubit_name: str, gate: str, output_dir: Path):
        """Save a plot of the dynamics using matplotlib."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        times = result["times"]
        expectations = result["expectations"]
        labels = result["labels"]
        
        plt.figure(figsize=(8, 4))
        for exp, label in zip(expectations, labels):
            plt.plot(times, exp, label=label)
        
        plt.xlabel("Time (ns)")
        plt.ylabel("Population")
        plt.title(f"{qubit_name} - {gate} Gate Dynamics")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(output_dir / f"{qubit_name}_{gate}_dynamics.png")
        plt.close()

    def generate_report(self, results: Dict[str, Dict], run_id: str, run_dir: Path):
        """Generate a MarkDown report for the comparison run."""
        report_path = run_dir / "comparison_report.md"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# QForge Comparison Report\n")
            f.write(f"**Run ID:** `{run_id}`\n\n")
            f.write(f"**Date:** {os.path.basename(str(run_dir)).split('_')[0]}\n\n")
            
            f.write("## 1. Executive Summary\n")
            # Determine winners
            f.write("| Metric | Winner | Value |\n")
            f.write("| :--- | :--- | :--- |\n")
            
            for metric, values in results.items():
                if not values: continue
                # Filter numerics
                numeric_values = {k: v for k, v in values.items() if isinstance(v, (int, float))}
                if not numeric_values: continue
                
                # Determine "best" (Higher is better usually, except maybe leakage? assuming higher fidelity/T1/freq)
                # Anharmonicity: magnitude usually desired to be large (negative or positive)
                # For simplicity assume max magnitude or max value
                if "Anharmonicity" in metric:
                     best_qubit = max(numeric_values, key=lambda k: abs(numeric_values[k]))
                     best_val = numeric_values[best_qubit]
                else:
                    best_qubit = max(numeric_values, key=numeric_values.get)
                    best_val = numeric_values[best_qubit]
                
                f.write(f"| {metric} | **{best_qubit}** | {best_val:.4f} |\n")
            
            f.write("\n## 2. Detailed Metrics\n")
            
            # Create a huge table? Or one per metric category?
            # Let's do one big table
            # Columns: Metric | Qubit 1 | Qubit 2 ...
            qubits = list(next(iter(results.values())).keys())
            
            header = "| Metric | " + " | ".join([f"**{q}**" for q in qubits]) + " |"
            sep = "| :--- | " + " | ".join([":---:" for _ in qubits]) + " |"
            
            f.write(header + "\n")
            f.write(sep + "\n")
            
            for metric, values in results.items():
                row = f"| {metric} | "
                for q in qubits:
                    val = values.get(q, "-")
                    if isinstance(val, float):
                        val = f"{val:.4f}"
                    row += f"{val} | "
                f.write(row + "\n")
            
            f.write("\n## 3. Visualization\n")
            # Embed plots
            plots_dir = run_dir / "plots"
            for plot_file in plots_dir.glob("*.png"):
                rel_path = f"plots/{plot_file.name}"
                f.write(f"### {plot_file.stem.replace('_', ' ').title()}\n")
                f.write(f"![{plot_file.stem}]({rel_path})\n\n")
                
        # Also print path for CLI
        print(f"Report generated: {report_path}")
    
    def save_comparison(self, results: Dict, output_path: str):
        """Legacy save method wrapper."""
        # Just dump JSON if requested specifically via CLI output override
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
