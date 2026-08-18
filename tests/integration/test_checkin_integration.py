"""Integration tests for app.services.checkin against the real test
database — ownership/admin authorization, privacy filtering, and the
soft/hard delete distinction all depend on real DB state.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.visibility import Visibility
from app.exceptions import (
    CheckinNotFoundError,
    EmptyProductListError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    ProductNotAtVenueError,
    VenueNotFoundError,
)
from app.models.checkin_product import CheckinProduct
from app.models.product import Product
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.seeds.identity import global_product_type_id, venue_category_id
from app.services import checkin as checkin_service
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service
from app.services.checkin import ProductRating

_CAFE_CATEGORY_ID = venue_category_id("cafe")
_FILTER_COFFEE_TYPE_ID = global_product_type_id("filter-coffee")
_LAT = 40.9905
_LNG = 29.0234
_TZ = "Europe/Istanbul"


async def _create_user(session: AsyncSession, *, role: str = UserRole.USER) -> User:
    user = User(auth_provider="clerk", auth_provider_id=f"user_{uuid4()}", role=role)
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, added_by: User) -> Venue:
    venue = Venue(
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _create_product(
    session: AsyncSession, venue: Venue, *, is_available: bool = True
) -> Product:
    product = Product(
        venue_id=venue.id,
        global_type_id=_FILTER_COFFEE_TYPE_ID,
        name="Filtre Kahve",
        is_available=is_available,
    )
    session.add(product)
    await session.flush()
    return product


async def test_create_checkin_persists_and_is_retrievable(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    product = await _create_product(db_session, venue)

    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=user.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        note="harika bir yer",
    )

    fetched = await checkin_service.get_checkin(db_session, checkin.id, viewer=user)
    assert fetched.note == "harika bir yer"

    result = await db_session.execute(
        select(CheckinProduct).where(CheckinProduct.checkin_id == checkin.id)
    )
    products = result.scalars().all()
    assert len(products) == 1
    assert products[0].rating == 4


async def test_create_checkin_raises_when_venue_does_not_exist(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    with pytest.raises(VenueNotFoundError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=uuid4(),
            products=[ProductRating(product_id=uuid4(), rating=4)],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_with_no_products(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    with pytest.raises(EmptyProductListError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=venue.id,
            products=[],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_when_product_belongs_to_another_venue(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    other_venue = await _create_venue(db_session, user)
    product_elsewhere = await _create_product(db_session, other_venue)

    with pytest.raises(ProductNotAtVenueError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=venue.id,
            products=[ProductRating(product_id=product_elsewhere.id, rating=4)],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_when_product_is_no_longer_available(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    product = await _create_product(db_session, venue, is_available=False)

    with pytest.raises(ProductNotAtVenueError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=venue.id,
            products=[ProductRating(product_id=product.id, rating=4)],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_on_future_visit_date(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    product = await _create_product(db_session, venue)

    with pytest.raises(FutureVisitDateError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=venue.id,
            products=[ProductRating(product_id=product.id, rating=4)],
            visited_at=date.today() + timedelta(days=1),
            visited_tz=_TZ,
        )


async def test_get_checkin_hides_private_checkin_from_other_users(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=other_user)

    fetched = await checkin_service.get_checkin(db_session, checkin.id, viewer=owner)
    assert fetched.id == checkin.id


async def test_get_checkin_reveals_private_checkin_to_admin(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    fetched = await checkin_service.get_checkin(db_session, checkin.id, viewer=admin)
    assert fetched.id == checkin.id


async def test_get_checkin_reveals_close_friends_checkin_only_to_close_friends(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    close_friend_user = await _create_user(db_session)
    stranger = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=close_friend_user.id, following_id=owner.id
    )
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=close_friend_user.id
    )
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.CLOSE_FRIENDS,
    )

    fetched = await checkin_service.get_checkin(
        db_session, checkin.id, viewer=close_friend_user
    )
    assert fetched.id == checkin.id

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=stranger)


async def test_list_checkins_for_venue_filters_private_checkins(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PUBLIC,
    )
    private_checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=3)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    as_stranger = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=other_user, limit=20, offset=0
    )
    assert all(c.id != private_checkin.id for c in as_stranger)
    assert len(as_stranger) == 1

    as_owner = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=owner, limit=20, offset=0
    )
    assert any(c.id == private_checkin.id for c in as_owner)
    assert len(as_owner) == 2


async def test_list_checkins_for_user_filters_private_checkins(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    as_stranger = await checkin_service.list_checkins_for_user(
        db_session, owner.id, viewer=other_user, limit=20, offset=0
    )
    as_owner = await checkin_service.list_checkins_for_user(
        db_session, owner.id, viewer=owner, limit=20, offset=0
    )

    assert as_stranger == []
    assert len(as_owner) == 1


async def test_update_checkin_persists_changes_for_the_owner(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    updated = await checkin_service.update_checkin(
        db_session, checkin.id, current_user=owner, updates={"note": "değişti"}
    )

    assert updated.note == "değişti"


async def test_update_checkin_raises_for_non_owner(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    with pytest.raises(NotCheckinOwnerError):
        await checkin_service.update_checkin(
            db_session,
            checkin.id,
            current_user=other_user,
            updates={"note": "başkası düzenlemeye çalıştı"},
        )


async def test_update_checkin_by_non_owner_on_a_private_checkin_returns_not_found(
    db_session: AsyncSession,
) -> None:
    """Existence-leak fix: a stranger who can't even see a private
    checkin must get the same `CheckinNotFoundError` a nonexistent id
    would — never `NotCheckinOwnerError`, which would confirm the id
    belongs to something real (see app.core.authz.ensure_visible_and_owned).
    """
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.update_checkin(
            db_session, checkin.id, current_user=stranger, updates={"note": "x"}
        )


async def test_soft_delete_excludes_checkin_from_listings_and_lookup(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=owner
    )

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=owner)

    listing = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=owner, limit=20, offset=0
    )
    assert listing == []

    # The row itself still exists — this was a soft delete.
    result = await db_session.execute(
        select(CheckinProduct).where(CheckinProduct.checkin_id == checkin.id)
    )
    assert len(result.scalars().all()) == 1


async def test_hard_delete_removes_checkin_and_cascades_to_products(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    await checkin_service.hard_delete_checkin(db_session, checkin.id)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=owner)

    result = await db_session.execute(
        select(CheckinProduct).where(CheckinProduct.checkin_id == checkin.id)
    )
    assert result.scalars().all() == []


async def test_hard_delete_can_purge_an_already_soft_deleted_checkin(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    product = await _create_product(db_session, venue)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        products=[ProductRating(product_id=product.id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
    )
    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=owner
    )

    await checkin_service.hard_delete_checkin(db_session, checkin.id)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.hard_delete_checkin(db_session, checkin.id)
