"""User domain: profile edits, account freeze/reactivate, and deletion.

`display_name`, `bio`, `avatar_url`, `city`, `locale`, and `timezone` are
freely editable. `username` is the exception — it is the handle search,
mentions, and profile URLs key off of, so changing it is rate-limited
(PDD §6, §7). `email` and `avatar_url` also arrive from the auth provider's
webhook; the profile edit here wins for `avatar_url` until the provider
sends its next update, which is accepted as the cost of letting a user
change it at all.

Deletion is permanent and total — the one deliberate exception to
"historical data is never deleted" (PDD §7). It is implemented as a plain
`DELETE` of the `users` row: every table referencing `users.id` declares its
own delete policy (see the models), so the database performs the purge and
there is no list of tables here to fall out of date. A venue the account
added survives with `added_by` set to `NULL`, since a venue is a shared
resource rather than personal content.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    AccountNotFrozenError,
    UsernameChangedTooRecentlyError,
    UsernameTakenError,
    UserNotFoundError,
)
from app.models.user import User, UserStatus

# How long a user must wait between handle changes. A starting point, not a
# researched number: it exists to make impersonation-by-handle-churn costly,
# and is the kind of threshold the PDD expects to calibrate once there is
# real usage (§18). One place to change it.
USERNAME_CHANGE_INTERVAL_DAYS = 30

# Fields a user may change about themselves. `username` is handled
# separately because it alone is rate-limited and uniqueness-checked;
# `role` and `status` are absent on purpose — neither is ever settable
# through a user-facing endpoint (PDD §7, §11).
_EDITABLE_FIELDS = frozenset(
    {"display_name", "bio", "avatar_url", "city", "country_code", "locale", "timezone"}
)


def _next_username_change_allowed_at(changed_at: datetime) -> datetime:
    """When the handle may next be changed, given its last change."""
    return changed_at + timedelta(days=USERNAME_CHANGE_INTERVAL_DAYS)


async def _ensure_username_available(
    session: AsyncSession, *, username: str, current_user_id: uuid.UUID
) -> None:
    """Reject a handle that already belongs to somebody else.

    The unique constraint is the real guarantee — this check exists so the
    caller gets a clear error instead of an integrity violation, and it
    deliberately doesn't treat the user's own current handle as taken.
    """
    result = await session.execute(
        select(User.id).where(User.username == username, User.id != current_user_id)
    )
    if result.scalar_one_or_none() is not None:
        raise UsernameTakenError(f"username already taken: {username}")


async def update_profile(
    session: AsyncSession,
    *,
    user: User,
    changes: dict[str, object],
    now: datetime | None = None,
) -> User:
    """Apply `changes` to `user`'s own profile and return the updated row.

    Only fields present in `changes` are touched, so a partial update never
    clears anything it didn't mention. Unknown or non-editable keys are
    ignored rather than rejected — the request schema is what defines the
    editable surface, and this is the second line of defence.

    Raises `UsernameTakenError` if the requested handle belongs to someone
    else, and `UsernameChangedTooRecentlyError` if the last change was
    inside the rate-limit window.
    """
    now = now or datetime.now(UTC)
    new_username = changes.get("username")

    if isinstance(new_username, str) and new_username != user.username:
        if user.username_changed_at is not None:
            allowed_at = _next_username_change_allowed_at(user.username_changed_at)
            if now < allowed_at:
                raise UsernameChangedTooRecentlyError(allowed_at)
        await _ensure_username_available(
            session, username=new_username, current_user_id=user.id
        )
        user.username = new_username
        user.username_changed_at = now

    for field, value in changes.items():
        if field in _EDITABLE_FIELDS:
            setattr(user, field, value)

    await session.commit()
    await session.refresh(user)
    return user


async def freeze_account(session: AsyncSession, *, user: User) -> User:
    """Freeze the user's own account — self-service and reversible.

    Idempotent: freezing an already-frozen account changes nothing. A
    suspended account is left alone; suspension is an admin action and a
    user must not be able to convert it into something they can undo.
    """
    if user.status == UserStatus.ACTIVE:
        user.status = UserStatus.FROZEN
        await session.commit()
        await session.refresh(user)
    return user


async def reactivate_account(session: AsyncSession, *, user: User) -> User:
    """Reactivate a frozen account. Called when the user signs back in —
    logging in *is* the reactivation gesture (PDD §6).

    Raises `AccountNotFrozenError` for a suspended account, which is
    admin-only and never user-reversible.
    """
    if user.status == UserStatus.ACTIVE:
        return user
    if user.status != UserStatus.FROZEN:
        raise AccountNotFrozenError(f"account is {user.status}, not frozen")

    user.status = UserStatus.ACTIVE
    await session.commit()
    await session.refresh(user)
    return user


async def suspend_account(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Suspend an account. Admin-only (see `app.core.authz.require_admin`
    on the route this backs) and never user-reversible, the one status
    `reactivate_account` explicitly refuses to undo (PDD §6, §11).
    Idempotent.

    Raises `UserNotFoundError` if `user_id` doesn't exist.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"user not found: {user_id}")
    if user.status != UserStatus.SUSPENDED:
        user.status = UserStatus.SUSPENDED
        await session.commit()
        await session.refresh(user)
    return user


async def delete_account(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Permanently delete an account and everything personal to it.

    The cascade is declared on the foreign keys themselves rather than
    enumerated here, so this can't drift out of step with the schema as new
    user-owned tables are added — a new table simply declares its own
    policy and is covered automatically.
    """
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
