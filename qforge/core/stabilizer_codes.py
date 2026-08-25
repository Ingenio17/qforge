"""
stabilizer_codes.py

Declarative stabilizer-code specifications consumed by ErrorCorrectionEngine.

A `StabilizerCode` packages everything the engine needs to encode one logical
qubit into physical data + ancilla qubits, run syndrome extraction, decode a
syndrome into a correction, and read out the logical state -- WITHOUT the
engine knowing anything about the specific code (3-qubit repetition, Steane,
Shor, ...). Adding a new code means writing a new `StabilizerCode` instance
here (generators + syndrome table + logical operators + decoder); no change
to ErrorCorrectionEngine itself is required, as long as the code's
stabilizer generators are CSS-type (see below).

CSS restriction
----------------
Each `StabilizerGenerator` is a Pauli string that is *uniformly* X-type or
Z-type across every data qubit it touches (never a mixed X/Z generator, and
never bare Y). This is the CSS (Calderbank-Shor-Steane) restriction. It is
satisfied by the 3-qubit repetition code (Z-type generators only) and by the
codes intended as the next additions -- the 7-qubit Steane code and the
9-qubit Shor code -- both of which are CSS codes built entirely from pure-X
and pure-Z stabilizer generators. Non-CSS stabilizer codes are out of scope
for the generic syndrome-extraction circuit in ErrorCorrectionEngine.

To add a new CSS code
----------------------
1. Enumerate its stabilizer generators as `StabilizerGenerator(basis, data_qubits, ancilla)`
   entries, one ancilla per generator.
2. Build the syndrome -> correction lookup table (`syndrome_to_correction`),
   mapping each non-trivial syndrome bit-tuple (ordered by ancilla index) to
   the `(data_qubit_local_idx, pauli_type)` correction that fixes it.
3. Specify which local data-qubit indices carry the transversal logical X
   (`logical_x_qubits`) and logical Z (`logical_z_qubits`).
4. Provide a `decode` function turning measured data-qubit bits into a
   decoded logical bit ("0"/"1").
5. Instantiate a `StabilizerCode` with these pieces and pass it to
   `ErrorCorrectionEngine.execute_stabilizer_workflow(..., code=YOUR_CODE)`.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple


@dataclass(frozen=True)
class StabilizerGenerator:
    """
    One stabilizer generator of a CSS-type code.

    basis       : "Z" or "X" -- the Pauli type shared by every data qubit
                  this generator acts on non-trivially.
    data_qubits : LOCAL data-qubit indices (0..code.num_data-1) the
                  generator acts on.
    ancilla     : LOCAL ancilla index (0..code.num_ancilla-1) used to
                  measure this generator. Each generator must use a
                  distinct ancilla.
    """
    basis: str
    data_qubits: Tuple[int, ...]
    ancilla: int

    def __post_init__(self):
        if self.basis not in ("X", "Z"):
            raise ValueError(
                f"StabilizerGenerator.basis must be 'X' or 'Z', got {self.basis!r}"
            )
        if len(self.data_qubits) == 0:
            raise ValueError("StabilizerGenerator.data_qubits must be non-empty")


@dataclass(frozen=True)
class StabilizerCode:
    """
    Full declarative specification of a CSS stabilizer error-correcting
    code for one logical qubit block.

    name         : human-readable code name, used only for logging.
    num_data     : number of physical data qubits per logical block.
    num_ancilla  : number of physical ancilla qubits per logical block
                   (one per stabilizer generator).
    generators   : the code's stabilizer generators.
    syndrome_to_correction:
                   maps a measured syndrome outcome (a tuple of 0/1 of
                   length num_ancilla, ordered by ancilla index) to the
                   correction to apply: (data_qubit_local_idx, pauli_type)
                   where pauli_type is "X" or "Z". A syndrome absent from
                   this dict (typically the all-zero syndrome) means "no
                   correction".
    logical_x_qubits, logical_z_qubits:
                   LOCAL data-qubit indices that the transversal logical
                   X / Z operator acts on. `logical_x_qubits` is read
                   directly by ErrorCorrectionEngine to decide which data
                   qubits a transversal logical X drive touches.
                   `logical_z_qubits` is reserved for a future transversal
                   logical-Z / logical-basis-readout implementation and is
                   not yet consumed by the engine.
    decode       : function mapping a list of `num_data` measured bit
                   values (0/1, one per data qubit, already projected to
                   the computational subspace) to a decoded logical bit
                   character ("0" or "1").
    """
    name: str
    num_data: int
    num_ancilla: int
    generators: Tuple[StabilizerGenerator, ...]
    syndrome_to_correction: Dict[Tuple[int, ...], Tuple[int, str]]
    logical_x_qubits: Tuple[int, ...]
    logical_z_qubits: Tuple[int, ...]
    decode: Callable[[List[int]], str]

    def __post_init__(self):
        if len(self.generators) != self.num_ancilla:
            raise ValueError(
                f"StabilizerCode '{self.name}': {len(self.generators)} generators "
                f"but num_ancilla={self.num_ancilla} (must match 1:1)."
            )
        seen_ancillas = set()
        for gen in self.generators:
            if gen.ancilla in seen_ancillas:
                raise ValueError(
                    f"StabilizerCode '{self.name}': ancilla {gen.ancilla} is used "
                    f"by more than one generator."
                )
            seen_ancillas.add(gen.ancilla)
            if not (0 <= gen.ancilla < self.num_ancilla):
                raise ValueError(
                    f"StabilizerCode '{self.name}': generator ancilla index "
                    f"{gen.ancilla} out of range [0, {self.num_ancilla})."
                )
            for dq in gen.data_qubits:
                if not (0 <= dq < self.num_data):
                    raise ValueError(
                        f"StabilizerCode '{self.name}': generator data-qubit "
                        f"index {dq} out of range [0, {self.num_data})."
                    )


def _majority_vote_decode(bits: List[int]) -> str:
    """Return '1' if a strict majority of `bits` are 1, else '0'."""
    ones = sum(bits)
    return "1" if ones > len(bits) / 2 else "0"


# ---------------------------------------------------------------------------
# 3-qubit bit-flip repetition code
# ---------------------------------------------------------------------------
#
# Data qubits: D0, D1, D2.  Ancillas: A0 (measures Z0 Z1), A1 (measures Z1 Z2).
#
#     (A0=0, A1=0) -> no error
#     (A0=1, A1=0) -> X on D0
#     (A0=1, A1=1) -> X on D1
#     (A0=0, A1=1) -> X on D2
#
# This reproduces, unchanged, the syndrome table and transversal-gate
# behaviour that error_correction_engine.py implemented directly before the
# stabilizer-formalism refactor.

REPETITION_3 = StabilizerCode(
    name="3-qubit repetition code",
    num_data=3,
    num_ancilla=2,
    generators=(
        StabilizerGenerator(basis="Z", data_qubits=(0, 1), ancilla=0),
        StabilizerGenerator(basis="Z", data_qubits=(1, 2), ancilla=1),
    ),
    syndrome_to_correction={
        (1, 0): (0, "X"),
        (1, 1): (1, "X"),
        (0, 1): (2, "X"),
    },
    logical_x_qubits=(0, 1, 2),
    logical_z_qubits=(0, 1, 2),
    decode=_majority_vote_decode,
)


# ---------------------------------------------------------------------------
# Future codes
# ---------------------------------------------------------------------------
# Additional CSS stabilizer codes -- e.g. the 7-qubit Steane code (6
# generators: 3 X-type + 3 Z-type from the classical Hamming(7,4) code) or
# the 9-qubit Shor code (8 generators: 6 Z-type for the inner bit-flip codes
# + 2 X-type for the outer phase-flip code) -- can be added here as further
# `StabilizerCode` instances. Each one only needs its generators, syndrome
# table, logical-operator support, and decoder; ErrorCorrectionEngine
# requires no changes to run them.
