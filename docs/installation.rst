============
Installation
============

QubitWeave needs Python 3.11 or newer.

From PyPI
=========

.. code-block:: bash

   $ pip install QubitWeave

This installs the full simulation stack: scqubits for circuit physics, QuTiP for
dynamics, and NumPy, SciPy, matplotlib, pandas, Click, Rich, prompt-toolkit and
plotext for the numerics and the terminal interface.

From source
===========

.. code-block:: bash

   $ git clone https://github.com/Ingenio17/QubitWeave.git
   $ cd QubitWeave
   $ pip install -e .

Use ``pip install -e ".[dev]"`` to run the test suite, which adds pytest,
pytest-cov, Black, Ruff and mypy.

Optional extras
===============

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Extra
     - What it adds
   * - ``QubitWeave[dev]``
     - Test, lint and type checking tools.
   * - ``QubitWeave[docs]``
     - Sphinx and the theme used to build this site.
   * - ``QubitWeave[hardware]``
     - Qiskit Metal, for chip layout work. Large, and not needed for any of the
       physics in this documentation.

No part of the core toolkit imports Qiskit Metal, so that extra is only needed for
layout work.

Checking the install
====================

.. code-block:: bash

   $ QubitWeave info
   $ QubitWeave --interactive

``QubitWeave info`` prints the version and the components that loaded. If the wizard
opens and can create a transmon, the numerical stack is working.

Notes
=====

QubitWeave builds no native extensions of its own, but scqubits and QuTiP ship compiled
code. A C/C++ toolchain is required on platforms without prebuilt wheels for them.

Simulation output is written under ``outputs/``, relative to the working directory:
registered qubits, designed devices, plots, runs and the gate calibration cache.
``QubitWeave clean`` removes it.
