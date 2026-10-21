=============
CLI reference
=============

Every command delegates to an engine. The CLI contains no physics of its own, so
everything below is also reachable from Python.

``--help`` works at every level: ``qforge --help``, ``qforge qubit --help``,
``qforge qubit create --help``.

Top level
=========

.. code-block:: bash

    $ qforge --interactive     # guided terminal wizard
    $ qforge --gui             # desktop interface
    $ qforge --cache-clear     # empty the calibration cache and exit
    $ qforge --version

    $ qforge info              # version and loaded components
    $ qforge citations         # BibTeX for scqubits, QuTiP and Qiskit

``qforge citations`` prints BibTeX entries for the libraries qforge is built on.
scqubits and QuTiP carry most of the numerical work and should be cited alongside it.

Qubits
======

.. code-block:: bash

    $ qforge qubit create --type transmon --name Q1 --EJ 15 --EC 0.3
    $ qforge qubit create --type fluxonium --name F1 --preset high_coherence
    $ qforge qubit list
    $ qforge qubit analyze --name Q1 --plot --coherence
    $ qforge qubit export Q1 --format qutip --output q1.py
    $ qforge qubit delete Q1

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Command
     - Options
   * - ``create``
     - ``--type/-t`` (transmon, fluxonium, flux, zeropi), ``--name/-n``, ``--EJ``,
       ``--EC``, ``--EL``, ``--flux``, ``--preset/-p``, ``--output/-o``,
       ``--relative``
   * - ``list``
     - Name, type, frequency and anharmonicity for every registered qubit.
   * - ``analyze``
     - ``--name/-n``, ``--plot``, ``--coherence``, ``--relative``
   * - ``export``
     - ``NAME``, ``--format/-f`` (json, qutip, qiskit), ``--output/-o``
   * - ``delete``
     - ``NAME``

``--type`` is an option rather than a positional argument. Explicit parameters such
as ``--EJ`` override any value supplied by ``--preset``. ``--relative`` displays
energies against the ground state, which is the convenient form for reading
transition frequencies.

Gates
=====

.. code-block:: bash

    $ qforge gate simulate --qubit Q1 --gate X --duration 40 --noise realistic
    $ qforge gate simulate --qubit Q1 --gate H --duration 40 --steps 200 --save

Options: ``--qubit``, ``--gate`` (X, Y, Z, H), ``--duration`` in ns (default 20),
``--noise`` (none, realistic), ``--steps`` (default 100), ``--save`` to write a
matplotlib figure under ``outputs/plots/``.

Populations are plotted in the terminal either way.

Two-qubit gates, calibration and QASM workflows are currently available only through
the Python API and the wizard. See :doc:`quickstart` and :doc:`interfaces`.

Comparison
==========

.. code-block:: bash

    $ qforge compare qubits --qubits transmon,fluxonium --metrics all
    $ qforge compare qubits --qubits Q1,F1 --gates X,H --tag demo

Options: ``--qubits`` (comma separated names or types), ``--metrics`` (coherence,
fidelity, frequency, anharmonicity, all), ``--gates`` to also simulate dynamics per
qubit, ``--tag`` to label the run, ``--output/-o`` for raw JSON.

Named qubits are taken from the session. A bare type name builds a temporary qubit
from that type's defaults, which allows architectures to be compared without
registering anything.

Results land in a timestamped directory under ``outputs/runs/`` with a report and any
plots.

Examples
========

.. code-block:: bash

    $ qforge example list
    $ qforge example run --name 02_single_qubit_gates

Housekeeping
============

.. code-block:: bash

    $ qforge cache clear             # drop the gate calibration cache
    $ qforge clean                   # remove outputs/runs
    $ qforge clean --all             # everything under outputs/, plus the session
    $ qforge clean --days 7          # only runs older than a week
    $ qforge clean --dry-run         # show what would go, delete nothing

Clear the calibration cache after changing a qubit's physical parameters. Calibrated
durations are keyed by qubit name, so a stale entry describes a gate that no longer
exists.

``clean`` asks for confirmation before deleting unless ``--force`` is given.

Developer
=========

.. code-block:: bash

    $ qforge dev sync

Regenerates the preset table in ``docs/qubits.rst`` from ``QUBIT_PRESETS`` in
``qforge/config/defaults.py``. Run it after adding a qubit type or changing a preset,
so the documentation and the code cannot drift apart.

Stubs
=====

``qforge circuit build``, ``qforge workflow run`` and ``qforge hardware design`` are
placeholders that print a notice and exit. The functionality behind the first two is
available through ``PhysicalWorkflowEngine`` and the wizard's workflow menu.

Where output goes
=================

.. code-block:: text

    outputs/
      qubits/.qforge_session.json     registered qubits
      qubits/.qforge_metrics.json     memoized frequencies, so listing stays fast
      devices/.qforge_devices.json    designed devices
      calib_cache.json                gate calibrations
      runs/                           comparison runs, one directory each
      plots/                          saved figures
      gates/  circuits/  hardware/  comparisons/

Paths are relative to the working directory and are configured in
``qforge/config/defaults.py`` under ``OUTPUT_DIRS``.
