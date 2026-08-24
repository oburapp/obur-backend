"""Schemas for the venue category catalog."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.services.venue_category import CategoryNode


class VenueCategoryResponse(BaseModel):
    """One category, its resolved display name, and its children.

    `slug` is the stable identifier to key logic off; `name` is already
    localized for the request and is display text only.
    """

    id: UUID
    slug: str
    name: str
    children: list[VenueCategoryResponse]

    @classmethod
    def from_node(cls, node: CategoryNode) -> VenueCategoryResponse:
        return cls(
            id=node.id,
            slug=node.slug,
            name=node.name,
            children=[cls.from_node(child) for child in node.children],
        )
