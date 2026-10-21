=======================
Units and conventions
=======================

Unit and dimension errors account for most defects in this kind of code. This page
records the conventions qforge follows, as a reference to check new code against.

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

Converting to solver units
--------------------------

A Hamiltonian in GHz is not in the units a time-domain solver expects. QuTiP integrates
:math:`\dot{\psi} = -iH\psi` with time in the same units the Hamiltonian's inverse
implies, so a Hamiltonian expressed in GHz must be multiplied by :math:`2\pi` to
become rad/ns:

.. code-block:: python

    H_rad_per_ns = H_ghz * 2 * np.pi

qforge does this explicitly at the boundary between the physics layer and the solver.
``GateEngine._get_qubit_hamiltonian`` returns a Hamiltonian already in rad/ns, and
``QuantumDevice.effective_operators`` converts rather than leaving it to the caller.
A Hamiltonian assembled by hand should be converted once, at the point where the
value stops being a frequency and becomes a generator of time evolution.

Hilbert space
=============

A physical qubit in qforge is not a two-level system. It is the lowest
``truncated_dim`` eigenstates of a superconducting circuit, and :math:`|2\rangle`,
:math:`|3\rangle` and above are part of the simulation rather than noise to be
discarded.

Leakage out of the computational subspace is one of the quantities qforge is built
to measure. A fast pulse on a transmon with 250 MHz of anharmonicity populates
:math:`|2\rangle`, and a simulation truncated to two levels cannot represent that at
all.

Dimensions
----------

QuTiP tracks the tensor structure of a composite object in ``.dims``. For an
N qubit register with local dimensions :math:`[d_0, d_1, \ldots]`:

.. code-block:: text

    ket        dims = [[d0, d1, ...], [1, 1, ...]]
    operator   dims = [[d0, d1, ...], [d0, d1, ...]]

Local dimensions are generally unequal. A transmon truncated to 4 levels beside a
fluxonium truncated to 6 gives ``[4, 6]``, and every operator must agree with that.

Embedding a subsystem operator into a larger register requires preserving the
ordering and the ``dims``, and tracing nothing out. Tracing out the rest of the
register to apply a local gate destroys its entanglement with the remaining qubits.
``ErrorCorrectionEngine._apply_unitary_to_subsystem`` shows the pattern: build the
full space operator by tensoring identities of the right local dimension around the
subsystem operator, then apply it to the whole state.

Fidelity metrics
================

These quantities are distinct, and qforge reports them separately.

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

A state fidelity computed on a single input state is not a gate fidelity. It
establishes only that the gate behaved correctly for that input, which a poorly
calibrated gate can satisfy by coincidence.

Session state and persistence
=============================

``QubitEngine`` writes every registered qubit to
``outputs/qubits/.qforge_session.json``. Creating a qubit therefore has a side
effect that outlives the process, which is what lets the CLI work across separate
invocations.

Two consequences follow:

* ``GateEngine`` reloads the session on nearly every call, so a qubit created in
  one engine instance is visible to another.
* Workflows that create temporary physical qubits have to clean up after themselves.
  ``ErrorCorrectionEngine`` registers data and ancilla clones, and deletes them in a
  ``finally`` block, so they do not remain in the qubit list after a run.

``DeviceEngine`` keeps a parallel registry at ``outputs/devices/.qforge_devices.json``.
It stores the netlist source rather than a pickled model, so reloading a session
rebuilds the device from its own definition.

Gate calibrations live in ``outputs/calib_cache.json``, keyed by qubit names, gate
type, coupling and drive parameters. They persist deliberately, since the sweeps
dominate the cost of most workflows. Clear them with ``qforge cache clear`` after
changing a qubit's physical parameters.

``outputs/qubits/.qforge_metrics.json`` memoizes the frequency and anharmonicity
shown when qubits are listed, so menus and pickers do not re-diagonalize every
registered qubit each time they open. Entries are keyed by qubit type and
parameters and stamped with the scqubits version, so they invalidate themselves
when either changes. Nothing needs to be cleared by hand.
