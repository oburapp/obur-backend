"""Shared check-in rating scale.

Four discrete values, no neutral option — an even count structurally
reduces rating inflation (everyone giving the top score), unlike a 1-5
star scale. See the PDD's "Rating System" section. Used by both
every venue-level criterion on `CHECKIN` — one scale, one meaning, in
one place so it can't drift.
"""

MIN_RATING = 1
MAX_RATING = 4


class RatingLabel:
    """Named values for the four rating points, for readable comparisons
    (e.g. `rating == RatingLabel.VERY_GOOD`) instead of bare integers.
    """

    BAD = 1
    AVERAGE = 2
    GOOD = 3
    VERY_GOOD = 4
