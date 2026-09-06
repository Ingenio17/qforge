=======================
Units and conventions
=======================

Most bugs in this kind of code are unit bugs or dimension bugs. This page collects
the conventions qforge follows so you can check your own code against them.

Units
=====

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Quantity
     - Unit
     - Note
   * - Circuit energies (:math:`E_J`, :math:`E_C`, :math:`E_L`)
     - GHz
     - This is :math:`E/h`, the convention scqubits uses.
   * - Transition frequencies
     - GHz
     - :math:`f_{01}`, :math:`f_{12}` and so on.
   * - Anharmonicity
     - GHz or MHz
     - Reported in MHz where the number is small. Field names say which.
   * - Gate durations, pulse times
     - ns
     - Everything in the time domain.
   * - Coherence times
     - microseconds
     - :math:`T_1`, :math:`T_2`.
   * - Coupling strength :math:`g`
     - GHz
     - Converted internally before it reaches a solver.
   * - External flux
     - :math:`\Phi_0`
     - Reduced flux. Half a flux quantum is ``0.5``.
   * - Offset charge :math:`n_g`
     - Cooper pairs (2e)
     - 
   * - Temperature
     - kelvin
     - Default bath temperature is 0.015 K.

The one conversion that matters
-------------------------------

A Hamiltonian in GHz is not what a time domain solver wants. QuTiP integrates
:math:`\dot{\psi} = -iH\psi` with time in the same units the Hamiltonian's inverse
implies, so a Hamiltonian expressed in GHz must be multiplied by :math:`2\pi` to
become rad/ns:

.. code-block:: python

    H_rad_per_ns = H_ghz * 2 * np.pi

qforge does this explicitly at the boundary between the physics layer and the solver.
``GateEngine._get_qubit_hamiltonian`` returns a Hamiltonian already in rad/ns, and
``QuantumDevice.effective_operators`` converts rather than leaving it to the caller.
If you build a Hamiltonian yourself, do the conversion once, at the point where the
value stops being a frequency and starts being a generator of time evolution.

Hilbert space
=============

A physical qubit in qforge is not two levels. It is the lowest ``truncated_dim``
eigenstates of a superconducting circuit, and :math:`|2\rangle`, :math:`|3\rangle`
and up are part of the simulation, not noise to be discarded.

That matters because leakage out of the computational subspace is one of the things
qforge exists to measure. A fast pulse on a transmon with 250 MHz of anharmonicity
will populate :math:`|2\rangle`, and if the simulation truncates to two levels you
simply never see it.

Dimensions
----------

QuTiP tracks the tensor structure of a composite object in ``.dims``. For an
N qubit register with local dimensions :math:`[d_0, d_1, \ldots]`:

.. code-block:: text

    ket        dims = [[d0, d1, ...], [1, 1, ...]]
    operator   dims = [[d0, d1, ...], [d0, d1, ...]]

Local dimensions are generally not equal. A transmon truncated to 4 levels next to a
fluxonium truncated to 6 gives ``[4, 6]``, and any operator you build has to agree.

When you embed a subsystem operator into a larger register, keep the ordering, keep
the ``dims``, and do not partial trace anything away. Tracing out the rest of the
register to apply a local gate destroys entanglement with the qubits you traced out.
``ErrorCorrectionEngine._apply_unitary_to_subsystem`` shows the pattern: build the
full space operator by tensoring identities of the right local dimension around the
subsystem operator, then apply it to the whole state.

Fidelity metrics
================

These are different numbers and qforge keeps them apart. So should you.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Metric
     - Definition
   * - State fidelity
     - :math:`\mathcal{F} = \left(\mathrm{Tr}\sqrt{\sqrt{\rho}\,\sigma\sqrt{\rho}}\right)^2`,
       between one output state and one target state.
   * - Trace distance
     - How distinguishable two states are. Complements fidelity.
   * - Purity
     - :math:`\mathrm{Tr}(\rho^2)`. Drops below 1 as decoherence sets in.
   * - Average gate fidelity
     - :math:`\mathcal{F}_{\mathrm{avg}} = \frac{|\mathrm{Tr}(U_{\mathrm{ideal}}^\dagger U_{\mathrm{sim}})|^2 + d}{d(d+1)}`
       with :math:`d = 2^N`, averaged over all input states.
   * - Process fidelity
     - Computed from the Choi matrix of the simulated channel.
   * - Leakage
     - Population outside the computational subspace at the end of the gate.

A state fidelity computed on one input state is not a gate fidelity. It tells you
the gate worked for that input, which for a badly calibrated gate can be true by
accident.

Session state and persistence
=============================

``QubitEngine`` writes every registered qubit to
``outputs/qubits/.qforge_session.json``. Creating a qubit therefore has a side
effect that outlives the process, which is what lets the CLI work across separate
invocations.

Two consequences worth knowing:

* ``GateEngine`` reloads the session on nearly every call, so a qubit created in
  one engine instance is visible to another.
* Workflows that create temporary physical qubits have to clean up after themselves.
  ``ErrorCorrectionEngine`` registers data and ancilla clones, and deletes them in a
  ``finally`` block, so they never linger in your qubit list after a run.

``DeviceEngine`` keeps a parallel registry at ``outputs/devices/.qforge_devices.json``.
It stores the netlist source rather than a pickled model, so reloading a session
rebuilds the device from its own definition.

Gate calibrations live in ``outputs/calib_cache.json``, keyed by qubit names, gate
type, coupling and drive parameters. They persist deliberately, since the sweeps are
expensive. Clear them with ``qforge cache clear`` after changing a qubit's physical
parameters.
