"""Integration tests for app.services.list against the real test
database — visibility filtering, fractional-indexing ordering (which
depends on `ListItem.position`'s real `COLLATE "C"` — see
app/models/list_item.py), and cascade deletes all depend on real DB
state.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.visibility import Visibility
from app.exceptions import (
    DuplicateListItemError,
    ListItemNotFoundError,
    ListNotFoundError,
    NotListOwnerError,
    VenueNotFoundError,
)
from app.models.list_item import ListItem
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service
from app.services import list as list_service

_CAFE_CATEGORY_ID = venue_category_id("cafe")


async def _create_user(session: AsyncSession) -> User:
    user = User(auth_provider="clerk", auth_provider_id=f"user_{uuid4()}")
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, added_by: User, *, name: str) -> Venue:
    venue = Venue(
        name=name,
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def test_create_list_defaults_to_public(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)

    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Kahveciler"
    )

    assert venue_list.visibility == Visibility.PUBLIC


async def test_get_list_hides_private_list_from_other_users(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Gizli liste", visibility=Visibility.PRIVATE
    )

    with pytest.raises(ListNotFoundError):
        await list_service.get_list(db_session, venue_list.id, viewer=other_user)

    fetched = await list_service.get_list(db_session, venue_list.id, viewer=owner)
    assert fetched.id == venue_list.id


async def test_get_list_reveals_close_friends_list_only_to_close_friends(
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
    venue_list = await list_service.create_list(
        db_session,
        user_id=owner.id,
        title="Yakın arkadaşlara özel",
        visibility=Visibility.CLOSE_FRIENDS,
    )

    visible = await list_service.get_list(
        db_session, venue_list.id, viewer=close_friend_user
    )
    assert visible.id == venue_list.id

    with pytest.raises(ListNotFoundError):
        await list_service.get_list(db_session, venue_list.id, viewer=stranger)


async def test_get_list_raises_when_it_does_not_exist(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(ListNotFoundError):
        await list_service.get_list(db_session, uuid4(), viewer=owner)


async def test_update_list_persists_changes_for_the_owner(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    updated = await list_service.update_list(
        db_session, venue_list.id, current_user=owner, updates={"title": "Yeni başlık"}
    )

    assert updated.title == "Yeni başlık"


async def test_update_list_raises_when_it_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(ListNotFoundError):
        await list_service.update_list(
            db_session, uuid4(), current_user=owner, updates={"title": "x"}
        )


async def test_delete_list_raises_when_it_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(ListNotFoundError):
        await list_service.delete_list(db_session, uuid4(), current_user=owner)


async def test_add_list_item_raises_when_list_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner, name="Mekan")

    with pytest.raises(ListNotFoundError):
        await list_service.add_list_item(
            db_session, uuid4(), current_user=owner, venue_id=venue.id
        )


async def test_move_list_item_raises_when_list_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(ListNotFoundError):
        await list_service.move_list_item(
            db_session, uuid4(), uuid4(), current_user=owner, after_item_id=None
        )


async def test_move_list_item_raises_when_item_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    with pytest.raises(ListItemNotFoundError):
        await list_service.move_list_item(
            db_session, venue_list.id, uuid4(), current_user=owner, after_item_id=None
        )


async def test_remove_list_item_raises_when_list_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)

    with pytest.raises(ListNotFoundError):
        await list_service.remove_list_item(
            db_session, uuid4(), uuid4(), current_user=owner
        )


async def test_update_list_raises_for_non_owner(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    with pytest.raises(NotListOwnerError):
        await list_service.update_list(
            db_session, venue_list.id, current_user=stranger, updates={"title": "x"}
        )


async def test_delete_list_cascades_to_its_items(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner, name="Mekan A")
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    item = await list_service.add_list_item(
        db_session, venue_list.id, current_user=owner, venue_id=venue.id
    )

    await list_service.delete_list(db_session, venue_list.id, current_user=owner)

    result = await db_session.execute(select(ListItem).where(ListItem.id == item.id))
    assert result.scalar_one_or_none() is None


async def test_add_list_item_raises_when_venue_missing(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    with pytest.raises(VenueNotFoundError):
        await list_service.add_list_item(
            db_session, venue_list.id, current_user=owner, venue_id=uuid4()
        )


async def test_add_list_item_raises_on_duplicate_venue(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner, name="Mekan A")
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    await list_service.add_list_item(
        db_session, venue_list.id, current_user=owner, venue_id=venue.id
    )

    with pytest.raises(DuplicateListItemError):
        await list_service.add_list_item(
            db_session, venue_list.id, current_user=owner, venue_id=venue.id
        )


async def test_add_list_item_appends_to_the_end_by_default(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    venues = [
        await _create_venue(db_session, owner, name=f"Mekan {i}") for i in range(3)
    ]

    items = [
        await list_service.add_list_item(
            db_session, venue_list.id, current_user=owner, venue_id=venue.id
        )
        for venue in venues
    ]

    ordered = await list_service.list_items_for_list(
        db_session, venue_list.id, limit=20, offset=0
    )
    assert [item.id for item in ordered] == [item.id for item in items]


async def test_add_list_item_inserts_after_a_given_item(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    venue_a = await _create_venue(db_session, owner, name="A")
    venue_b = await _create_venue(db_session, owner, name="B")
    venue_c = await _create_venue(db_session, owner, name="C")
    item_a = await list_service.add_list_item(
        db_session, venue_list.id, current_user=owner, venue_id=venue_a.id
    )
    item_c = await list_service.add_list_item(
        db_session, venue_list.id, current_user=owner, venue_id=venue_c.id
    )

    item_b = await list_service.add_list_item(
        db_session,
        venue_list.id,
        current_user=owner,
        venue_id=venue_b.id,
        after_item_id=item_a.id,
    )

    ordered = await list_service.list_items_for_list(
        db_session, venue_list.id, limit=20, offset=0
    )
    assert [item.id for item in ordered] == [item_a.id, item_b.id, item_c.id]


async def test_move_list_item_to_the_very_start(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    venues = [
        await _create_venue(db_session, owner, name=f"Mekan {i}") for i in range(3)
    ]
    items = [
        await list_service.add_list_item(
            db_session, venue_list.id, current_user=owner, venue_id=venue.id
        )
        for venue in venues
    ]

    await list_service.move_list_item(
        db_session, venue_list.id, items[-1].id, current_user=owner, after_item_id=None
    )

    ordered = await list_service.list_items_for_list(
        db_session, venue_list.id, limit=20, offset=0
    )
    assert ordered[0].id == items[-1].id


async def test_move_list_item_raises_when_after_item_belongs_to_another_list(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    list_a = await list_service.create_list(db_session, user_id=owner.id, title="A")
    list_b = await list_service.create_list(db_session, user_id=owner.id, title="B")
    venue_a = await _create_venue(db_session, owner, name="A")
    venue_b = await _create_venue(db_session, owner, name="B")
    item_in_a = await list_service.add_list_item(
        db_session, list_a.id, current_user=owner, venue_id=venue_a.id
    )
    item_in_b = await list_service.add_list_item(
        db_session, list_b.id, current_user=owner, venue_id=venue_b.id
    )

    with pytest.raises(ListItemNotFoundError):
        await list_service.move_list_item(
            db_session,
            list_a.id,
            item_in_a.id,
            current_user=owner,
            after_item_id=item_in_b.id,
        )


async def test_remove_list_item_raises_for_an_item_not_on_this_list(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    with pytest.raises(ListItemNotFoundError):
        await list_service.remove_list_item(
            db_session, venue_list.id, uuid4(), current_user=owner
        )


async def test_remove_list_item_removes_it_and_preserves_remaining_order(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    venues = [
        await _create_venue(db_session, owner, name=f"Mekan {i}") for i in range(3)
    ]
    items = [
        await list_service.add_list_item(
            db_session, venue_list.id, current_user=owner, venue_id=venue.id
        )
        for venue in venues
    ]

    await list_service.remove_list_item(
        db_session, venue_list.id, items[1].id, current_user=owner
    )

    ordered = await list_service.list_items_for_list(
        db_session, venue_list.id, limit=20, offset=0
    )
    assert [item.id for item in ordered] == [items[0].id, items[2].id]


async def test_repeated_drag_to_front_ends_in_exact_reverse_insertion_order(
    db_session: AsyncSession,
) -> None:
    """Empirical regression guard for the fractional-indexing/collation
    bug found during development (see ADR-0007 and
    app/models/list_item.py's docstring): `position` must be `COLLATE
    "C"`, or `ORDER BY position` silently returns items out of order
    after repeated inserts-before-the-current-first-item.
    """
    owner = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    venues = [
        await _create_venue(db_session, owner, name=f"Mekan {i}") for i in range(15)
    ]

    inserted_ids = []
    for venue in venues:
        item = await list_service.add_list_item(
            db_session, venue_list.id, current_user=owner, venue_id=venue.id
        )
        await list_service.move_list_item(
            db_session, venue_list.id, item.id, current_user=owner, after_item_id=None
        )
        inserted_ids.append(item.id)

    ordered = await list_service.list_items_for_list(
        db_session, venue_list.id, limit=20, offset=0
    )
    assert [item.id for item in ordered] == list(reversed(inserted_ids))


async def test_list_lists_for_user_excludes_close_friends_list_from_a_non_close_friend(
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
    await list_service.create_list(
        db_session, user_id=owner.id, title="Herkese açık", visibility=Visibility.PUBLIC
    )
    await list_service.create_list(
        db_session,
        user_id=owner.id,
        title="Yakın arkadaşlara özel",
        visibility=Visibility.CLOSE_FRIENDS,
    )

    as_close_friend = await list_service.list_lists_for_user(
        db_session, owner.id, viewer=close_friend_user, limit=20, offset=0
    )
    as_stranger = await list_service.list_lists_for_user(
        db_session, owner.id, viewer=stranger, limit=20, offset=0
    )

    assert len(as_close_friend) == 2
    assert len(as_stranger) == 1


async def test_list_lists_for_user_close_friend_isolation_across_owners(
    db_session: AsyncSession,
) -> None:
    """Being A's close friend must not grant visibility into B's
    close_friends content — the correlated EXISTS subquery
    (app.core.authz.close_friend_of_owner_exists) must be scoped to the
    row's own owner, not "is this viewer anyone's close friend".
    """
    owner_a = await _create_user(db_session)
    owner_b = await _create_user(db_session)
    close_friend_of_a = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=close_friend_of_a.id, following_id=owner_a.id
    )
    await close_friend_service.add_close_friend(
        db_session, user_id=owner_a.id, friend_id=close_friend_of_a.id
    )
    await list_service.create_list(
        db_session,
        user_id=owner_b.id,
        title="B'nin özel listesi",
        visibility=Visibility.CLOSE_FRIENDS,
    )

    b_lists_as_seen_by_a_close_friend = await list_service.list_lists_for_user(
        db_session, owner_b.id, viewer=close_friend_of_a, limit=20, offset=0
    )

    assert b_lists_as_seen_by_a_close_friend == []
