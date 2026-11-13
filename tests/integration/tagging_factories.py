"""Shared setup for the mention and hashtag integration tests
(ADR-0019 in obur-docs): users, a venue, mutual follows, close friends,
and check-ins created through the real service so mention and hashtag
handling runs exactly as it does for a request.

Every helper leaves the session's identity set to the user who acted
last, the same way a request would, so RLS sees what it would see live.
"""

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.text_tokens import mention_token
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_TZ = "Europe/Istanbul"


async def create_user(session: AsyncSession, *, username: str | None = None) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=username or f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    session.add(user)
    await session.flush()
    await set_current_user_identity(session, user.id)
    return user


async def create_venue(session: AsyncSession, added_by: User) -> Venue:
    await set_current_user_identity(session, added_by.id)
    venue = Venue(
        name="Karaköy Lokantası",
        lat=41.0226,
        lng=28.9770,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def follow(session: AsyncSession, follower: User, following: User) -> None:
    await set_current_user_identity(session, follower.id)
    await follow_service.follow_user(
        session, follower_id=follower.id, following_id=following.id
    )


async def befriend(session: AsyncSession, a: User, b: User) -> None:
    """Make `a` and `b` mutual followers."""
    await follow(session, a, b)
    await follow(session, b, a)


async def add_close_friend(session: AsyncSession, owner: User, friend: User) -> None:
    await set_current_user_identity(session, owner.id)
    await close_friend_service.add_close_friend(
        session, user_id=owner.id, friend_id=friend.id
    )


async def post_checkin(
    session: AsyncSession,
    author: User,
    venue: Venue,
    *,
    note: str | None = None,
    visibility: str = Visibility.PUBLIC,
) -> Checkin:
    await set_current_user_identity(session, author.id)
    return await checkin_service.create_checkin(
        session,
        user_id=author.id,
        idempotency_key=uuid4(),
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        note=note,
        visibility=visibility,
    )


def mentioning(*users: User, text: str = "lunch with") -> str:
    """A note mentioning `users` the way a client writes it."""
    return " ".join([text, *(mention_token(user.id) for user in users)])


def ids(users: list[User]) -> set[UUID]:
    return {user.id for user in users}
