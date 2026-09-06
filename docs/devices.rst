==============
Device design
==============

The four preset qubit types cover a lot of ground, but not everything. If you want a
circuit that is not a transmon, a fluxonium, a flux qubit or zero-pi, draw it: write
the capacitors, inductors, junctions and resistors as a netlist, and qforge quantizes
whatever you wrote.

.. code-block:: text

    netlist (C, L, JJ, R, ground)
        │
        ▼  device_netlist
    branch energies EC, EL, EJ in GHz, units resolved
        │
        ▼
    node fluxes and charges, with the circuit's own loop and ground structure
        │
        ▼  device_engine, through scqubits symbolic quantization
    symbolic Hamiltonian, then a numerical one in a truncated basis
        │
        ▼
    eigenvalues, transitions, anharmonicity, dispersion, coherence
        │
        ▼  device_report
    tables, terminal plots, saved figures

Three modules, cleanly split. ``device_netlist`` does the language and unit
conversion and no physics. ``device_engine`` does the physics and never prints.
``device_report`` renders and never computes. Simulation therefore stays usable
headless, and the CLI and GUI share one renderer.

Getting started
===============

The fastest route is the wizard: ``qforge --interactive``, then "Design a device",
then "Start from a template". Nine worked circuits ship with qforge, from an LC
resonator to zero-pi.

From Python:

.. code-block:: python

    from qforge.core.device_engine import DeviceEngine

    engine = DeviceEngine()
    device = engine.create_device_from_file("examples/device_files/transmon.qdl")

    result = device.analyze()
    print(result["f01_ghz"], result["anharmonicity_mhz"])

The netlist language
====================

Free form, one card per line, keywords case insensitive. If you have written SPICE,
this will look familiar.

.. code-block:: text

    * A custom transmon                     -- '*' starts a full-line comment
    .title  Custom transmon
    .param  EJ0 = 15GHz                     -- named, sweepable parameter

    J1  1  0  EJ={EJ0}  EC=0.3GHz           -- Josephson junction
    C1  1  0  90fF                          -- shunt capacitor
    L1  1  0  100nH                         -- linear inductor
    R1  1  0  1MOhm                         -- resistor, dissipation only
    K1  L1 L2  EML=1nH                      -- mutual inductance between L1 and L2

    .flux    1 = 0.5                        -- external flux through loop 1, in Phi_0
    .charge  1 = 0.0                        -- offset charge ng_1, in units of 2e
    .cutoff  n1 = 30                        -- basis cutoff for periodic variable 1
    .levels  8                              -- eigenvalues to compute
    .end

Elements
--------

Cards are ``<name> <node+> <node-> <values...>``, and the first letter of the name
picks the element type, exactly like SPICE.

.. list-table::
   :header-rows: 1
   :widths: 12 30 58

   * - Letter
     - Card
     - Values
   * - ``C``
     - Capacitor
     - ``90fF`` or ``EC=0.3`` (GHz)
   * - ``L``
     - Inductor
     - ``100nH`` or ``EL=0.5`` (GHz)
   * - ``J``
     - Josephson junction
     - ``EJ=15 EC=0.3`` or ``Ic=30nA Cj=2fF``. Harmonics with ``EJ2=``, ``EJ3=``.
   * - ``R``
     - Resistor
     - ``1MOhm``. Not part of the Hamiltonian, used for the loading estimate.
   * - ``K``
     - Mutual inductance
     - ``k=0.05``, ``M=1nH`` or ``EML=<GHz>``, between two named inductors.

Node ``0``, ``gnd`` and ``ground`` all mean ground. Any other label becomes a circuit
node.

Units
-----

A bare number is always GHz, and the parser records a note saying so, because a
silently misread unit is the most common way this kind of code gives a wrong answer.

Physical units are SI with case sensitive prefixes: ``T G M k m u n p f a``.
``M`` is mega and ``m`` is milli, so ``1MOhm`` and ``1mOhm`` are a million ohms
apart. SPICE's case insensitive ``MEG`` convention is deliberately not supported: a
netlist mixing GHz with fF and nH has no room for an ambiguous ``M``.

Recognised units are ``Hz``, ``F``, ``H``, ``A``, ``J``, ``eV`` and ``Ohm``.

The conversions, with CODATA 2018 constants:

.. math::

    E_C = \frac{e^2}{2C}, \qquad
    E_L = \frac{(\Phi_0/2\pi)^2}{L}, \qquad
    E_J = \frac{I_c \Phi_0}{2\pi}, \qquad
    E_J = \frac{(\Phi_0/2\pi)^2}{L_J}

Directives
----------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Directive
     - Meaning
   * - ``.title <text>``
     - Human readable title.
   * - ``.name <text>``
     - Device name. Defaults to the file name.
   * - ``.param NAME = <value>``
     - A named, sweepable circuit parameter.
   * - ``.ground <node>``
     - Choose the ground node. Default is ``0`` or ``gnd``.
   * - ``.flux <i|all> = <Phi_0>``
     - External flux through loop ``i``.
   * - ``.charge <i|all> = <2e>``
     - Offset charge on periodic variable ``i``.
   * - ``.cutoff n<i>|ext<i>|all = N``
     - Basis cutoff for a variable.
   * - ``.levels <N>``
     - Eigenvalues to compute. Default 8.
   * - ``.options k=v ...``
     - ``ext_basis``, ``basis_completion``, ``truncated_dim``,
       ``use_dynamic_flux_grouping``, ``generate_noise_methods``.
   * - ``.end``
     - Stop parsing here.

Expressions
-----------

``{EJ0 / 50}`` evaluates over ``.param`` values, with ``+ - * / ** %`` and ``sqrt``,
``exp``, ``log``, ``log10``, ``sin``, ``cos``, ``tan``, ``abs``, ``min``, ``max``,
``round``, plus the constant ``pi``.

A bare ``.param`` name used directly, as in ``EJ=EJ0``, stays symbolic, which is what
makes it sweepable afterwards without editing the file.

Print the full reference at any time with ``device_report.render_format_reference()``,
or from the device menu in the wizard.

Basis cutoffs
=============

scqubits defaults to a charge cutoff of 5 for periodic variables, which is far too
small for a transmon. At :math:`E_J/E_C \approx 70` it misplaces the ground state by
several hundred MHz. A custom netlist has no preset to fall back on, so qforge picks
its own defaults and scales them down as the number of modes grows, since the Hilbert
space is the product over all of them:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Modes of that kind
     - Charge cutoff per periodic variable
     - Grid points per extended variable
   * - 1
     - 30
     - 110
   * - 2
     - 25
     - 50
   * - 3
     - 12
     - 25
   * - more
     - 8
     - 15

These are starting points, not answers. Override with ``.cutoff``, and check the
result:

.. code-block:: python

    check = device.check_convergence()
    print(check["converged"], check["max_transition_shift_mhz"])

``check_convergence`` re-diagonalizes with every cutoff raised by 50 percent and
reports the largest change in any transition frequency, so the spectrum comes with an
honest error bar. Move more than 1 MHz and it is called unconverged. It runs
automatically inside ``analyze()`` for Hilbert spaces below 40,000 states, where the
second diagonalization is cheap. The circuit's cutoffs are restored before it
returns.

Analysis
========

.. code-block:: python

    result = device.analyze(
        levels=8,
        coherence=True,
        matrix_elements=True,
        temperature=0.015,
    )

The result is a JSON serializable dict. The main keys:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - What it holds
   * - ``energies_ghz``, ``relative_ghz``
     - Absolute eigenvalues and eigenvalues referred to the ground state.
   * - ``f01_ghz``, ``f12_ghz``
     - The first two transitions.
   * - ``anharmonicity_ghz``, ``anharmonicity_mhz``
     - :math:`\alpha = f_{12} - f_{01}`.
   * - ``anharmonicity_meaningful``, ``anharmonicity_note``
     - Whether that number means what it usually means. See below.
   * - ``addressable``
     - Whether any realistic pulse can drive 0 to 1 without also driving 1 to 2.
   * - ``convergence``
     - The cutoff check, when it ran.
   * - ``matrix_elements``
     - :math:`|\langle i|Q|j\rangle|` per mode, plus ``g01`` and ``g12``.
   * - ``coherence``
     - Per channel noise estimates from scqubits.
   * - ``dissipation``
     - Classical loading estimate for each resistor.
   * - ``notes``, ``warnings``
     - Notes say how the netlist was read. Warnings say the answer may be wrong.

On anharmonicity
----------------

:math:`f_{12} - f_{01}` is only an anharmonicity when the circuit has one mode. With
several modes, level 2 may belong to a different mode entirely, and the difference is
then a spacing between two unrelated transitions. A circuit with no junctions is
purely harmonic and has no anharmonicity at all.

qforge does not quietly report a misleading number. ``anharmonicity_meaningful``
tells you which case you are in and ``anharmonicity_note`` explains it in words.

Matrix elements
---------------

``charge_matrix_elements`` gives :math:`|\langle i|Q|j\rangle|` in the energy
eigenbasis: periodic variables report the Cooper pair number operator, extended
variables the conjugate charge. These set how strongly a voltage drive couples one
level to another, which is what tells you whether a designed device can be driven at
all and which transition a drive will hit hardest. They are a coupling, not a gate
rate.

Coherence and dissipation
-------------------------

``coherence()`` asks scqubits which noise mechanisms this topology actually has: a
capacitive branch brings dielectric loss, an inductor brings inductive loss and flux
noise, a periodic variable brings charge noise, every junction brings critical
current noise. Times come back in microseconds. They are order of magnitude estimates
built on generic quality factors, not measurements of a fabricated device.

``dissipation()`` is separate and deliberately not called :math:`T_1`. For a resistor
:math:`R` across a node pair that also carries capacitance :math:`C`, it reports the
parallel RLC decay time :math:`\tau = RC` and the loaded quality factor
:math:`Q = 2\pi f_{01} R C`. That is a lumped element estimate of how hard the
environment loads the mode. It knows nothing about the circuit's eigenstates.

Sweeps
======

.. code-block:: python

    import numpy as np

    sweep = device.sweep("flux", np.linspace(0, 1, 41), levels=5)
    # {"parameter": ..., "values": [...], "energies_ghz": [[...]],
    #  "transitions_ghz": [[...]], "unit": "Phi_0"}

Sweep any external flux, offset charge, or named ``.param``. Friendly spellings work,
so ``"flux"``, ``"flux1"`` and ``"ng1"`` all resolve. With ``relative=True``, the
default, energies are reported against each point's own ground state, which is what a
spectroscopy plot shows. The device's own parameter value is restored when the sweep
finishes.

``sweepable_parameters()`` lists what this particular circuit exposes.

Handing a device to the gate engine
===================================

.. code-block:: python

    ops = device.effective_operators(levels=3)

    ops["H_ghz"]             # diagonal Hamiltonian, referred to the ground state
    ops["H_rad_per_ns"]      # the same thing times 2*pi, ready for QuTiP
    ops["charge_operators"]  # projected into the same basis

The conversion to rad/ns happens here rather than being left for you to remember.
Ask for three levels or more and :math:`|2\rangle` stays in the model instead of
being projected away, which is the whole point of keeping leakage visible.

Templates
=========

.. list-table::
   :header-rows: 1
   :widths: 26 12 62

   * - Template
     - Cost
     - What it shows
   * - ``transmon``
     - fast
     - A junction with a large shunt capacitor, around 4.8 GHz and -235 MHz.
   * - ``fluxonium``
     - fast
     - A junction shunted by a 327 nH superinductor, at the half flux sweet spot.
   * - ``cooper_pair_box``
     - fast
     - :math:`E_J/E_C` near 1. Sweep the offset charge to see why the transmon
       replaced it.
   * - ``lc_resonator``
     - fast
     - No junction at all, an exactly harmonic mode at 1.678 GHz. A good sanity
       check.
   * - ``flux_qubit``
     - moderate
     - Three junctions in a loop, one smaller by alpha.
   * - ``transmon_resonator``
     - moderate
     - A transmon near 4.7 GHz coupled through 5 fF to a 7 GHz resonator.
   * - ``coupled_transmons``
     - moderate
     - A detuned pair sharing a coupling capacitor.
   * - ``coupled_resonators``
     - moderate
     - Two resonators joined by a mutual inductance, with a resistor for loading.
       Demonstrates the ``K`` and ``R`` cards.
   * - ``zero_pi``
     - heavy
     - Two junctions, two superinductors, three modes. Exotic and slow.

.. code-block:: python

    from qforge.core import device_library

    device_library.list_templates()
    source = device_library.template_source("fluxonium")
    path = device_library.write_template("fluxonium", "my_fluxonium.qdl")

Each template is a complete runnable schematic and doubles as documentation of the
language by example. The cost label is a warning about Hilbert space size: a three
mode design takes considerably longer than a transmon.

Managing devices
================

.. code-block:: python

    engine.list_devices()
    engine.get_device("transmon_example")
    engine.has_device("transmon_example")
    engine.delete_device("transmon_example")

    engine.save_netlist("transmon_example", "out.qdl")
    engine.save_result("transmon_example", result)

Devices live under ``outputs/devices/`` with their registry at
``.qforge_devices.json``, kept separate from the preset qubits in
``outputs/qubits/``. A netlist device is not one of the four scqubits qubit types and
is deliberately not registered as one.

What gets stored is the netlist source, which is the complete self describing
definition of the device, so a reloaded session rebuilds an identical model rather
than restoring a pickled object. A saved netlist that no longer parses is skipped on
load rather than breaking the session.

Rendering
=========

.. code-block:: python

    from qforge.core import device_report

    device_report.render_netlist(device.netlist)     # elements, values, connectivity
    device_report.render_schematic(device.netlist)   # text drawing
    device_report.render_analysis(result)            # the full report
    device_report.render_sweep(sweep)

    device_report.plot_spectrum_terminal(result)
    device_report.plot_sweep_terminal(sweep)
    device_report.save_plots(device, result)         # matplotlib figures to disk

Every one of these takes an already computed result. None of them run physics.
