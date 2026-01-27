"""
Terminal plotting utility using plotext.
"""

import plotext as plt
import numpy as np


class TerminalPlotter:
    """Helper class for terminal-based plotting."""
    
    @staticmethod
    def plot_time_evolution(times, expectations, labels, title="Time Evolution"):
        """
        Plot time evolution of expectation values.
        
        Args:
            times: Array of time points
            expectations: List of expectation value arrays
            labels: List of labels for each expectation value
            title: Plot title
        """
        plt.clear_figure()
        plt.theme("dark")
        
        times_list = list(times)
        for i, expect in enumerate(expectations):
            plt.plot(times_list, list(expect), label=labels[i])
            
        plt.title(title)
        plt.xlabel("Time (ns)")
        plt.ylabel("Expectation Value")
        plt.grid(True, True)
        plt.show()

    @staticmethod
    def plot_spectrum(energies, title="Energy Spectrum"):
        """
        Plot energy spectrum.
        
        Args:
            energies: Array of energy levels
            title: Plot title
        """
        plt.clear_figure()
        plt.theme("dark")
        
        # Plot levels as scatter points
        x = np.arange(len(energies)).tolist()
        energies_list = list(energies)
        plt.scatter(x, energies_list, label="Energy Levels", marker="hd")
        plt.plot(x, energies_list)  # Connect lines for visual flow
        
        plt.title(title)
        plt.xlabel("Level Index")
        plt.ylabel("Energy (GHz)")
        plt.grid(True, True)
        plt.show()
