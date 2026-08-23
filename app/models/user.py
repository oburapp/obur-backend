"""USER model."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.i18n import DEFAULT_LOCALE
from app.models.base import Base


class UserRole:
    """Allowed values for `User.role`.

    A plain string, not a boolean `is_admin` — adding a tier later (e.g.
    a moderator role) is a new allowed value, not a schema change. Never
    settable through any user-facing endpoint or the Clerk webhook — see
    `app.core.authz`.
    """

    USER = "user"
    ADMIN = "admin"


class UserStatus:
    """Allowed values for `User.status` — standing, not permission.

    Deliberately separate from `User.role`: `role` is what a user is
    allowed to do, `status` is where their account stands. Conflating
    them would make "suspended admin" unrepresentable.

    `FROZEN` is self-service and reversible — the user freezes their own
    account and reactivates it just by signing back in. `SUSPENDED` is
    admin-only, set by resolving a report, and never user-reversible.
    Neither value is reachable by the other actor.
    """

    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"


_DEFAULT_USER_ROLE = UserRole.USER
_DEFAULT_USER_STATUS = UserStatus.ACTIVE
_ALLOWED_USER_STATUSES = (
    UserStatus.ACTIVE,
    UserStatus.FROZEN,
    UserStatus.SUSPENDED,
)


class User(Base):
    """A registered Obur user, identity-linked to an external auth provider.

    `auth_provider` / `auth_provider_id` are deliberately not named after
    Clerk specifically — see docs/roadmap.md Phase 1 and the PDD's
    "Auth identity is provider-agnostic by field name" design decision.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "auth_provider", "auth_provider_id", name="uq_user_auth_identity"
        ),
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_USER_STATUSES)
            + ")",
            name="ck_users_status_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    auth_provider: Mapped[str] = mapped_column(String, nullable=False)
    auth_provider_id: Mapped[str] = mapped_column(String, nullable=False)
    # Shown everywhere and freely editable, with deliberately no
    # uniqueness constraint — two people may share a display name, the
    # same split Instagram draws between a name and a handle. What makes
    # an account addressable is `username` below.
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    # The handle: unique, and what search, mentions, and profile URLs key
    # off of. Edits are rate-limited (unlike display_name), since an
    # unrestricted handle is an impersonation vector in a way a display
    # name isn't. Seeded from the auth provider or generated — see
    # app.core.user_identity.
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # When the handle was last changed, or NULL if it never has been. Drives
    # the rate limit in app.services.user — kept on the row rather than in
    # Redis because the window spans weeks, and a cache flush must not hand
    # someone a fresh allowance.
    username_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    locale: Mapped[str] = mapped_column(
        String, nullable=False, server_default=DEFAULT_LOCALE
    )
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_USER_ROLE
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_USER_STATUS
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
