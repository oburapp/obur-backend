"""Unit test for app.models.venue_save's `VenueSaveTypeValue` Literal —
guards against it drifting from `VenueSaveType`'s own class attributes,
the same PEP 586 duplication issue as `Visibility`/`VisibilityValue`
(see app.core.visibility and tests/unit/test_visibility.py).
"""

from typing import get_args

from app.models.venue_save import VenueSaveType, VenueSaveTypeValue


def test_venue_save_type_literal_matches_class_attributes() -> None:
    literal_values = set(get_args(VenueSaveTypeValue))
    class_values = {
        VenueSaveType.VISITED,
        VenueSaveType.WISHLIST,
        VenueSaveType.FAVORITE,
    }

    assert literal_values == class_values
