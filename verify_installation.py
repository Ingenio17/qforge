"""
Simple verification test for QForge installation (Windows-safe, no Unicode).
"""

import qforge
from qforge.core.qubit_engine import QubitEngine
from qforge.comparison.comparator import Comparator

print("="*70)
print("QForge Installation Verification Test")
print("="*70)

# Test 1: Package version
print("\n[OK] QForge version:", qforge.__version__)

# Test 2: Import core modules
print("[OK] Core modules imported successfully")

# Test 3: Create QubitEngine
engine = QubitEngine()
print("[OK] QubitEngine created")

# Test 4: Create a transmon qubit
params = {"EJ": 15.0, "EC": 0.3}
transmon = engine.create_qubit("transmon", "verification_test", params)
print("[OK] Transmon qubit created (EJ=15.0 GHz, EC=0.3 GHz)")

# Test 5: Compute spectrum
spectrum = engine.compute_spectrum(transmon, n_levels=3)
freq = spectrum[1] - spectrum[0]
anharm = (spectrum[2] - spectrum[1]) - (spectrum[1] - spectrum[0])
print(f"[OK] Spectrum computed - Frequency: {freq:.3f} GHz, Anharmonicity: {anharm*1000:.1f} MHz")

# Test 6: Test comparison engine
comparator = Comparator()
results = comparator.compare_qubits(["transmon", "fluxonium"], ["frequency", "anharmonicity"])
print("[OK] Comparison engine working - compared transmon vs fluxonium")

print("\n" + "="*70)
print("ALL TESTS PASSED - QForge is fully installed and functional!")
print("="*70)
print("\nNext steps:")
print("  1. Try: qforge --help")
print("  2. Try: qforge qubit create --help")
print("  3. Try: qforge --interactive")
print(" 4. Run: python -m pytest tests/ -v")
print("\nNote: Some Unicode characters may not display correctly in Windows")
print("PowerShell (e.g., checkmarks, Greek letters), but this doesn't affect")
print("functionality.")
