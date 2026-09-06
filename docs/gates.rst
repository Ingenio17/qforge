=====
Gates
=====

``GateEngine`` is where a logical operation becomes a pulse. It takes the eigenbasis
and physical operators of a circuit from ``QubitEngine``, builds a time dependent
Hamiltonian out of drives and couplings, hands it to QuTiP, and reports what
actually happened to the state.

Nothing here multiplies an ideal unitary unless you ask for one. An X gate is a
Gaussian microwave pulse acting on the charge operator. A CNOT on a tunable coupler
is a flux pulse through an avoided crossing wrapped in two calibrated
:math:`\pi/2` rotations.

.. code-block:: python

    from qforge.core.gate_engine import GateEngine

    gates = GateEngine()
    result = gates.simulate_dynamics("Q1", gate_type="X", duration=40.0)

Building the Hamiltonian
========================

Static part
-----------

For each qubit, qforge takes the lowest ``truncated_dim`` eigenvalues from scqubits
and builds a diagonal Hamiltonian, converting GHz to rad/ns as it goes:

.. code-block:: python

    evals = qubit.eigenvals(evals_count=dim)
    H0 = qt.Qobj(np.diag(evals)) * 2 * np.pi

Physical operators
------------------

Drive operators are pulled from the same eigenbasis rather than assumed. Driving a
transmon means applying a voltage that couples to the charge operator
:math:`\hat{n}`, and a flux bias couples to :math:`\hat{\varphi}`:

.. code-block:: python

    n_mat   = qubit.matrixelement_table("n_operator",   evals_count=dim)
    phi_mat = qubit.matrixelement_table("phi_operator", evals_count=dim)

These are exact matrix elements between the circuit's real eigenstates, which is
what makes leakage predictions meaningful. If a model exposes neither operator,
qforge falls back to the harmonic approximation
:math:`\hat{n} \approx \tfrac{i}{\sqrt{2}}(a^\dagger - a)` and
:math:`\hat{\varphi} \approx \tfrac{1}{\sqrt{2}}(a^\dagger + a)`.

Multi-qubit systems
-------------------

The N qubit Hamiltonian is the sum of local terms plus whatever interactions the
topology declares:

.. math::

    \mathcal{H}_{\mathrm{sys}} = \sum_i \mathcal{H}_{0,i}
        + \sum_{\langle i,j \rangle} g_{ij}\, \hat{O}_i \otimes \hat{O}_j

with :math:`\hat{O} = \hat{n}` for capacitive coupling and
:math:`\hat{O} = \hat{\varphi}` for inductive coupling. See :doc:`couplings`.

Rotating frame
==============

Integrating a 5 GHz carrier over a 40 ns pulse means resolving hundreds of
oscillations that carry no information about the gate. qforge transforms into the
frame rotating at :math:`\omega_{01}` first:

.. math::

    \mathcal{H}_{0,\mathrm{rot}} = \mathrm{diag}(0,\, 0,\, \alpha,\, \ldots)

where :math:`\alpha = \omega_{12} - \omega_{01}` is the anharmonicity. The
computational subspace goes flat, the higher levels keep their detuning, and the
solver only has to follow the envelope.

Single qubit control
====================

.. list-table::
   :header-rows: 1
   :widths: 12 88

   * - Gate
     - Physical implementation
   * - X
     - Capacitive drive on :math:`\hat{n}`.
   * - Y
     - The same drive phase shifted by 90 degrees. qforge builds it by taking the
       :math:`\hat{n}` matrix and forcing it purely imaginary and antisymmetric,
       :math:`i\,\mathrm{tril}(\hat{n}) - i\,\mathrm{triu}(\hat{n})`, which keeps
       the operator Hermitian.
   * - Z
     - Flux tuning or a Stark shift, mapped onto :math:`\hat{\varphi}`. In compiled
       circuits Z is virtual instead, see below.
   * - H
     - Synthesized from a :math:`Y(\pi/2)`-like drive, which preserves the global
       phase the algorithm expects.

Pulse envelopes
---------------

The default envelope is a Gaussian six sigma wide, so
:math:`\sigma = T/6` and :math:`\mu = T/2`:

.. math::

    \Omega(t) = A \exp\!\left(-\frac{(t-\mu)^2}{2\sigma^2}\right)

The peak amplitude is not guessed. qforge integrates the envelope numerically and
solves for the :math:`A` that makes the total rotation come out at the target angle:

.. math::

    A = \frac{\theta}{2\, |\langle 0|\hat{H}_{\mathrm{ctrl}}|1\rangle| \int \Omega(t)\,dt}

DRAG
----

A short pulse is spectrally wide, and with only a couple of hundred MHz of
anharmonicity between them, a drive meant for :math:`0 \rightarrow 1` also reaches
:math:`1 \rightarrow 2`. Derivative Removal by Adiabatic Gate fixes this by adding a
quadrature component proportional to the derivative of the envelope, scaled by the
anharmonicity:

.. math::

    \Omega_{\mathrm{DRAG}}(t) \propto \frac{\lambda}{\alpha}\, \dot{\Omega}(t)

In the code the in-phase term multiplies :math:`\cos(\omega t + \phi)` and the DRAG
term multiplies :math:`\sin(\omega t + \phi)`, with :math:`\lambda` exposed as
``drag_lambda`` (default 0.5) and :math:`\alpha` read from the qubit's own spectrum.
Turn it off with ``use_drag=False`` and watch :math:`|2\rangle` fill up.

Virtual Z
---------

A :math:`Z` rotation does not need a pulse at all. Because every subsequent X and Y
drive carries a phase, an :math:`R_Z(\theta)` can be absorbed by shifting the phase
of everything that follows. That costs no time and causes no decoherence, so
compiled circuits use it wherever they can. The ``virtual_z`` argument on the
simulation entry points carries that offset.

Two qubit gates
===============

Cross resonance
---------------

On a capacitively coupled pair, drive the control at the target's frequency. The
exchange interaction turns that drive into an effective :math:`ZX` term, which is a
CNOT up to local rotations.

Tunable coupler CZ and CNOT
---------------------------

A tunable coupler natively produces a controlled phase, so qforge compiles a
requested CNOT into the hardware sequence
:math:`X(-\pi/2) \rightarrow \mathrm{CZ} \rightarrow X(+\pi/2)` on the target. The
CZ itself is built like this:

1. Compute the flux detuning that brings :math:`|11\rangle` and :math:`|02\rangle`
   into resonance, from the qubits' own spectra.
2. Apply a physical :math:`X(-\pi/2)` pulse to the target.
3. Apply a flux pulse detuning the target and a :math:`\sin^2` coupler pulse
   simultaneously. The flux pulse is a raised cosine flat top, not a full width
   Gaussian: it reaches the working point quickly and holds it. A slow continuous
   sweep spends the whole pulse crossing other unintended near resonances, notably
   :math:`|11\rangle` against :math:`|c2\rangle`, and adiabatically leaks population
   into them.
4. Integrate the Stark phase accumulated during the flux pulse.
5. Apply the closing :math:`X(+\pi/2)` with its phase offset by exactly that amount,
   which is a virtual Z correction.

Noise
=====

With ``noise_model="realistic"``, qforge fetches the qubit's coherence estimate,
turns :math:`T_1` into a relaxation rate :math:`\Gamma_1 = 1/T_1`, and adds a
collapse operator to QuTiP's Lindblad solver:

.. code-block:: python

    c_ops.append(np.sqrt(rate_relax) * qt.destroy(dim))

The evolution then runs as a master equation and the state comes back as a density
matrix, so purity drops the way it should over a long sequence. With
``noise_model="none"`` the evolution is closed and the state stays pure.

Calibration
===========

.. code-block:: python

    duration, score = gates.calibrate_gate(
        "Q1",
        gate_type="X",
        parameter="duration",
    )

``calibrate_gate`` sweeps one parameter (duration, amplitude, detuning) and returns
the value that maximises the target population, along with that population.

It runs in three stages so it converges without burning simulations:

1. **Analytic guess.** For a single qubit gate the lab frame estimate is

   .. math::

       T_{\mathrm{est}} = \frac{3\,(\theta/\pi)}{A\, |\langle 0|\hat{n}|1\rangle| \sqrt{2\pi}}

   For a tunable coupler CZ it starts from :math:`T \approx 1/(\sqrt{2}\,g)`.

2. **Coarse sweep.** 20 points across a window of plus or minus 25 percent around
   the guess. That window is wide enough to find the :math:`\pi` peak and narrow
   enough to avoid locking onto the :math:`3\pi` one.

3. **Fine sweep.** Zoom in on the coarse peak and re-sweep another 20 points.

The calibration cache
---------------------

Sweeps are the expensive part of most workflows, so results are cached both in
memory and on disk at ``outputs/calib_cache.json``.

* A class level dictionary holds calibrations for the process. A class level flag
  makes sure the disk file is read exactly once, when the first ``GateEngine`` is
  constructed.
* Cache keys are tuples of qubit names, gate type, coupling and drive parameters.
  JSON needs string keys, so qforge writes ``str(key_tuple)`` and reads it back with
  ``ast.literal_eval``, which reconstructs the tuple exactly.

Clear the cache with ``qforge cache clear`` after changing a qubit's physical
parameters. A stale calibration is worse than none.

Fidelity and tomography
=======================

State tomography
----------------

.. code-block:: python

    metrics = gates.perform_state_tomography(state, target)
    # {"fidelity": ..., "trace_distance": ..., "purity": ...}

Fidelity is :math:`\left(\mathrm{Tr}\sqrt{\sqrt{\rho}\,\sigma\sqrt{\rho}}\right)^2`,
trace distance measures distinguishability, and purity
:math:`\mathrm{Tr}(\rho^2)` tracks how far decoherence has taken you.

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

Rather than run :math:`4^N` separate state simulations, qforge computes the exact
propagator, projects it into the :math:`2^N` computational subspace, and evaluates

.. math::

    \mathcal{F}_{\mathrm{avg}} =
        \frac{|\mathrm{Tr}(U_{\mathrm{ideal}}^\dagger U_{\mathrm{sim}})|^2 + d}{d(d+1)}

with :math:`d = 2^N`. For tunable coupler CNOTs the local basis transformations are
applied to the propagator first, so it is compared against the logical CNOT and not
against the bare CZ.

Process tomography
------------------

``generate_process_tomography`` builds the full process matrix: it computes the
propagator over the time dependent Hamiltonian, projects into the computational
subspace, converts to a superoperator and then to a Choi matrix. That is what
``CircuitEngine`` turns into Kraus operators when you want a physically derived
noise channel for circuit level simulation.

.. warning::

   These are different metrics with different meanings. A state fidelity on one
   input state is not an average gate fidelity, and neither is a process fidelity.
   :doc:`conventions` lists them side by side.

Ideal paths
===========

qforge does keep exact operator paths, and uses them on purpose:

* circuit level abstractions where the pulse has already been calibrated,
* error correction workflows, where simulating every syndrome extraction CNOT as a
  full ODE solve would be intractable,
* tests and known logical operations.

The rule is that a method meant to model hardware keeps its Hamiltonian, drive and
coupling formulation. An ideal operator is a deliberate choice for a layer that has
already accounted for the physics, not a shortcut past it.
