=============
CLI reference
=============

Every command delegates to an engine. Nothing here holds physics of its own, so
anything below is also reachable from Python.

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

Please do run ``qforge citations`` if you publish. qforge stands on scqubits and
QuTiP, and both deserve the citation.

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

``--type`` is an option, not a positional argument. Explicit ``--EJ`` and friends
override whatever ``--preset`` supplied. ``--relative`` displays energies against the
ground state, which is usually what you want for reading off transition frequencies.

Gates
=====

.. code-block:: bash

    $ qforge gate simulate --qubit Q1 --gate X --duration 40 --noise realistic
    $ qforge gate simulate --qubit Q1 --gate H --duration 40 --steps 200 --save

Options: ``--qubit``, ``--gate`` (X, Y, Z, H), ``--duration`` in ns (default 20),
``--noise`` (none, realistic), ``--steps`` (default 100), ``--save`` to write a
matplotlib figure under ``outputs/plots/``.

Populations are plotted in the terminal either way.

Two qubit gates, calibration and QASM workflows are Python API and wizard territory
today. See :doc:`quickstart` and :doc:`interfaces`.

Comparison
==========

.. code-block:: bash

    $ qforge compare qubits --qubits transmon,fluxonium --metrics all
    $ qforge compare qubits --qubits Q1,F1 --gates X,H --tag demo

Options: ``--qubits`` (comma separated names or types), ``--metrics`` (coherence,
fidelity, frequency, anharmonicity, all), ``--gates`` to also simulate dynamics per
qubit, ``--tag`` to label the run, ``--output/-o`` for raw JSON.

Named qubits are taken from your session. Bare type names build one from that type's
defaults, so you can compare architectures without registering anything.

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
durations are keyed by qubit name, and a stale entry is worse than no entry at all.

``clean`` asks before deleting unless you pass ``--force``.

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
placeholders. They print a notice and exit. The functionality behind the first two
exists today through ``PhysicalWorkflowEngine`` and the wizard's workflow menu.

Where output goes
=================

.. code-block:: text

    outputs/
      qubits/.qforge_session.json     registered qubits
      devices/.qforge_devices.json    designed devices
      calib_cache.json                gate calibrations
      runs/                           comparison runs, one directory each
      plots/                          saved figures
      gates/  circuits/  hardware/  comparisons/

Paths are relative to where you run qforge, and are configured in
``qforge/config/defaults.py`` under ``OUTPUT_DIRS``.
