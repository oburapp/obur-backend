"""Integration tests for app.services.venue against the real test database.

These exercise the PostGIS `ST_DWithin` duplicate check and the `pg_trgm`
trigram name search directly — the exact behavior
tests/unit/test_venue_service.py can't verify with mocks alone (see
docs/testing-strategy.md and ADR-0003 in obur-docs).
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DuplicateVenueNearbyError, VenueCategoryNotFoundError
from app.models.user import User
from app.seeds.identity import venue_category_id
from app.services import venue as venue_service

_CAFE_CATEGORY_ID = venue_category_id("cafe")
# Kadıköy, Istanbul — an arbitrary real coordinate, not itself meaningful.
_LAT = 40.9905
_LNG = 29.0234


async def _create_user(db_session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_venue_persists_and_is_retrievable(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    venue = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    fetched = await venue_service.get_venue(db_session, venue.id)
    assert fetched.id == venue.id
    assert fetched.name == "Kadıköy Kahve Durağı"


async def test_create_venue_raises_when_category_does_not_exist(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    with pytest.raises(VenueCategoryNotFoundError):
        await venue_service.create_venue(
            db_session,
            name="Kadıköy Kahve Durağı",
            lat=_LAT,
            lng=_LNG,
            category_id=uuid4(),
            added_by=user.id,
        )


async def test_create_venue_raises_when_another_venue_is_within_50_meters(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
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
        )


async def test_create_venue_succeeds_when_duplicate_is_confirmed(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    first = await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    second = await venue_service.create_venue(
        db_session,
        name="Aynı Yerdeki Başka Kafe — 2. Kat",
        lat=_LAT + 0.00018,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
        confirm_duplicate=True,
    )

    assert second.id != first.id


async def test_create_venue_succeeds_when_existing_venue_is_far_away(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    # ~1.1km away — well outside the duplicate radius.
    far_venue = await venue_service.create_venue(
        db_session,
        name="Üsküdar'da Başka Bir Kafe",
        lat=_LAT + 0.01,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    assert far_venue.id is not None


async def test_search_venues_finds_by_exact_turkish_name(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    results = await venue_service.search_venues(db_session, "döner", limit=20, offset=0)

    assert any(venue.name == "Kadıköy'de En İyi Döner" for venue in results)


async def test_search_venues_finds_turkish_name_typed_without_diacritics(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    # No Turkish keyboard, or just not bothering — a very common real
    # input pattern. See ADR-0003: this was previously a real gap.
    results = await venue_service.search_venues(db_session, "doner", limit=20, offset=0)

    assert any(venue.name == "Kadıköy'de En İyi Döner" for venue in results)


async def test_search_venues_tolerates_a_typo(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    results = await venue_service.search_venues(db_session, "dner", limit=20, offset=0)

    assert any(venue.name == "Kadıköy'de En İyi Döner" for venue in results)


async def test_search_venues_finds_a_non_turkish_name(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Starbucks Bağdat Caddesi",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    results = await venue_service.search_venues(
        db_session, "starbucks", limit=20, offset=0
    )

    assert any(venue.name == "Starbucks Bağdat Caddesi" for venue in results)


async def test_search_venues_excludes_non_matching_names(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    await venue_service.create_venue(
        db_session,
        name="Kadıköy'de En İyi Döner",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )

    results = await venue_service.search_venues(db_session, "sushi", limit=20, offset=0)

    assert results == []
