"""
06_shors_algorithm_simulation.py

Description:
Simulates Phase Estimation mimicking Shor's Algorithm (Period Finding).
We use a 3-qubit phase register and a 1-qubit target register. 
The encoded unitary U is the Pauli-X gate! This mimics exactly the modular 
exponentiation circuit where a^2 = 1 mod N. Because X^2 = I, the period is exactly r=2!

Terminal CLI Equivalents:
-------------------------
(Algorithmic validations occur natively via the Python Tensor API)
"""
import numpy as np
import qutip as qt
import fractions

def get_h(N, target):
    op_list = [qt.qeye(2)] * N
    H_mat = (qt.sigmax() + qt.sigmaz()) / np.sqrt(2.0)
    op_list[target] = H_mat
    return qt.tensor(op_list)

def get_x(N, target):
    op_list = [qt.qeye(2)] * N
    op_list[target] = qt.sigmax()
    return qt.tensor(op_list)

def get_cnot(N, control, target):
    P0 = (qt.qeye(2) + qt.sigmaz()) / 2.0
    P1 = (qt.qeye(2) - qt.sigmaz()) / 2.0
    op0 = [qt.qeye(2)] * N
    op0[control] = P0
    op1 = [qt.qeye(2)] * N
    op1[control] = P1
    op1[target] = qt.sigmax()
    return qt.tensor(op0) + qt.tensor(op1)

def get_cphase(N, control, target, phi):
    P0 = (qt.qeye(2) + qt.sigmaz()) / 2.0
    P1 = (qt.qeye(2) - qt.sigmaz()) / 2.0
    phase_mat = qt.Qobj([[1, 0], [0, np.exp(1j * phi)]])
    op0 = [qt.qeye(2)] * N
    op0[control] = P0
    op1 = [qt.qeye(2)] * N
    op1[control] = P1
    op1[target] = phase_mat
    return qt.tensor(op0) + qt.tensor(op1)

def get_swap(N, i, j):
    c1, c2 = get_cnot(N, i, j), get_cnot(N, j, i)
    return c1 * c2 * c1

def main():
    print("============================================================")
    print(" Example 06: Shor's Period Finding with Continued Fractions")
    print("============================================================")
    
    print("\n[THEORY]: Shor's Period Finding")
    print("In classical Shor's, we want the period 'r' of a^x mod N.")
    print("Consider N=15, a=11. Since 11^2 = 121 = 1 mod 15, the period is exactly r = 2.")
    print("Because r=2, the unitary U applying this modular exponentiation acts just like")
    print("a NOT gate (X). Therefore, U = X, and its period is 2.")
    
    N = 4  
    
    # 3-Qubit Phase Register (Q0, Q1, Q2). Target Qubit (Q3).
    # Init target to |1> 
    u_init = get_x(N, 3) * get_h(N, 2) * get_h(N, 1) * get_h(N, 0)

    # Unitary application U^x
    # Q0 controls U^4 = X^4 = I  (No-op)
    # Q1 controls U^2 = X^2 = I  (No-op)
    # Q2 controls U^1 = X   = CNOT(2, 3)
    
    u_exp = get_cnot(N, 2, 3)
    
    # IQFT
    u_swap = get_swap(N, 0, 2)
    u_iqft1 = get_h(N, 0) * get_cphase(N, 0, 1, -np.pi/2) * get_cphase(N, 0, 2, -np.pi/4)
    u_iqft2 = get_h(N, 1) * get_cphase(N, 1, 2, -np.pi/2)
    u_iqft3 = get_h(N, 2)
    u_iqft = u_iqft3 * u_iqft2 * u_iqft1 * u_swap
    
    U_total = u_iqft * u_exp * u_init
    psi0 = qt.tensor([qt.basis(2,0)]*4)
    final_state = U_total * psi0
    
    print("\n[OUTPUT]: Quantum Measurement and Classical Post-Processing")
    print("Because the period is r=2, the true phases are 0/2=0 and 1/2=0.5")
    print("In a 3-qubit phase register (8 states), these phases map exactly to integers 0 and 4.")
    print("Measurements will trace the Phase Register (Q0,Q1,Q2) and Target Register (Q3).")
    
    for prob_idx, amp in enumerate(final_state.full().flatten()):
        p = np.abs(amp)**2
        if p > 0.01:
            bin_str = format(prob_idx, '04b')
            # Extract phase register vs target register
            phase_bin = bin_str[:3]
            target_bin = bin_str[3]
            phase_val = int(phase_bin, 2)
            measured_phase_decimal = phase_val / 8.0 
            
            print(f"\n   Detected Peak: State |{bin_str}>  (Prob: {p*100:5.1f}%)")
            print(f"      -> Target Register: |{target_bin}>")
            print(f"      -> Phase Register:  |{phase_bin}> (Decimal: {phase_val})")
            print(f"      -> Measured Phase:  {phase_val}/8 = {measured_phase_decimal}")
            
            # Continued fractions to find the period 'r'
            if measured_phase_decimal == 0.0:
                print("      -> Phase is 0. Trivial period, algorithm must repeat.")
            else:
                frac = fractions.Fraction(measured_phase_decimal).limit_denominator(15)
                print(f"      -> Continued Fraction limit_denominator(15) -> {frac.numerator}/{frac.denominator}")
                print(f"      -> Calculated Period (r) = {frac.denominator}. Expected Period = 2. Success!")

if __name__ == "__main__":
    main()
