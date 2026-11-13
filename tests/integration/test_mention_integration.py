"""Integration tests for mentions (ADR-0019 in obur-docs) against the real
database: who can be mentioned, what an edit does, and every way a
mention stops being valid while its text stays.
"""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import MentionNotAllowedError, TooManyMentionsError
from app.models.checkin import Checkin
from app.models.checkin_mention import CheckinMention
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserStatus
from app.services import block as block_service
from app.services import checkin as checkin_service
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service
from app.services import mention as mention_service
from app.services.mention import mention_views
from tests.integration.tagging_factories import (
    add_close_friend,
    befriend,
    create_user,
    create_venue,
    follow,
    ids,
    mentioning,
    post_checkin,
)

_MENTION_LIMIT = 10


async def _active(session: AsyncSession, checkin: Checkin) -> set[UUID]:
    await set_current_user_identity(session, checkin.user_id)
    result = await session.execute(
        select(CheckinMention.mentioned_user_id).where(
            CheckinMention.checkin_id == checkin.id
        )
    )
    return set(result.scalars().all())


async def _mention_notifications(session: AsyncSession, user: User) -> int:
    await set_current_user_identity(session, user.id)
    result = await session.execute(
        select(Notification.id).where(
            Notification.user_id == user.id,
            Notification.type == NotificationType.MENTION,
        )
    )
    return len(result.scalars().all())


async def _edit(
    session: AsyncSession, checkin: Checkin, author: User, **updates: object
) -> Checkin:
    await set_current_user_identity(session, author.id)
    return await checkin_service.update_checkin(
        session, checkin.id, current_user=author, updates=updates
    )


async def test_a_mutual_follower_is_mentioned_and_notified(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    friend = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, friend)

    checkin = await post_checkin(db_session, author, venue, note=mentioning(friend))

    assert await _active(db_session, checkin) == {friend.id}
    assert await _mention_notifications(db_session, friend) == 1


async def test_a_one_way_follower_cannot_be_mentioned(db_session: AsyncSession) -> None:
    author = await create_user(db_session)
    fan = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await follow(db_session, fan, author)

    with pytest.raises(MentionNotAllowedError):
        await post_checkin(db_session, author, venue, note=mentioning(fan))


@pytest.mark.parametrize(
    ("visibility", "close_friend", "allowed"),
    [
        (Visibility.CLOSE_FRIENDS, True, True),
        (Visibility.CLOSE_FRIENDS, False, False),
        (Visibility.PRIVATE, True, False),
    ],
)
async def test_only_people_who_can_see_the_checkin_can_be_mentioned(
    db_session: AsyncSession, visibility: str, close_friend: bool, allowed: bool
) -> None:
    author = await create_user(db_session)
    friend = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, friend)
    if close_friend:
        await add_close_friend(db_session, author, friend)

    if allowed:
        checkin = await post_checkin(
            db_session, author, venue, note=mentioning(friend), visibility=visibility
        )
        assert await _active(db_session, checkin) == {friend.id}
    else:
        with pytest.raises(MentionNotAllowedError):
            await post_checkin(
                db_session,
                author,
                venue,
                note=mentioning(friend),
                visibility=visibility,
            )


async def test_more_than_the_limit_of_mentions_is_rejected(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    venue = await create_venue(db_session, author)
    crowd = [await create_user(db_session) for _ in range(_MENTION_LIMIT + 1)]

    with pytest.raises(TooManyMentionsError):
        await post_checkin(db_session, author, venue, note=mentioning(*crowd))


async def test_an_edit_notifies_only_newly_added_people(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    ali, ayse = await create_user(db_session), await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    await befriend(db_session, author, ayse)
    checkin = await post_checkin(db_session, author, venue, note=mentioning(ali))

    await _edit(db_session, checkin, author, note=mentioning(ali, ayse))

    assert await _active(db_session, checkin) == ids([ali, ayse])
    assert await _mention_notifications(db_session, ali) == 1
    assert await _mention_notifications(db_session, ayse) == 1


async def test_removing_someone_drops_the_mention_and_readding_notifies_again(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    ali = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    checkin = await post_checkin(db_session, author, venue, note=mentioning(ali))

    await _edit(db_session, checkin, author, note="lunch alone")
    assert await _active(db_session, checkin) == set()
    await _edit(db_session, checkin, author, note=mentioning(ali))

    assert await _active(db_session, checkin) == {ali.id}
    assert await _mention_notifications(db_session, ali) == 2


async def test_making_a_checkin_private_removes_mentions_but_keeps_the_text(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    ali = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    note = mentioning(ali)
    checkin = await post_checkin(db_session, author, venue, note=note)

    edited = await _edit(db_session, checkin, author, visibility=Visibility.PRIVATE)

    assert await _active(db_session, checkin) == set()
    assert edited.note == note
    views = await mention_views(db_session, [edited])
    assert [(v.user_id, v.username) for v in views[edited.id]] == [(ali.id, None)]


async def test_unfollowing_alone_keeps_a_mention_on_a_public_checkin(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    ali = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    checkin = await post_checkin(db_session, author, venue, note=mentioning(ali))

    await set_current_user_identity(db_session, ali.id)
    await follow_service.unfollow_user(
        db_session, follower_id=ali.id, following_id=author.id
    )
    await _edit(db_session, checkin, author, note=mentioning(ali, text="edited"))

    assert await _active(db_session, checkin) == {ali.id}


async def test_a_dormant_mention_never_blocks_an_edit_and_returns_when_eligible(
    db_session: AsyncSession,
) -> None:
    """The scenario ADR-0019 walks through: block, edit, unblock, follow
    again, edit again.
    """
    author = await create_user(db_session)
    ali = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    checkin = await post_checkin(db_session, author, venue, note=mentioning(ali))
    await set_current_user_identity(db_session, author.id)
    await block_service.create_block(
        db_session, blocker_id=author.id, blocked_id=ali.id
    )
    assert await _active(db_session, checkin) == set()

    await _edit(db_session, checkin, author, note=mentioning(ali, text="typo fixed"))
    assert await _active(db_session, checkin) == set()

    await set_current_user_identity(db_session, author.id)
    await block_service.remove_block(
        db_session, blocker_id=author.id, blocked_id=ali.id
    )
    await befriend(db_session, author, ali)
    await _edit(db_session, checkin, author, note=mentioning(ali, text="again"))

    assert await _active(db_session, checkin) == {ali.id}
    # The block purged the original notification, and a restored mention
    # deliberately doesn't send a second one.
    assert await _mention_notifications(db_session, ali) == 0


@pytest.mark.parametrize("how", ["removed", "unfollowed", "follower_removed"])
async def test_leaving_close_friends_removes_mentions_on_close_friends_checkins(
    db_session: AsyncSession, how: str
) -> None:
    """The trigger, for each of the three ways the row disappears."""
    author = await create_user(db_session)
    ali = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    await add_close_friend(db_session, author, ali)
    inner = await post_checkin(
        db_session,
        author,
        venue,
        note=mentioning(ali),
        visibility=Visibility.CLOSE_FRIENDS,
    )
    public = await post_checkin(db_session, author, venue, note=mentioning(ali))

    if how == "removed":
        await set_current_user_identity(db_session, author.id)
        await close_friend_service.remove_close_friend(
            db_session, user_id=author.id, friend_id=ali.id
        )
    elif how == "unfollowed":
        await set_current_user_identity(db_session, ali.id)
        await follow_service.unfollow_user(
            db_session, follower_id=ali.id, following_id=author.id
        )
    else:
        await set_current_user_identity(db_session, author.id)
        await follow_service.remove_follower(
            db_session, user_id=author.id, follower_id=ali.id
        )

    assert await _active(db_session, inner) == set()
    assert await _active(db_session, public) == {ali.id}


async def test_a_block_removes_mentions_in_both_directions(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    ali = await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    by_author = await post_checkin(db_session, author, venue, note=mentioning(ali))
    by_ali = await post_checkin(db_session, ali, venue, note=mentioning(author))

    await set_current_user_identity(db_session, ali.id)
    await block_service.create_block(
        db_session, blocker_id=ali.id, blocked_id=author.id
    )

    assert await _active(db_session, by_author) == set()
    assert await _active(db_session, by_ali) == set()


async def test_views_follow_a_username_change_and_hide_a_frozen_account(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    ali, ayse = await create_user(db_session), await create_user(db_session)
    venue = await create_venue(db_session, author)
    await befriend(db_session, author, ali)
    await befriend(db_session, author, ayse)
    checkin = await post_checkin(db_session, author, venue, note=mentioning(ali, ayse))

    await set_current_user_identity(db_session, ali.id)
    ali.username = "ali_renamed"
    await db_session.flush()
    await set_current_user_identity(db_session, ayse.id)
    ayse.status = UserStatus.FROZEN
    await db_session.flush()
    views = await mention_views(db_session, [checkin])

    assert [(v.user_id, v.username) for v in views[checkin.id]] == [
        (ali.id, "ali_renamed"),
        (ayse.id, None),
    ]


async def test_mentionable_users_are_eligible_people_matching_the_prefix(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    eren = await create_user(db_session, username="eren_m")
    erkan = await create_user(db_session, username="erkan")
    fan = await create_user(db_session, username="erol")
    await befriend(db_session, author, eren)
    await befriend(db_session, author, erkan)
    await add_close_friend(db_session, author, eren)
    await follow(db_session, fan, author)

    # A real request runs as the author, whose close friends list RLS
    # shows only to them and the friends on it.
    await set_current_user_identity(db_session, author.id)

    async def mentionable(visibility: str) -> list[UUID]:
        users = await mention_service.list_mentionable_users(
            db_session,
            author_id=author.id,
            visibility=visibility,
            username_prefix="ER",
            limit=20,
            offset=0,
        )
        return [user.id for user in users]

    assert await mentionable(Visibility.PUBLIC) == [eren.id, erkan.id]
    assert await mentionable(Visibility.CLOSE_FRIENDS) == [eren.id]
    assert await mentionable(Visibility.PRIVATE) == []
