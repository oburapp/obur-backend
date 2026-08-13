"""Tests for Clerk webhook payload parsing."""

from app.schemas.webhook import ClerkEmailAddress, ClerkUserData


def test_primary_email_resolves_the_matching_address() -> None:
    data = ClerkUserData(
        id="user_abc",
        email_addresses=[
            ClerkEmailAddress(id="idn_1", email_address="first@example.com"),
            ClerkEmailAddress(id="idn_2", email_address="primary@example.com"),
        ],
        primary_email_address_id="idn_2",
    )

    assert data.primary_email == "primary@example.com"


def test_primary_email_is_none_when_no_primary_id_set() -> None:
    data = ClerkUserData(
        id="user_abc",
        email_addresses=[
            ClerkEmailAddress(id="idn_1", email_address="first@example.com")
        ],
        primary_email_address_id=None,
    )

    assert data.primary_email is None


def test_primary_email_is_none_when_primary_id_matches_nothing() -> None:
    data = ClerkUserData(
        id="user_abc",
        email_addresses=[
            ClerkEmailAddress(id="idn_1", email_address="first@example.com")
        ],
        primary_email_address_id="idn_does_not_exist",
    )

    assert data.primary_email is None
