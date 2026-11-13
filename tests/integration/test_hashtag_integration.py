"""Integration tests for hashtags (ADR-0019 in obur-docs) against the real
database: linking from text, case-insensitive matching, and what a
hashtag page shows.
"""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import TooManyHashtagsError
from app.models.checkin import Checkin
from app.models.hashtag import Hashtag
from app.models.user import User
from app.services import block as block_service
from app.services import checkin as checkin_service
from app.services import hashtag as hashtag_service
from app.services import list as list_service
from app.services import mute as mute_service
from tests.integration.tagging_factories import create_user, create_venue, post_checkin

_PAGE = {"limit": 20, "offset": 0}


async def _page(
    session: AsyncSession, tag: str, viewer: User | None = None
) -> list[UUID]:
    checkins = await hashtag_service.list_checkins_for_hashtag(
        session, tag, viewer=viewer, **_PAGE
    )
    return [checkin.id for checkin in checkins]


async def _hashtag_rows(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Hashtag)) or 0


async def test_different_casings_share_one_tag_and_one_page(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    before = await _hashtag_rows(db_session)
    first = await post_checkin(db_session, author, venue, note="great #Kahve")
    second = await post_checkin(db_session, author, venue, note="more #KAHVE!")

    assert await _hashtag_rows(db_session) == before + 1
    assert set(await _page(db_session, "kahve")) == {first.id, second.id}


async def test_dotted_capital_i_matches_its_lowercase(db_session: AsyncSession) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    checkin = await post_checkin(db_session, author, venue, note="#İstanbulKahvesi")

    assert await _page(db_session, "istanbulkahvesi") == [checkin.id]


async def test_the_note_keeps_the_tag_as_typed(db_session: AsyncSession) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)

    checkin = await post_checkin(db_session, author, venue, note="#AnadoluMutfağı")

    assert checkin.note == "#AnadoluMutfağı"


async def test_editing_the_note_relinks_its_tags(db_session: AsyncSession) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    checkin = await post_checkin(db_session, author, venue, note="#brunch #kahve")

    await checkin_service.update_checkin(
        db_session, checkin.id, current_user=author, updates={"note": "#kahve #tatlı"}
    )

    assert await _page(db_session, "brunch") == []
    assert await _page(db_session, "kahve") == [checkin.id]
    assert await _page(db_session, "tatlı") == [checkin.id]


async def test_too_many_tags_rejects_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    count = await db_session.scalar(select(func.count()).select_from(Checkin))

    with pytest.raises(TooManyHashtagsError):
        await post_checkin(db_session, author, venue, note="#a1 #b2 #c3 #d4 #e5 #f6")

    assert await db_session.scalar(select(func.count()).select_from(Checkin)) == count


@pytest.mark.parametrize("visibility", [Visibility.PRIVATE, Visibility.CLOSE_FRIENDS])
async def test_the_page_shows_only_public_checkins(
    db_session: AsyncSession, visibility: str
) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await post_checkin(db_session, author, venue, note="#gizli", visibility=visibility)

    assert await _page(db_session, "gizli") == []


async def test_the_page_skips_deleted_checkins(db_session: AsyncSession) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    checkin = await post_checkin(db_session, author, venue, note="#silindi")
    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=author
    )

    assert await _page(db_session, "silindi") == []


async def test_the_page_hides_blocked_content_but_shows_muted(
    db_session: AsyncSession,
) -> None:
    viewer = await create_user(db_session)
    blocked = await create_user(db_session)
    muted = await create_user(db_session)
    venue = await create_venue(db_session, viewer)
    from_blocked = await post_checkin(db_session, blocked, venue, note="#ortak")
    from_muted = await post_checkin(db_session, muted, venue, note="#ortak")
    await set_current_user_identity(db_session, viewer.id)
    await block_service.create_block(
        db_session, blocker_id=viewer.id, blocked_id=blocked.id
    )
    await mute_service.create_mute(db_session, user_id=viewer.id, muted_id=muted.id)

    page = await _page(db_session, "ortak", viewer=viewer)

    assert from_muted.id in page
    assert from_blocked.id not in page


async def test_list_descriptions_are_tagged_and_paged(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    public = await list_service.create_list(
        db_session, user_id=owner.id, title="Best", description="my #Kahve spots"
    )
    await list_service.create_list(
        db_session,
        user_id=owner.id,
        title="Mine",
        description="#kahve",
        visibility=Visibility.PRIVATE,
    )

    lists = await hashtag_service.list_lists_for_hashtag(
        db_session, "KAHVE", viewer=None, **_PAGE
    )

    assert [found.id for found in lists] == [public.id]


async def test_editing_a_list_description_relinks_its_tags(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Best", description="#old"
    )

    await list_service.update_list(
        db_session,
        venue_list.id,
        current_user=owner,
        updates={"description": "#new"},
    )

    old = await hashtag_service.list_lists_for_hashtag(
        db_session, "old", viewer=None, **_PAGE
    )
    new = await hashtag_service.list_lists_for_hashtag(
        db_session, "new", viewer=None, **_PAGE
    )
    assert old == []
    assert [found.id for found in new] == [venue_list.id]
