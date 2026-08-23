"""Deterministic UUIDs for seed rows.

Seed rows (venue categories) have slug-based stable identity, not
database-generated identity — the same slug must always resolve to the
same UUID so the seed migration can bulk-upsert self-referencing rows
(a category's `parent_id`) in a single pass, with no insert-then-lookup
round trip.

`_SEED_NAMESPACE` is a fixed, randomly generated UUID used the same way
`uuid.NAMESPACE_DNS` etc. are used by `uuid.uuid5` in the standard
library — it must never change once seed data has been applied anywhere,
since changing it would change every derived id.
"""

import uuid

_SEED_NAMESPACE = uuid.UUID("787548b6-69ff-4c31-b308-50f826abe79a")


def venue_category_id(slug: str) -> uuid.UUID:
    """Deterministic id for a VENUE_CATEGORY row, derived from its slug."""
    return uuid.uuid5(_SEED_NAMESPACE, f"venue_category:{slug}")
