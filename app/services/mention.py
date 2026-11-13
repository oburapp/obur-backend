"""Mention domain (ADR-0019 in obur-docs): who can be mentioned, keeping
`checkin_mentions` in step with a note's `@[<user_id>]` tokens, and
resolving tokens to current usernames for responses.

Two eligibility rules, deliberately different:

- **To be newly mentioned** a person must be a mutual follower of the
  author *and* able to see the check-in (any mutual follower for
  `public`, one on the author's close friends list for `close_friends`,
  nobody for `private`).
- **To keep an existing mention** only the "can see" half is re-checked.
  Unfollowing alone doesn't remove a mention on a `public` check-in.

A token already in the previous note is never a reason to reject an edit.
If its mention was removed earlier, the edit restores it silently when
the person is eligible again, and leaves it as a placeholder otherwise.

Close-friend removal is enforced separately, by a database trigger on
`close_friends` (migration for ADR-0019), because two of the three ways
that row disappears are foreign-key cascades this code never sees.
"""

import uuid
from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_tokens import parse_mention_ids
from app.core.visibility import Visibility
from app.exceptions import MentionNotAllowedError
from app.models.checkin import Checkin
from app.models.checkin_mention import CheckinMention
from app.models.close_friend import CloseFriend
from app.models.follow import Follow
from app.models.notification import NotificationTargetType, NotificationType
from app.models.user import User, UserStatus
from app.services.notification import create_notification


class MentionPlan(BaseModel):
    """What applying a note's mentions will write, worked out before the
    check-in itself is written so an invalid mention rejects the request
    without leaving anything behind.
    """

    keep: list[uuid.UUID]
    insert: list[uuid.UUID]
    notify: list[uuid.UUID]


class MentionView(BaseModel):
    """One token in a note as a response shows it. `username` is None when
    the mention is no longer active; clients show a placeholder.
    """

    user_id: uuid.UUID
    username: str | None


def _mutual_follow(author_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(
        exists().where(Follow.follower_id == author_id, Follow.following_id == User.id),
        exists().where(Follow.follower_id == User.id, Follow.following_id == author_id),
    )


def _can_see(author_id: uuid.UUID, visibility: str) -> ColumnElement[bool]:
    if visibility == Visibility.CLOSE_FRIENDS:
        return exists().where(
            CloseFriend.user_id == author_id, CloseFriend.friend_id == User.id
        )
    return User.id.is_not(None)


async def eligible_user_ids(
    session: AsyncSession,
    *,
    author_id: uuid.UUID,
    candidate_ids: Sequence[uuid.UUID],
    visibility: str,
    require_mutual_follow: bool,
) -> set[uuid.UUID]:
    """The subset of `candidate_ids` that may be mentioned in (or keep a
    mention on) a check-in by `author_id` with `visibility`.
    """
    if not candidate_ids or visibility == Visibility.PRIVATE:
        return set()
    conditions = [
        User.id.in_(candidate_ids),
        User.status == UserStatus.ACTIVE,
        _can_see(author_id, visibility),
    ]
    if require_mutual_follow:
        conditions.append(_mutual_follow(author_id))
    result = await session.execute(select(User.id).where(*conditions))
    return set(result.scalars().all())


async def _active_mention_ids(
    session: AsyncSession, checkin_id: uuid.UUID
) -> set[uuid.UUID]:
    result = await session.execute(
        select(CheckinMention.mentioned_user_id).where(
            CheckinMention.checkin_id == checkin_id
        )
    )
    return set(result.scalars().all())


def _classify_tokens(
    new_ids: list[uuid.UUID],
    previous_ids: set[uuid.UUID],
    active_ids: set[uuid.UUID] | None,
) -> tuple[list[uuid.UUID], list[uuid.UUID], list[uuid.UUID]]:
    """Split a note's tokens into newly added ones, dormant ones (already
    in the previous note, mention removed since), and kept active ones.
    """
    active = active_ids or set()
    added = [uid for uid in new_ids if uid not in previous_ids]
    dormant = [uid for uid in new_ids if uid in previous_ids and uid not in active]
    kept = [uid for uid in new_ids if uid in active]
    return added, dormant, kept


async def plan_mentions(
    session: AsyncSession,
    *,
    author_id: uuid.UUID,
    visibility: str,
    new_note: str | None,
    old_note: str | None = None,
    active_ids: set[uuid.UUID] | None = None,
) -> MentionPlan:
    """Work out a note's mentions for a create (`old_note` None) or an
    edit.

    Raises `TooManyMentionsError` per app.core.text_tokens.
    Raises `MentionNotAllowedError` if a newly added person isn't eligible.
    """
    added, dormant, kept = _classify_tokens(
        parse_mention_ids(new_note), set(parse_mention_ids(old_note)), active_ids
    )
    eligible = await eligible_user_ids(
        session,
        author_id=author_id,
        candidate_ids=added + dormant,
        visibility=visibility,
        require_mutual_follow=True,
    )
    if any(user_id not in eligible for user_id in added):
        raise MentionNotAllowedError("a newly mentioned person isn't eligible")
    still_visible = await eligible_user_ids(
        session,
        author_id=author_id,
        candidate_ids=kept,
        visibility=visibility,
        require_mutual_follow=False,
    )
    return MentionPlan(
        keep=[uid for uid in kept if uid in still_visible],
        insert=[uid for uid in added + dormant if uid in eligible],
        notify=added,
    )


async def plan_checkin_edit(
    session: AsyncSession, checkin: Checkin, *, new_note: str | None, visibility: str
) -> MentionPlan:
    """`plan_mentions` for an edit of an existing check-in."""
    return await plan_mentions(
        session,
        author_id=checkin.user_id,
        visibility=visibility,
        new_note=new_note,
        old_note=checkin.note,
        active_ids=await _active_mention_ids(session, checkin.id),
    )


async def apply_mentions(
    session: AsyncSession,
    *,
    checkin_id: uuid.UUID,
    author_id: uuid.UUID,
    plan: MentionPlan,
) -> None:
    """Write a plan inside the caller's transaction: drop rows the note no
    longer supports, add new and restored ones, notify newly added people.
    """
    await session.execute(
        delete(CheckinMention).where(
            CheckinMention.checkin_id == checkin_id,
            CheckinMention.mentioned_user_id.not_in(plan.keep),
        )
    )
    if plan.insert:
        await session.execute(
            insert(CheckinMention)
            .values(
                [
                    {"checkin_id": checkin_id, "mentioned_user_id": user_id}
                    for user_id in plan.insert
                ]
            )
            .on_conflict_do_nothing()
        )
    for user_id in plan.notify:
        await create_notification(
            session,
            user_id=user_id,
            type=NotificationType.MENTION,
            actor_id=author_id,
            target_type=NotificationTargetType.CHECKIN,
            target_id=checkin_id,
        )


async def mention_views(
    session: AsyncSession, checkins: Sequence[Checkin]
) -> dict[uuid.UUID, list[MentionView]]:
    """Resolve every token in `checkins`' notes in one query: the current
    username for an active mention of a visible account, None otherwise.
    """
    ids = [checkin.id for checkin in checkins]
    result = await session.execute(
        select(CheckinMention.checkin_id, User.id, User.username)
        .join(User, User.id == CheckinMention.mentioned_user_id)
        .where(CheckinMention.checkin_id.in_(ids), User.status == UserStatus.ACTIVE)
    )
    active = {(row.checkin_id, row.id): row.username for row in result}
    return {
        checkin.id: [
            MentionView(user_id=uid, username=active.get((checkin.id, uid)))
            for uid in parse_mention_ids(checkin.note)
        ]
        for checkin in checkins
    }


async def list_mentionable_users(
    session: AsyncSession,
    *,
    author_id: uuid.UUID,
    visibility: str,
    username_prefix: str,
    limit: int,
    offset: int,
) -> list[User]:
    """The people `author_id` may newly mention in a check-in with
    `visibility`, for the `@` dropdown, filtered by username prefix.
    """
    if visibility == Visibility.PRIVATE:
        return []
    result = await session.execute(
        select(User)
        .where(
            User.status == UserStatus.ACTIVE,
            User.username.istartswith(username_prefix, autoescape=True),
            _mutual_follow(author_id),
            _can_see(author_id, visibility),
        )
        .order_by(User.username)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
