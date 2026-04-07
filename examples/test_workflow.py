import os
from qforge.core.qubit_engine import QubitEngine
from qforge.core.gate_engine import GateEngine
from qforge.core.workflow_engine import PhysicalWorkflowEngine

def test():
    q_eng = QubitEngine()
    g_eng = GateEngine()
    
    # Create two qubits
    q_eng.create_qubit("transmon", "Q0", {"EJ": 15.0, "EC": 0.3})
    q_eng.create_qubit("transmon", "Q1", {"EJ": 14.0, "EC": 0.3})
    
    wf_eng = PhysicalWorkflowEngine(q_eng, g_eng)
    
    qubits = ["Q0", "Q1"]
    couplings = [{"q1": 0, "q2": 1, "type": "tunable_coupler", "strength": 0.05}]
    
    print("Executing Bell State...")
    res = wf_eng.execute_workflow(qubits, couplings, "C:/Users/sdsha/OneDrive - Indian Institute of Technology Bombay/IITB/BTP/qforge/examples/bell_state.qasm")
    
    final_pops = {k: v[-1] for k, v in res["populations"].items()}
    print("Populations at end:", final_pops)
    
    print("\nExecuting Deutsch...")
    res2 = wf_eng.execute_workflow(qubits, couplings, "C:/Users/sdsha/OneDrive - Indian Institute of Technology Bombay/IITB/BTP/qforge/examples/deutsch.qasm")
    final_pops2 = {k: v[-1] for k, v in res2["populations"].items()}
    print("Populations at end:", final_pops2)

if __name__ == "__main__":
    test()
