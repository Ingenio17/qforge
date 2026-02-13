# Agent Instructions for QForge

Use this file as a prompt for your AI coding assistant (e.g., GitHub Copilot, Cursor, etc.) when you have added a new feature to QForge.

## Workflow: Finalizing a New Feature

**Context**: You have just implemented a new feature in the `qforge` core engine (e.g., a new Qubit type in `qubit_engine.py`, or a new Gate in `gate_engine.py`).

**Prompt for AI Agent**:
> "I have added a new feature: [Feature Name/Type]. Please verify it and finalize the integration by following the steps in `docs/AGENT_INSTRUCTIONS.md`."

---

### checklist: Adding a Qubit Type

1.  **Update `qforge/config/defaults.py`**
    -   Add the new qubit type key to `QUBIT_PRESETS`.
    -   Define default parameters (e.g., `EJ`, `EC`) under `"typical"`.
    -   *Note*: The CLI and Interactive mode will automatically pick this up!

2.  **Generate Documentation**
    -   Update `docs/qubits.md` (or create it if missing).
    -   Add a section for the new qubit.
    -   Include the Hamiltonian and parameter definitions.
    -   **Action**: `qforge dev sync` (if implemented) can auto-generate the parameter table.

3.  **Create Example Script**
    -   Create a new file: `examples/[qubit_type]_demo.py`.
    -   Content should include:
        ```python
        from qforge.core.qubit_engine import QubitEngine
        engine = QubitEngine()
        q = engine.create_qubit(“[qubit_type]”, “my_qubit”, { ...params... })
        print(q.eigenvals(5))
        ```
    -   Run the script to verify it works without error.

4.  **Verify Interactive Mode**
    -   Run `qforge --interactive`.
    -   Type `create` and check if your new qubit type appears in the autocomplete list.

---

### checklist: Adding a Gate

1.  **Update `qforge/config/defaults.py`**
    -   Add the gate key to `GATE_DEFAULTS`.

2.  **Update `qforge/core/gate_engine.py`**
    -   Implement the simulation logic in `simulate_two_qubit_dynamics` or relevant method.

3.  **Generate Documentation**
    -   Update `docs/gates.md`.
    -   Explain the gate's physics/Hamiltonian.

4.  **Create Example Script**
    -   Create `examples/gate_[gate_name].py`.
    -   Simulate the gate on a standard qubit pair (e.g., 2 Transmons).

---

### checklist: Adding a CLI Command

1.  **Register Command**
    -   Ensure the command is added to `qforge/cli/main.py` or a subcommand group.

2.  **Update Interactive Mode**
    -   If the command is complex, add a "Wizard" function in `qforge/cli/interactive.py` (e.g., `_wizard_my_command`).
    -   Add it to the main loop in `run_interactive`.

3.  **Update Documentation**
    -   Add to `getting_started.md` under "CLI Commands".

---

## Automation Helper

Run this command to auto-update documentation tables from `defaults.py`:

```bash
qforge dev sync
```

(Ensure you have implemented this command if strictly required, otherwise update docs manually.)
