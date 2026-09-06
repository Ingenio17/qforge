=============
API reference
=============

Generated from the source. For what these engines are for and how they fit together,
read the Physics section first.

Qubits
======

.. automodule:: qforge.core.qubit_engine
   :members:
   :undoc-members:
   :show-inheritance:

Gates and dynamics
==================

.. automodule:: qforge.core.gate_engine
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.coupling
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.tomography
   :members:
   :undoc-members:
   :show-inheritance:

Circuits and workflows
======================

.. automodule:: qforge.core.workflow_engine
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.decompose
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.circuit_engine
   :members:
   :undoc-members:
   :show-inheritance:

Error correction
================

These two modules carry long developer notes in their module docstrings, covering
the CSS restriction, the syndrome tables and the memory strategy. That material is
written up in :doc:`error_correction`, so only the public classes are reproduced
here.

.. currentmodule:: qforge.core.stabilizer_codes

.. autoclass:: StabilizerCode
   :members:

.. autoclass:: StabilizerGenerator
   :members:

.. autoclass:: EncodingStep
   :members:

The bundled code specifications are ``REPETITION_3``, ``STEANE_7`` and ``SHOR_9``.

.. currentmodule:: qforge.core.error_correction_engine

.. autoclass:: ErrorCorrectionEngine
   :members:
   :undoc-members:
   :show-inheritance:

Device design
=============

.. automodule:: qforge.core.device_netlist
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.device_engine
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.device_library
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.device_report
   :members:
   :undoc-members:
   :show-inheritance:

Comparison
==========

.. automodule:: qforge.comparison.comparator
   :members:
   :undoc-members:
   :show-inheritance:

Utilities
=========

.. automodule:: qforge.utils.terminal_plot
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.utils.analysis
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.utils.circuit_diagram
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: qforge.core.run_manager
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
=============

.. automodule:: qforge.config.defaults
   :members:
   :undoc-members:
