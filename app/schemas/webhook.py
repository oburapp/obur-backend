"""Schemas for incoming Clerk webhook payloads.

Field names match Clerk's own User object exactly (`id`, `email_addresses`,
`image_url`, ...) — this is the one schema module allowed to look
Clerk-shaped, since it exists specifically to parse what Clerk sends.
"""

from pydantic import BaseModel


class ClerkEmailAddress(BaseModel):
    """One entry in a Clerk user's `email_addresses` list."""

    id: str
    email_address: str


class ClerkUserData(BaseModel):
    """The `data` payload of a Clerk `user.*` webhook event."""

    id: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email_addresses: list[ClerkEmailAddress] = []
    primary_email_address_id: str | None = None
    image_url: str | None = None

    @property
    def primary_email(self) -> str | None:
        """Resolve the primary email address from `email_addresses`."""
        if self.primary_email_address_id is None:
            return None
        return next(
            (
                email.email_address
                for email in self.email_addresses
                if email.id == self.primary_email_address_id
            ),
            None,
        )


class ClerkWebhookEvent(BaseModel):
    """A Clerk webhook event envelope (`user.created`, `.updated`, `.deleted`)."""

    type: str
    data: ClerkUserData


class WebhookAckResponse(BaseModel):
    """Acknowledgement returned to Clerk after processing a webhook event."""

    status: str
