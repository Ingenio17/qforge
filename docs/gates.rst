=====
Gates
=====

``GateEngine`` turns a logical operation into a pulse. It takes the eigenbasis and
physical operators of a circuit from ``QubitEngine``, assembles a time-dependent
Hamiltonian from the declared drives and couplings, integrates it with QuTiP, and
reports the resulting state.

An X gate is a Gaussian microwave pulse acting on the charge operator. A CNOT is
whichever pulse sequence the declared coupling can produce. Ideal operators are used
only where a layer has already accounted for the physics, as described under
:ref:`ideal-paths` below.

.. code-block:: python

    from QubitWeave.core.gate_engine import GateEngine

    gates = GateEngine()
    result = gates.simulate_dynamics("Q1", gate_type="X", duration=40.0)

Building the Hamiltonian
========================

Static part
-----------

For each qubit, the lowest ``truncated_dim`` eigenvalues from scqubits form a
diagonal Hamiltonian, converted from GHz to rad/ns:

.. code-block:: python

    evals = qubit.eigenvals(evals_count=dim)
    H0 = qt.Qobj(np.diag(evals)) * 2 * np.pi

Physical operators
------------------

Drive operators come from the same eigenbasis rather than from an approximation.
Driving a transmon applies a voltage that couples to the charge operator
:math:`\hat{n}`; a flux bias couples to the phase operator :math:`\hat{\varphi}`:

.. code-block:: python

    n_mat   = qubit.matrixelement_table("n_operator",   evals_count=dim)
    phi_mat = qubit.matrixelement_table("phi_operator", evals_count=dim)

These are exact matrix elements between the circuit's eigenstates, which is what
makes the leakage predictions meaningful. If a model exposes neither operator,
QubitWeave falls back to the harmonic approximation
:math:`\hat{n} \approx \tfrac{i}{\sqrt{2}}(a^\dagger - a)` and
:math:`\hat{\varphi} \approx \tfrac{1}{\sqrt{2}}(a^\dagger + a)`.

Multi-qubit systems
-------------------

The N-qubit Hamiltonian is the sum of the local terms plus one interaction term per
declared coupling. The available interactions and their operators are listed in
:doc:`couplings`.

Rotating frame
==============

Integrating a 5 GHz carrier over a 40 ns pulse resolves hundreds of oscillations
that carry no information about the gate. The static Hamiltonian is therefore
transformed into the frame rotating at :math:`\omega_{01}`:

.. math::

    \mathcal{H}_{0,\mathrm{rot}} = \mathrm{diag}(0,\, 0,\, \alpha,\, \ldots)

where :math:`\alpha = \omega_{12} - \omega_{01}` is the anharmonicity. The
computational subspace becomes flat, the higher levels retain their detuning, and
the solver follows the envelope rather than the carrier.

Single-qubit control
====================

.. list-table::
   :header-rows: 1
   :widths: 12 88

   * - Gate
     - Physical implementation
   * - X
     - Drive on the charge operator :math:`\hat{n}`.
   * - Y
     - The same drive, shifted 90 degrees in phase. Constructed by taking the
       :math:`\hat{n}` matrix and forcing it purely imaginary and antisymmetric,
       :math:`i\,\mathrm{tril}(\hat{n}) - i\,\mathrm{triu}(\hat{n})`, which keeps
       the operator Hermitian.
   * - Z
     - Flux tuning or a Stark shift, mapped onto :math:`\hat{\varphi}`. Compiled
       circuits use a virtual Z instead, described below.
   * - H
     - Synthesized from a :math:`Y(\pi/2)`-like drive, which preserves the global
       phase an algorithm expects.

Pulse envelopes
---------------

The default envelope is a Gaussian six sigma wide, truncated to the gate duration,
with :math:`\sigma = T/6` and :math:`\mu = T/2`:

.. math::

    \Omega(t) = A \exp\!\left(-\frac{(t-\mu)^2}{2\sigma^2}\right)

A rotation angle is the product of the pulse area and the drive matrix element, so
the peak amplitude follows from the angle required. ``simulate_dynamics`` integrates
the envelope numerically and solves for it:

.. math::

    A = \frac{\theta}{2\, |\langle 0|\hat{H}_{\mathrm{ctrl}}|1\rangle| \int \Omega(t)\,dt}

The same envelope has a closed-form area, exposed as ``GAUSSIAN_AREA_PER_NS``:

.. math::

    \frac{1}{T}\int_0^T \Omega(t)\,dt \Big/ A
        = \frac{\sqrt{2\pi}\,\mathrm{erf}(3/\sqrt{2})}{6}

which is what the two-qubit calibration uses to avoid a numerical integral inside a
sweep.

DRAG
----

A short pulse is spectrally wide, and with only a few hundred MHz of anharmonicity
available, a drive intended for :math:`0 \rightarrow 1` also reaches
:math:`1 \rightarrow 2`. Derivative Removal by Adiabatic Gate suppresses this by
adding a quadrature component proportional to the derivative of the envelope, scaled
by the anharmonicity:

.. math::

    \Omega_{\mathrm{DRAG}}(t) \propto \frac{\lambda}{\alpha}\, \dot{\Omega}(t)

The in-phase term multiplies :math:`\cos(\omega t + \phi)` and the DRAG term
multiplies :math:`\sin(\omega t + \phi)`. :math:`\lambda` is exposed as
``drag_lambda`` and defaults to 0.5; :math:`\alpha` is read from the qubit's own
spectrum. Setting ``use_drag=False`` disables the correction, which makes the
leakage it removes visible in the :math:`|2\rangle` population.

Virtual Z
---------

A :math:`Z` rotation requires no pulse. Since every subsequent X and Y drive carries
a phase, :math:`R_Z(\theta)` can be absorbed by shifting the phase of everything
that follows, at no cost in time or coherence. Compiled circuits use this wherever
possible. The ``virtual_z`` argument on the simulation entry points carries the
offset.

Two-qubit gates
===============

The mechanism depends on the coupling, because the coupling determines what can be
controlled.

Microwave-activated CNOT, fixed capacitive coupling
---------------------------------------------------

A fixed capacitive coupling offers no coupler to pulse and no flux knob to sweep, so
the CNOT is realized as a ZZ-activated conditional rotation.

The interaction :math:`g\,\hat{n}_1 \hat{n}_2` shifts the target's 0-1 transition
depending on whether the control is in :math:`|0\rangle` or :math:`|1\rangle`:

.. math::

    \omega_{\mathrm{targ}}^{(0)} = \frac{E_{01} - E_{00}}{2\pi}, \qquad
    \omega_{\mathrm{targ}}^{(1)} = \frac{E_{11} - E_{10}}{2\pi}, \qquad
    \zeta = \omega_{\mathrm{targ}}^{(1)} - \omega_{\mathrm{targ}}^{(0)}

A :math:`\pi` pulse on the target at :math:`\omega_{\mathrm{targ}}^{(1)}` therefore
flips it only when the control is excited, which is a CNOT up to single-qubit
phases.

All four energies and the drive matrix element are read from the dressed eigenstates
of the coupled pair, not from the bare product states, because an always-on coupling
hybridizes the levels and a drive computed from bare frequencies lands off resonance.
``_dressed_computational_basis`` labels each eigenstate by the bare state it most
overlaps and gauge-fixes the eigenvectors so their dominant amplitude is real and
positive, without which QuTiP's arbitrary eigenvector phases would propagate into
every matrix element.

The pulse area required for a :math:`\pi` rotation is :math:`\pi/|m|`, where
:math:`m` is the drive matrix element on the conditional transition. Dividing by the
duration and by ``GAUSSIAN_AREA_PER_NS`` gives the amplitude, and the drive phase is
set to :math:`-\arg(m)` to place the rotation axis along x.

Two quantities bound the gate, and both are computed rather than assumed:

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Diagnostic
     - Meaning
   * - ``selectivity``
     - :math:`|\zeta| \cdot T`. Whether the pulse is spectrally narrow enough to
       leave the control=0 branch alone. Below roughly 1 the pulse flips the target
       regardless of the control, which is an unconditional X rather than a CNOT.
       The target is 2.5, above which the control=0 branch stays above 99 percent
       population.
   * - ``dressed_purity``
     - The smallest overlap any of the four computational eigenstates has on its
       bare product state. Populations are reported in the bare basis, so this
       bounds how clean the gate can look there regardless of calibration. A value
       below 0.90 raises a warning, since it reflects the chosen coupling strength
       rather than the gate.

Both appear in the returned schedule, along with ``zeta_ghz``, the two branch
frequencies, and human-readable ``warnings`` that suggest a workable duration or
coupling strength:

.. code-block:: python

    result = gates.simulate_two_qubit_dynamics(
        "Q1", "Q2",
        gate_type="CNOT",
        coupling_type="capacitive",
        coupling_strength=0.03,
        duration=120.0,
    )

    result["schedule"]["zeta_ghz"]
    result["schedule"]["selectivity"]
    result["warnings"]

Schedules are cached in memory by control, target, coupling strength and duration,
since computing one means diagonalizing the coupled pair. Supplying an explicit
drive on the target suppresses the compiled pulse, leaving manual control of the
drive.

Tunable-coupler CZ and CNOT
---------------------------

A tunable coupler natively produces a controlled phase, so a requested CNOT is
compiled into :math:`X(-\pi/2) \rightarrow \mathrm{CZ} \rightarrow X(+\pi/2)` on the
target. The CZ itself is built as follows:

1. Compute, from the qubits' own spectra, the flux detuning that brings
   :math:`|11\rangle` and :math:`|02\rangle` into resonance.
2. Apply a physical :math:`X(-\pi/2)` pulse to the target.
3. Apply a flux pulse detuning the target together with a :math:`\sin^2` coupler
   pulse. The flux pulse is a raised-cosine flat top rather than a full-width
   Gaussian: it reaches the working point quickly and holds it. A slow continuous
   sweep spends the whole pulse crossing unintended near-resonances, notably
   :math:`|11\rangle` against :math:`|c2\rangle`, and adiabatically transfers
   population into them.
4. Integrate the Stark phase accumulated during the flux pulse.
5. Apply the closing :math:`X(+\pi/2)` with its phase offset by that amount, which
   is a virtual Z correction.

This recipe is for weakly anharmonic pairs. It models a flux pulse as a rigid shift of
the whole ladder, which stops being meaningful when a qubit's anharmonicity exceeds
half its frequency or the required detuning exceeds three quarters of it. A half-flux
fluxonium is far past both.

Such pairs use a **parametrically activated** CZ instead. The coupler is modulated at
the frequency separating :math:`|11\rangle` from :math:`|02\rangle` and
:math:`|20\rangle`,

.. math::

    g(t) = g\,f(t)\cos(2\pi f_{\mathrm{mod}} t), \qquad
    f_{\mathrm{mod}} = |E_{02} - E_{11}| / h

which makes the exchange resonant while both qubits stay at their operating points.
One full cycle out of :math:`|11\rangle` and back is a CZ, and a detuned cycle is an
arbitrary controlled phase. Frequency and duration are solved for by maximising the
average gate fidelity of the full multilevel propagator, with no rotating-wave
approximation. The Z phase the pulse leaves on each qubit is undone in the frame. The
mechanism is chosen automatically; passing an explicit ``detuning`` forces the
flux-activated gate. See :mod:`QubitWeave.core.parametric_gate`.

Noise
=====

With ``noise_model="realistic"``, the qubit's coherence estimate supplies
:math:`T_1`, which becomes a relaxation rate :math:`\Gamma_1 = 1/T_1` and enters
QuTiP's Lindblad solver as a collapse operator:

.. code-block:: python

    c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))

The evolution then runs as a master equation and returns a density matrix, so purity
falls over a long sequence. With ``noise_model="none"`` the evolution is closed and
the state remains pure.

Calibration
===========

.. code-block:: python

    duration, score = gates.calibrate_gate(
        "Q1",
        gate_type="X",
        parameter="duration",
    )

``calibrate_gate`` sweeps one parameter and returns the value maximising the target
population together with that population. Supported parameters are ``duration``,
``amplitude``, ``detuning`` and ``virtual_z``.

A duration sweep starts from an analytic estimate, whose form depends on the gate:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Case
     - Coarse range
   * - Single-qubit X, Y, H
     - 20 points across :math:`\pm 25` percent of
       :math:`T_{\mathrm{est}} = 3(\theta/\pi) \big/ \left(A |\langle 0|\hat{n}|1\rangle| \sqrt{2\pi}\right)`.
       The window is wide enough to find the :math:`\pi` peak and narrow enough to
       exclude the :math:`3\pi` one.
   * - Tunable-coupler CZ or CNOT
     - 12 points around each of ten scales of :math:`T_{\mathrm{est}} = 1/(\sqrt{2}g)`,
       from 0.15 to 7.5 times it. The achievable fidelity against coupler-pulse
       duration is multi-peaked, because the coupling-driven population transfer
       interferes with the detuning's own dynamical phase, and the tallest peak is
       not reliably near :math:`T_{\mathrm{est}}`.
   * - Parametric CZ or CNOT (strongly anharmonic pair on a tunable coupler)
     - Not swept. The duration is solved for, and the score returned is the average
       gate fidelity of the CZ.
   * - Capacitive CZ
     - 20 points across :math:`\pm 20` percent of :math:`T_{\mathrm{est}} = \pi/(4g)`.
   * - Anything else
     - 20 points from 10 to 100 ns.

A fine sweep of 20 points then zooms in on the coarse peak and is accepted only if
it improves on it.

The calibration cache
---------------------

Sweeps dominate the cost of most workflows, so results are cached in memory and on
disk at ``outputs/calib_cache.json``.

* A class-level dictionary holds calibrations for the process, and a class-level
  flag ensures the disk file is read once, when the first ``GateEngine`` is
  constructed.
* Cache keys are tuples of qubit names, gate type, coupling and drive parameters.
  JSON requires string keys, so QubitWeave writes ``str(key_tuple)`` and reads it back
  with ``ast.literal_eval``, which reconstructs the tuple exactly.

Run ``QubitWeave cache clear`` after changing a qubit's physical parameters, since a
calibration keyed to the old ones no longer describes the gate.

Fidelity and tomography
=======================

State tomography
----------------

.. code-block:: python

    metrics = gates.perform_state_tomography(state, target)
    # {"fidelity": ..., "trace_distance": ..., "purity": ...}

Fidelity is :math:`\left(\mathrm{Tr}\sqrt{\sqrt{\rho}\,\sigma\sqrt{\rho}}\right)^2`,
trace distance measures distinguishability, and purity :math:`\mathrm{Tr}(\rho^2)`
tracks the loss of coherence.

Average gate fidelity
---------------------

.. code-block:: python

    result = gates.calculate_gate_fidelity(
        "Q1", "Q2",
        gate_type="CNOT",
        coupling_type="tunable_coupler",
        strength=0.05,
        duration=150.0,
    )

Rather than running :math:`4^N` separate state simulations, QubitWeave computes the
exact propagator, projects it into the :math:`2^N` computational subspace, and
evaluates

.. math::

    \mathcal{F}_{\mathrm{avg}} =
        \frac{|\mathrm{Tr}(U_{\mathrm{ideal}}^\dagger U_{\mathrm{sim}})|^2 + d}{d(d+1)}

with :math:`d = 2^N`. For tunable-coupler CNOTs the local basis transformations are
applied to the propagator first, so the comparison is against the logical CNOT
rather than against the bare CZ.

Process tomography
------------------

``generate_process_tomography`` computes the propagator over the time-dependent
Hamiltonian, projects it into the computational subspace, converts it to a
superoperator and then to a Choi matrix. ``CircuitEngine`` turns that into Kraus
operators for circuit-level simulation with a physically derived noise channel.

.. warning::

   These metrics are not interchangeable. A state fidelity on one input state is
   neither an average gate fidelity nor a process fidelity. :doc:`conventions`
   compares them.

.. _ideal-paths:

Ideal operator paths
====================

QubitWeave keeps exact operator paths and uses them deliberately in three places:

* circuit-level abstractions where the pulse has already been calibrated,
* error-correction workflows, where a full ODE solve for every syndrome-extraction
  CNOT would be intractable,
* tests and known logical operations.

A method intended to model hardware retains its Hamiltonian, drive and coupling
formulation. An ideal operator is a choice made for a layer that has already
accounted for the physics, not a substitute for it.
