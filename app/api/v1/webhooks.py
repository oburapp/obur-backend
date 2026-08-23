"""Webhook endpoints. Clerk keeps `User` rows in sync via these — the
primary sync mechanism; `app.core.auth`'s JIT provisioning is only a
fallback for the race where a request arrives before a webhook does.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from app.core.config import get_settings
from app.core.database import get_session
from app.core.user_identity import default_display_name, fallback_username
from app.exceptions import InvalidWebhookSignatureError
from app.models.user import User
from app.schemas.webhook import ClerkUserData, ClerkWebhookEvent, WebhookAckResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
settings = get_settings()

_AUTH_PROVIDER = "clerk"
_USER_UPSERT_EVENTS = {"user.created", "user.updated"}


def _verify_signature(payload: bytes, headers: dict[str, str]) -> dict[str, object]:
    """Verify the Svix webhook signature, return the parsed JSON payload."""
    if not settings.clerk_webhook_secret:
        # Webhook(...) raises EmptyWebhookSecretError for this, a different
        # type than WebhookVerificationError — checked explicitly so it
        # maps to a clean 401 instead of an unhandled 500. Expected until
        # a real webhook is registered in the Clerk Dashboard (see
        # docs/roadmap.md Phase 1).
        raise InvalidWebhookSignatureError("CLERK_WEBHOOK_SECRET is not configured")

    try:
        return Webhook(settings.clerk_webhook_secret).verify(payload, headers)
    except WebhookVerificationError as e:
        raise InvalidWebhookSignatureError(str(e)) from e


async def _upsert_user(session: AsyncSession, data: ClerkUserData) -> None:
    """Create or update the `User` row matching this Clerk user.

    `username` and `display_name` are seeded on insert and then left
    alone: they are Obur-owned profile fields, edited through Obur's own
    profile endpoint (with a rate limit on the handle), so letting a
    later `user.updated` overwrite them would silently undo a change the
    user made here. Provider-owned fields — `email` and `avatar_url` —
    keep syncing on every event, which is the reason this webhook exists
    at all.
    """
    username = data.username or fallback_username(_AUTH_PROVIDER, data.id)
    stmt = pg_insert(User).values(
        auth_provider=_AUTH_PROVIDER,
        auth_provider_id=data.id,
        username=username,
        display_name=default_display_name(
            first_name=data.first_name,
            last_name=data.last_name,
            username=username,
        ),
        email=data.primary_email,
        avatar_url=data.image_url,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_user_auth_identity",
        set_={
            "email": stmt.excluded.email,
            "avatar_url": stmt.excluded.avatar_url,
        },
    )
    await session.execute(stmt)
    await session.commit()


async def _delete_user(session: AsyncSession, auth_provider_id: str) -> None:
    """Remove the `User` row for a deleted Clerk account.

    A plain delete is the whole purge: every table referencing `users.id`
    declares its own delete policy, so the database cascades personal
    content away and sets `VENUE.added_by` to `NULL` for venues the account
    added. Nothing to enumerate here, and nothing to keep in step as new
    user-owned tables appear.

    This is the one deliberate exception to "historical data is never
    deleted" (PDD §7): once someone asks to be forgotten, the data goes,
    not just its attribution.
    """
    await session.execute(
        delete(User).where(
            User.auth_provider == _AUTH_PROVIDER,
            User.auth_provider_id == auth_provider_id,
        )
    )
    await session.commit()


@router.post("/clerk")
async def handle_clerk_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookAckResponse:
    """Handle Clerk `user.created` / `user.updated` / `user.deleted` events.

    Other event types are acknowledged and ignored — Clerk may be
    configured to send more than this endpoint currently acts on.
    """
    body = await request.body()
    try:
        payload = _verify_signature(body, dict(request.headers))
    except InvalidWebhookSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        ) from e

    event = ClerkWebhookEvent.model_validate(payload)

    if event.type in _USER_UPSERT_EVENTS:
        await _upsert_user(session, event.data)
    elif event.type == "user.deleted":
        await _delete_user(session, event.data.id)

    return WebhookAckResponse(status="ok")
