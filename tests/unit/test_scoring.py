"""Unit tests for app.core.scoring: the PDD §8 procedure as ADR-0020 in
obur-docs settles it.
"""

import math

import pytest

from app.core.scoring import (
    SCORE_FLOOR,
    lower_bound,
    t_critical_95,
    tier_for,
    tier_from_sample,
)

# Published one-sided 95% critical values (any Student's t table).
_PUBLISHED_T = {1: 6.314, 2: 2.920, 9: 1.833, 10: 1.812, 30: 1.697, 60: 1.671}
_TABLE_TOLERANCE = 0.0006
_NORMAL_95 = 1.6449


@pytest.mark.parametrize(("df", "expected"), _PUBLISHED_T.items())
def test_t_critical_values_match_published_tables(df: int, expected: float) -> None:
    assert t_critical_95(df) == pytest.approx(expected, abs=_TABLE_TOLERANCE)


def test_beyond_the_table_the_normal_value_is_used() -> None:
    assert t_critical_95(101) == _NORMAL_95
    assert t_critical_95(100) - _NORMAL_95 < 0.02


def test_degrees_of_freedom_below_one_are_rejected() -> None:
    with pytest.raises(ValueError):
        t_critical_95(0)


def test_lower_bound_applies_the_formula() -> None:
    count, mean, std_dev = 16, 3.0, 0.8
    expected = mean - t_critical_95(count - 1) * std_dev / math.sqrt(count)

    assert lower_bound(count, mean, std_dev) == pytest.approx(expected)


def test_lower_bound_is_clipped_to_the_rating_scale() -> None:
    assert lower_bound(10, 1.2, 3.0) == 1.0
    assert lower_bound(10, 4.0, 0.0) == 4.0


@pytest.mark.parametrize(
    ("bound", "tier"),
    [
        (4.0, "extremely_favorable"),
        (3.71, "extremely_favorable"),
        (3.7, "very_favorable"),
        (3.41, "very_favorable"),
        (3.4, "fairly_favorable"),
        (3.11, "fairly_favorable"),
        (3.1, "somewhat_favorable"),
        (2.81, "somewhat_favorable"),
        (2.8, "mixed"),
        (2.2, "mixed"),
        (2.19, "somewhat_unfavorable"),
        (1.9, "somewhat_unfavorable"),
        (1.89, "fairly_unfavorable"),
        (1.6, "fairly_unfavorable"),
        (1.59, "very_unfavorable"),
        (1.3, "very_unfavorable"),
        (1.29, "extremely_unfavorable"),
        (1.0, "extremely_unfavorable"),
    ],
)
def test_tiers_follow_the_pdd_table_at_every_boundary(bound: float, tier: str) -> None:
    assert tier_for(bound) == tier


def test_below_the_floor_there_is_no_tier() -> None:
    assert tier_from_sample(SCORE_FLOOR - 1, 4.0, 0.0) is None
    assert tier_from_sample(0, None, None) is None


def test_at_the_floor_a_tier_is_given() -> None:
    assert tier_from_sample(SCORE_FLOOR, 4.0, 0.0) == "extremely_favorable"


def test_disagreement_pulls_the_tier_down_at_the_same_mean() -> None:
    agreed = tier_from_sample(SCORE_FLOOR, 3.5, 0.1)
    split = tier_from_sample(SCORE_FLOOR, 3.5, 1.5)

    assert agreed == "very_favorable"
    assert split == "mixed"
