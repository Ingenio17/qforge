"""
Device Engine: quantize a custom circuit netlist and analyse the resulting qubit.

This is the simulation half of the "Design Device" workflow. It takes the
validated schematic produced by :mod:`qforge.core.device_netlist`, hands the
circuit to scqubits' symbolic circuit quantization, and reports what the device
actually is: its energy levels, transition frequencies, anharmonicity, charge and
flux dispersion, coherence estimates and drive matrix elements.

The physical chain is the one qforge follows everywhere::

    netlist (C, L, JJ, R, ground)
        -> branch energies EC, EL, EJ  (GHz)
        -> node fluxes and charges, with the circuit's own loop/ground structure
        -> symbolic Hamiltonian, then a numerical one in a truncated basis
        -> eigenvalues, transitions, anharmonicity, dispersion, coherence

Nothing here plots or prints. Rendering lives in
:mod:`qforge.core.device_report`, so every method below is usable headless.

Units
-----
Energies are GHz throughout (that is E/h, the convention scqubits and the rest of
qforge use), times are ns unless a field name says otherwise, external flux is in
units of the flux quantum, and offset charge is in units of 2e (Cooper pairs).
A Hamiltonian handed to a time-domain solver must be multiplied by 2*pi to become
rad/ns; :meth:`QuantumDevice.effective_operators` does that conversion explicitly
rather than leaving it to the caller to remember.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from qforge.config.defaults import OUTPUT_DIRS
from qforge.core.device_netlist import (
    DeviceNetlist,
    NetlistError,
    parse_netlist,
    parse_netlist_file,
)

__all__ = ["DeviceEngine", "QuantumDevice", "DeviceError"]


class DeviceError(Exception):
    """A device could not be built, or an analysis could not be carried out."""


# ---------------------------------------------------------------------------
# Basis-size defaults
# ---------------------------------------------------------------------------
#
# scqubits defaults to a charge cutoff of 5 for periodic variables, which is far
# too small for a transmon: at EJ/EC ~ 70 it misplaces the ground state by
# several hundred MHz. Since a custom netlist has no preset to fall back on, the
# engine chooses its own defaults and scales them down as the number of modes
# grows, because the Hilbert space is the product over all of them.
#
# These are starting points, not answers. `.cutoff` in the netlist overrides
# them, and QuantumDevice.check_convergence() measures whether the choice was
# good enough for the circuit at hand.

# Charge cutoff n_cut per periodic variable, keyed by how many there are.
DEFAULT_PERIODIC_CUTOFFS: dict[int, int] = {1: 30, 2: 25, 3: 12}
DEFAULT_PERIODIC_CUTOFF_MANY = 8

# Grid points per extended variable, keyed by how many there are. A single
# extended variable gets 110, matching qforge's fluxonium preset.
DEFAULT_EXTENDED_CUTOFFS: dict[int, int] = {1: 110, 2: 50, 3: 25}
DEFAULT_EXTENDED_CUTOFF_MANY = 15

# Above this Hilbert-space dimension, diagonalization gets slow enough that the
# caller deserves a warning before it starts.
LARGE_HILBERT_DIM = 40_000

# Factor by which cutoffs are raised in a convergence check, and the transition
# shift above which the result is called unconverged (in GHz).
CONVERGENCE_CUTOFF_FACTOR = 1.5
CONVERGENCE_TOLERANCE_GHZ = 1e-3

# Bath temperature used for the built-in coherence estimates, in kelvin. Matches
# NOISE_DEFAULTS in qforge.config.defaults.
DEFAULT_TEMPERATURE_K = 0.015


class QuantumDevice:
    """
    A quantized custom circuit: a netlist plus the scqubits model built from it.

    Construct one through :class:`DeviceEngine`, or directly from a netlist::

        device = QuantumDevice(parse_netlist_file("transmon.qdl"))
        result = device.analyze()
        print(result["f01_ghz"], result["anharmonicity_mhz"])

    The scqubits circuit is built lazily on first use, so constructing a device
    is cheap and parse errors surface before any linear algebra happens.
    """

    def __init__(self, netlist: DeviceNetlist, name: str | None = None):
        if not isinstance(netlist, DeviceNetlist):
            raise TypeError("QuantumDevice needs a DeviceNetlist")
        self.netlist = netlist
        self.name = name or netlist.name
        # Notes come from the netlist and say how it was read; warnings come from
        # quantizing it and say something may be wrong with the answer. Keeping
        # them apart stops "this value was read as GHz" from looking like a fault.
        self.notes: list[str] = list(netlist.notes)
        self.warnings: list[str] = []
        self._circuit = None
        self._yaml = netlist.to_scqubits_yaml()

    # -- construction ------------------------------------------------------

    @property
    def circuit(self):
        """The underlying ``scqubits.Circuit``, built on first access."""
        if self._circuit is None:
            self._circuit = self._build_circuit()
        return self._circuit

    @property
    def scqubits_yaml(self) -> str:
        """The circuit description handed to scqubits, useful for debugging."""
        return self._yaml

    def rebuild(self) -> None:
        """Discard the quantized model so the next access rebuilds it from the netlist."""
        self._circuit = None

    def _build_circuit(self):
        try:
            import scqubits as scq
        except ImportError as exc:  # pragma: no cover - scqubits is a hard dependency
            raise DeviceError("scqubits is required to quantize a device netlist") from exc

        options = self.netlist.options

        # A circuit with no junctions has an exactly quadratic potential, and
        # scqubits asks for the harmonic-oscillator basis in that case: it is both
        # more accurate and far cheaper than discretizing a flux grid over an
        # exact oscillator. An explicit .options ext_basis still wins.
        default_ext_basis = "harmonic" if not self.netlist.junctions else "discretized"

        kwargs = dict(
            from_file=False,
            ext_basis=str(options.get("ext_basis", default_ext_basis)),
            basis_completion=str(options.get("basis_completion", "heuristic")),
            use_dynamic_flux_grouping=bool(options.get("use_dynamic_flux_grouping", False)),
            truncated_dim=int(options.get("truncated_dim", max(10, self.netlist.levels))),
        )
        want_noise = bool(options.get("generate_noise_methods", True))

        try:
            circuit = scq.Circuit(self._yaml, generate_noise_methods=want_noise, **kwargs)
        except Exception as exc:
            if want_noise:
                # The noise-method generator is the fragile part for unusual
                # topologies; the circuit itself is usually still fine without it.
                try:
                    circuit = scq.Circuit(self._yaml, generate_noise_methods=False, **kwargs)
                    self._warn(
                        f"Coherence estimates are unavailable for this topology "
                        f"({type(exc).__name__}: {exc})."
                    )
                except Exception as inner:
                    raise DeviceError(self._build_failure_message(inner)) from inner
            else:
                raise DeviceError(self._build_failure_message(exc)) from exc

        self._apply_cutoffs(circuit)
        self._apply_biases(circuit)
        return circuit

    def _build_failure_message(self, exc: Exception) -> str:
        return (
            f"Could not quantize '{self.name}': {type(exc).__name__}: {exc}\n"
            f"The circuit qforge handed to scqubits was:\n{self._yaml}"
        )

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    # -- basis and bias ----------------------------------------------------

    def _apply_cutoffs(self, circuit) -> None:
        """
        Set every variable's basis cutoff, from the netlist where given and from
        the size-aware defaults otherwise.
        """
        categories = circuit.var_categories
        periodic = list(categories.get("periodic", []))
        extended = list(categories.get("extended", []))

        default_periodic = DEFAULT_PERIODIC_CUTOFFS.get(len(periodic), DEFAULT_PERIODIC_CUTOFF_MANY)
        default_extended = DEFAULT_EXTENDED_CUTOFFS.get(len(extended), DEFAULT_EXTENDED_CUTOFF_MANY)

        requested = {key.lower(): value for key, value in self.netlist.cutoffs.items()}

        def lookup(prefix: str, index: int, fallback: int) -> int:
            for key in (f"{prefix}{index}", prefix, "all"):
                if key in requested:
                    return requested[key]
            return fallback

        applied: dict[str, int] = {}
        for index in periodic:
            applied[f"cutoff_n_{index}"] = lookup("n", index, default_periodic)
        for index in extended:
            applied[f"cutoff_ext_{index}"] = lookup("ext", index, default_extended)

        for attribute, value in applied.items():
            if attribute in circuit.cutoff_names:
                setattr(circuit, attribute, int(value))

        unknown = set(requested) - {"all", "n", "ext"}
        for index in periodic:
            unknown.discard(f"n{index}")
        for index in extended:
            unknown.discard(f"ext{index}")
        if unknown:
            self._warn(
                f".cutoff refers to variable(s) {', '.join(sorted(unknown))} that this "
                f"circuit does not have. Its variables are: "
                f"{', '.join(circuit.cutoff_names) or 'none'}."
            )

    def _apply_biases(self, circuit) -> None:
        """Apply the netlist's ``.flux`` and ``.charge`` directives."""
        flux_names = [symbol.name for symbol in circuit.external_fluxes]
        charge_names = [symbol.name for symbol in circuit.offset_charges]

        for target, value in self.netlist.fluxes.items():
            if target == "all":
                for name in flux_names:
                    setattr(circuit, name, float(value))
                continue
            index = _as_index(target)
            applied = False
            for name in flux_names:
                if _trailing_index(name) == index:
                    setattr(circuit, name, float(value))
                    applied = True
            if not applied:
                self._warn(
                    f".flux {target} was ignored: this circuit has "
                    f"{len(flux_names)} independent loop(s)."
                )

        for target, value in self.netlist.charges.items():
            if target == "all":
                for name in charge_names:
                    setattr(circuit, name, float(value))
                continue
            index = _as_index(target)
            applied = False
            for name in charge_names:
                if _trailing_index(name) == index:
                    setattr(circuit, name, float(value))
                    applied = True
            if not applied:
                self._warn(
                    f".charge {target} was ignored: this circuit has "
                    f"{len(charge_names)} periodic (charge) variable(s)."
                )

    # -- introspection -----------------------------------------------------

    @property
    def hilbert_dim(self) -> int:
        """Dimension of the truncated Hilbert space the circuit is diagonalized in."""
        return int(self.circuit.hilbertdim())

    def external_flux_names(self) -> list[str]:
        """scqubits' names for the circuit's independent external fluxes."""
        return [symbol.name for symbol in self.circuit.external_fluxes]

    def offset_charge_names(self) -> list[str]:
        """scqubits' names for the circuit's offset charges."""
        return [symbol.name for symbol in self.circuit.offset_charges]

    def free_charge_names(self) -> list[str]:
        """Free charges, which only appear when the circuit has no ground node."""
        return [symbol.name for symbol in getattr(self.circuit, "free_charges", [])]

    def circuit_parameter_names(self) -> list[str]:
        """Named branch parameters, i.e. the ``.param`` values used symbolically."""
        return [symbol.name for symbol in getattr(self.circuit, "symbolic_params", {})]

    def sweepable_parameters(self) -> dict[str, float]:
        """
        Every knob :meth:`sweep` accepts, mapped to its current value.

        Covers named circuit parameters (GHz), external fluxes (flux quanta) and
        offset charges (Cooper pairs).
        """
        circuit = self.circuit
        knobs: dict[str, float] = {}
        for name in self.circuit_parameter_names():
            knobs[name] = float(getattr(circuit, name))
        for name in self.external_flux_names():
            knobs[name] = float(getattr(circuit, name))
        for name in self.offset_charge_names():
            knobs[name] = float(getattr(circuit, name))
        return knobs

    def resolve_parameter(self, name: str) -> str:
        """
        Map a user-facing knob name onto the attribute scqubits uses.

        Accepts the scqubits name itself, and the friendlier spellings a terminal
        user is likely to type: ``flux1``/``Phi1``/``1`` for the first external
        flux, and ``ng1``/``charge1`` for the first offset charge.
        """
        circuit = self.circuit
        if hasattr(circuit, name) and name in self.sweepable_parameters():
            return name

        lowered = name.strip().lower()
        flux_names = self.external_flux_names()
        charge_names = self.offset_charge_names()

        if lowered in ("flux", "phi") and len(flux_names) == 1:
            return flux_names[0]
        if lowered in ("ng", "charge") and len(charge_names) == 1:
            return charge_names[0]

        index = _as_index(lowered)
        if index is not None:
            for prefix, names in (("flux", flux_names), ("phi", flux_names)):
                if lowered.startswith(prefix) or lowered == str(index):
                    for candidate in names:
                        if _trailing_index(candidate) == index:
                            return candidate
            if lowered.startswith(("ng", "charge")):
                for candidate in charge_names:
                    if _trailing_index(candidate) == index:
                        return candidate

        for candidate in self.sweepable_parameters():
            if candidate.lower() == lowered:
                return candidate

        raise DeviceError(
            f"'{name}' is not a parameter of this device. Available: "
            f"{', '.join(self.sweepable_parameters()) or 'none'}"
        )

    def set_parameter(self, name: str, value: float) -> None:
        """Set one sweepable parameter, by any name :meth:`resolve_parameter` accepts."""
        setattr(self.circuit, self.resolve_parameter(name), float(value))

    def describe_circuit(self) -> dict[str, Any]:
        """Structural facts about the quantized circuit, for reports and sessions."""
        circuit = self.circuit
        categories = circuit.var_categories
        try:
            symbolic = str(circuit.sym_hamiltonian(return_expr=True))
        except Exception:
            symbolic = ""
        return {
            "hilbert_dim": self.hilbert_dim,
            "num_modes": len(categories.get("periodic", [])) + len(categories.get("extended", [])),
            "periodic_vars": list(categories.get("periodic", [])),
            "extended_vars": list(categories.get("extended", [])),
            "free_vars": list(categories.get("free", [])),
            "frozen_vars": list(categories.get("frozen", [])),
            "cutoffs": {name: int(getattr(circuit, name)) for name in circuit.cutoff_names},
            "external_fluxes": {
                name: float(getattr(circuit, name)) for name in self.external_flux_names()
            },
            "offset_charges": {
                name: float(getattr(circuit, name)) for name in self.offset_charge_names()
            },
            "free_charges": {
                name: float(getattr(circuit, name)) for name in self.free_charge_names()
            },
            "parameters": {
                name: float(getattr(circuit, name)) for name in self.circuit_parameter_names()
            },
            "is_purely_harmonic": bool(getattr(circuit, "is_purely_harmonic", False)),
            "is_grounded": bool(getattr(circuit, "is_grounded", True)),
            "symbolic_hamiltonian": symbolic,
        }

    # -- spectrum ----------------------------------------------------------

    def eigenvalues(self, levels: int | None = None) -> np.ndarray:
        """
        The lowest ``levels`` eigenvalues of the circuit Hamiltonian, in GHz.

        These are absolute energies E/h, not referred to the ground state.
        """
        count = self._level_count(levels)
        return np.asarray(self._diagonalize(count, with_states=False), dtype=float)

    def eigensystem(self, levels: int | None = None):
        """Eigenvalues (GHz) and eigenvectors, with the same solver fallback."""
        return self._diagonalize(self._level_count(levels), with_states=True)

    def _level_count(self, levels: int | None) -> int:
        count = int(levels or self.netlist.levels)
        if count < 2:
            raise DeviceError("At least 2 levels are needed to describe a qubit.")
        if count > self.hilbert_dim:
            raise DeviceError(
                f"Asked for {count} levels but the truncated Hilbert space only has "
                f"{self.hilbert_dim} states. Raise the cutoffs with .cutoff."
            )
        return count

    def _diagonalize(self, count: int, with_states: bool):
        """
        Diagonalize the circuit, falling back to a dense solver if the sparse one
        gives up.

        scqubits reaches for ARPACK by default, which is the right choice for the
        large sparse Hamiltonians these circuits produce. But ARPACK is iterative,
        and on a badly conditioned Hamiltonian (a circuit spanning many orders of
        magnitude in energy, say) it can exhaust its iterations without converging
        on a single eigenvector. A dense solve is slower and heavier but always
        returns an answer, which is much better than handing the user an ARPACK
        traceback for a circuit they just drew.
        """
        circuit = self.circuit
        solve = circuit.eigensys if with_states else circuit.eigenvals
        try:
            return solve(evals_count=count)
        except Exception as exc:
            original = getattr(circuit, "type_of_matrices", None)
            if original != "sparse":
                raise DeviceError(
                    f"Could not diagonalize '{self.name}': {type(exc).__name__}: {exc}"
                ) from exc
            try:
                circuit.type_of_matrices = "dense"
                result = solve(evals_count=count)
            except Exception as inner:
                circuit.type_of_matrices = original
                raise DeviceError(
                    f"Could not diagonalize '{self.name}' with either the sparse or "
                    f"the dense solver: {type(inner).__name__}: {inner}\n"
                    f"The Hilbert space has {self.hilbert_dim:,} states; try different "
                    f"cutoffs, or check the branch energies for an implausible value."
                ) from inner
            self._warn(
                f"The sparse eigensolver did not converge ({type(exc).__name__}), so "
                f"a dense one was used instead. This is usually a sign that the "
                f"circuit's branch energies span a very wide range."
            )
            return result

    def spectrum(self, levels: int | None = None) -> dict[str, Any]:
        """
        Energy levels and everything that follows directly from them.

        Returns absolute energies, energies relative to the ground state, the
        successive level spacings, f01 and f12, and the anharmonicity
        ``alpha = f12 - f01``, which is what decides whether the circuit can be
        addressed as a qubit at all.

        The anharmonicity is only the anharmonicity of a ladder when the circuit
        has a single mode. With several modes, level 2 may belong to a different
        mode entirely, and ``f12 - f01`` is then a spacing between unrelated
        transitions; ``anharmonicity_meaningful`` says which case this is, and
        ``anharmonicity_note`` explains it in words.
        """
        energies = self.eigenvalues(levels)
        relative = energies - energies[0]
        spacings = np.diff(energies)

        categories = self.circuit.var_categories
        num_modes = len(categories.get("periodic", [])) + len(categories.get("extended", []))
        purely_harmonic = bool(getattr(self.circuit, "is_purely_harmonic", False))

        result: dict[str, Any] = {
            "levels": int(len(energies)),
            "energies_ghz": energies.tolist(),
            "relative_ghz": relative.tolist(),
            "level_spacings_ghz": spacings.tolist(),
            "transitions_ghz": [
                {"from": i, "to": i + 1, "frequency_ghz": float(spacings[i])}
                for i in range(len(spacings))
            ],
            "f01_ghz": float(spacings[0]),
            "num_modes": num_modes,
        }

        if len(spacings) >= 2:
            f01, f12 = float(spacings[0]), float(spacings[1])
            anharmonicity = f12 - f01
            if purely_harmonic:
                note = (
                    "This circuit has no junctions, so every mode is a harmonic "
                    "oscillator with an evenly spaced ladder. A non-zero value here "
                    "is the spacing between two different modes, not an anharmonicity."
                )
                meaningful = False
            elif num_modes > 1:
                note = (
                    f"This circuit has {num_modes} modes, so levels 1 and 2 need not "
                    f"belong to the same ladder. Read f12 - f01 as the spacing between "
                    f"consecutive eigenvalues, and check the mode structure before "
                    f"calling it an anharmonicity."
                )
                meaningful = False
            else:
                note = "alpha = f12 - f01 for the single mode of this circuit."
                meaningful = True

            result.update(
                {
                    "f12_ghz": f12,
                    "anharmonicity_ghz": anharmonicity,
                    "anharmonicity_mhz": anharmonicity * 1e3,
                    "relative_anharmonicity": anharmonicity / f01 if f01 else float("nan"),
                    "anharmonicity_meaningful": meaningful,
                    "anharmonicity_note": note,
                    # Below about a MHz of anharmonicity, no realistic pulse can
                    # address 0-1 without driving 1-2.
                    "addressable": bool(meaningful and abs(anharmonicity) * 1e3 > 1.0),
                }
            )
        else:
            result.update(
                {
                    "f12_ghz": None,
                    "anharmonicity_ghz": None,
                    "anharmonicity_mhz": None,
                    "relative_anharmonicity": None,
                    "anharmonicity_meaningful": False,
                    "anharmonicity_note": "At least 3 levels are needed for an anharmonicity.",
                    "addressable": None,
                }
            )
        return result

    def check_convergence(self, levels: int | None = None) -> dict[str, Any]:
        """
        Re-diagonalize with larger cutoffs and report how much the answer moved.

        A truncated basis is an approximation, and for a circuit nobody has seen
        before there is no preset that says how large it needs to be. This raises
        every cutoff by :data:`CONVERGENCE_CUTOFF_FACTOR` and returns the largest
        change in any transition frequency, so the reported spectrum comes with
        an honest error bar.

        The circuit's cutoffs are restored before returning.
        """
        circuit = self.circuit
        count = int(levels or self.netlist.levels)
        baseline = self.eigenvalues(count)
        baseline_transitions = np.diff(baseline)

        original = {name: int(getattr(circuit, name)) for name in circuit.cutoff_names}
        raised = {
            name: max(value + 1, int(round(value * CONVERGENCE_CUTOFF_FACTOR)))
            for name, value in original.items()
        }

        try:
            for name, value in raised.items():
                setattr(circuit, name, value)
            refined = np.asarray(self._diagonalize(count, with_states=False), dtype=float)
        except Exception as exc:
            for name, value in original.items():
                setattr(circuit, name, value)
            return {
                "converged": None,
                "error": f"{type(exc).__name__}: {exc}",
                "cutoffs": original,
            }
        finally:
            for name, value in original.items():
                setattr(circuit, name, value)

        refined_transitions = np.diff(refined)
        shift = float(np.max(np.abs(refined_transitions - baseline_transitions)))
        return {
            "converged": bool(shift < CONVERGENCE_TOLERANCE_GHZ),
            "max_transition_shift_ghz": shift,
            "max_transition_shift_mhz": shift * 1e3,
            "tolerance_ghz": CONVERGENCE_TOLERANCE_GHZ,
            "cutoffs": original,
            "raised_cutoffs": raised,
        }

    # -- matrix elements ---------------------------------------------------

    def charge_matrix_elements(self, levels: int | None = None) -> dict[str, Any]:
        """
        Charge-operator matrix elements between the lowest eigenstates.

        For each mode this returns ``|<i|Q|j>|`` in the energy eigenbasis. These
        set how strongly a voltage drive on that mode couples one level to
        another, so they are what tells you whether a designed device can be
        driven at all, and which transition a drive will hit hardest.

        Periodic (charge) variables report the Cooper-pair number operator
        ``n_i``; extended variables report the conjugate charge ``Q_i``.
        """
        circuit = self.circuit
        count = int(levels or self.netlist.levels)
        categories = circuit.var_categories

        operators: list[tuple[str, str]] = []
        for index in categories.get("periodic", []):
            operators.append((f"n{index}", f"n{index}_operator"))
        for index in categories.get("extended", []):
            operators.append((f"Q{index}", f"Q{index}_operator"))

        if not operators:
            return {"operators": {}, "note": "This circuit has no dynamical charge variables."}

        try:
            evals, evecs = self._diagonalize(count, with_states=True)
        except Exception as exc:
            return {"operators": {}, "error": f"{type(exc).__name__}: {exc}"}

        tables: dict[str, Any] = {}
        for label, attribute in operators:
            method = getattr(circuit, attribute, None)
            if method is None:
                continue
            try:
                matrix = method()
                dense = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
                projected = evecs.conj().T @ (dense @ evecs)
                tables[label] = {
                    "abs": np.abs(projected).tolist(),
                    "g01": float(abs(projected[0, 1])),
                    "g12": float(abs(projected[1, 2])) if count > 2 else None,
                }
            except Exception as exc:
                tables[label] = {"error": f"{type(exc).__name__}: {exc}"}

        return {
            "operators": tables,
            "note": (
                "Values are |<i|Q|j>| in the eigenbasis, in units of 2e for periodic "
                "variables. They set the drive coupling, not a gate rate on their own."
            ),
        }

    # -- coherence and dissipation -----------------------------------------

    def coherence(self, temperature: float = DEFAULT_TEMPERATURE_K) -> dict[str, Any]:
        """
        Coherence estimates from scqubits' noise channels for this topology.

        scqubits works out which mechanisms apply from the circuit itself: a
        capacitive branch brings dielectric loss, an inductor brings inductive
        loss and flux noise, a periodic variable brings charge noise, and every
        junction brings critical-current noise. Times are returned in
        microseconds.

        These are order-of-magnitude estimates built on generic quality factors
        and noise amplitudes, not measurements of a fabricated device.
        """
        circuit = self.circuit
        # A scqubits Circuit always carries the noise method names; they raise when
        # the methods were not generated, so the flag is what has to be checked.
        if not getattr(circuit, "generate_noise_methods", False):
            return {
                "available": False,
                "reason": (
                    "Noise methods were not generated for this circuit "
                    "(.options generate_noise_methods=true turns them on)."
                ),
                "channels": {},
            }

        try:
            import scqubits as scq

            scq.settings.T1_DEFAULT_WARNING = False
        except Exception:
            pass

        channels: dict[str, dict[str, Any]] = {}
        try:
            effective = list(circuit.effective_noise_channels())
        except Exception as exc:
            return {
                "available": False,
                "reason": f"scqubits could not list noise channels: {exc}",
                "channels": {},
            }

        for channel in effective:
            method = getattr(circuit, channel, None)
            if method is None:
                continue
            try:
                # scqubits returns times in units of 1/frequency; with energies in
                # GHz that is nanoseconds.
                time_ns = float(method(T=temperature))
            except TypeError:
                try:
                    time_ns = float(method())
                except Exception as exc:
                    channels[channel] = {"error": f"{type(exc).__name__}: {exc}"}
                    continue
            except Exception as exc:
                channels[channel] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            if np.isfinite(time_ns):
                channels[channel] = {"time_us": time_ns / 1e3, "kind": _channel_kind(channel)}

        try:
            supported = list(circuit.supported_noise_channels())
        except Exception:
            supported = []

        summary: dict[str, Any] = {
            "available": True,
            "temperature_k": temperature,
            "channels": channels,
            "supported": supported,
        }
        for label, method_name in (
            ("t1_effective_us", "t1_effective"),
            ("t2_effective_us", "t2_effective"),
        ):
            method = getattr(circuit, method_name, None)
            if method is None:
                continue
            try:
                value = float(method())
                summary[label] = value / 1e3 if np.isfinite(value) else None
            except Exception:
                summary[label] = None
        return summary

    def dissipation(self, f01_ghz: float | None = None) -> list[dict[str, Any]]:
        """
        Classical loading estimate for each resistor in the netlist.

        Resistors are not part of the circuit Hamiltonian; they describe an
        environment. For a resistor R sitting across a node pair that also carries
        a capacitance C, the parallel RLC energy decay time is ``tau = R C`` and
        the loaded quality factor at the qubit frequency is ``Q = 2*pi*f01*R*C``.

        This is a lumped-element estimate of how hard the environment loads the
        mode. It is deliberately not called T1: it does not know the circuit's
        eigenstates, and it is not the quantum noise calculation that
        :meth:`coherence` performs.
        """
        entries: list[dict[str, Any]] = []
        for resistor in self.netlist.resistors:
            node_a, node_b = resistor.node_indices
            capacitance = self.netlist.capacitance_between(node_a, node_b)
            entry: dict[str, Any] = {
                "name": resistor.name,
                "nodes": list(resistor.nodes),
                "resistance_ohm": resistor.resistance_ohm,
                "parallel_capacitance_f": capacitance or None,
                "tau_rc_ns": None,
                "quality_factor": None,
            }
            if capacitance > 0 and resistor.resistance_ohm:
                tau_seconds = resistor.resistance_ohm * capacitance
                entry["tau_rc_ns"] = tau_seconds * 1e9
                if f01_ghz:
                    entry["quality_factor"] = 2.0 * np.pi * f01_ghz * 1e9 * tau_seconds
            else:
                entry["note"] = (
                    "No capacitance directly across this resistor, so there is no "
                    "local RC time to quote."
                )
            entries.append(entry)
        return entries

    # -- sweeps ------------------------------------------------------------

    def sweep(
        self,
        parameter: str,
        values: Sequence[float],
        levels: int | None = None,
        relative: bool = True,
    ) -> dict[str, Any]:
        """
        Recompute the spectrum across a range of one parameter.

        Args:
            parameter: A knob from :meth:`sweepable_parameters`, or a friendly
                spelling such as ``"flux"``, ``"flux1"`` or ``"ng1"``.
            values: The parameter values to step through.
            levels: How many eigenvalues to track. Defaults to the netlist's.
            relative: Report energies relative to each point's own ground state,
                which is what a spectroscopy plot shows.

        Returns:
            A dict with ``values``, ``energies`` as a ``(len(values), levels)``
            table, the ``transitions`` from the ground state, and the parameter's
            resolved name. The device's own parameter value is restored on exit.
        """
        attribute = self.resolve_parameter(parameter)
        count = int(levels or self.netlist.levels)
        grid = np.asarray(list(values), dtype=float)
        if grid.size == 0:
            raise DeviceError("A sweep needs at least one value.")

        circuit = self.circuit
        original = float(getattr(circuit, attribute))
        try:
            data = circuit.get_spectrum_vs_paramvals(
                attribute, grid, evals_count=count, subtract_ground=relative
            )
            table = np.asarray(data.energy_table, dtype=float)
        except Exception as exc:
            raise DeviceError(
                f"Sweep over '{attribute}' failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            setattr(circuit, attribute, original)

        transitions = table - table[:, [0]]
        return {
            "parameter": attribute,
            "requested_parameter": parameter,
            "values": grid.tolist(),
            "energies_ghz": table.tolist(),
            "transitions_ghz": transitions.tolist(),
            "relative": bool(relative),
            "levels": count,
            "unit": _parameter_unit(
                attribute, self.external_flux_names(), self.offset_charge_names()
            ),
        }

    # -- export ------------------------------------------------------------

    def effective_operators(self, levels: int = 3) -> dict[str, Any]:
        """
        The device reduced to a few levels, ready for time-domain simulation.

        Returns the diagonal Hamiltonian in the energy eigenbasis, referred to the
        ground state, both in GHz and in rad/ns (the angular-frequency units a
        QuTiP solver expects), together with the charge operators projected into
        the same basis so a drive can be written down without leaving qforge's
        conventions.

        Truncating here keeps the leakage levels that matter: pass ``levels=3``
        or more and ``|2>`` stays in the model rather than being projected away.
        """
        try:
            import qutip as qt
        except ImportError as exc:  # pragma: no cover - qutip is a hard dependency
            raise DeviceError("QuTiP is required to export operators") from exc

        circuit = self.circuit
        if levels < 2:
            raise DeviceError("At least 2 levels are needed.")
        evals, evecs = self._diagonalize(self._level_count(levels), with_states=True)
        relative = np.asarray(evals, dtype=float) - float(evals[0])

        hamiltonian_ghz = qt.Qobj(np.diag(relative))
        operators: dict[str, Any] = {}
        categories = circuit.var_categories
        for index in categories.get("periodic", []):
            operators[f"n{index}"] = f"n{index}_operator"
        for index in categories.get("extended", []):
            operators[f"Q{index}"] = f"Q{index}_operator"

        projected: dict[str, Any] = {}
        for label, attribute in operators.items():
            method = getattr(circuit, attribute, None)
            if method is None:
                continue
            matrix = method()
            dense = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
            projected[label] = qt.Qobj(evecs.conj().T @ (dense @ evecs))

        return {
            "levels": levels,
            "energies_ghz": relative.tolist(),
            "H_ghz": hamiltonian_ghz,
            "H_rad_per_ns": 2.0 * np.pi * hamiltonian_ghz,
            "charge_operators": projected,
        }

    # -- the whole story ---------------------------------------------------

    def analyze(
        self,
        levels: int | None = None,
        coherence: bool = True,
        matrix_elements: bool = True,
        convergence: bool | None = None,
        temperature: float = DEFAULT_TEMPERATURE_K,
    ) -> dict[str, Any]:
        """
        Run the full analysis of the device and return one structured result.

        Args:
            levels: Eigenvalues to compute. Defaults to the netlist's ``.levels``.
            coherence: Include scqubits' noise-channel estimates.
            matrix_elements: Include charge matrix elements between eigenstates.
            convergence: Re-check the answer against larger cutoffs. Defaults to
                True for Hilbert spaces below :data:`LARGE_HILBERT_DIM`, where the
                second diagonalization is cheap.
            temperature: Bath temperature in kelvin for the coherence estimates.

        Returns:
            A JSON-serializable dict. See the module docstring for units.
        """
        started = time.time()
        circuit_info = self.describe_circuit()

        if circuit_info["hilbert_dim"] >= LARGE_HILBERT_DIM:
            self._warn(
                f"The truncated Hilbert space has {circuit_info['hilbert_dim']:,} states; "
                f"diagonalization may be slow. Lower the cutoffs with .cutoff if so."
            )
        if circuit_info["free_vars"]:
            self._warn(
                f"Variable(s) {circuit_info['free_vars']} are free: their conjugate "
                f"charge is conserved and they carry no dynamics. This usually means "
                f"a node is under-constrained, or the circuit has no ground."
            )

        result: dict[str, Any] = {
            "name": self.name,
            "title": self.netlist.title,
            "netlist": self.netlist.describe(),
            "circuit": circuit_info,
        }
        result.update(self.spectrum(levels))

        if convergence is None:
            convergence = circuit_info["hilbert_dim"] < LARGE_HILBERT_DIM
        if convergence:
            result["convergence"] = self.check_convergence(levels)
            if result["convergence"].get("converged") is False:
                self._warn(
                    f"Transitions moved by "
                    f"{result['convergence']['max_transition_shift_mhz']:.3f} MHz when the "
                    f"basis was enlarged, so the spectrum is not converged. "
                    f"Raise the cutoffs with .cutoff."
                )

        # Both keys are always present so callers and renderers can rely on the
        # result's shape whether or not the section was asked for.
        result["matrix_elements"] = (
            self.charge_matrix_elements(levels)
            if matrix_elements
            else {"operators": {}, "skipped": True}
        )
        result["coherence"] = (
            self.coherence(temperature=temperature)
            if coherence
            else {"available": False, "reason": "Not requested.", "channels": {}}
        )

        result["dissipation"] = self.dissipation(result.get("f01_ghz"))
        result["notes"] = list(self.notes)
        result["warnings"] = list(self.warnings)
        result["elapsed_s"] = time.time() - started
        return result

    def to_dict(self) -> dict[str, Any]:
        """A serializable record of the device: its name and its netlist source."""
        return {
            "name": self.name,
            "title": self.netlist.title,
            "source": self.netlist.source,
            "source_path": self.netlist.source_path,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_index(text: str) -> int | None:
    """Pull a trailing integer out of a knob name: ``"flux2"`` -> 2, ``"2"`` -> 2."""
    digits = ""
    for char in reversed(str(text).strip()):
        if char.isdigit():
            digits = char + digits
        else:
            break
    return int(digits) if digits else None


def _trailing_index(name: str) -> int | None:
    return _as_index(name)


def _parameter_unit(attribute: str, flux_names: Iterable[str], charge_names: Iterable[str]) -> str:
    if attribute in set(flux_names):
        return "Phi_0"
    if attribute in set(charge_names):
        return "2e"
    return "GHz"


def _channel_kind(channel: str) -> str:
    """Classify a scqubits noise channel as relaxation or dephasing, for display."""
    if channel.startswith("t1"):
        return "T1 (relaxation)"
    if channel.startswith("tphi"):
        return "Tphi (dephasing)"
    return "other"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class DeviceEngine:
    """
    Registry and persistence for custom devices designed from netlists.

    Mirrors :class:`~qforge.core.qubit_engine.QubitEngine`'s role for preset qubit
    types: it creates devices, keeps them for the session, and persists them to
    disk so they survive between CLI invocations. What it stores is the netlist
    source, which is the complete and self-describing definition of the device,
    so a reloaded session rebuilds an identical model rather than restoring a
    pickled object.

    Devices live under ``outputs/devices/``, separately from the preset qubits in
    ``outputs/qubits/``; a netlist-defined device is not one of the four scqubits
    qubit types and is deliberately not registered as one.
    """

    def __init__(self, output_dir: str | None = None):
        base = output_dir or os.path.join(OUTPUT_DIRS["base"], "devices")
        self.output_dir = Path(base)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self.output_dir / ".qforge_devices.json"
        self._devices: dict[str, QuantumDevice] = {}
        self.load_session()

    # -- persistence -------------------------------------------------------

    def load_session(self) -> None:
        """Reload devices saved by an earlier session, skipping any that no longer parse."""
        if not self._session_file.exists():
            return
        try:
            with open(self._session_file, encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return

        for name, record in saved.items():
            try:
                netlist = parse_netlist(
                    record["source"], name=name, source_path=record.get("source_path")
                )
                self._devices[name] = QuantumDevice(netlist, name=name)
            except (NetlistError, KeyError, TypeError):
                continue

    def _save_session(self) -> None:
        payload = {name: device.to_dict() for name, device in self._devices.items()}
        try:
            with open(self._session_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except OSError:
            # A read-only output directory must not break an otherwise fine session.
            pass

    # -- creation ----------------------------------------------------------

    def create_device(
        self, source: str, name: str | None = None, overwrite: bool = False
    ) -> QuantumDevice:
        """
        Parse a netlist and register the device it describes.

        Args:
            source: The netlist text.
            name: Device name. A ``.name`` directive in the source wins.
            overwrite: Replace an existing device of the same name.

        Raises:
            NetlistError: If the netlist is not a valid circuit.
            DeviceError: If a device of that name already exists and ``overwrite``
                is False.
        """
        netlist = parse_netlist(source, name=name)
        device_name = netlist.name
        if device_name in self._devices and not overwrite:
            raise DeviceError(
                f"A device named '{device_name}' already exists. Choose another name, "
                f"or delete it first."
            )
        device = QuantumDevice(netlist, name=device_name)
        self._devices[device_name] = device
        self._save_session()
        return device

    def create_device_from_file(
        self, path: str, name: str | None = None, overwrite: bool = False
    ) -> QuantumDevice:
        """Parse a netlist file and register the device. See :meth:`create_device`."""
        netlist = parse_netlist_file(path, name=name)
        device_name = netlist.name
        if device_name in self._devices and not overwrite:
            raise DeviceError(
                f"A device named '{device_name}' already exists. Choose another name, "
                f"or delete it first."
            )
        device = QuantumDevice(netlist, name=device_name)
        self._devices[device_name] = device
        self._save_session()
        return device

    # -- registry ----------------------------------------------------------

    def list_devices(self) -> list[dict[str, Any]]:
        """Summaries of every registered device, without quantizing any of them."""
        out = []
        for name, device in self._devices.items():
            netlist = device.netlist
            out.append(
                {
                    "name": name,
                    "title": netlist.title,
                    "num_nodes": netlist.num_nodes,
                    "num_branches": len(netlist.branches),
                    "num_junctions": len(netlist.junctions),
                    "num_loops": netlist.num_loops,
                    "source_path": netlist.source_path,
                }
            )
        return out

    def get_device(self, name: str) -> QuantumDevice:
        """Look up a registered device by name."""
        if name not in self._devices:
            raise DeviceError(
                f"No device named '{name}'. Registered devices: "
                f"{', '.join(sorted(self._devices)) or 'none'}"
            )
        return self._devices[name]

    def has_device(self, name: str) -> bool:
        return name in self._devices

    def delete_device(self, name: str) -> None:
        """Remove a device from the session and from the saved registry."""
        if name not in self._devices:
            raise DeviceError(f"No device named '{name}'.")
        del self._devices[name]
        self._save_session()

    # -- convenience -------------------------------------------------------

    def analyze(self, name: str, **kwargs) -> dict[str, Any]:
        """Analyze a registered device. See :meth:`QuantumDevice.analyze`."""
        return self.get_device(name).analyze(**kwargs)

    def save_netlist(self, name: str, path: str) -> str:
        """Write a registered device's netlist source to a file."""
        device = self.get_device(name)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(device.netlist.source, encoding="utf-8")
        return str(destination)

    def save_result(self, name: str, result: dict[str, Any], path: str | None = None) -> str:
        """
        Write an analysis result to JSON.

        QuTiP objects and numpy arrays are not part of an analysis result, so it
        serializes directly; anything unexpected is stringified rather than
        raising and losing the run.
        """
        destination = Path(path) if path else self.output_dir / f"{name}_analysis.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, default=str)
        return str(destination)
