"""
Qubit Engine: Wrapper around scqubits for qubit physics modeling.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
# Lazy imports for heavy libraries to speed up CLI startup
# import scqubits as scq
# import matplotlib.pyplot as plt

from qforge.config.defaults import QUBIT_PRESETS, NOISE_DEFAULTS, OUTPUT_DIRS


class QubitEngine:
    """Engine for qubit modeling and physics calculations using scqubits."""

    # Frequency and anharmonicity follow from a qubit's type and parameters
    # alone, never from its name, so they are memoized for the life of the
    # process and shared across engine instances.
    #
    # This exists because listing qubits is a menu operation. The CLI wizard
    # redraws its main menu after every action, and both it and the GUI resolve
    # the qubit list again for each picker they open. Diagonalizing a fluxonium,
    # a zero-pi or a designed device on every one of those made the menus lag.
    # Sessions rebuild their qubit objects from the session file, which throws
    # away whatever scqubits had cached on the old objects, so the memo has to
    # live on the class rather than on a qubit.
    # It is also written to disk, so a fresh process (every CLI command is one)
    # does not repeat the work either. That mirrors how GateEngine persists its
    # pulse calibrations, and for the same reason.
    _metrics_cache: Dict[str, Tuple[float, float]] = {}
    _metrics_cache_loaded: bool = False
    _metrics_cache_dirty: bool = False
    _METRICS_CACHE_LIMIT = 512

    def __init__(self):
        """Initialize the qubit engine."""
        self._qubits = {}  # Store created qubits
        self._ensure_output_dirs()
        self._session_file = Path(OUTPUT_DIRS["qubits"]) / ".qforge_session.json"
        self._metrics_file = Path(OUTPUT_DIRS["qubits"]) / ".qforge_metrics.json"
        self._load_session()  # Load previously created qubits

    def load_session(self):
        """update session (all qubits) from disk."""
        self._load_session()
    
    def _ensure_output_dirs(self):
        """Create output directories if they don't exist."""
        for dir_path in OUTPUT_DIRS.values():
            Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    def _save_session(self):
        """Save current session (all qubits) to disk."""
        # Helper to convert numpy types to python types
        def convert(o):
            if isinstance(o, np.integer): return int(o)
            if isinstance(o, np.floating): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            raise TypeError

        session_data = {
            name: {
                "type": data["type"],
                "params": data["params"],
                "name": name,
            }
            for name, data in self._qubits.items()
        }
        
        try:
            with open(self._session_file, 'w') as f:
                json.dump(session_data, f, indent=2, default=convert)
        except Exception:
            # Silently fail if can't save - don't break user workflow
            pass
    
    def _load_session(self):
        """Load previous session (all qubits) from disk."""
        if not self._session_file.exists():
            return
        
        try:
            with open(self._session_file, 'r') as f:
                session_data = json.load(f)
            
            # Recreate qubits from session
            for name, qubit_data in session_data.items():
                try:
                    existing = self._qubits.get(name)
                    if (
                        existing is not None
                        and existing["type"] == qubit_data["type"]
                        and existing["params"] == qubit_data["params"]
                    ):
                        # Already in memory and unchanged on disk. Rebuilding it
                        # would only discard the eigenvalues scqubits has cached
                        # on the object, and the engines call load_session()
                        # constantly.
                        continue

                    qubit_obj = self._create_qubit_object(
                        qubit_data["type"],
                        qubit_data["params"]
                    )
                    self._qubits[name] = {
                        "object": qubit_obj,
                        "type": qubit_data["type"],
                        "params": qubit_data["params"],
                        "name": name,
                    }
                except Exception:
                    # Skip qubits that fail to load
                    pass
        except Exception:
            # If session file is corrupted, start fresh
            pass
    
    def _create_qubit_object(self, qubit_type, params):
        """Internal method to create qubit object from type and params."""
        import scqubits as scq
        from scqubits import Transmon, Fluxonium, FluxQubit, ZeroPi
        
        qubit_type = qubit_type.lower()
        
        if qubit_type == "transmon":
            ej = params.get("EJ", 15.0)
            ec = params.get("EC", 0.3)
            if ej <= 0 or ec <= 0:
                raise ValueError("Transmon energies (EJ, EC) must be positive.")
                
            return Transmon(
                EJ=ej,
                EC=ec,
                ng=params.get("ng", 0.0),
                ncut=params.get("ncut", 30),
                truncated_dim=params.get("truncated_dim", 4)
            )
        elif qubit_type == "fluxonium":
            return Fluxonium(
                EJ=params.get("EJ", 8.9),
                EC=params.get("EC", 2.5),
                EL=params.get("EL", 0.5),
                flux=params.get("flux", 0.5),
                cutoff=params.get("cutoff", 110),
                truncated_dim=params.get("truncated_dim", 4)
            )
        elif qubit_type == "flux":
            return FluxQubit(
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
                truncated_dim=params.get("truncated_dim", 4)
            )
        elif qubit_type == "zeropi":
            grid = params.get("grid", (-6.0, 6.0, 100))
            return ZeroPi(
                EJ=params.get("EJ", 10.0),
                EL=params.get("EL", 0.1),
                ECJ=params.get("ECJ", 20.0),
                EC=params.get("EC", 0.04),
                ng=params.get("ng", 0.0),
                flux=params.get("flux", 0.0),
                grid=scq.Grid1d(*grid),
                ncut=params.get("ncut", 30),
                truncated_dim=params.get("truncated_dim", 4)
            )
        elif qubit_type == "device":
            # A custom circuit designed from a netlist rather than one of the
            # four preset models. params carries the netlist source in full, so
            # a saved session rebuilds the identical circuit without depending
            # on the file it was written in. DeviceQubit adapts it to the same
            # interface the preset qubits present, so everything downstream
            # (gates, couplings, workflows, error correction) is unchanged.
            # Imported here, like scqubits above, to keep CLI startup light.
            from qforge.core.device_qubit import build_device_qubit

            return build_device_qubit(params)
        else:
            raise ValueError(f"Unknown qubit type: {qubit_type}")
    
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
        # Use the internal method to create qubit object
        qubit = self._create_qubit_object(qubit_type, params)
        
        # Store metadata
        self._qubits[name] = {
            "object": qubit,
            "type": qubit_type.lower(),
            "params": params,
            "name": name,
        }
        
        # Save session after creating qubit
        self._save_session()
        
        return qubit
    
    def get_qubit(self, name: str):
        """Get a qubit by name."""
        if name not in self._qubits:
            raise ValueError(f"Qubit '{name}' not found. Use 'qforge qubit list' to see available qubits.")
        return self._qubits[name]["object"]
    
    def delete_qubit(self, name: str):
        """
        Delete a qubit by name.
        
        Args:
            name: Name of the qubit to delete
        """
        if name not in self._qubits:
            raise ValueError(f"Qubit '{name}' not found.")
        
        del self._qubits[name]
        self._save_session()
    
    @staticmethod
    def _metrics_key(qubit_type: str, params: Dict[str, Any]) -> Optional[str]:
        """
        A deterministic cache key for one qubit's spectrum-derived metrics.

        The parameters are hashed rather than stored verbatim, because a
        device-backed qubit carries its entire netlist source in ``params`` and
        the key ends up on disk.

        Returns None for anything that will not serialize, in which case the
        metrics are computed and simply not memoized. Listing qubits must never
        fail because of the cache.
        """
        try:
            payload = json.dumps([qubit_type, params], sort_keys=True, default=repr)
        except Exception:
            return None
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _metrics_stamp() -> str:
        """
        Identifies what produced the cached numbers, so an upgrade discards them.

        The version is read from package metadata rather than by importing
        scqubits, which would undo the lazy import that keeps CLI startup quick.
        """
        try:
            from importlib.metadata import version
            return f"scqubits={version('scqubits')}"
        except Exception:
            return "scqubits=unknown"

    def _ensure_metrics_cache_loaded(self):
        """Read memoized metrics from disk, at most once per process."""
        if QubitEngine._metrics_cache_loaded:
            return
        QubitEngine._metrics_cache_loaded = True

        if not self._metrics_file.exists():
            return
        try:
            with open(self._metrics_file, 'r') as f:
                stored = json.load(f)
            if stored.get("stamp") != self._metrics_stamp():
                return  # A different scqubits computed these; recompute instead.
            for key, value in stored.get("entries", {}).items():
                # Honour the same bound the in-memory cache uses, so a large
                # file cannot grow the cache past it.
                if len(QubitEngine._metrics_cache) >= self._METRICS_CACHE_LIMIT:
                    break
                QubitEngine._metrics_cache[key] = (float(value[0]), float(value[1]))
        except Exception:
            # A corrupt or unreadable cache just means recomputing.
            QubitEngine._metrics_cache.clear()

    def _flush_metrics_cache(self):
        """Write newly computed metrics to disk, if there are any."""
        if not QubitEngine._metrics_cache_dirty:
            return
        QubitEngine._metrics_cache_dirty = False
        try:
            payload = {
                "stamp": self._metrics_stamp(),
                "entries": {k: list(v) for k, v in QubitEngine._metrics_cache.items()},
            }
            with open(self._metrics_file, 'w') as f:
                json.dump(payload, f)
        except Exception:
            # Same policy as the session file: never break a workflow over a cache.
            pass

    @classmethod
    def _remember_metrics(cls, key: str, metrics: Tuple[float, float]):
        """Memoize one qubit's metrics, dropping the oldest entry when full."""
        if len(cls._metrics_cache) >= cls._METRICS_CACHE_LIMIT:
            cls._metrics_cache.pop(next(iter(cls._metrics_cache)))
        cls._metrics_cache[key] = metrics
        cls._metrics_cache_dirty = True

    def _qubit_metrics(self, data: Dict[str, Any]) -> Tuple[float, float]:
        """
        Frequency and anharmonicity in GHz for one registered qubit.

        Diagonalizes on the first request for a given type and parameter set,
        then answers from the memo.
        """
        self._ensure_metrics_cache_loaded()

        key = self._metrics_key(data["type"], data.get("params", {}))
        if key is not None:
            cached = QubitEngine._metrics_cache.get(key)
            if cached is not None:
                return cached

        try:
            evals = data["object"].eigenvals(evals_count=3)
            frequency = float(evals[1] - evals[0])
            anharmonicity = float((evals[2] - evals[1]) - (evals[1] - evals[0]))
        except Exception:
            frequency = 0.0
            anharmonicity = 0.0

        # A failure is cached too: the same type and parameters will fail the
        # same way, and retrying a slow diagonalization on every redraw is the
        # thing this cache exists to avoid.
        metrics = (frequency, anharmonicity)
        if key is not None:
            self._remember_metrics(key, metrics)
        return metrics

    def list_qubit_names(self) -> List[str]:
        """
        Names of every registered qubit, in the order they were created.

        Nothing is diagonalized, so this is the call to use for menus, pickers
        and duplicate-name checks that need the names and not the physics.
        """
        return list(self._qubits.keys())

    def list_qubits(self) -> List[Dict]:
        """List all created qubits with their properties."""
        qubit_list = []

        for name, data in self._qubits.items():
            frequency, anharmonicity = self._qubit_metrics(data)

            qubit_list.append({
                "name": name,
                "type": data["type"],
                "frequency": frequency,
                "anharmonicity": anharmonicity,
            })

        # One write per listing pass at most, rather than one per qubit.
        self._flush_metrics_cache()

        return qubit_list
    
    def compute_spectrum(self, qubit, n_levels: int = 5, subtract_ground: bool = False) -> np.ndarray:
        """
        Compute energy spectrum of the qubit.
        
        Args:
            qubit: scqubits qubit object
            n_levels: Number of energy levels to compute
            subtract_ground: Whether to subtract ground state energy (setting E0 = 0)
        
        Returns:
            Array of energy eigenvalues
        """
        evals = qubit.eigenvals(evals_count=n_levels)
        if subtract_ground and len(evals) > 0:
            evals = evals - evals[0]
        return evals
    
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
            import scqubits as scq
            scq.settings.T1_DEFAULT_WARNING = False

            # T1 from dielectric loss
            # scqubits returns time in units of 1/frequency.
            # Since frequency is in GHz, time is in ns.
            t1_diel_ns = qubit.t1_capacitive(
                T=temperature,
                Q_cap=1e6  # Quality factor
            )
            t1_diel_us = t1_diel_ns / 1000.0  # Convert ns to μs
            
            coherence_data["T1 (dielectric)"] = {
                "value": t1_diel_us,
                "limit": "Capacitive loss"
            }
        except:
            # Fallback to typical values
            t1_diel_us = NOISE_DEFAULTS.get(qubit_type, {}).get("T1_dielectric", 50.0)
            coherence_data["T1 (dielectric)"] = {
                "value": t1_diel_us,
                "limit": "Estimated"
            }
        
        try:
            # T2 from dephasing
            # T2 ≈ 2*T1 in the best case (no pure dephasing)
            t2_estimate = 2 * t1_diel_us * 0.7  # Factor of 0.7 accounts for typical pure dephasing
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
    
    def visualize(self, qubit, plot_type: str = "spectrum", save: bool = True, subtract_ground: bool = False):
        """
        Visualize qubit properties.
        
        Args:
            qubit: scqubits qubit object
            plot_type: Type of visualization (spectrum, wavefunctions, matrix_elements)
            save: Whether to save the plot
            subtract_ground: Whether to subtract ground state energy (for spectrum)
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        if plot_type == "spectrum":
            # Plot energy spectrum
            evals = qubit.eigenvals(evals_count=10)
            if subtract_ground and len(evals) > 0:
                evals = evals - evals[0]
            ax.plot(range(len(evals)), evals, 'o-', linewidth=2, markersize=8)
            ax.set_xlabel("Energy Level", fontsize=12)
            ax.set_ylabel("Energy (GHz)", fontsize=12)
            ax.set_title("Energy Spectrum" + (" (Relative)" if subtract_ground else ""), fontsize=14)
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
    
    def visualize_enhanced(self, qubit, plot_types: list = None, save: bool = True, subtract_ground: bool = False):
        """
        Create comprehensive visualizations for a qubit.
        
        Args:
            qubit: scqubits qubit object
            plot_types: List of plot types to generate
                Options: "spectrum", "wavefunctions", "matrix_elements", "potential"
                If None, generates all applicable plots
            save: Whether to save plots
            subtract_ground: Whether to subtract ground state energy (for spectrum)
        
        Returns:
            dict: Mapping plot_type -> file_path
        """
        import matplotlib
        matplotlib.use('Agg')
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
                    path = plot_energy_spectrum(qubit, qubit_name, save_path=save_path, subtract_ground=subtract_ground)
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
