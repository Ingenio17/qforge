"""
07_grovers_algorithm_simulation.py

Description:
Simulates Grover's Search Algorithm interactively. 
We search a 4-qubit Hilbert space (N=16 items) for a marked target state (|1010>), 
and demonstrate step-by-step how the probability amplifies with each cycle.

Terminal CLI Equivalents:
-------------------------
(Algorithmic validations occur natively via the Python Tensor API)
"""
import numpy as np
import qutip as qt

def get_h(N, target):
    op_list = [qt.qeye(2)] * N
    H_mat = (qt.sigmax() + qt.sigmaz()) / np.sqrt(2.0)
    op_list[target] = H_mat
    return qt.tensor(op_list)

def get_x(N, target):
    op_list = [qt.qeye(2)] * N
    op_list[target] = qt.sigmax()
    return qt.tensor(op_list)

def main():
    print("============================================================")
    print(" Example 07: Grover's Target Amplification (Step-by-Step)")
    print("============================================================")
    
    N = 4
    
    print("\n[THEORY]: Mathematical Amplification")
    print("An unsorted database of 2^4 = 16 entries initially assigns 1/16 (6.25%) ")
    print("probability to any item. Using amplitude amplification, we invert the phase ")
    print("of the target state, then invert all amplitudes around their mean. ")
    
    u_superposition = get_h(N, 3) * get_h(N, 2) * get_h(N, 1) * get_h(N, 0)
        
    print("\n[STEP 1]: Constructing Oracle for Secret State |1010> (Decimal 10)")
    oracle_mat = np.eye(16, dtype=complex)
    oracle_mat[10, 10] = -1 
    u_oracle = qt.Qobj(oracle_mat, dims=[[2]*4, [2]*4])
    
    print("[STEP 2]: Constructing Grover Diffusion Operator")
    u_x_all = get_x(N, 3) * get_x(N, 2) * get_x(N, 1) * get_x(N, 0)
    
    diff_mat = np.eye(16, dtype=complex)
    diff_mat[15, 15] = -1
    u_diff_z = qt.Qobj(diff_mat, dims=[[2]*4, [2]*4])
    
    u_diffusion = u_superposition * u_x_all * u_diff_z * u_x_all * u_superposition
    
    u_grover_step = u_diffusion * u_oracle
    
    psi0 = qt.tensor([qt.basis(2,0)]*4)
    current_state = u_superposition * psi0
    
    print("\n[OUTPUT]: Executing Grover Cycles and monitoring P(|1010>)")
    print("Expected: P(|1010>) should rise from 6.25% to near 100% after ~3 iterations.")
    
    print(f"\n   Initial Superposition: P(|1010>) = {np.abs(current_state.full()[10][0])**2 * 100:5.1f}%")
    
    for cycle in range(1, 4):
        current_state = u_grover_step * current_state
        amp = current_state.full()[10][0]
        prob = np.abs(amp)**2 * 100
        print(f"   After Cycle {cycle}:         P(|1010>) = {prob:5.1f}%")
            
    print("\n[CONCLUSION]:")
    print("Perfect target state finding executed seamlessly using strict spatial algebraic tensors.")

if __name__ == "__main__":
    main()
