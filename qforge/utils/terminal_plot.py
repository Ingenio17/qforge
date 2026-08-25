"""
Terminal plotting utility using plotext.
"""

import plotext as plt
import numpy as np
import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


class TerminalPlotter:
    """Helper class for terminal-based plotting."""
    
    @staticmethod
    def plot_time_evolution(times, expectations, labels, title="Time Evolution", ylim=None, height=25):
        """
        Plot time evolution of expectation values.
        
        Args:
            times: Array of time points
            expectations: List of expectation value arrays
            labels: List of labels for each expectation value
            title: Plot title
            ylim: Tuple of (min_y, max_y) to force axis limits (optional)
            height: Maximum vertical lines for the plot (prevents terminal wrapping)
        """
        plt.clear_figure()
        plt.theme("dark")

        # Force a specific plot size to prevent the terminal buffer from overflowing.
        # limit_size(False, False) is required here: plotext otherwise silently caps
        # plotsize() to the auto-detected terminal width, which in a non-TTY context
        # (e.g. output captured by a GUI console redirector rather than a real
        # terminal) commonly falls back to ~80 columns regardless of what is
        # requested, making the box a different size than intended.
        plt.limit_size(False, False)
        plt.plotsize(100, height)

        times_list = list(times)
        for i, expect in enumerate(expectations):
            plt.plot(times_list, list(expect), label=labels[i])

        plt.title(title)
        plt.xlabel("Time (ns)")
        plt.ylabel("Expectation Value")

        if ylim is not None:
            plt.ylim(ylim[0], ylim[1])

        # Horizontal gridlines only: plotext draws a vertical gridline in the
        # same column as (or immediately beside) the plot's right-hand border
        # whenever grid(True, True) is used, which renders as a doubled/split
        # vertical line down the right edge instead of a single clean border.
        # Horizontal gridlines don't touch the border and render correctly.
        plt.grid(True, False)
        plt.show()

    @staticmethod
    def plot_spectrum(energies, title="Energy Spectrum", height=25):
        """
        Plot energy spectrum.

        Args:
            energies: Array of energy levels
            title: Plot title
            height: Maximum vertical lines for the plot (prevents terminal wrapping)
        """
        plt.clear_figure()
        plt.theme("dark")

        # See plot_time_evolution() above for why both of these are required:
        # limit_size(False, False) stops plotext from silently capping the
        # requested plotsize() to whatever (possibly wrong) width it
        # auto-detects in a non-TTY context, and grid(True, False) avoids the
        # vertical-gridline/right-border collision that otherwise renders as
        # a doubled/broken box outline.
        plt.limit_size(False, False)
        plt.plotsize(100, height)

        # Plot levels as scatter points
        x = np.arange(len(energies)).tolist()
        energies_list = list(energies)
        plt.scatter(x, energies_list, label="Energy Levels", marker="hd")
        plt.plot(x, energies_list)  # Connect lines for visual flow

        plt.title(title)
        plt.xlabel("Level Index")
        plt.ylabel("Energy (GHz)")
        plt.grid(True, False)
        plt.show()