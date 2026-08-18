"""Unit tests for app.core.visibility.

`VisibilityValue` is a hand-duplicated `Literal[...]` of `Visibility`'s
own class attributes (PEP 586 forbids building a `Literal` from
attribute references — see the module's own comment). This test is the
guard against those two representations drifting apart.
"""

from typing import get_args

from app.core.visibility import Visibility, VisibilityValue


def test_visibility_literal_matches_class_attributes() -> None:
    literal_values = set(get_args(VisibilityValue))
    class_values = {Visibility.PUBLIC, Visibility.CLOSE_FRIENDS, Visibility.PRIVATE}

    assert literal_values == class_values


def test_visibility_class_has_exactly_three_tiers() -> None:
    assert len(get_args(VisibilityValue)) == 3
