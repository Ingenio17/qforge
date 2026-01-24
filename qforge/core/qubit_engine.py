"""
Qubit Engine: Wrapper around scqubits for qubit physics modeling.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import scqubits as scq
from scqubits import Transmon, Fluxonium, FluxQubit, ZeroPi
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for terminal use
import matplotlib.pyplot as plt

from qforge.config.defaults import QUBIT_PRESETS, NOISE_DEFAULTS, OUTPUT_DIRS


class QubitEngine:
    """Engine for qubit modeling and physics calculations using scqubits."""
    
    def __init__(self):
        """Initialize the qubit engine."""
        self._qubits = {}  # Store created qubits
        self._ensure_output_dirs()
    
    def _ensure_output_dirs(self):
        """Create output directories if they don't exist."""
        for dir_path in OUTPUT_DIRS.values():
            Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    def create_qubit(self, qubit_type: str, name: str, params: Dict[str, Any]):
        """
        Create a qubit instance.
        
        Args:
            qubit_type: Type of qubit (transmon, fluxonium, flux, zeropi)
            name: Name for the qubit
            params: Qubit parameters
        
        Returns:
            scqubits qubit object
        """
        qubit_type = qubit_type.lower()
        
        # Create the appropriate scqubits object
        if qubit_type == "transmon":
            qubit = Transmon(
                EJ=params.get("EJ", 15.0),
                EC=params.get("EC", 0.3),
                ng=params.get("ng", 0.0),
                ncut=params.get("ncut", 30),
                truncated_dim=params.get("truncated_dim", 10)
            )
        
        elif qubit_type == "fluxonium":
            qubit = Fluxonium(
                EJ=params.get("EJ", 8.9),
                EC=params.get("EC", 2.5),
                EL=params.get("EL", 0.5),
                flux=params.get("flux", 0.5),
                cutoff=params.get("cutoff", 110),
                truncated_dim=params.get("truncated_dim", 10)
            )
        
        elif qubit_type == "flux":
            qubit = FluxQubit(
                EJ1=params.get("EJ1", 10.0),
                EJ2=params.get("EJ2", 10.0),
                EJ3=params.get("EJ3", 10.0),
                ECJ1=params.get("ECJ1", 1.0),
                ECJ2=params.get("ECJ2", 1.0),
                ECJ3=params.get("ECJ3", 1.0),
                ECg1=params.get("ECg1", 50.0),
                ECg2=params.get("ECg2", 50.0),
                ng1=params.get("ng1", 0.0),
                ng2=params.get("ng2", 0.0),
                flux=params.get("flux", 0.5),
                ncut=params.get("ncut", 10),
                truncated_dim=params.get("truncated_dim", 10)
            )
        
        elif qubit_type == "zeropi":
            grid = params.get("grid", (-6.0, 6.0, 100))
            qubit = ZeroPi(
                EJ=params.get("EJ", 10.0),
                EL=params.get("EL", 0.1),
                ECJ=params.get("ECJ", 20.0),
                EC=params.get("EC", 0.04),
                ng=params.get("ng", 0.0),
                flux=params.get("flux", 0.0),
                grid=scq.Grid1d(*grid),
                ncut=params.get("ncut", 30),
                truncated_dim=params.get("truncated_dim", 10)
            )
        
        else:
            raise ValueError(f"Unknown qubit type: {qubit_type}")
        
        # Store metadata
        self._qubits[name] = {
            "object": qubit,
            "type": qubit_type,
            "params": params,
            "name": name,
        }
        
        return qubit
    
    def get_qubit(self, name: str):
        """Get a qubit by name."""
        if name not in self._qubits:
            raise ValueError(f"Qubit '{name}' not found. Use 'qforge qubit list' to see available qubits.")
        return self._qubits[name]["object"]
    
    def list_qubits(self) -> List[Dict]:
        """List all created qubits with their properties."""
        qubit_list = []
        
        for name, data in self._qubits.items():
            qubit = data["object"]
            
            # Compute basic properties
            try:
                evals = qubit.eigenvals(evals_count=3)
                frequency = evals[1] - evals[0]
                anharmonicity = (evals[2] - evals[1]) - (evals[1] - evals[0])
            except:
                frequency = 0.0
                anharmonicity = 0.0
            
            qubit_list.append({
                "name": name,
                "type": data["type"],
                "frequency": frequency,
                "anharmonicity": anharmonicity,
            })
        
        return qubit_list
    
    def compute_spectrum(self, qubit, n_levels: int = 5) -> np.ndarray:
        """
        Compute energy spectrum of the qubit.
        
        Args:
            qubit: scqubits qubit object
            n_levels: Number of energy levels to compute
        
        Returns:
            Array of energy eigenvalues
        """
        return qubit.eigenvals(evals_count=n_levels)
    
    def estimate_coherence(self, qubit, temperature: float = 0.015) -> Dict[str, Dict]:
        """
        Estimate coherence times for the qubit.
        
        Args:
            qubit: scqubits qubit object
            temperature: Bath temperature in Kelvin
        
        Returns:
            Dictionary with coherence time estimates
        """
        # Get qubit type from stored data
        qubit_type = None
        for data in self._qubits.values():
            if data["object"] is qubit:
                qubit_type = data["type"]
                break
        
        if qubit_type is None:
            qubit_type = "transmon"  # Default assumption
        
        # Use scqubits built-in coherence calculations when available
        coherence_data = {}
        
        try:
            # T1 from dielectric loss
            t1_diel = qubit.t1_capacitive(
                T=temperature,
                Q_cap=1e6  # Quality factor
            )
            coherence_data["T1 (dielectric)"] = {
                "value": t1_diel * 1e6,  # Convert to μs
                "limit": "Capacitive loss"
            }
        except:
            # Fallback to typical values
            t1_diel = NOISE_DEFAULTS.get(qubit_type, {}).get("T1_dielectric", 50.0)
            coherence_data["T1 (dielectric)"] = {
                "value": t1_diel,
                "limit": "Estimated"
            }
        
        try:
            # T2 from dephasing
            # T2 ≈ 2*T1 in the best case (no pure dephasing)
            t2_estimate = 2 * t1_diel * 0.7  # Factor of 0.7 accounts for typical pure dephasing
            coherence_data["T2 (echo)"] = {
                "value": t2_estimate,
                "limit": "Estimated from T1"
            }
        except:
            t2_echo = NOISE_DEFAULTS.get(qubit_type, {}).get("T2_echo", 35.0)
            coherence_data["T2 (echo)"] = {
                "value": t2_echo,
                "limit": "Estimated"
            }
        
        return coherence_data
    
    def visualize(self, qubit, plot_type: str = "spectrum", save: bool = True):
        """
        Visualize qubit properties.
        
        Args:
            qubit: scqubits qubit object
            plot_type: Type of visualization (spectrum, wavefunctions, matrix_elements)
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(10, 6))
        
        if plot_type == "spectrum":
            # Plot energy spectrum
            evals = qubit.eigenvals(evals_count=10)
            ax.plot(range(len(evals)), evals, 'o-', linewidth=2, markersize=8)
            ax.set_xlabel("Energy Level", fontsize=12)
            ax.set_ylabel("Energy (GHz)", fontsize=12)
            ax.set_title("Energy Spectrum", fontsize=14)
            ax.grid(True, alpha=0.3)
        
        elif plot_type == "wavefunctions":
            # Plot wavefunctions for first few states
            qubit.plot_wavefunction(which=[0, 1, 2], mode='real')
            ax = plt.gca()
        
        if save:
            # Find qubit name
            qubit_name = "unknown"
            for name, data in self._qubits.items():
                if data["object"] is qubit:
                    qubit_name = name
                    break
            
            output_path = Path(OUTPUT_DIRS["plots"]) / f"{qubit_name}_{plot_type}.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            return str(output_path)
        else:
            plt.show()
    
    def export_to_qutip(self, qubit, output_path: str):
        """
        Export qubit Hamiltonian to QuTiP format.
        
        Args:
            qubit: scqubits qubit object
            output_path: Path to save the Hamiltonian
        """
        import pickle
        
        # Get Hamiltonian in QuTiP format
        H = qubit.hamiltonian()  # Returns QuTiP Qobj
        
        # Save as pickle
        with open(output_path, 'wb') as f:
            pickle.dump(H, f)
    
    def export_to_qiskit(self, qubit, output_path: str):
        """
        Export qubit parameters for Qiskit noise modeling.
        
        Args:
            qubit: scqubits qubit object
            output_path: Path to save parameters
        """
        # Get qubit name and type
        qubit_name = "unknown"
        qubit_type = "unknown"
        params = {}
        
        for name, data in self._qubits.items():
            if data["object"] is qubit:
                qubit_name = name
                qubit_type = data["type"]
                params = data["params"]
                break
        
        # Compute relevant parameters
        evals = qubit.eigenvals(evals_count=3)
        frequency = evals[1] - evals[0]
        anharmonicity = (evals[2] - evals[1]) - (evals[1] - evals[0])
        
        # Create export data
        export_data = {
            "name": qubit_name,
            "type": qubit_type,
            "parameters": params,
            "frequency_GHz": float(frequency),
            "anharmonicity_GHz": float(anharmonicity),
            "T1_us": 50.0,  # Placeholder - would come from coherence estimation
            "T2_us": 35.0,   # Placeholder
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
    
    def save_qubit(self, qubit, output_path: str):
        """
        Save qubit to JSON file.
        
        Args:
            qubit: scqubits qubit object
            output_path: Path to save file
        """
        # Find qubit data
        for name, data in self._qubits.items():
            if data["object"] is qubit:
                save_data = {
                    "name": name,
                    "type": data["type"],
                    "parameters": data["params"],
                }
                
                with open(output_path, 'w') as f:
                    json.dump(save_data, f, indent=2)
                return
        
        raise ValueError("Qubit not found in engine")
    
    def load_qubit(self, input_path: str) -> Any:
        """
        Load qubit from JSON file.
        
        Args:
            input_path: Path to qubit file
        
        Returns:
            scqubits qubit object
        """
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        return self.create_qubit(
            qubit_type=data["type"],
            name=data["name"],
            params=data["parameters"]
        )
    
    def parameter_sweep(self, qubit_type: str, param_name: str, param_range, 
                       fixed_params: dict, property_name: str = "frequency"):
        """
        Sweep a parameter and compute resulting properties.
        
        Args:
            qubit_type: Type of qubit
            param_name: Parameter to sweep
            param_range: Range of values (list or array)
            fixed_params: Fixed parameters
            property_name: Property to compute (frequency, anharmonicity, T1)
        
        Returns:
            dict with parameter values and property values
        """
        import numpy as np
        
        results = {
            "parameter": param_name,
            "parameter_values": [],
            "property": property_name,
            "property_values": []
        }
        
        for param_val in param_range:
            params = fixed_params.copy()
            params[param_name] = param_val
            
            try:
                # Create temporary qubit
                qubit = self.create_qubit(qubit_type, f"_sweep_temp", params)
                
                # Compute requested property
                if property_name == "frequency":
                    evals = qubit.eigenvals(evals_count=2)
                    value = evals[1] - evals[0]
                elif property_name == "anharmonicity":
                    evals = qubit.eigenvals(evals_count=3)
                    omega_01 = evals[1] - evals[0]
                    omega_12 = evals[2] - evals[1]
                    value = (omega_12 - omega_01) * 1000  # MHz
                elif property_name == "T1":
                    coherence = self.estimate_coherence(qubit)
                    value = coherence.get("T1 (dielectric)", {}).get("value", 0)
                elif property_name == "T2":
                    coherence = self.estimate_coherence(qubit)
                    value = coherence.get("T2 (echo)", {}).get("value", 0)
                else:
                    value = 0
                
                results["parameter_values"].append(param_val)
                results["property_values"].append(value)
                
            except Exception as e:
                # Skip failed calculations
                pass
        
        return results
    
    def visualize_enhanced(self, qubit, plot_types: list = None, save: bool = True):
        """
        Create comprehensive visualizations for a qubit.
        
        Args:
            qubit: scqubits qubit object
            plot_types: List of plot types to generate
                Options: "spectrum", "wavefunctions", "matrix_elements", "potential"
                If None, generates all applicable plots
            save: Whether to save plots
        
        Returns:
            dict: Mapping plot_type -> file_path
        """
        import matplotlib.pyplot as plt
        from pathlib import Path
        
        if plot_types is None:
            plot_types = ["spectrum", "wavefunctions", "potential"]
        
        # Find qubit name
        qubit_name = "unknown"
        for name, data in self._qubits.items():
            if data["object"] is qubit:
                qubit_name = name
                break
        
        saved_plots = {}
        
        for plot_type in plot_types:
            try:
                if plot_type == "spectrum":
                    # Enhanced energy spectrum
                    from qforge.utils.analysis import plot_energy_spectrum
                    save_path = None
                    if save:
                        save_path = str(Path(OUTPUT_DIRS["plots"]) / f"{qubit_name}_spectrum.png")
                    path = plot_energy_spectrum(qubit, qubit_name, save_path=save_path)
                    if path:
                        saved_plots[plot_type] = path
                
                elif plot_type == "wavefunctions":
                    # Use scqubits built-in
                    qubit.plot_wavefunction(which=[0, 1, 2, 3], mode='real')
                    plt.suptitle(f"Wavefunctions: {qubit_name}", fontsize=14, fontweight='bold')
                    if save:
                        save_path = Path(OUTPUT_DIRS["plots"]) / f"{qubit_name}_wavefunctions.png"
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        plt.savefig(save_path, dpi=150, bbox_inches='tight')
                        plt.close()
                        saved_plots[plot_type] = str(save_path)
                    else:
                        plt.show()
                
                elif plot_type == "potential":
                    # Use scqubits potential plot
                    try:
                        qubit.plot_potential()
                        plt.suptitle(f"Potential: {qubit_name}", fontsize=14, fontweight='bold')
                        if save:
                            save_path = Path(OUTPUT_DIRS["plots"]) / f"{qubit_name}_potential.png"
                            save_path.parent.mkdir(parents=True, exist_ok=True)
                            plt.savefig(save_path, dpi=150, bbox_inches='tight')
                            plt.close()
                            saved_plots[plot_type] = str(save_path)
                        else:
                            plt.show()
                    except:
                        pass  # Not all qubits support potential plots
                
            except Exception as e:
                print(f"Warning: Could not generate {plot_type} plot: {e}")
        
        return saved_plots
