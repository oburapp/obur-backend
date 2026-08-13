"""USER model."""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.i18n import DEFAULT_LOCALE
from app.models.base import Base


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
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    auth_provider: Mapped[str] = mapped_column(String, nullable=False)
    auth_provider_id: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    locale: Mapped[str] = mapped_column(
        String, nullable=False, server_default=DEFAULT_LOCALE
    )
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
