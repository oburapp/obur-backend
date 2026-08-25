"""Integration tests for app.services.venue against the real test database.

These exercise the PostGIS `ST_DWithin` duplicate check and the `pg_trgm`
trigram name search directly — the exact behavior
tests/unit/test_venue_service.py can't verify with mocks alone (see
docs/testing-strategy.md and ADR-0003 in obur-docs).
"""

import uuid
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotEligibleForVerificationError,
)
from app.models.user import User, UserRole
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import venue as venue_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
# Kadıköy, Istanbul — an arbitrary real coordinate, not itself meaningful.
_LAT = 40.9905
_LNG = 29.0234


async def _create_user(db_session: AsyncSession, *, role: str = UserRole.USER) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_venue_persists_and_is_retrievable(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)

    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    fetched = await venue_service.get_venue(db_session, venue.id)
    assert fetched.id == venue.id
    assert fetched.name == "Kadıköy Kahve Durağı"


async def test_create_venue_raises_when_category_does_not_exist(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)

    with pytest.raises(VenueCategoryNotFoundError):
        await venue_service.create_venue(
            db_session,
            name="Kadıköy Kahve Durağı",
            lat=_LAT,
            lng=_LNG,
            category_id=uuid4(),
            added_by=user.id,
            district="Kadıköy",
        )


async def test_create_venue_raises_when_another_venue_is_within_50_meters(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    # ~20m north of the first venue — inside the 50m duplicate radius.
    with pytest.raises(DuplicateVenueNearbyError):
        await venue_service.create_venue(
            db_session,
            name="Aynı Yerdeki Başka Kafe",
            lat=_LAT + 0.00018,
            lng=_LNG,
            category_id=_CAFE_CATEGORY_ID,
            added_by=user.id,
            district="Kadıköy",
        )


async def test_create_venue_succeeds_when_duplicate_is_confirmed(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    first = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    second = await venue_service.create_venue(
        db_session,
        name="Aynı Yerdeki Başka Kafe — 2. Kat",
        lat=_LAT + 0.00018,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
        confirm_duplicate=True,
    )

    assert second.id != first.id


async def test_create_venue_succeeds_when_existing_venue_is_far_away(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    # ~1.1km away — well outside the duplicate radius.
    far_venue = await venue_service.create_venue(
        db_session,
        name="Üsküdar'da Başka Bir Kafe",
        lat=_LAT + 0.01,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    assert far_venue.id is not None


async def test_search_venues_finds_by_exact_turkish_name(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    results = await venue_service.search_venues(db_session, "döner", limit=20, offset=0)

    assert any(venue.name == "Kadıköy'de En İyi Döner" for venue in results)


async def test_search_venues_finds_turkish_name_typed_without_diacritics(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    # No Turkish keyboard, or just not bothering — a very common real
    # input pattern. See ADR-0003: this was previously a real gap.
    results = await venue_service.search_venues(db_session, "doner", limit=20, offset=0)

    assert any(venue.name == "Kadıköy'de En İyi Döner" for venue in results)


async def test_search_venues_tolerates_a_typo(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    results = await venue_service.search_venues(db_session, "dner", limit=20, offset=0)

    assert any(venue.name == "Kadıköy'de En İyi Döner" for venue in results)


async def test_search_venues_finds_a_non_turkish_name(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Starbucks Bağdat Caddesi",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    results = await venue_service.search_venues(
        db_session, "starbucks", limit=20, offset=0
    )

    assert any(venue.name == "Starbucks Bağdat Caddesi" for venue in results)


async def test_search_venues_excludes_non_matching_names(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
    )

    results = await venue_service.search_venues(db_session, "sushi", limit=20, offset=0)

    assert results == []


async def _checkin_at(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    venue_id: uuid.UUID,
    visibility: str = Visibility.PUBLIC,
) -> None:
    await set_current_user_identity(db_session, user_id)
    await checkin_service.create_checkin(
        db_session,
        user_id=user_id,
        venue_id=venue_id,
        rating_taste=4,
        rating_service=4,
        rating_ambiance=4,
        rating_value=4,
        visited_at=date.today(),
        visited_tz="Europe/Istanbul",
        visibility=visibility,
    )


async def test_create_venue_with_matching_google_places_id_resolves_idempotently(
    db_session: AsyncSession,
) -> None:
    """An exact `google_places_id` match is a certain duplicate per
    ADR-0009: no "did you mean this one?" prompt, just the same venue
    back, even far away and with a different name.
    """
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    first = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
        google_places_id="ChIJexact_match_test",
    )

    second = await venue_service.create_venue(
        db_session,
        name="Tamamen Farklı Bir İsim",
        lat=_LAT + 0.5,  # far away, would fail the 50m fallback
        lng=_LNG + 0.5,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Üsküdar",
        google_places_id="ChIJexact_match_test",
    )

    assert second.id == first.id


async def test_google_places_id_match_is_not_bypassable_via_confirm_duplicate(
    db_session: AsyncSession,
) -> None:
    """Unlike the 50m fallback, the exact-match layer has nothing to
    confirm: it's the same business by definition, per ADR-0009.
    """
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)
    first = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Kadıköy",
        google_places_id="ChIJnot_bypassable",
    )

    second = await venue_service.create_venue(
        db_session,
        name="Farklı İsim",
        lat=_LAT + 0.5,
        lng=_LNG + 0.5,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        district="Üsküdar",
        google_places_id="ChIJnot_bypassable",
        confirm_duplicate=True,
    )

    assert second.id == first.id


async def test_evaluate_venue_verification_sets_is_verified_at_threshold_with_match(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
        google_places_id="ChIJverify_auto",
    )

    for _ in range(3):
        checker = await _create_user(db_session)
        await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)

    fetched = await venue_service.get_venue(db_session, venue.id)
    assert fetched.is_verified is True


async def test_evaluate_venue_verification_stays_false_below_threshold(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
        google_places_id="ChIJverify_below",
    )

    for _ in range(2):
        checker = await _create_user(db_session)
        await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)

    fetched = await venue_service.get_venue(db_session, venue.id)
    assert fetched.is_verified is False


async def test_evaluate_venue_verification_ignores_venues_without_google_places_id(
    db_session: AsyncSession,
) -> None:
    """No `google_places_id` means check-ins alone never verify a venue,
    per ADR-0009, it only becomes *eligible* for `verify_venue_by_admin`.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
    )

    for _ in range(5):
        checker = await _create_user(db_session)
        await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)

    fetched = await venue_service.get_venue(db_session, venue.id)
    assert fetched.is_verified is False


async def test_evaluate_venue_verification_only_counts_public_checkins(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
        google_places_id="ChIJverify_private",
    )

    checker = await _create_user(db_session)
    await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)
    for _ in range(2):
        private_checker = await _create_user(db_session)
        await _checkin_at(
            db_session,
            user_id=private_checker.id,
            venue_id=venue.id,
            visibility=Visibility.PRIVATE,
        )

    # 1 public + 2 private: below the threshold of 3 public check-ins.
    fetched = await venue_service.get_venue(db_session, venue.id)
    assert fetched.is_verified is False


async def test_verify_venue_by_admin_succeeds_at_threshold(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
    )

    for _ in range(5):
        checker = await _create_user(db_session)
        await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)

    # venues_update's RLS policy (migration c1d5a8f042e7) is admin-only,
    # the identity from the last check-in above is an ordinary user's,
    # so this has to switch to an admin before the actual write happens.
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    verified = await venue_service.verify_venue_by_admin(db_session, venue.id)
    assert verified.is_verified is True


async def test_verify_venue_by_admin_is_idempotent_once_already_verified(
    db_session: AsyncSession,
) -> None:
    """A second call (e.g. two admins reviewing the same report queue
    entry) is a no-op, not a repeat write or a raised error, even for
    a venue that's since dropped below the check-in threshold (a
    checker's account was purged, say): verification never revokes
    itself once earned.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
    )

    for _ in range(5):
        checker = await _create_user(db_session)
        await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    await venue_service.verify_venue_by_admin(db_session, venue.id)

    verified_again = await venue_service.verify_venue_by_admin(db_session, venue.id)
    assert verified_again.is_verified is True


async def test_verify_venue_by_admin_raises_below_threshold(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
    )

    for _ in range(4):
        checker = await _create_user(db_session)
        await _checkin_at(db_session, user_id=checker.id, venue_id=venue.id)

    with pytest.raises(VenueNotEligibleForVerificationError):
        await venue_service.verify_venue_by_admin(db_session, venue.id)
