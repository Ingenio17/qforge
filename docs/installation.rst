============
Installation
============

qforge needs Python 3.11 or newer.

From PyPI
=========

.. code-block:: bash

   $ pip install qforge

That pulls in the whole simulation stack: scqubits for circuit physics, QuTiP for
dynamics, plus NumPy, SciPy, matplotlib, pandas, Click, Rich, prompt-toolkit and
plotext for the terminal interface.

From source
===========

.. code-block:: bash

   $ git clone https://github.com/Ingenio17/qforge.git
   $ cd qforge
   $ pip install -e .

Use ``pip install -e ".[dev]"`` if you plan to run the test suite. That adds
pytest, pytest-cov, Black, Ruff and mypy.

Optional extras
===============

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Extra
     - What it adds
   * - ``qforge[dev]``
     - Test, lint and type checking tools.
   * - ``qforge[docs]``
     - Sphinx and the theme used to build this site.
   * - ``qforge[hardware]``
     - Qiskit Metal, for chip layout work. Large, and not needed for any of the
       physics in this documentation.

Nothing in the core toolkit imports Qiskit Metal, so skip that extra unless you
are doing layout.

Checking the install
====================

.. code-block:: bash

   $ qforge info
   $ qforge --interactive

``qforge info`` prints the version and the engines that loaded. If the interactive
wizard opens and lets you create a transmon, the numerical stack is working.

Notes
=====

Installing from source builds no native extensions of its own, but scqubits and
QuTiP do ship compiled code. On platforms without prebuilt wheels you will need a
working C/C++ toolchain.

qforge writes simulation output under ``outputs/`` relative to the directory you
run it from: registered qubits, designed devices, plots, runs and the gate
calibration cache. ``qforge clean`` clears it out.
