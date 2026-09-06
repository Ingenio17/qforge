# Agent instructions for qforge

Hand this file to your coding assistant after adding a feature, so the docs, the
presets and the examples do not drift away from the code.

> "I have added a new feature: [name]. Verify it and finish the integration by
> following `docs/AGENT_INSTRUCTIONS.md`."

## Where documentation lives

| Page | Covers |
|---|---|
| `docs/quickstart.rst` | The five minute tour, in Python |
| `docs/interfaces.rst` | Wizard, GUI, browser sandbox |
| `docs/cli.rst` | Every CLI command and its options |
| `docs/conventions.rst` | Units, Hilbert space, dims, persistence |
| `docs/qubits.rst` | QubitEngine, models, presets, coherence, sweeps |
| `docs/couplings.rst` | Coupling Hamiltonians |
| `docs/gates.rst` | Drives, DRAG, calibration, noise, fidelity |
| `docs/qasm.rst` | Transpiler and workflow engine |
| `docs/error_correction.rst` | Stabilizer codes and the EC engine |
| `docs/devices.rst` | Netlist language and device engine |
| `docs/api.rst` | Autodoc, generated from source |
| `docs/examples.rst` | Gallery of the bundled scripts |

Build and check before you finish:

```bash
pip install -r docs/requirements.txt
python -m sphinx -b html docs docs/_build/html
```

The build should produce no new warnings. Warnings in the API pages usually mean a
docstring is not valid reStructuredText: `|0>` reads as a substitution reference,
`**kwargs` as bold, and an aligned `field : description` block needs to be a literal
block introduced by `::`.

## Adding a qubit type

1. Add the type to `QUBIT_PRESETS` in `qforge/config/defaults.py`, with an `_info`
   entry and a `typical` parameter set. The CLI and the wizard pick it up
   automatically.
2. Wire the type into `QubitEngine._create_qubit_object`.
3. Add a section to `docs/qubits.rst` with the Hamiltonian and the parameter list.
4. Run `qforge dev sync` to regenerate the preset table on that page.
5. Add `examples/NN_<name>_demo.py` and run it.
6. Check it appears in `qforge --interactive` under "Create a qubit".

## Adding a gate

1. Add defaults to `GATE_DEFAULTS` in `qforge/config/defaults.py`.
2. Implement the physics in `qforge/core/gate_engine.py`. Keep the Hamiltonian, the
   drive and the coupling explicit. Do not substitute an ideal unitary for a method
   that is supposed to model hardware.
3. Document the drive operator, the envelope and any approximation in
   `docs/gates.rst`.
4. Add a test with a physics sanity check: a known rotation angle, unitarity, or the
   right behaviour at zero drive.
5. Add an example script that runs it on a standard pair of transmons.

## Adding a coupling

1. Implement it in `qforge/core/coupling.py` and register it in
   `CouplingGenerator.get_coupling`.
2. Write the Hamiltonian and the units of `g` into `docs/couplings.rst`, and say
   which native gate it produces.
3. Test the zero coupling limit and the tensor dimensions.

## Adding an error correcting code

1. Write a `StabilizerCode` in `qforge/core/stabilizer_codes.py`: generators, the
   syndrome table, logical operators and the encoding circuit. It must be CSS.
2. No change to `ErrorCorrectionEngine` should be needed. If one is, say why in the
   commit.
3. Add the code to the table in `docs/error_correction.rst`.
4. Test the generators commute, that every single qubit error maps to the right
   correction, and that the encoding circuit really produces the codeword.

## Adding a CLI command

1. Add it to a group under `qforge/cli/commands/` and register it in
   `qforge/cli/main.py`.
2. Keep the physics in the engines. A Click handler should parse arguments, call an
   engine and render the result.
3. Add a wizard entry in `qforge/cli/interactive.py` if the flow needs more than a
   couple of arguments.
4. Document it in `docs/cli.rst`.

## Before opening a pull request

```bash
black qforge tests
ruff check qforge tests
pytest
```
