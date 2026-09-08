"""
Present a netlist-designed device as an ordinary qforge qubit.

:class:`DeviceQubit` is an adapter. It wraps a
:class:`~qforge.core.device_engine.QuantumDevice` and exposes the same small
interface that qforge's engines already expect from an scqubits qubit object, so
a circuit somebody drew themselves can be registered with
:class:`~qforge.core.qubit_engine.QubitEngine` and then driven, coupled,
calibrated and error-corrected exactly like a preset transmon or fluxonium.

The interface the engines actually use is narrow, and this class implements all
of it:

===========================  =========================================
``truncated_dim``            how many levels the engines keep
``eigenvals(evals_count=)``  energies in GHz
``eigensys(evals_count=)``   energies and eigenvectors
``n_operator()``             charge operator, in the circuit's own basis
``phi_operator()``           phase operator, for extended modes only
``matrixelement_table(...)`` an operator projected into the eigenbasis
``t1_capacitive(...)``       coherence estimate, when scqubits can give one
===========================  =========================================

Two details make this an adapter rather than a subclass.

A preset qubit has one mode and one obvious charge operator. A designed circuit
may have several, so this picks the mode carrying the 0-1 transition, scoring each
by ``|<0|Q|1>| / sqrt(<0|Q^2|0>)``. That is the mode a drive couples to, and
therefore the one a gate acts on. It is recorded on :attr:`qubit_mode` so the
choice is inspectable rather than hidden.

``phi_operator`` is deliberately absent for periodic (charge) modes. A compact
phase has no well-defined operator, which is exactly why ``scqubits.Transmon``
does not offer one either, and ``GateEngine._get_qubit_hamiltonian`` tests for it
with ``hasattr`` before using it. Reporting one anyway would hand the gate engine
an operator with no physical meaning.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from qforge.core.device_engine import DeviceError, QuantumDevice
from qforge.core.device_netlist import parse_netlist

__all__ = ["DeviceQubit", "build_device_qubit", "device_qubit_params", "clear_cache"]

# Levels kept by default, matching the truncated_dim of the preset qubit types
# in qforge.config.defaults so a device drops into the same workflows.
DEFAULT_TRUNCATED_DIM = 4

# Rebuilding a device means re-running scqubits' symbolic quantization, which
# takes a couple of seconds. QubitEngine reconstructs every registered qubit each
# time it loads its session, and GateEngine reloads the session on every
# Hamiltonian request, so without a cache a single gate simulation would pay that
# cost repeatedly. A netlist plus a truncation fully determines the qubit, so
# handing back the same instance is safe.
_CACHE: dict[tuple[str, int], DeviceQubit] = {}


def clear_cache() -> None:
    """Forget every cached device qubit. Mainly useful in tests."""
    _CACHE.clear()


class DeviceQubit:
    """
    A designed device, wearing the interface of an scqubits qubit.

    Build one through :func:`build_device_qubit`, which caches, rather than
    constructing directly.

    Construction is cheap on purpose: it parses the netlist but does not
    quantize. The scqubits circuit is built on first real use, so loading a
    session full of devices costs nothing until one of them is simulated.
    """

    def __init__(
        self,
        source: str,
        name: str = "device",
        truncated_dim: int = DEFAULT_TRUNCATED_DIM,
        source_path: str | None = None,
    ):
        self.netlist = parse_netlist(source, name=name, source_path=source_path)
        self.device = QuantumDevice(self.netlist, name=name)
        self.name = name
        self.truncated_dim = int(truncated_dim)
        self._qubit_mode: tuple[str, int] | None = None

    # -- identity ---------------------------------------------------------

    def __repr__(self) -> str:
        return f"DeviceQubit(name={self.name!r}, truncated_dim={self.truncated_dim})"

    @property
    def source(self) -> str:
        """The netlist this qubit was built from."""
        return self.netlist.source

    # -- spectrum ---------------------------------------------------------

    def eigenvals(self, evals_count: int = 6, **_kwargs) -> np.ndarray:
        """Lowest ``evals_count`` energies, in GHz. Absolute, not ground-referred."""
        return self.device.eigenvalues(evals_count)

    def eigensys(self, evals_count: int = 6, **_kwargs):
        """Energies (GHz) and eigenvectors, as scqubits returns them."""
        return self.device.eigensystem(evals_count)

    def hilbertdim(self) -> int:
        return self.device.hilbert_dim

    # -- mode selection ---------------------------------------------------

    @property
    def qubit_mode(self) -> tuple[str, int]:
        """
        The circuit mode this qubit lives on, as ``(kind, index)``.

        ``kind`` is ``"periodic"`` for a charge variable or ``"extended"`` for a
        flux variable. Chosen once, by whichever mode's charge operator connects
        the ground and first excited states most strongly relative to its own
        zero-point spread. See :meth:`_select_qubit_mode` for why the
        normalisation matters.
        """
        if self._qubit_mode is None:
            self._qubit_mode = self._select_qubit_mode()
        return self._qubit_mode

    def _mode_operators(self) -> list[tuple[str, int, str]]:
        """Every mode's charge operator, as ``(kind, index, attribute name)``."""
        categories = self.device.circuit.var_categories
        operators = [
            ("periodic", index, f"n{index}_operator") for index in categories.get("periodic", [])
        ]
        operators += [
            ("extended", index, f"Q{index}_operator") for index in categories.get("extended", [])
        ]
        return operators

    def _select_qubit_mode(self) -> tuple[str, int]:
        """
        Pick the mode that carries the 0-1 transition.

        A drive reaches a mode through its charge operator, so the qubit lives on
        whichever mode's charge operator connects the ground and first excited
        states most strongly. The comparison has to be made in a scale-free way,
        though: a periodic variable's ``n`` counts Cooper pairs while an extended
        variable's ``Q`` is in scqubits' oscillator units, and the raw matrix
        elements are simply not on the same footing.

        Each operator is therefore normalised by its own zero-point spread in the
        ground state, ``|<0|Q|1>| / sqrt(<0|Q^2|0>)``. That asks what fraction of
        the fluctuation a mode already has goes into the 0-1 transition, which is
        near 1 for the mode that is the qubit and well below it for a spectator.
        In the transmon-plus-resonator template the raw elements favour the
        resonator (1.32 against the transmon's 1.21) purely because its operator
        is scaled differently; normalised, the transmon wins 0.999 to 0.487, as
        it should, since level 1 of that circuit is the transmon excitation.
        """
        operators = self._mode_operators()
        if not operators:
            raise DeviceError(
                f"'{self.name}' has no dynamical charge variable, so it cannot be "
                f"driven as a qubit."
            )
        if len(operators) == 1:
            kind, index, _ = operators[0]
            return kind, index

        circuit = self.device.circuit
        levels = max(2, min(self.truncated_dim, self.device.hilbert_dim))
        _evals, evecs = self.device.eigensystem(levels)
        ground = evecs[:, 0]

        best = None
        for kind, index, attribute in operators:
            method = getattr(circuit, attribute, None)
            if method is None:
                continue
            try:
                matrix = method()
                # Both products work for sparse and dense operators alike, and a
                # matrix-vector product keeps this cheap for large circuits.
                coupling = abs((evecs.conj().T @ (matrix @ evecs))[0, 1])
                spread = float(np.linalg.norm(matrix @ ground))
            except Exception:
                continue
            if spread <= 0:
                continue
            score = coupling / spread
            if best is None or score > best[0]:
                best = (score, kind, index)

        if best is None:
            kind, index, _ = operators[0]
            return kind, index
        return best[1], best[2]

    def _charge_operator_name(self) -> str:
        kind, index = self.qubit_mode
        return f"n{index}_operator" if kind == "periodic" else f"Q{index}_operator"

    # -- operators --------------------------------------------------------

    def n_operator(self):
        """
        Charge operator of the qubit mode, in the circuit's own basis.

        Returned unprojected, exactly as scqubits' qubit classes do, because
        :meth:`matrixelement_table` is what projects it into the eigenbasis.
        """
        matrix = getattr(self.device.circuit, self._charge_operator_name())()
        return matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)

    def _phase_operator(self):
        """Phase operator of the qubit mode. Extended modes only."""
        _kind, index = self.qubit_mode
        matrix = getattr(self.device.circuit, f"θ{index}_operator")()
        return matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)

    def __getattr__(self, attribute: str):
        """
        Expose ``phi_operator`` only when the qubit mode has a phase operator.

        ``GateEngine._get_qubit_hamiltonian`` decides whether to use a phase
        operator with ``hasattr``, so a periodic mode has to genuinely not have
        one; a compact phase is not an observable, and scqubits' own Transmon
        offers no ``phi_operator`` either. Defining it here rather than as a
        normal method is what keeps that ``hasattr`` honest.

        ``__getattr__`` runs only when normal lookup fails, so this costs nothing
        for every other attribute.
        """
        if attribute == "phi_operator":
            # Guard against recursion while __init__ has not finished yet.
            if "device" not in self.__dict__:
                raise AttributeError(attribute)
            if self.qubit_mode[0] != "extended":
                raise AttributeError(
                    f"{type(self).__name__!r} has no phi_operator: the qubit mode is "
                    f"a periodic charge variable, whose phase is compact."
                )
            return self._phase_operator
        raise AttributeError(attribute)

    def matrixelement_table(
        self, operator: str, evecs=None, evals_count: int = 6, **_kwargs
    ) -> np.ndarray:
        """
        Matrix elements ``<i|O|j>`` of a named operator, in the energy eigenbasis.

        Mirrors ``scqubits.QubitBaseClass.matrixelement_table``: the operator is
        named by attribute, looked up on this object, and projected onto the
        lowest ``evals_count`` eigenstates.
        """
        method = getattr(self, operator, None)
        if method is None:
            raise AttributeError(f"'{self.name}' has no operator '{operator}'")
        if evecs is None:
            _evals, evecs = self.eigensys(evals_count=evals_count)
        dense = np.asarray(method())
        return evecs.conj().T @ (dense @ evecs)

    # -- noise ------------------------------------------------------------

    def t1_capacitive(self, **kwargs) -> float:
        """
        Dielectric-loss T1, in nanoseconds, when scqubits can compute one.

        Units follow scqubits: times come back as 1/frequency, and with energies
        in GHz that is ns. ``QubitEngine.estimate_coherence`` divides by 1000 to
        reach microseconds, so this must not do that conversion itself.
        """
        circuit = self.device.circuit
        if not getattr(circuit, "generate_noise_methods", False):
            raise DeviceError(f"'{self.name}' was built without noise methods.")
        return float(circuit.t1_capacitive(**kwargs))

    def t1_effective(self, **kwargs) -> float:
        """Effective T1 in nanoseconds, over every channel scqubits supports."""
        return float(self.device.circuit.t1_effective(**kwargs))

    def t2_effective(self, **kwargs) -> float:
        """Effective T2 in nanoseconds, over every channel scqubits supports."""
        return float(self.device.circuit.t2_effective(**kwargs))

    # -- plotting ---------------------------------------------------------

    def plot_wavefunction(self, which=0, mode: str = "real", **kwargs):
        """
        Plot a wavefunction, accepting the argument shapes qforge already passes.

        ``QubitEngine.visualize`` asks for several states at once, which this
        scqubits version's circuit plotter does not accept, so a list is reduced
        to its first entry rather than raising.
        """
        if isinstance(which, (list, tuple)):
            which = which[0] if which else 0
        return self.device.circuit.plot_wavefunction(which=which, **kwargs)

    def plot_potential(self, **kwargs):
        return self.device.circuit.plot_potential(**kwargs)

    # -- serialization ----------------------------------------------------

    def to_params(self) -> dict[str, Any]:
        """The parameter dict QubitEngine persists in its session file."""
        return device_qubit_params(
            self.netlist.source,
            truncated_dim=self.truncated_dim,
            device_name=self.name,
            source_path=self.netlist.source_path,
        )


def device_qubit_params(
    source: str,
    truncated_dim: int = DEFAULT_TRUNCATED_DIM,
    device_name: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    """
    Build the ``params`` dict for a device-backed qubit.

    The netlist source is carried in full rather than a path, so a registered
    qubit keeps working after the file it came from is edited or deleted, and a
    session file is a complete, self-contained record of the circuit.
    """
    return {
        "source": source,
        "truncated_dim": int(truncated_dim),
        "device_name": device_name,
        "source_path": source_path,
    }


def build_device_qubit(params: dict[str, Any]) -> DeviceQubit:
    """
    Rebuild a device-backed qubit from its persisted parameters.

    This is the entry point ``QubitEngine._create_qubit_object`` uses for the
    ``"device"`` qubit type. Results are cached by netlist and truncation, since
    a session reload reconstructs every qubit and quantization is not cheap.
    """
    source = params.get("source")
    if not source:
        raise DeviceError(
            "A device qubit needs its netlist in params['source']. "
            "Register it through the device designer rather than by hand."
        )
    truncated_dim = int(params.get("truncated_dim", DEFAULT_TRUNCATED_DIM))
    name = params.get("device_name") or "device"

    key = (source, truncated_dim)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    qubit = DeviceQubit(
        source,
        name=name,
        truncated_dim=truncated_dim,
        source_path=params.get("source_path"),
    )
    _CACHE[key] = qubit
    return qubit
