"""Block domain: one user removing another entirely, in both directions
at once (see ADR-0010 in obur-docs, PDD §11).

Creating a block auto-unfollows in both directions and purges existing
likes, bookmarks, and notifications between the two people, also in
both directions, all in the one transaction the block itself commits
in. Follow removal is plain `session.delete()`, not
`app.services.follow.unfollow_user`: that function commits on its own,
which would split this into several transactions and risk a
half-finished block (unfollowed but not yet purged) if a later step
failed. The likes/bookmarks/notifications purge goes through
`rls_purge_interactions_between`, a narrow `SECURITY DEFINER` bypass
(migration 619903be1de5): `checkin_likes_delete`/`list_likes_delete`/
`checkin_bookmarks_delete`/`list_bookmarks_delete` are owner-only and
`notifications_delete` only ever authorized the recipient, so removing
the *other* party's row would fail under ordinary RLS.

Close-friend status needs no code here at all: `CLOSE_FRIEND`'s
foreign key already cascades off the exact `FOLLOW` row it depends on,
so deleting both follow directions clears it for free.
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BlockNotFoundError, SelfBlockError
from app.models.block import Block
from app.models.follow import Follow
from app.models.user import User


async def create_block(
    session: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID
) -> Block:
    """Make `blocker_id` block `blocked_id`. Idempotent: blocking
    someone already blocked just returns the existing relationship.

    Raises `SelfBlockError` if `blocker_id == blocked_id`.
    """
    if blocker_id == blocked_id:
        raise SelfBlockError("a user cannot block themselves")

    existing = await session.get(Block, (blocker_id, blocked_id))
    if existing is not None:
        return existing

    block = Block(blocker_id=blocker_id, blocked_id=blocked_id)
    session.add(block)

    for follower_id, following_id in (
        (blocker_id, blocked_id),
        (blocked_id, blocker_id),
    ):
        follow = await session.get(Follow, (follower_id, following_id))
        if follow is not None:
            await session.delete(follow)

    await session.execute(
        text("SELECT rls_purge_interactions_between(:user_a, :user_b)"),
        {"user_a": blocker_id, "user_b": blocked_id},
    )

    await session.commit()
    await session.refresh(block)
    return block


async def remove_block(
    session: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID
) -> None:
    """Undo a block. PDD §11 makes this the blocker's action alone, and
    `blocks_delete`'s own RLS policy (blocker-or-admin, not widened)
    already enforces that: this function trusts its caller to supply
    the acting identity as `blocker_id`, the same trust
    `app.services.follow.unfollow_user` places in its own `follower_id`.

    Raises `BlockNotFoundError` if the block doesn't exist. Unblocking
    restores nothing else, no earlier follow or close-friend status
    (PDD §11).
    """
    block = await session.get(Block, (blocker_id, blocked_id))
    if block is None:
        raise BlockNotFoundError(f"{blocker_id} has not blocked {blocked_id}")
    await session.delete(block)
    await session.commit()


async def list_blocked_users(
    session: AsyncSession, *, limit: int, offset: int
) -> list[User]:
    """List the users the *current session's own identity* has blocked.

    Deliberately takes no `blocker_id` parameter: it goes through
    `rls_list_blocked_users` (migration `f1d017015e34`), a `SECURITY
    DEFINER` bypass of `users_select` (fully symmetric, neither party
    can see the other's row, so an ordinary join here would return
    nothing for the very people this list exists to show). A real RLS
    bypass is only as safe as what decides whose blocklist comes back,
    so that decision is made by `rls_current_user_id()` inside the
    function itself, not by an argument this function would otherwise
    have to trust a caller to pass correctly.
    """
    stmt = select(User).from_statement(
        text(
            "SELECT * FROM rls_list_blocked_users("
            "CAST(:result_limit AS int), CAST(:result_offset AS int))"
        )
    )
    result = await session.execute(
        stmt, {"result_limit": limit, "result_offset": offset}
    )
    return list(result.scalars().all())
