"""
01_qubit_creation.py

Description:
This example introduces qforge's core feature: treating qubits as physical, multi-level 
superconducting circuits. It creates qubits, calculates their spectrum, and extracts 
physical operators.

Terminal CLI Equivalents:
-------------------------
qforge qubit create --type transmon --name T1 --EJ 15.0 --EC 0.3
qforge qubit analyze --name T1

qforge qubit create --type fluxonium --name F1 --EJ 9.0 --EC 2.4 --EL 0.5
qforge qubit analyze --name F1
"""
import numpy as np
from qforge import QubitEngine

def main():
    print("============================================================")
    print(" Example 01: Physical Qubit Creation and Analysis")
    print("============================================================")
    
    eng = QubitEngine()

    print("\n[STEP 1]: Creating a Transmon Qubit")
    eng.create_qubit("transmon", "T1", {"EJ": 15.0, "EC": 0.3, "truncated_dim": 6})
    t1 = eng.get_qubit("T1")
    
    print("\n[OUTPUT]: Transmon Energy Spectrum (GHz)")
    evals_t1, _ = t1.eigensys(evals_count=4)
    for i, ev in enumerate(evals_t1):
        print(f"   State |{i}> Energy: {ev:8.3f} GHz   (Frequency wrt |0>: {ev - evals_t1[0]:8.3f} GHz)")
        
    print("\n[STEP 2]: Creating a Fluxonium Qubit")
    eng.create_qubit("fluxonium", "F1", {"EJ": 9.0, "EC": 2.4, "EL": 0.5, "truncated_dim": 10})
    f1 = eng.get_qubit("F1")
    
    print("\n[OUTPUT]: Fluxonium Energy Spectrum (GHz)")
    evals_f1, _ = f1.eigensys(evals_count=4)
    for i, ev in enumerate(evals_f1):
        print(f"   State |{i}> Energy: {ev:8.3f} GHz   (Frequency wrt |0>: {ev - evals_f1[0]:8.3f} GHz)")
    
    print("\n[OUTPUT]: Analyzing the Charge Operator <i|n|j> Matrix for capacitive coupling")
    
    n_mat = f1.matrixelement_table("n_operator", evals_count=4)
    np.set_printoptions(precision=2, suppress=True)
    for r in range(4):
        row_str = " | ".join([f"{val.real:5.2f} + {val.imag:5.2f}j" for val in n_mat[r][:4]])
        print(f"   < {r} | n | j > : [{row_str}]")

if __name__ == "__main__":
    main()
