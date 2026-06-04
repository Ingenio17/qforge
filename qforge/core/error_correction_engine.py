"""
error_correction_engine.py

Provides the ErrorCorrectionEngine with active mid-circuit measurement, 
real-time feedback, and dynamic physical allocation for a 3-qubit repetition code.
"""
import re
import numpy as np
import copy
import qutip as qt
from typing import List, Dict, Tuple, Any

from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.core.workflow_engine import PhysicalWorkflowEngine
from qforge.core.workflow_engine import QASMTranspiler

class ErrorCorrectionEngine:
    def __init__(self, qubit_engine: QubitEngine, gate_engine: GateEngine):
        self.qubit_engine = qubit_engine
        self.gate_engine = gate_engine
        self.workflow_engine = PhysicalWorkflowEngine(qubit_engine, gate_engine)

    def generate_3q_repetition_mapping(self, logical_names: List[str]) -> Dict[str, Dict[str, List[str]]]:
        """
        Dynamically allocates 3 data and 2 ancilla qubits per logical qubit.
        Returns a mapping dictionary and the flat list of physical names.
        """
        mapping = {}
        for l_name in logical_names:
            mapping[l_name] = {
                "data": [f"{l_name}_D0", f"{l_name}_D1", f"{l_name}_D2"],
                "ancilla": [f"{l_name}_A0", f"{l_name}_A1"]
            }
        return mapping

    def _get_flat_physical_names(self, logical_names: List[str], mapping: Dict) -> List[str]:
        """Flattens the mapping into the exact ordered list expected by the GateEngine."""
        physical_names = []
        for l_name in logical_names:
            physical_names.extend(mapping[l_name]["data"])
            physical_names.extend(mapping[l_name]["ancilla"])
        return physical_names

    def execute_3q_repetition_workflow(self, logical_names: List[str], qasm_path: str) -> Dict:
        """
        Executes a 3-qubit repetition code schedule with ACTIVE error correction
        scaling dynamically to N logical qubits.
        """
        print(f"1. [3Q-RepEC] Transpiling logical QASM from '{qasm_path}'...")
        transpiler = QASMTranspiler()
        logical_circuit = transpiler.parse_file(qasm_path)
        
        # Dynamically map physical qubits
        mapping = self.generate_3q_repetition_mapping(logical_names)
        physical_names = self._get_flat_physical_names(logical_names, mapping)
        
        print(f"2. [3Q-RepEC] Allocated {len(physical_names)} physical qubits for {len(logical_names)} logical qubits.")
        
        # Initial State: All physical qubits at |0>
        current_state = qt.tensor([qt.basis(2, 0) for _ in range(len(physical_names))])
        
        # Simulate circuit step-by-step
        for step_idx, instruction in enumerate(logical_circuit.instructions):
            print(f"\n--- [3Q-RepEC] Executing Cycle {step_idx}: {instruction.name} ---")
            
            # 1. Map Logical Instruction
            schedule_chunk, step_time, ec_couplings = self._generate_3q_repetition_step_schedule(instruction, mapping)
            
            # 2. Run Physical Simulation for this specific chunk (resuming from current_state)
            sim_result = self.gate_engine.simulate_n_qubit_dynamics(
                qubit_names=physical_names,
                gate_type="EC_Cycle",
                duration=step_time,
                couplings=ec_couplings,
                drives=schedule_chunk,
                initial_state=current_state, 
                steps=max(20, int(step_time))
            )
            
            current_state = sim_result["final_state"]
            
            # 3. ACTIVE ERROR CORRECTION: Measure Ancillas, Collapse, and Correct
            current_state = self._syndrome_measurement_3q_repetition(current_state, logical_names, mapping, physical_names)
            
        print("\n[3Q-RepEC] Circuit execution complete.")
        return {"logical_populations": self._decode_3q_repetition_logical_state(current_state, logical_names, mapping, physical_names)}


    def _syndrome_measurement_3q_repetition(self, state: qt.Qobj, logical_names: List[str], mapping: Dict, physical_names: List[str]) -> qt.Qobj:
        """
        Loops through every logical block, performs mid-circuit measurement on its specific ancillas,
        collapses the wavefunction, and applies real-time X corrections dynamically.
        """
        N_phys = len(physical_names)
        I = qt.qeye(2)
        P0 = qt.basis(2, 0) * qt.basis(2, 0).dag()
        P1 = qt.basis(2, 1) * qt.basis(2, 1).dag()
        X = qt.sigmax()

        current_state = state

        for l_name in logical_names:
            print(f"  [Syndrome Check] Evaluating logical block: {l_name}")
            
            # Find the absolute indices of this logical block's qubits in the massive tensor state
            idx_D0 = physical_names.index(mapping[l_name]["data"][0])
            idx_D1 = physical_names.index(mapping[l_name]["data"][1])
            idx_D2 = physical_names.index(mapping[l_name]["data"][2])
            idx_A0 = physical_names.index(mapping[l_name]["ancilla"][0])
            idx_A1 = physical_names.index(mapping[l_name]["ancilla"][1])

            # 1. Build measurement projectors dynamically for the N-qubit state
            projectors = {}
            for synd in [(0,0), (1,0), (0,1), (1,1)]:
                op_list = [I for _ in range(N_phys)]
                op_list[idx_A0] = P1 if synd[0] == 1 else P0
                op_list[idx_A1] = P1 if synd[1] == 1 else P0
                projectors[synd] = qt.tensor(op_list)

            # 2. Calculate probabilities
            probs = {synd: np.real(qt.expect(proj, current_state)) for synd, proj in projectors.items()}

            # 3. Simulate Quantum Measurement
            syndromes = list(probs.keys())
            prob_values = list(probs.values())
            
            # Handle numerical edge case where sum might be slightly off 1.0 due to float precision
            prob_sum = sum(prob_values)
            if prob_sum > 0:
                prob_values = [p / prob_sum for p in prob_values] 
            else:
                prob_values = [1.0, 0.0, 0.0, 0.0] # Fallback if state is completely destroyed
            
            measured_idx = np.random.choice(len(syndromes), p=prob_values)
            measured_syndrome = syndromes[measured_idx]
            measured_prob = prob_values[measured_idx]

            print(f"    -> {l_name} Measured Syndrome (A0, A1): {measured_syndrome} (Prob: {measured_prob:.4f})")

            # 4. Collapse the wavefunction
            current_state = (projectors[measured_syndrome] * current_state) / np.sqrt(measured_prob)

            # 5. Apply Real-Time Feed-Forward Corrections
            def apply_x_at_index(state_to_correct, target_idx):
                op_list = [I for _ in range(N_phys)]
                op_list[target_idx] = X
                return qt.tensor(op_list) * state_to_correct

            if measured_syndrome == (1, 0):
                print(f"    -> ALERT: Applying X correction to {mapping[l_name]['data'][0]}")
                current_state = apply_x_at_index(current_state, idx_D0)
            elif measured_syndrome == (1, 1):
                print(f"    -> ALERT: Applying X correction to {mapping[l_name]['data'][1]}")
                current_state = apply_x_at_index(current_state, idx_D1)
            elif measured_syndrome == (0, 1):
                print(f"    -> ALERT: Applying X correction to {mapping[l_name]['data'][2]}")
                current_state = apply_x_at_index(current_state, idx_D2)

            # 6. Reset Ancillas to |0> for the next cycle
            if measured_syndrome[0] == 1:
                current_state = apply_x_at_index(current_state, idx_A0)
            if measured_syndrome[1] == 1:
                current_state = apply_x_at_index(current_state, idx_A1)

        return current_state

    def _generate_3q_repetition_step_schedule(self, instruction, mapping):
        """
        Placeholder function representing translation of a single logical gate 
        into transversal schedules + syndrome extraction CNOTs.
        """
        return [], 50.0, {}

    def _decode_3q_repetition_logical_state(self, state: qt.Qobj, logical_names: List[str], mapping: Dict, physical_names: List[str]) -> Dict[str, float]:
        """
        Extracts final logical populations for N logical qubits using majority vote on the data qubits.
        """
        diag = state.diag()
        logical_pops = {}
        N_phys = len(physical_names)
        
        for i, prob in enumerate(diag):
            if prob < 1e-6: continue
            
            # Get binary representation of state index
            bin_str = format(i, f'0{N_phys}b')
            
            logical_bitstring = ""
            for l_name in logical_names:
                idx_D0 = physical_names.index(mapping[l_name]["data"][0])
                idx_D1 = physical_names.index(mapping[l_name]["data"][1])
                idx_D2 = physical_names.index(mapping[l_name]["data"][2])
                
                # Majority voting for this logical qubit
                data_bits = [bin_str[idx_D0], bin_str[idx_D1], bin_str[idx_D2]]
                ones = data_bits.count('1')
                logical_val = "1" if ones >= 2 else "0"
                logical_bitstring += logical_val
                
            logical_pops[logical_bitstring] = logical_pops.get(logical_bitstring, 0.0) + float(np.real(prob))
            
        return logical_pops