"""Response shapes for a venue's score (PDD §8, ADR-0020 in obur-docs).

Tier keys only, never a mean or a bound: clients map each key to their
own wording, in the reader's language, the same way they handle problem
types (ADR-0015).
"""

from pydantic import BaseModel

from app.core.scoring import Tier


class CriteriaTiers(BaseModel):
    """One tier per rated criterion; None below the floor."""

    taste: Tier | None
    service: Tier | None
    ambiance: Tier | None
    value: Tier | None


class VenueScore(BaseModel):
    """What a venue page shows about how it's rated: tiers only, never a
    number other than how many check-ins they rest on.
    """

    tier: Tier | None
    criteria: CriteriaTiers
    checkin_count: int
