"""Shared visibility levels for user-generated content.

`CHECKIN`, `LIST`, and `VENUE_SAVE` all use the same three tiers and the
same authorization check (`app.core.authz.can_view`) — one owner-chosen
setting, not a separate bespoke privacy concept per resource type.
"""

from typing import Literal


class Visibility:
    """Allowed values for a resource's `visibility` column."""

    PUBLIC = "public"
    CLOSE_FRIENDS = "close_friends"
    PRIVATE = "private"


# PEP 586 only allows literal expressions (not attribute references, even
# to a `Final`-typed class member) as `Literal[...]` arguments, so this
# can't be built from `Visibility`'s own attributes — a
# `test_visibility_literal_matches_class` unit test keeps the two in
# sync instead.
VisibilityValue = Literal["public", "close_friends", "private"]
