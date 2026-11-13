"""RLS policy tests for `hashtags`, `checkin_hashtags`, `list_hashtags`,
and `checkin_mentions` (migration c33dcad29d14, ADR-0016 and ADR-0019 in
obur-docs), held to ADR-0016's five criteria:

1. Every test runs as the application role (`db_session`'s engine).
2. "Can see" and "cannot see" are asserted together.
3. Assertions use raw Core statements, never a service.
4. Parity: a query with no visibility filter of its own still sees only
   rows whose parent the caller can see.
5. Fail closed: with no identity, rows of non-public parents are hidden
   and nothing can be written.
"""

from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import Table, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import clear_current_user_identity, set_current_user_identity
from app.core.visibility import Visibility
from app.models.checkin_mention import CheckinMention
from app.models.hashtag import CheckinHashtag, Hashtag, ListHashtag
from app.services import list as list_service
from tests.integration.tagging_factories import (
    add_close_friend,
    befriend,
    create_user,
    create_venue,
    mentioning,
    post_checkin,
)

_mentions = cast(Table, CheckinMention.__table__)
_checkin_tags = cast(Table, CheckinHashtag.__table__)
_list_tags = cast(Table, ListHashtag.__table__)
_hashtags = cast(Table, Hashtag.__table__)


async def _visible(session: AsyncSession, table: Table, parent: str) -> set[UUID]:
    """Parent ids of every row in `table` the current identity can see,
    with no filter of the query's own (criterion 4).
    """
    return set((await session.execute(select(table.c[parent]))).scalars().all())


async def test_tag_and_mention_rows_follow_their_checkins_visibility(
    db_session: AsyncSession,
) -> None:
    """Criteria 2, 3, 4: a close-friends check-in's rows are visible to its
    author and a close friend, not to a stranger; a public one's to all.
    """
    author = await create_user(db_session)
    friend = await create_user(db_session)
    stranger = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, friend)
    await add_close_friend(db_session, author, friend)
    inner = await post_checkin(
        db_session,
        author,
        venue,
        note=mentioning(friend, text="#iç"),
        visibility=Visibility.CLOSE_FRIENDS,
    )
    public = await post_checkin(db_session, author, venue, note="#dış")

    for viewer, sees_inner in ((author, True), (friend, True), (stranger, False)):
        await set_current_user_identity(db_session, viewer.id)
        tags = await _visible(db_session, _checkin_tags, "checkin_id")
        mentions = await _visible(db_session, _mentions, "checkin_id")
        assert public.id in tags
        assert (inner.id in tags) is sees_inner
        assert (inner.id in mentions) is sees_inner


async def test_private_list_tags_are_visible_only_to_the_owner(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    hidden = await list_service.create_list(
        db_session,
        user_id=owner.id,
        title="Mine",
        description="#gizli",
        visibility=Visibility.PRIVATE,
    )
    stranger = await create_user(db_session)

    await set_current_user_identity(db_session, stranger.id)
    assert hidden.id not in await _visible(db_session, _list_tags, "list_id")
    await set_current_user_identity(db_session, owner.id)
    assert hidden.id in await _visible(db_session, _list_tags, "list_id")


async def test_no_identity_sees_only_public_parents(db_session: AsyncSession) -> None:
    """Criterion 5."""
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    private = await post_checkin(
        db_session, author, venue, note="#kapalı", visibility=Visibility.PRIVATE
    )
    public = await post_checkin(db_session, author, venue, note="#açık")

    await clear_current_user_identity(db_session)
    visible = await _visible(db_session, _checkin_tags, "checkin_id")

    assert public.id in visible
    assert private.id not in visible


async def test_a_stranger_cannot_add_a_mention_to_someone_elses_checkin(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    checkin = await post_checkin(db_session, author, venue)
    stranger = await create_user(db_session)

    await set_current_user_identity(db_session, stranger.id)
    with pytest.raises(ProgrammingError, match="row-level security"):
        await db_session.execute(
            _mentions.insert().values(
                checkin_id=checkin.id, mentioned_user_id=stranger.id
            )
        )


async def test_a_stranger_cannot_tag_someone_elses_checkin(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    checkin = await post_checkin(db_session, author, venue, note="#kahve")
    tag_id = await db_session.scalar(
        select(_hashtags.c.id).where(_hashtags.c.tag == "kahve")
    )
    stranger = await create_user(db_session)

    await set_current_user_identity(db_session, stranger.id)
    with pytest.raises(ProgrammingError, match="row-level security"):
        await db_session.execute(
            _checkin_tags.insert().values(checkin_id=checkin.id, hashtag_id=tag_id)
        )


async def test_a_stranger_cannot_delete_someone_elses_tag_or_mention(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    friend = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, friend)
    checkin = await post_checkin(
        db_session, author, venue, note=mentioning(friend, text="#kahve")
    )
    stranger = await create_user(db_session)

    await set_current_user_identity(db_session, stranger.id)
    tags = await db_session.execute(
        _checkin_tags.delete().where(_checkin_tags.c.checkin_id == checkin.id)
    )
    mentions = await db_session.execute(
        _mentions.delete().where(_mentions.c.checkin_id == checkin.id)
    )

    assert tags.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]
    assert mentions.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_anyone_reads_hashtags_but_only_a_signed_in_user_creates_one(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    venue = await create_venue(db_session, user)
    await post_checkin(db_session, user, venue, note="#herkese")

    await clear_current_user_identity(db_session)
    assert "herkese" in set(
        (await db_session.execute(select(_hashtags.c.tag))).scalars().all()
    )
    with pytest.raises(ProgrammingError, match="row-level security"):
        await db_session.execute(_hashtags.insert().values(tag="anonim"))
