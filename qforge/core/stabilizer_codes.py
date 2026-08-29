"""
stabilizer_codes.py

Declarative stabilizer-code specifications consumed by ErrorCorrectionEngine.

A `StabilizerCode` packages everything the engine needs to encode one logical
qubit into physical data + ancilla qubits, run syndrome extraction, decode a
syndrome into a correction, and read out the logical state -- WITHOUT the
engine knowing anything about the specific code (3-qubit repetition, Shor,
...). Adding a new code means writing a new `StabilizerCode` instance here
(generators + syndrome table + logical operators); no change to
ErrorCorrectionEngine itself is required, as long as the code's stabilizer
generators are CSS-type (see below).

CSS restriction
----------------
Each `StabilizerGenerator` is a Pauli string that is *uniformly* X-type or
Z-type across every data qubit it touches (never a mixed X/Z generator, and
never bare Y). This is the CSS (Calderbank-Shor-Steane) restriction. It is
satisfied by the 3-qubit repetition code (Z-type generators only) and by the
9-qubit Shor code (`SHOR_9`, six Z-type + two X-type generators). Non-CSS
stabilizer codes are out of scope for the generic syndrome-extraction
circuit in ErrorCorrectionEngine.

Logical operators are similarly declared as a Pauli type + a set of local
data-qubit indices (`logical_x_qubits`/`logical_x_pauli` and
`logical_z_qubits`/`logical_z_pauli`). For the repetition code these are the
"obvious" choices (transversal X, transversal Z-product) built from the same
Pauli type as the logical operator's name would suggest. For the Shor code
they are NOT: because Shor's code is built by concatenating an inner
bit-flip code with an outer phase-flip code, the physical operator that
implements logical X-bar turns out to be a *Z*-type string (one Z per
block), and the physical operator that implements logical Z-bar is an
*X*-type string (transversal X on a single block). This is a well-known,
textbook property of the Shor code, not a bug -- see the comments next to
`SHOR_9` below for the derivation.

To add a new CSS code
----------------------
1. Enumerate its stabilizer generators as `StabilizerGenerator(basis, data_qubits, ancilla)`
   entries, one ancilla per generator.
2. Build the syndrome -> correction lookup table (`syndrome_to_correction`),
   mapping each non-trivial syndrome bit-tuple (ordered by ancilla index) to
   a LIST of `(data_qubit_local_idx, pauli_type)` corrections that fixes it.
   A list (not a single correction) is required in general because
   independent error types (e.g. a bit-flip AND a phase-flip) can be
   diagnosed by different generators and need to be corrected
   simultaneously -- this happens for the Shor code but never for the
   repetition code, whose corrections are always singleton lists.
3. Specify which local data-qubit indices + Pauli type realize the
   transversal logical X (`logical_x_qubits`/`logical_x_pauli`) and logical
   Z (`logical_z_qubits`/`logical_z_pauli`).
4. Write the `encoding_circuit`: the sequence of `EncodingStep`s that turns
   the data block's initial |00...0> into the actual codeword |0>_L. This
   is NOT optional for any code whose |0>_L is not itself a computational
   basis state (true of essentially every code other than the repetition
   code) -- skipping it means every workflow starts from an arbitrary,
   generally non-codeword state instead of |0>_L.
5. Instantiate a `StabilizerCode` with these pieces and pass it to
   `ErrorCorrectionEngine.execute_stabilizer_workflow(..., code=YOUR_CODE)`.

No per-code `decode` callback is needed: ErrorCorrectionEngine decodes any
`StabilizerCode` by projectively measuring the declared logical-Z operator
(a joint measurement across all logical qubits, so entanglement between
logical qubits is preserved in the returned population dict) -- this is
required for physical correctness in general. The repetition code's
codewords happen to coincide with computational-basis states, so this is
mathematically identical (see error_correction_engine.py) to majority-voting
raw data-qubit populations, but that coincidence does not hold for the Shor
code: |0>_L and |1>_L touch the exact same set of computational-basis
strings with the exact same probabilities and differ only in relative
phase, which a bit-population/majority-vote reading of the diagonal cannot
see. Only a genuine logical-Z projective measurement decodes it correctly.
"""

import itertools
from dataclasses import dataclass
from typing import Dict, List, Tuple


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
class EncodingStep:
    """
    One gate of a code's |0>_L encoding circuit, applied to LOCAL data-qubit
    indices, starting from the data block in |00...0>.

    gate    : "H" (Hadamard on `target`) or "ICX" (ideal CNOT, `control` ->
              `target`).
    control : local data-qubit index (ICX only; ignored for H).
    target  : local data-qubit index the gate acts on.
    """
    gate: str
    target: int
    control: int = -1

    def __post_init__(self):
        if self.gate not in ("H", "ICX"):
            raise ValueError(f"EncodingStep.gate must be 'H' or 'ICX', got {self.gate!r}")
        if self.gate == "ICX" and self.control < 0:
            raise ValueError("EncodingStep(gate='ICX') requires a non-negative control index")


@dataclass(frozen=True)
class StabilizerCode:
    """
    Full declarative specification of a CSS stabilizer error-correcting
    code for one logical qubit block.

    name         : human-readable code name, used only for logging.
    num_data     : number of physical data qubits per logical block.
    num_ancilla  : number of physical ancilla qubits per logical block
                   (one per stabilizer generator).
    generators   : the code's stabilizer generators. All generators must
                   mutually commute (a requirement of being a valid
                   stabilizer group) -- ErrorCorrectionEngine relies on this
                   to extract and measure them one at a time rather than as
                   one large joint operation.
    syndrome_to_correction:
                   maps a measured syndrome outcome (a tuple of 0/1 of
                   length num_ancilla, ordered by ancilla index) to the
                   LIST of corrections to apply: each entry is
                   (data_qubit_local_idx, pauli_type) with pauli_type "X" or
                   "Z". A syndrome absent from this dict (typically the
                   all-zero syndrome) means "no correction". Most codes only
                   ever need a single-element list; a list is supported
                   because independent generators can require independent,
                   simultaneous corrections (see the Shor code).
    logical_x_qubits, logical_x_pauli:
                   the physical operator that implements the transversal
                   logical X: apply Pauli `logical_x_pauli` to every local
                   data-qubit index in `logical_x_qubits`.
    logical_z_qubits, logical_z_pauli:
                   the physical operator whose +1/-1 eigenvalue is the
                   logical Z-basis outcome: apply Pauli `logical_z_pauli` to
                   every local data-qubit index in `logical_z_qubits`, and
                   read the code out via P(logical=0) = (1+<Z_bar>)/2. Used
                   directly by ErrorCorrectionEngine's decode step.
    encoding_circuit:
                   the sequence of `EncodingStep`s that prepares |0>_L,
                   starting from the data block in the computational basis
                   state |00...0>. Required because a code's logical |0>_L
                   is not, in general, itself a computational basis state:
                   simply initializing the physical register to |00...0>
                   does NOT prepare a valid codeword for such codes at all.
                   The repetition code's |0>_L happens to equal |000>, so
                   its (still explicitly declared, for uniformity) encoding
                   circuit is provably a no-op there.
    """
    name: str
    num_data: int
    num_ancilla: int
    generators: Tuple[StabilizerGenerator, ...]
    syndrome_to_correction: Dict[Tuple[int, ...], List[Tuple[int, str]]]
    logical_x_qubits: Tuple[int, ...]
    logical_x_pauli: str
    logical_z_qubits: Tuple[int, ...]
    logical_z_pauli: str
    encoding_circuit: Tuple[EncodingStep, ...]

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
        for pauli in (self.logical_x_pauli, self.logical_z_pauli):
            if pauli not in ("X", "Z"):
                raise ValueError(
                    f"StabilizerCode '{self.name}': logical Pauli must be "
                    f"'X' or 'Z', got {pauli!r}."
                )


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
        (1, 0): [(0, "X")],
        (1, 1): [(1, "X")],
        (0, 1): [(2, "X")],
    },
    logical_x_qubits=(0, 1, 2),
    logical_x_pauli="X",
    logical_z_qubits=(0, 1, 2),
    logical_z_pauli="Z",
    # |0>_L = |000> is already the |00...0> initial state, so this GHZ-style
    # encoding circuit (CNOT(0->1), CNOT(0->2)) is a mathematical no-op when
    # the control qubit starts in |0>: it is declared here purely for
    # uniformity with codes where the encoding step is NOT a no-op.
    encoding_circuit=(
        EncodingStep(gate="ICX", control=0, target=1),
        EncodingStep(gate="ICX", control=0, target=2),
    ),
)


# ---------------------------------------------------------------------------
# 9-qubit Shor code
# ---------------------------------------------------------------------------
#
# The Shor code concatenates the 3-qubit phase-flip code (outer layer) with
# the 3-qubit bit-flip code (inner layer): each of the outer code's 3
# "logical" qubits is itself encoded into 3 physical qubits via the
# bit-flip code, giving 9 physical data qubits total, grouped into 3 blocks
# of 3:
#
#     block 0 = D0, D1, D2      block 1 = D3, D4, D5      block 2 = D6, D7, D8
#
#     |0>_L = (|000>+|111>)_0 (|000>+|111>)_1 (|000>+|111>)_2 / (2*sqrt(2))
#     |1>_L = (|000>-|111>)_0 (|000>-|111>)_1 (|000>-|111>)_2 / (2*sqrt(2))
#
# Stabilizer generators (8 total = 9 data qubits - 1 logical qubit):
#   * 6 Z-type "inner" generators, 2 per block, exactly the repetition
#     code's Z0Z1/Z1Z2 pattern applied independently within each block --
#     these detect and localize bit-flip (X) errors within a block.
#   * 2 X-type "outer" generators, X0X1X2X3X4X5 and X3X4X5X6X7X8, comparing
#     adjacent blocks -- these detect phase-flip (Z) errors at block
#     granularity. (All 8 generators pairwise commute: two Z-type
#     generators always commute, two X-type generators always commute, and
#     each X-type generator overlaps each Z-type generator on an even
#     number of qubits -- 0 or 2 -- so they commute too.)
#
# Error model and correction
# ---------------------------
# A bit-flip (X) error on any one data qubit is detected and corrected
# EXACTLY like the repetition code, independently within whichever block it
# occurred in, using that block's own pair of inner-generator ancillas.
#
# A phase-flip (Z) error on ANY ONE data qubit within a block has an
# IDENTICAL effect on the encoded state to a Z error on any other qubit in
# that same block: Z_i (|000>+|111>) = |000>-|111> regardless of which
# local index i is hit, since Z_i only ever contributes a sign flip to the
# |111> term. So phase errors can only be localized to a BLOCK (not to an
# individual qubit within it) by the outer X-type generators, and are
# corrected by applying Z to any single representative qubit of the
# affected block (canonically its first qubit).
#
# Because the inner (bit-flip) and outer (phase-flip) errors are diagnosed
# by disjoint sets of generators and can occur simultaneously and
# independently, a single syndrome can require BOTH an X correction (from
# an inner block) AND a Z correction (from the outer pair) at once -- hence
# corrections are lists, not single tuples.
#
# Logical operators (see the module docstring for why X and Z are swapped
# relative to the naive physical-X-for-logical-X expectation):
#   Z_bar = X0 X1 X2   (transversal X on any single whole block; direct
#                        calculation: X0X1X2 fixes (|000>+|111>) and negates
#                        (|000>-|111>), i.e. +1 eigenvalue on |0>_L, -1 on
#                        |1>_L -- exactly the logical-Z convention.)
#   X_bar = Z0 Z3 Z6   (one Z per block; direct calculation: Z0 alone maps
#                        (|000>+|111>)_0 -> (|000>-|111>)_0, so applying one
#                        Z per block maps |0>_L -> |1>_L and vice versa --
#                        exactly the logical-X convention.)
#
# Encoding circuit (standard textbook construction, concatenating the
# 3-qubit phase-flip code's own encoding with the 3-qubit bit-flip code's):
#   1. CNOT(0->3), CNOT(0->6)         -- GHZ the 3 "block leaders" 0,3,6
#   2. H(0), H(3), H(6)               -- phase-flip-encode: a|000>+b|111>
#                                         on the leaders becomes a|+++>+b|--->
#   3. CNOT(i->i+1), CNOT(i->i+2)     -- for each leader i in {0,3,6},
#      for i in {0,3,6}                 bit-flip-encode it into its own block
# Direct calculation confirms this maps |0> (a=1,b=0) on qubit 0, with every
# other data qubit starting in |0>, to exactly |0>_L as defined above.

def _build_shor9_syndrome_table() -> Dict[Tuple[int, ...], List[Tuple[int, str]]]:
    """
    Build the full syndrome -> correction table for the 9-qubit Shor code.

    Ancilla layout (8 ancillas, in the same order as SHOR_9.generators):
        0,1 : block 0 inner Z-stabilizers (Z0Z1, Z1Z2) -> X correction in block 0
        2,3 : block 1 inner Z-stabilizers (Z3Z4, Z4Z5) -> X correction in block 1
        4,5 : block 2 inner Z-stabilizers (Z6Z7, Z7Z8) -> X correction in block 2
        6,7 : outer X-stabilizers (X0..X5, X3..X8)     -> Z correction on a
                                                           block representative

    Each inner ancilla pair reproduces the repetition code's own syndrome
    table applied to its 3-qubit block; the outer pair reproduces the same
    table at block granularity, correcting with Z on that block's qubit 0.
    The three inner corrections and the one outer correction are all
    independent and are combined (by list concatenation) whenever more than
    one is triggered by the same syndrome.
    """
    # 2-bit block syndrome -> local offset within that block (repetition-code table)
    inner_offset = {(1, 0): 0, (1, 1): 1, (0, 1): 2}
    # 2-bit outer syndrome -> which block's representative qubit needs Z
    outer_block = {(1, 0): 0, (1, 1): 1, (0, 1): 2}

    two_bit_outcomes = [(0, 0), (1, 0), (1, 1), (0, 1)]

    table: Dict[Tuple[int, ...], List[Tuple[int, str]]] = {}
    for s0 in two_bit_outcomes:
        for s1 in two_bit_outcomes:
            for s2 in two_bit_outcomes:
                for so in two_bit_outcomes:
                    syndrome = s0 + s1 + s2 + so
                    corrections: List[Tuple[int, str]] = []
                    for block_idx, block_syndrome in enumerate((s0, s1, s2)):
                        if block_syndrome in inner_offset:
                            local_dq = 3 * block_idx + inner_offset[block_syndrome]
                            corrections.append((local_dq, "X"))
                    if so in outer_block:
                        block_idx = outer_block[so]
                        corrections.append((3 * block_idx, "Z"))
                    if corrections:
                        table[syndrome] = corrections
    return table


SHOR_9 = StabilizerCode(
    name="9-qubit Shor code",
    num_data=9,
    num_ancilla=8,
    generators=(
        # Block 0 inner (bit-flip) generators
        StabilizerGenerator(basis="Z", data_qubits=(0, 1), ancilla=0),
        StabilizerGenerator(basis="Z", data_qubits=(1, 2), ancilla=1),
        # Block 1 inner (bit-flip) generators
        StabilizerGenerator(basis="Z", data_qubits=(3, 4), ancilla=2),
        StabilizerGenerator(basis="Z", data_qubits=(4, 5), ancilla=3),
        # Block 2 inner (bit-flip) generators
        StabilizerGenerator(basis="Z", data_qubits=(6, 7), ancilla=4),
        StabilizerGenerator(basis="Z", data_qubits=(7, 8), ancilla=5),
        # Outer (phase-flip) generators, comparing adjacent blocks
        StabilizerGenerator(basis="X", data_qubits=(0, 1, 2, 3, 4, 5), ancilla=6),
        StabilizerGenerator(basis="X", data_qubits=(3, 4, 5, 6, 7, 8), ancilla=7),
    ),
    syndrome_to_correction=_build_shor9_syndrome_table(),
    logical_x_qubits=(0, 3, 6),
    logical_x_pauli="Z",
    logical_z_qubits=(0, 1, 2),
    logical_z_pauli="X",
    encoding_circuit=(
        EncodingStep(gate="ICX", control=0, target=3),
        EncodingStep(gate="ICX", control=0, target=6),
        EncodingStep(gate="H", target=0),
        EncodingStep(gate="H", target=3),
        EncodingStep(gate="H", target=6),
        EncodingStep(gate="ICX", control=0, target=1),
        EncodingStep(gate="ICX", control=0, target=2),
        EncodingStep(gate="ICX", control=3, target=4),
        EncodingStep(gate="ICX", control=3, target=5),
        EncodingStep(gate="ICX", control=6, target=7),
        EncodingStep(gate="ICX", control=6, target=8),
    ),
)


# ---------------------------------------------------------------------------
# 7-qubit Steane code
# ---------------------------------------------------------------------------
#
# The Steane code is the CSS(C1, C2) construction built from the classical
# [7,4,3] Hamming code C1 and its dual C2 = C1^perp, the [7,3,4] simplex
# code (C2 subset C1, so the construction is valid). Both the X-type and
# Z-type stabilizer generators come from the SAME 3x7 parity-check matrix H
# of C1 (equivalently, a generator matrix of C2):
#
#     H = [ 1 0 1 0 1 0 1 ]   (row A: qubits {0,2,4,6})
#         [ 0 1 1 0 0 1 1 ]   (row B: qubits {1,2,5,6})
#         [ 0 0 0 1 1 1 1 ]   (row C: qubits {3,4,5,6})
#
# i.e. column j (0-indexed qubit j) of H is the 3-bit binary representation
# of (j+1). Each row gives one Z-type generator and one X-type generator
# (same qubit support, different Pauli), for 6 generators total (7 data
# qubits - 1 logical qubit = 6).
#
# All 6 generators mutually commute: two Z-type (or two X-type) generators
# trivially commute, and every X/Z pair from different rows overlaps on
# exactly 2 qubits (even), e.g. row-A-X = {0,2,4,6} and row-B-Z = {1,2,5,6}
# overlap on {2,6}; same-row X/Z pairs overlap on all 4 qubits (also even).
#
# Syndrome decoding (the classic "Hamming code" property): reading the 3
# Z-type-generator syndrome bits as a binary number (row A = bit 0, row B =
# bit 1, row C = bit 2) gives the 1-indexed physical qubit that suffered a
# bit-flip (X) error directly -- no lookup table search needed, because H's
# columns are literally the binary representations of the qubit indices.
# The same holds for the 3 X-type-generator bits and phase-flip (Z) errors.
# Both can be corrected simultaneously if triggered together, exactly like
# the Shor code's inner/outer corrections (hence corrections are lists
# here too, even though at most one X and one Z correction can ever appear
# together for this code).
#
# Logical operators: UNLIKE the Shor code, Steane uses the "obvious" CSS
# convention directly: logical X-bar = X on all 7 qubits (transversal X),
# logical Z-bar = Z on all 7 qubits (transversal Z) -- both built from the
# same Pauli type their names suggest. Steane is also famously self-dual
# enough to have a valid TRANSVERSAL HADAMARD (H on all 7 qubits swaps
# X-bar <-> Z-bar exactly, since they share the same 7-qubit support), and
# transversal CNOT/CZ between two Steane-encoded logical qubits implement
# logical CNOT/CZ directly with no direction reversal or basis mismatch --
# none of the Shor-code-specific workarounds in error_correction_engine.py
# are needed here, so the Steane execution path there reuses the fully
# generic transversal-gate machinery unmodified.
#
# All of the above (generator commutativity, the syndrome/binary-index
# correspondence for all 7 possible single-qubit errors, the logical
# operators, transversal CX and CZ acting as their logical counterparts
# with no reversal, and the encoding circuit below) were independently
# verified by direct state-vector simulation before this code was written.
#
# Encoding circuit: C2's generator matrix (= H above) is already in
# reduced row-echelon form with pivot columns {0, 1, 3} -- i.e. those are
# the "message" qubits. The standard CSS encoding recipe is: Hadamard the
# message qubits, then for each row, CNOT from its pivot (message) qubit to
# every OTHER qubit where that row has a 1. Direct simulation confirms this
# exactly reproduces |0>_L as constructed from the stabilizer group's
# common +1 eigenspace.

def _build_steane7_syndrome_table() -> Dict[Tuple[int, ...], List[Tuple[int, str]]]:
    """
    Build the full syndrome -> correction table for the 7-qubit Steane
    code using the binary-index Hamming-code property described above.

    Ancilla layout (6 ancillas, in the same order as STEANE_7.generators):
        0,1,2 : Z-type generators (rows A,B,C) -> X correction, qubit
                index = binary(s0,s1,s2) - 1 (bit 0 = ancilla 0's outcome)
        3,4,5 : X-type generators (rows A,B,C) -> Z correction, qubit
                index = binary(s3,s4,s5) - 1
    """
    table: Dict[Tuple[int, ...], List[Tuple[int, str]]] = {}
    for bits in itertools.product([0, 1], repeat=6):
        sZA, sZB, sZC, sXA, sXB, sXC = bits
        z_index = sZA + 2 * sZB + 4 * sZC   # 1-indexed qubit with an X error, 0 = none
        x_index = sXA + 2 * sXB + 4 * sXC   # 1-indexed qubit with a Z error, 0 = none
        corrections: List[Tuple[int, str]] = []
        if z_index != 0:
            corrections.append((z_index - 1, "X"))
        if x_index != 0:
            corrections.append((x_index - 1, "Z"))
        if corrections:
            table[bits] = corrections
    return table


STEANE_7 = StabilizerCode(
    name="7-qubit Steane code",
    num_data=7,
    num_ancilla=6,
    generators=(
        StabilizerGenerator(basis="Z", data_qubits=(0, 2, 4, 6), ancilla=0),
        StabilizerGenerator(basis="Z", data_qubits=(1, 2, 5, 6), ancilla=1),
        StabilizerGenerator(basis="Z", data_qubits=(3, 4, 5, 6), ancilla=2),
        StabilizerGenerator(basis="X", data_qubits=(0, 2, 4, 6), ancilla=3),
        StabilizerGenerator(basis="X", data_qubits=(1, 2, 5, 6), ancilla=4),
        StabilizerGenerator(basis="X", data_qubits=(3, 4, 5, 6), ancilla=5),
    ),
    syndrome_to_correction=_build_steane7_syndrome_table(),
    logical_x_qubits=(0, 1, 2, 3, 4, 5, 6),
    logical_x_pauli="X",
    logical_z_qubits=(0, 1, 2, 3, 4, 5, 6),
    logical_z_pauli="Z",
    encoding_circuit=(
        EncodingStep(gate="H", target=0),
        EncodingStep(gate="H", target=1),
        EncodingStep(gate="H", target=3),
        EncodingStep(gate="ICX", control=0, target=2),
        EncodingStep(gate="ICX", control=0, target=4),
        EncodingStep(gate="ICX", control=0, target=6),
        EncodingStep(gate="ICX", control=1, target=2),
        EncodingStep(gate="ICX", control=1, target=5),
        EncodingStep(gate="ICX", control=1, target=6),
        EncodingStep(gate="ICX", control=3, target=4),
        EncodingStep(gate="ICX", control=3, target=5),
        EncodingStep(gate="ICX", control=3, target=6),
    ),
)
