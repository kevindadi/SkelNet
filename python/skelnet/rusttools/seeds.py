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


def oracle_miri_seeds() -> list[int]:
    return list(range(ORACLE_MIRI_SEED_START,
                      ORACLE_MIRI_SEED_START + ORACLE_MIRI_SEED_COUNT))


def feedback_miri_seeds() -> list[int]:
    return list(range(FEEDBACK_MIRI_SEED_START,
                      FEEDBACK_MIRI_SEED_START + FEEDBACK_MIRI_SEED_COUNT))


def miri_many_seeds_flag(start: int, count: int) -> str:
    """The ``-Zmiri-many-seeds`` value for a half-open range of seeds."""
    return f"-Zmiri-many-seeds={start}..{start + count}"
