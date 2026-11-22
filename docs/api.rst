=============
API reference
=============

Generated from the source. For what these engines are for and how they fit together,
read the Physics section first.

Qubits
======

.. automodule:: QubitWeave.core.qubit_engine
   :members:
   :undoc-members:
   :show-inheritance:

Gates and dynamics
==================

.. automodule:: QubitWeave.core.gate_engine
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.coupling
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.tomography
   :members:
   :undoc-members:
   :show-inheritance:

Circuits and workflows
======================

.. automodule:: QubitWeave.core.workflow_engine
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.decompose
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.circuit_engine
   :members:
   :undoc-members:
   :show-inheritance:

Error correction
================

These two modules carry long developer notes in their module docstrings, covering
the CSS restriction, the syndrome tables and the memory strategy. That material is
written up in :doc:`error_correction`, so only the public classes are reproduced
here.

.. currentmodule:: QubitWeave.core.stabilizer_codes

.. autoclass:: StabilizerCode
   :members:

.. autoclass:: StabilizerGenerator
   :members:

.. autoclass:: EncodingStep
   :members:

The bundled code specifications are ``REPETITION_3``, ``STEANE_7`` and ``SHOR_9``.

.. currentmodule:: QubitWeave.core.error_correction_engine

.. autoclass:: ErrorCorrectionEngine
   :members:
   :undoc-members:
   :show-inheritance:

Device design
=============

.. automodule:: QubitWeave.core.device_netlist
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.device_engine
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.device_library
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.device_report
   :members:
   :undoc-members:
   :show-inheritance:

Comparison
==========

.. automodule:: QubitWeave.comparison.comparator
   :members:
   :undoc-members:
   :show-inheritance:

Utilities
=========

.. automodule:: QubitWeave.utils.terminal_plot
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.utils.analysis
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.utils.circuit_diagram
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: QubitWeave.core.run_manager
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
=============

.. automodule:: QubitWeave.config.defaults
   :members:
   :undoc-members:
