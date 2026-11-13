"""The venue score's statistics (PDD §8, ADR-0020 in obur-docs): pure
functions, no database access.

Each check-in is one observation, the mean of its four ratings, because a
visit's four ratings aren't independent. Below `SCORE_FLOOR` check-ins
there is no tier. Above it, the 95% one-sided confidence lower bound on
the mean is placed in the 9-tier band table, and only the tier is ever
shown.

Cut points and the floor are named constants so calibrating them against
real usage (PDD §18) is a value change.
"""

import math
from typing import Literal

from app.core.ratings import MAX_RATING, MIN_RATING

SCORE_FLOOR = 10

# One-sided 95% critical values of Student's t, t(0.95, df), for df 1 to
# 100. Generated once with scipy.stats.t.ppf(0.95, df), rounded to four
# places; SciPy is not a dependency. Beyond 100 degrees of freedom the
# normal value is used: at df = 100 the two differ by under 1%, far inside
# the band widths below.
_T_CRITICAL_95 = (
    6.3138, 2.92, 2.3534, 2.1318, 2.015, 1.9432, 1.8946, 1.8595, 1.8331, 1.8125,
    1.7959, 1.7823, 1.7709, 1.7613, 1.7531, 1.7459, 1.7396, 1.7341, 1.7291, 1.7247,
    1.7207, 1.7171, 1.7139, 1.7109, 1.7081, 1.7056, 1.7033, 1.7011, 1.6991, 1.6973,
    1.6955, 1.6939, 1.6924, 1.6909, 1.6896, 1.6883, 1.6871, 1.686, 1.6849, 1.6839,
    1.6829, 1.682, 1.6811, 1.6802, 1.6794, 1.6787, 1.6779, 1.6772, 1.6766, 1.6759,
    1.6753, 1.6747, 1.6741, 1.6736, 1.673, 1.6725, 1.672, 1.6716, 1.6711, 1.6706,
    1.6702, 1.6698, 1.6694, 1.669, 1.6686, 1.6683, 1.6679, 1.6676, 1.6672, 1.6669,
    1.6666, 1.6663, 1.666, 1.6657, 1.6654, 1.6652, 1.6649, 1.6646, 1.6644, 1.6641,
    1.6639, 1.6636, 1.6634, 1.6632, 1.663, 1.6628, 1.6626, 1.6624, 1.6622, 1.662,
    1.6618, 1.6616, 1.6614, 1.6612, 1.6611, 1.6609, 1.6607, 1.6606, 1.6604, 1.6602,
)  # fmt: skip
_NORMAL_CRITICAL_95 = 1.6449

Tier = Literal[
    "extremely_favorable",
    "very_favorable",
    "fairly_favorable",
    "somewhat_favorable",
    "mixed",
    "somewhat_unfavorable",
    "fairly_unfavorable",
    "very_unfavorable",
    "extremely_unfavorable",
]

# PDD §8's table. Favorable tiers start strictly above their lower cut,
# unfavorable tiers end strictly below their upper cut, and `mixed` is the
# closed range between, exactly as the table writes its intervals.
_FAVORABLE_CUTS: tuple[tuple[float, Tier], ...] = (
    (3.7, "extremely_favorable"),
    (3.4, "very_favorable"),
    (3.1, "fairly_favorable"),
    (2.8, "somewhat_favorable"),
)
_MIXED_FLOOR = 2.2
_UNFAVORABLE_CUTS: tuple[tuple[float, Tier], ...] = (
    (1.9, "somewhat_unfavorable"),
    (1.6, "fairly_unfavorable"),
    (1.3, "very_unfavorable"),
)
_LOWEST_TIER: Tier = "extremely_unfavorable"


def t_critical_95(degrees_of_freedom: int) -> float:
    """One-sided 95% critical value of Student's t."""
    if degrees_of_freedom < 1:
        raise ValueError("degrees of freedom must be at least 1")
    if degrees_of_freedom > len(_T_CRITICAL_95):
        return _NORMAL_CRITICAL_95
    return _T_CRITICAL_95[degrees_of_freedom - 1]


def lower_bound(count: int, mean: float, std_dev: float) -> float:
    """95% one-sided confidence lower bound on the mean, clipped to the
    rating scale. `std_dev` is the sample standard deviation.
    """
    margin = t_critical_95(count - 1) * std_dev / math.sqrt(count)
    return min(max(mean - margin, MIN_RATING), MAX_RATING)


def tier_for(bound: float) -> Tier:
    """Place a lower bound in PDD §8's 9-tier table."""
    for cut, tier in _FAVORABLE_CUTS:
        if bound > cut:
            return tier
    if bound >= _MIXED_FLOOR:
        return "mixed"
    for cut, tier in _UNFAVORABLE_CUTS:
        if bound >= cut:
            return tier
    return _LOWEST_TIER


def tier_from_sample(
    count: int, mean: float | None, std_dev: float | None
) -> Tier | None:
    """The tier for a sample, or None below `SCORE_FLOOR`."""
    if count < SCORE_FLOOR or mean is None:
        return None
    return tier_for(lower_bound(count, mean, std_dev or 0.0))
