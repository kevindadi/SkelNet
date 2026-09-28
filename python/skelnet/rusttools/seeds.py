"""Oracle and (reserved) feedback seed ranges.

The oracle's Shuttle/miri seeds are fixed and disjoint from the ranges reserved
for the round-4 dynamic/static feedback baselines, so calibration and feedback
can never collide.
"""

from __future__ import annotations

# Oracle (round 3): fixed, reproducible exploration seeds.
ORACLE_SHUTTLE_SEED = 0x5EED_0001
ORACLE_MIRI_SEED_START = 0x5EED_1000
ORACLE_MIRI_SEED_COUNT = 16

# Reserved for the round-4 feedback baselines. Not used in round 3.
FEEDBACK_SHUTTLE_SEED = 0xF00D_0001
FEEDBACK_MIRI_SEED_START = 0xF00D_1000
FEEDBACK_MIRI_SEED_COUNT = 64
# Dynamic feedback uses the first 16 seeds of the reserved miri window (D4-8).
FEEDBACK_MIRI_SEED_DEFAULT_COUNT = 16


def oracle_miri_seeds() -> list[int]:
    return list(range(ORACLE_MIRI_SEED_START,
                      ORACLE_MIRI_SEED_START + ORACLE_MIRI_SEED_COUNT))


def feedback_miri_seeds() -> list[int]:
    return list(range(FEEDBACK_MIRI_SEED_START,
                      FEEDBACK_MIRI_SEED_START + FEEDBACK_MIRI_SEED_COUNT))


def feedback_shuttle_seed() -> int:
    """Shuttle seed used by dynamic feedback (disjoint from the oracle)."""
    return FEEDBACK_SHUTTLE_SEED


def feedback_miri_window(count: int | None = None) -> tuple[int, int]:
    """``(start, count)`` for one feedback miri run, inside the reserved range."""
    n = FEEDBACK_MIRI_SEED_DEFAULT_COUNT if count is None else count
    if n < 0 or n > FEEDBACK_MIRI_SEED_COUNT:
        raise ValueError(
            f"feedback miri seed count {n} is outside 0..{FEEDBACK_MIRI_SEED_COUNT}")
    return FEEDBACK_MIRI_SEED_START, n


def miri_many_seeds_flag(start: int, count: int) -> str:
    """The ``-Zmiri-many-seeds`` value for a half-open range of seeds."""
    return f"-Zmiri-many-seeds={start}..{start + count}"
