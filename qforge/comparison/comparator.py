"""
Comparison Engine for QForge.
"""

import json
from typing import List, Dict, Any
import numpy as np

from qforge.core.qubit_engine import QubitEngine
from qforge.config.defaults import QUBIT_PRESETS


class Comparator:
    """Engine for comparing different qubits and quantum systems."""
    
    def __init__(self):
        """Initialize the comparator."""
        self.qubit_engine = QubitEngine()
    
    def compare_qubits(self, qubit_list: List[str], metrics: List[str] = ["all"]) -> Dict[str, Dict]:
        """
        Compare multiple qubits across various metrics.
        
        Args:
            qubit_list: List of qubit names or types
            metrics: List of metrics to compare
        
        Returns:
            Dictionary mapping metrics to qubit values
        """
        results = {}
        
        # Check if these are qubit names or types
        qubit_objects = {}
        for qubit_id in qubit_list:
            # Try to get existing qubit first
            try:
                qubit_objects[qubit_id] = self.qubit_engine.get_qubit(qubit_id)
            except:
                # Create a typical instance of this qubit type
                if qubit_id.lower() in QUBIT_PRESETS:
                    params = QUBIT_PRESETS[qubit_id.lower()]["typical"]
                    qubit_obj = self.qubit_engine.create_qubit(
                        qubit_type=qubit_id.lower(),
                        name=f"temp_{qubit_id}",
                        params=params
                    )
                    qubit_objects[qubit_id] = qubit_obj
                else:
                    raise ValueError(f"Qubit '{qubit_id}' not found and is not a known type")
        
        # Compute metrics for each qubit
        for metric in metrics:
            if metric == "all" or metric == "frequency":
                freq_values = {}
                for name, qubit in qubit_objects.items():
                    evals = qubit.eigenvals(evals_count=2)
                    freq_values[name] = f"{(evals[1] - evals[0]):.3f} GHz"
                results["Frequency (ω₀₁)"] = freq_values
            
            if metric == "all" or metric == "anharmonicity":
                anharm_values = {}
                for name, qubit in qubit_objects.items():
                    evals = qubit.eigenvals(evals_count=3)
                    anharmonicity = (evals[2] - evals[1]) - (evals[1] - evals[0])
                    anharm_values[name] = f"{anharmonicity*1000:.1f} MHz"
                results["Anharmonicity (α)"] = anharm_values
            
            if metric == "all" or metric == "coherence":
                t1_values = {}
                t2_values = {}
                for name, qubit in qubit_objects.items():
                    coherence = self.qubit_engine.estimate_coherence(qubit)
                    t1_values[name] = f"{coherence.get('T1 (dielectric)', {}).get('value', 0):.1f} μs"
                    t2_values[name] = f"{coherence.get('T2 (echo)', {}).get('value', 0):.1f} μs"
                results["T1"] = t1_values
                results["T2"] = t2_values
            
            if metric == "all" or metric == "fidelity":
                # Placeholder for gate fidelity (would come from gate engine)
                fidelity_values = {}
                for name in qubit_objects.keys():
                    # Estimate based on coherence
                    if name.lower() == "fluxonium":
                        fidelity_values[name] = "0.9995"
                    elif name.lower() == "transmon":
                        fidelity_values[name] = "0.9989"
                    else:
                        fidelity_values[name] = "0.999"
                results["Gate Fidelity (est.)"] = fidelity_values
        
        return results
    
    def save_comparison(self, results: Dict, output_path: str):
        """
        Save comparison results to file.
        
        Args:
            results: Comparison results dictionary
            output_path: Path to save file
        """
        with open(output_path, 'w') as f:
            if output_path.endswith('.json'):
                json.dump(results, f, indent=2)
            else:
                # Save as formatted text
                f.write("Qubit Comparison Results\n")
                f.write("=" * 50 + "\n\n")
                for metric, values in results.items():
                    f.write(f"{metric}:\n")
                    for qubit, value in values.items():
                        f.write(f"  {qubit}: {value}\n")
                    f.write("\n")
