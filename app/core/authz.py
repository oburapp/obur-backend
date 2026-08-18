"""Ownership-based authorization.

The base rule, for every user-owned resource: you may act on your own
resource. `UserRole.ADMIN` is an override on top of that rule, not a
replacement for it — an admin may act on anyone's resource, a regular
user only their own.

This is deliberately generic (`owner_id`, not "checkin owner") so the
same one-line check is reused as-is once other user-owned resources
(lists, likes) exist — see docs/roadmap.md Phase 4.
"""

import uuid

from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_user
from app.models.user import User, UserRole


def is_owner_or_admin(owner_id: uuid.UUID, current_user: User) -> bool:
    """Return whether `current_user` may view or modify a resource owned
    by `owner_id` — its own resource, or an admin acting on anyone's.
    Same rule for both: an admin's whole point is to see and act on
    content a regular user couldn't.
    """
    return current_user.id == owner_id or current_user.role == UserRole.ADMIN


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency for admin-only endpoints (e.g. permanently
    deleting a check-in) — raises 403 for a non-admin.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return current_user
