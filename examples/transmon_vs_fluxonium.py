"""
Transmon vs Fluxonium Comparison Example

This example compares transmon and fluxonium qubits across multiple metrics:
- Operating frequency
- Anharmonicity
- Coherence times (T1, T2)
- Gate fidelity estimates
"""

import sys
import os
# Enable UTF-8 console for beautiful Unicode output
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from qforge.utils.console import enable_unicode_console
enable_unicode_console()

from qforge.core.qubit_engine import QubitEngine
from qforge.comparison.comparator import Comparator


def main():
    print("=" * 70)
    print("QForge Example: Transmon vs Fluxonium Comparison")
    print("=" * 70)
    
    # Initialize engines
    engine = QubitEngine()
    comparator = Comparator()
    
    # Create transmon with typical parameters
    print("\n1. Creating transmon qubit...")
    transmon_params = {
        "EJ": 15.0,
        "EC": 0.3,
        "ng": 0.0,
        "ncut": 30,
    }
    transmon = engine.create_qubit("transmon", "transmon", transmon_params)
    print("   ✓ Transmon created")
    
    # Create fluxonium with typical parameters
    print("\n2. Creating fluxonium qubit...")
    fluxonium_params = {
        "EJ": 8.9,
        "EC": 2.5,
        "EL": 0.5,
        "flux": 0.5,
        "cutoff": 110,
    }
    fluxonium = engine.create_qubit("fluxonium", "fluxonium", fluxonium_params)
    print("   ✓ Fluxonium created")
    
    # Compute properties for both
    print("\n3. Comparing properties...")
    print("\n" + "=" * 70)
    
    # Transmon properties
    t_spectrum = engine.compute_spectrum(transmon, n_levels=3)
    t_freq = t_spectrum[1] - t_spectrum[0]
    t_anharm = (t_spectrum[2] - t_spectrum[1]) - (t_spectrum[1] - t_spectrum[0])
    t_coherence = engine.estimate_coherence(transmon)
    
    # Fluxonium properties
    f_spectrum = engine.compute_spectrum(fluxonium, n_levels=3)
    f_freq = f_spectrum[1] - f_spectrum[0]
    f_anharm = (f_spectrum[2] - f_spectrum[1]) - (f_spectrum[1] - f_spectrum[0])
    f_coherence = engine.estimate_coherence(fluxonium)
    
    # Display comparison table
    print(f"{'Metric':<25} {'Transmon':<20} {'Fluxonium':<20} {'Winner'}")
    print("=" * 70)
    
    # Frequency
    print(f"{'Frequency (GHz)':<25} {t_freq:<20.3f} {f_freq:<20.3f} {'—'}")
    
    # Anharmonicity
    print(f"{'Anharmonicity (MHz)':<25} {t_anharm*1000:<20.1f} {f_anharm*1000:<20.1f} {'Fluxonium ✓' if abs(f_anharm) > abs(t_anharm) else 'Transmon ✓'}")
    
    # Coherence times
    t_t1 = t_coherence.get('T1 (dielectric)', {}).get('value', 0)
    f_t1 = f_coherence.get('T1 (dielectric)', {}).get('value', 0)
    print(f"{'T1 (μs)':<25} {t_t1:<20.1f} {f_t1:<20.1f} {'Fluxonium ✓' if f_t1 > t_t1 else 'Transmon ✓'}")
    
    t_t2 = t_coherence.get('T2 (echo)', {}).get('value', 0)
    f_t2 = f_coherence.get('T2 (echo)', {}).get('value', 0)
    print(f"{'T2 (μs)':<25} {t_t2:<20.1f} {f_t2:<20.1f} {'Fluxonium ✓' if f_t2 > t_t2 else 'Transmon ✓'}")
    
    print("=" * 70)
    
    # Summary
    print("\n4. Summary:")
    print(f"\n   Transmon:")
    print(f"     • Higher operating frequency ({t_freq:.2f} GHz)")
    print(f"     • Lower anharmonicity ({t_anharm*1000:.1f} MHz)")
    print(f"     • Shorter coherence times (T1={t_t1:.1f} μs, T2={t_t2:.1f} μs)")
    print(f"     • Best for: Fast gates, easier control")
    
    print(f"\n   Fluxonium:")
    print(f"     • Lower operating frequency ({f_freq:.2f} GHz)")
    print(f"     • Higher anharmonicity ({f_anharm*1000:.1f} MHz)")
    print(f"     • Longer coherence times (T1={f_t1:.1f} μs, T2={f_t2:.1f} μs)")
    print(f"     • Best for: Long-lived quantum states, reduced errors")
    
    print("\n" + "=" * 70)
    print("Comparison completed!")
    print("=" * 70)
    print("\nRun this comparison from CLI:")
    print("  qforge compare qubits --qubits transmon,fluxonium --metrics all")


if __name__ == "__main__":
    main()
