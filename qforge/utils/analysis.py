"""
Enhanced qubit analysis and visualization tools.
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Tuple, Any


def plot_energy_spectrum(qubit, qubit_name: str, n_levels: int = 10, save_path: str = None):
    """
    Create comprehensive energy spectrum visualization.
    
    Args:
        qubit: scqubits qubit object
        qubit_name: Name of the qubit
        n_levels: Number of energy levels to plot
        save_path: Path to save figure (if None, display)
    
    Returns:
        Path to saved figure or None
    """
    fig, ax = plt.subplots(figsize=(12, 8))
    
    evals = qubit.eigenvals(evals_count=n_levels)
    
    # Plot energy levels as horizontal lines
    for i, energy in enumerate(evals):
        ax.hlines(energy, i-0.3, i+0.3, colors='blue', linewidth=4,
                 label=f'|{i}⟩' if i < 5 else None)
        ax.text(i+0.4, energy, f'{energy:.3f} GHz', fontsize=10)
    
    # Add transition arrows
    if len(evals) >= 2:
        omega_01 = evals[1] - evals[0]
        ax.annotate('', xy=(0.5, evals[1]), xytext=(0.5, evals[0]),
                   arrowprops=dict(arrowstyle='<->', color='red', lw=2.5))
        ax.text(0.7, (evals[0] + evals[1])/2, f'ω₀₁ = {omega_01:.4f} GHz',
               color='red', fontsize=11, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor='pink', alpha=0.5))
    
    if len(evals) >= 3:
        omega_12 = evals[2] - evals[1]
        alpha = omega_12 - omega_01
        ax.annotate('', xy=(1.5, evals[2]), xytext=(1.5, evals[1]),
                   arrowprops=dict(arrowstyle='<->', color='green', lw=2.5))
        ax.text(1.7, (evals[1] + evals[2])/2, f'ω₁₂ = {omega_12:.4f} GHz',
               color='green', fontsize=11, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.5))
        
        # Add anharmonicity callout
        ax.text(5, evals[0] + (evals[-1]-evals[0])*0.92,
               f'Anharmonicity α = {alpha*1000:.1f} MHz',
               fontsize=13, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    ax.set_xlabel("Energy Level", fontsize=14, fontweight='bold')
    ax.set_ylabel("Energy (GHz)", fontsize=14, fontweight='bold')
    ax.set_title(f"Energy Spectrum: {qubit_name}", fontsize=16, fontweight='bold')
    ax.set_xlim(-0.5, n_levels-0.5)
    ax.grid(True, alpha=0.3, axis='y', linestyle='--')
    if n_levels <= 10:
        ax.legend(loc='best', fontsize=10)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()
        return save_path
    else:
        plt.show()
        return None


def plot_parameter_sweep(qubit_type: str, param_name: str, param_range: np.ndarray,
                        fixed_params: Dict, property_name: str = "frequency",
                        save_path: str = None):
    """
    Sweep a qubit parameter and plot resulting property changes.
    
    Args:
        qubit_type: Type of qubit
        param_name: Parameter to sweep (e.g., 'EJ', 'EC')
        param_range: Array of parameter values
        fixed_params: Other fixed parameters
        property_name: What to plot ('frequency', 'anharmonicity', 'T1', etc.)
        save_path: Path to save figure
    
    Returns:
        tuple: (parameter_values, property_values, figure_path)
    """
    from qforge.core.qubit_engine import QubitEngine
    
    engine = QubitEngine()
    property_values = []
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for param_val in param_range:
        params = fixed_params.copy()
        params[param_name] = param_val
        
        try:
            qubit = engine.create_qubit(qubit_type, f"sweep_test_{param_val}", params)
            
            if property_name == "frequency":
                evals = qubit.eigenvals(evals_count=2)
                value = evals[1] - evals[0]
            elif property_name == "anharmonicity":
                evals = qubit.eigenvals(evals_count=3)
                omega_01 = evals[1] - evals[0]
                omega_12 = evals[2] - evals[1]
                value = (omega_12 - omega_01) * 1000  # in MHz
            elif property_name == "T1":
                coherence = engine.estimate_coherence(qubit)
                value = coherence.get("T1 (dielectric)", {}).get("value", 0)
            else:
                value = 0
            
            property_values.append(value)
        except:
            property_values.append(np.nan)
    
    # Plot
    ax.plot(param_range, property_values, 'o-', linewidth=2, markersize=6)
    ax.set_xlabel(f"{param_name} (GHz)", fontsize=12, fontweight='bold')
    
    if property_name == "frequency":
        ylabel = "Qubit Frequency ω₀₁ (GHz)"
    elif property_name == "anharmonicity":
        ylabel = "Anharmonicity α (MHz)"
    elif property_name == "T1":
        ylabel = "T1 Relaxation Time (μs)"
    else:
        ylabel = property_name
    
    ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')
    ax.set_title(f"{qubit_type.capitalize()} {property_name.capitalize()} vs {param_name}",
                fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()
    else:
        plt.show()
    
    return param_range, np.array(property_values), save_path


def plot_2d_parameter_sweep(qubit_type: str, param1_name: str, param1_range: np.ndarray,
                            param2_name: str, param2_range: np.ndarray,
                            other_params: Dict, property_name: str = "frequency",
                            save_path: str = None):
    """
    2D parameter sweep visualization (heatmap).
    
    Args:
        qubit_type: Type of qubit
        param1_name: First parameter to sweep
        param1_range: Array of first parameter values
        param2_name: Second parameter to sweep
        param2_range: Array of second parameter values
        other_params: Other fixed parameters
        property_name: What to plot
        save_path: Path to save figure
    
    Returns:
        tuple: (param1_vals, param2_vals, properties_2d, figure_path)
    """
    from qforge.core.qubit_engine import QubitEngine
    
    engine = QubitEngine()
    P1, P2 = np.meshgrid(param1_range, param2_range)
    properties_2d = np.zeros_like(P1)
    
    for i, p2_val in enumerate(param2_range):
        for j, p1_val in enumerate(param1_range):
            params = other_params.copy()
            params[param1_name] = p1_val
            params[param2_name] = p2_val
            
            try:
                qubit = engine.create_qubit(qubit_type, f"2d_sweep_{i}_{j}", params)
                
                if property_name == "frequency":
                    evals = qubit.eigenvals(evals_count=2)
                    value = evals[1] - evals[0]
                elif property_name == "anharmonicity":
                    evals = qubit.eigenvals(evals_count=3)
                    omega_01 = evals[1] - evals[0]
                    omega_12 = evals[2] - evals[1]
                    value = abs((omega_12 - omega_01) * 1000)  # in MHz
                else:
                    value = 0
                
                properties_2d[i, j] = value
            except:
                properties_2d[i, j] = np.nan
    
    # Plot heatmap
    fig, ax = plt.subplots(figsize=(10, 8))
    
    im = ax.contourf(P1, P2, properties_2d, levels=20, cmap='viridis')
    plt.colorbar(im, ax=ax, label=property_name)
    
    ax.set_xlabel(f"{param1_name} (GHz)", fontsize=12, fontweight='bold')
    ax.set_ylabel(f"{param2_name} (GHz)", fontsize=12, fontweight='bold')
    ax.set_title(f"{qubit_type.capitalize()} {property_name.capitalize()}: {param1_name} vs {param2_name}",
                fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()
    else:
        plt.show()
    
    return P1, P2, properties_2d, save_path
