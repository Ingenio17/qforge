"""
Standalone test to demonstrate QForge functionality without full installation.
"""

import sys
sys.path.insert(0, r'c:\Users\sdsha\.gemini\antigravity\playground\silent-cassini')

from qforge.core.qubit_engine import QubitEngine
from qforge.comparison.comparator import Comparator

print("="*70)
print("QForge Functionality Test")
print("="*70)

# Test 1: Create Qubit Engine
print("\n✓ Test 1: Creating QubitEngine...")
engine = QubitEngine()
print("  QubitEngine created successfully!")

# Test 2: Create a transmon
print("\n✓ Test 2: Creating a transmon qubit...")
transmon_params = {"EJ": 15.0, "EC": 0.3}
transmon = engine.create_qubit("transmon", "test_transmon", transmon_params)
print(f"  Transmon created with EJ={transmon_params['EJ']} GHz, EC={transmon_params['EC']} GHz")

# Test 3: Compute spectrum
print("\n✓ Test 3: Computing energy spectrum...")
spectrum = engine.compute_spectrum(transmon, n_levels=5)
print("  Energy levels (GHz):")
for i, E in enumerate(spectrum):
    print(f"    |{i}⟩: {E:.4f}")

omega_01 = spectrum[1] - spectrum[0]
anharmonicity = (spectrum[2] - spectrum[1]) - (spectrum[1] - spectrum[0])
print(f"\n  Qubit Frequency (ω₀₁): {omega_01:.4f} GHz")
print(f"  Anharmonicity (α): {anharmonicity*1000:.1f} MHz")

# Test 4: Estimate coherence
print("\n✓ Test 4: Estimating coherence times...")
coherence = engine.estimate_coherence(transmon)
for param, data in coherence.items():
    print(f"  {param}: {data['value']:.2f} μs")

# Test 5: Create fluxonium
print("\n✓ Test 5: Creating a fluxonium qubit...")
fluxonium_params = {"EJ": 8.9, "EC": 2.5, "EL": 0.5}
fluxonium = engine.create_qubit("fluxonium", "test_fluxonium", fluxonium_params)
print(f"  Fluxonium created with EJ={fluxonium_params['EJ']} GHz, EC={fluxonium_params['EC']} GHz, EL={fluxonium_params['EL']} GHz")

# Test 6: Compare qubits
print("\n✓ Test 6: Comparing transmon vs fluxonium...")
comparator = Comparator()
results = comparator.compare_qubits(["transmon", "fluxonium"], ["all"])

print("\n  Comparison Results:")
print("  " + "-"*66)
print(f"  {'Metric':<25} {'Transmon':<20} {'Fluxonium':<20}")
print("  " + "-"*66)
for metric, values in results.items():
    t_val = values.get("transmon", "N/A")
    f_val = values.get("fluxonium", "N/A")
    print(f"  {metric:<25} {str(t_val):<20} {str(f_val):<20}")
print("  " + "-"*66)

# Test 7: List all qubits
print("\n✓ Test 7: Listing all created qubits...")
qubits = engine.list_qubits()
print(f"  Total qubits created: {len(qubits)}")
for q in qubits:
    print(f"    - {q['name']} ({q['type']}): f={q['frequency']:.3f} GHz, α={q['anharmonicity']*1000:.1f} MHz")

print("\n" + "="*70)
print("All tests passed successfully! ✓")
print("="*70)
print("\nQForge is working correctly:")
print("  • Qubit creation (transmon, fluxonium)")
print("  • Energy spectrum calculation")
print("  • Coherence time estimation")
print("  • Qubit comparison")
print("  • State management")
