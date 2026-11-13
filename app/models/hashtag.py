"""HASHTAG, CHECKIN_HASHTAG, and LIST_HASHTAG models (ADR-0019 in
obur-docs).

`Hashtag.tag` is the case-insensitive match key from
`app.core.text_tokens.hashtag_key`, shared by everyone who uses the tag
and shown as its page heading. Inside a check-in or list a tag appears as
its author typed it, since it is part of their text. The link tables are
derived from that text on every create and edit, at most five per item.
A tag no longer linked to anything is kept: a harmless catalog row.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Hashtag(Base):
    """One tag, identified by its match key."""

    __tablename__ = "hashtags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tag: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CheckinHashtag(Base):
    """`checkin_id`'s note carries `hashtag_id`."""

    __tablename__ = "checkin_hashtags"

    checkin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checkins.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Its own index: the hashtag page looks rows up by tag, the opposite
    # direction from the primary key's leading column.
    hashtag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hashtags.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )


class ListHashtag(Base):
    """`list_id`'s description carries `hashtag_id`."""

    __tablename__ = "list_hashtags"

    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hashtag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hashtags.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
