"""Integration tests for app.services.venue_save against the real test
database — the unique constraint, the type/visibility CHECK constraints,
and the existence-leak fix (app.core.authz.ensure_visible_and_owned) all
depend on real DB state.
"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.visibility import Visibility
from app.exceptions import (
    NotVenueSaveOwnerError,
    VenueNotFoundError,
    VenueSaveNotFoundError,
)
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_save import VenueSave
from app.seeds.identity import venue_category_id
from app.services import venue_save as venue_save_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")


async def _create_user(session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, added_by: User) -> Venue:
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def test_save_venue_raises_when_venue_missing(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    with pytest.raises(VenueNotFoundError):
        await venue_save_service.save_venue(
            db_session, user_id=user.id, venue_id=uuid4(), type="visited"
        )


async def test_save_venue_defaults_to_private(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    save = await venue_save_service.save_venue(
        db_session, user_id=user.id, venue_id=venue.id, type="visited"
    )

    assert save.visibility == Visibility.PRIVATE


async def test_save_venue_is_idempotent_per_type(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    first = await venue_save_service.save_venue(
        db_session, user_id=user.id, venue_id=venue.id, type="visited"
    )
    second = await venue_save_service.save_venue(
        db_session, user_id=user.id, venue_id=venue.id, type="visited"
    )

    assert first.id == second.id


async def test_save_venue_allows_independent_saves_per_type(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    visited = await venue_save_service.save_venue(
        db_session, user_id=user.id, venue_id=venue.id, type="visited"
    )
    wishlist = await venue_save_service.save_venue(
        db_session, user_id=user.id, venue_id=venue.id, type="wishlist"
    )

    assert visited.id != wishlist.id


async def test_get_venue_save_returns_it_to_the_owner(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    save = await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )

    fetched = await venue_save_service.get_venue_save(db_session, save.id, viewer=owner)

    assert fetched.id == save.id


async def test_list_venue_saves_for_user_filters_by_viewer(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )
    await venue_save_service.save_venue(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        type="wishlist",
        visibility=Visibility.PUBLIC,
    )

    as_stranger = await venue_save_service.list_venue_saves_for_user(
        db_session, owner.id, viewer=stranger, limit=20, offset=0
    )
    as_owner = await venue_save_service.list_venue_saves_for_user(
        db_session, owner.id, viewer=owner, limit=20, offset=0
    )

    assert len(as_stranger) == 1
    assert len(as_owner) == 2


async def test_update_venue_save_raises_when_it_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(VenueSaveNotFoundError):
        await venue_save_service.update_venue_save(
            db_session,
            uuid4(),
            current_user=owner,
            updates={"visibility": Visibility.PUBLIC},
        )


async def test_update_venue_save_persists_changes_for_the_owner(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    save = await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )

    updated = await venue_save_service.update_venue_save(
        db_session,
        save.id,
        current_user=owner,
        updates={"visibility": Visibility.PUBLIC},
    )

    assert updated.visibility == Visibility.PUBLIC


async def test_delete_venue_save_raises_when_it_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(VenueSaveNotFoundError):
        await venue_save_service.delete_venue_save(
            db_session, uuid4(), current_user=owner
        )


async def test_get_venue_save_raises_when_invisible_to_a_stranger(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    save = await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )

    with pytest.raises(VenueSaveNotFoundError):
        await venue_save_service.get_venue_save(db_session, save.id, viewer=stranger)


async def test_update_venue_save_by_non_owner_on_invisible_save_returns_not_found(
    db_session: AsyncSession,
) -> None:
    """Existence-leak fix: a private save's non-owner mutation attempt
    must 404, not 403 — same rule as checkin/list (see
    app.core.authz.ensure_visible_and_owned).
    """
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    save = await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )

    with pytest.raises(VenueSaveNotFoundError):
        await venue_save_service.update_venue_save(
            db_session,
            save.id,
            current_user=stranger,
            updates={"visibility": Visibility.PUBLIC},
        )


async def test_update_venue_save_by_non_owner_on_visible_save_returns_not_owner(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    save = await venue_save_service.save_venue(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        type="visited",
        visibility=Visibility.PUBLIC,
    )

    with pytest.raises(NotVenueSaveOwnerError):
        await venue_save_service.update_venue_save(
            db_session,
            save.id,
            current_user=stranger,
            updates={"visibility": Visibility.PRIVATE},
        )


async def test_delete_venue_save_removes_the_row(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    save = await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )

    await venue_save_service.delete_venue_save(db_session, save.id, current_user=owner)

    with pytest.raises(VenueSaveNotFoundError):
        await venue_save_service.get_venue_save(db_session, save.id, viewer=owner)


async def test_db_rejects_an_invalid_type_bypassing_the_service_layer(
    db_session: AsyncSession,
) -> None:
    """Defense in depth: `VenueSaveType`'s allowed values are enforced by
    a CHECK constraint (`ck_venue_saves_type_allowed`), not just Pydantic
    at the API boundary — see app/models/venue_save.py.
    """
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                VenueSave(user_id=owner.id, venue_id=venue.id, type="not_a_real_type")
            )
            await db_session.flush()


async def test_db_rejects_an_invalid_visibility_bypassing_the_service_layer(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                VenueSave(
                    user_id=owner.id,
                    venue_id=venue.id,
                    type="visited",
                    visibility="not_a_real_tier",
                )
            )
            await db_session.flush()
