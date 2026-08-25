"""Translating domain exceptions into RFC 9457 problem responses.

Routes raise domain exceptions and do not catch them. This module is the one
place that decides which problem type each becomes, which has two effects
worth the indirection:

Exception text can no longer reach a client by accident. Before this, every
route mapped its own errors and roughly fifteen of them passed `str(e)`
straight through, so a caller could read `"user 8f3a… may not delete list
2b1c…"`. There is now no per-route decision to get wrong — a domain error
either has an entry here or surfaces as a generic internal error, and both
are safe.

And an unmapped exception is visible rather than silent: it becomes a 500
with a logged traceback, not a leaked message.

See ADR-0015 in obur-docs.
"""

from typing import Any

from app.core import problems
from app.core.problems import Problem
from app.exceptions import (
    AccountNotFrozenError,
    AuthError,
    BookmarkNotFoundError,
    CheckinError,
    CheckinNotFoundError,
    CloseFriendNotFoundError,
    DuplicateListItemError,
    DuplicateVenueNearbyError,
    FollowNotFoundError,
    FutureVisitDateError,
    InvalidTokenError,
    InvalidWebhookSignatureError,
    LikeNotFoundError,
    ListError,
    ListItemNotFoundError,
    ListNotFoundError,
    NotAFollowerError,
    NotCheckinOwnerError,
    NotListOwnerError,
    NotVenueSaveOwnerError,
    SelfFollowError,
    SocialError,
    UserError,
    UsernameChangedTooRecentlyError,
    UsernameTakenError,
    VenueCategoryNotFoundError,
    VenueError,
    VenueNotEligibleForVerificationError,
    VenueNotFoundError,
    VenueSaveNotFoundError,
)

# The base classes app/main.py registers a handler against. Registering per
# base rather than on `Exception` matters: Starlette routes a bare
# `Exception` handler through `ServerErrorMiddleware`, which re-raises after
# responding so a crash still reaches the server log. A domain error is an
# expected outcome, not a crash, and must not be re-raised.
DOMAIN_BASE_ERRORS: tuple[type[Exception], ...] = (
    AuthError,
    CheckinError,
    ListError,
    SocialError,
    UserError,
    VenueError,
)

# Every "not found" that stands for something the caller may simply not be
# allowed to see resolves to the same problem an absent id would — the
# existence-leak standard, applied at the HTTP boundary as well as in
# app.core.authz.
DOMAIN_PROBLEMS: dict[type[Exception], Problem] = {
    # Check-ins
    CheckinNotFoundError: problems.CHECKIN_NOT_FOUND,
    NotCheckinOwnerError: problems.NOT_RESOURCE_OWNER,
    FutureVisitDateError: problems.FUTURE_VISIT_DATE,
    # Lists
    ListNotFoundError: problems.LIST_NOT_FOUND,
    ListItemNotFoundError: problems.LIST_ITEM_NOT_FOUND,
    NotListOwnerError: problems.NOT_RESOURCE_OWNER,
    DuplicateListItemError: problems.DUPLICATE_LIST_ITEM,
    # Venues
    VenueNotFoundError: problems.VENUE_NOT_FOUND,
    VenueCategoryNotFoundError: problems.VENUE_CATEGORY_NOT_FOUND,
    DuplicateVenueNearbyError: problems.DUPLICATE_VENUE_NEARBY,
    VenueNotEligibleForVerificationError: problems.VENUE_NOT_ELIGIBLE_FOR_VERIFICATION,
    VenueSaveNotFoundError: problems.VENUE_SAVE_NOT_FOUND,
    NotVenueSaveOwnerError: problems.NOT_RESOURCE_OWNER,
    # Social graph. A like, bookmark, follow, or close-friend link that
    # isn't there is one condition to a caller, whatever it was they were
    # trying to undo.
    FollowNotFoundError: problems.RELATIONSHIP_NOT_FOUND,
    NotAFollowerError: problems.NOT_A_FOLLOWER,
    SelfFollowError: problems.SELF_FOLLOW,
    CloseFriendNotFoundError: problems.RELATIONSHIP_NOT_FOUND,
    LikeNotFoundError: problems.RELATIONSHIP_NOT_FOUND,
    BookmarkNotFoundError: problems.RELATIONSHIP_NOT_FOUND,
    # Account
    UsernameTakenError: problems.USERNAME_TAKEN,
    UsernameChangedTooRecentlyError: problems.USERNAME_CHANGED_TOO_RECENTLY,
    AccountNotFrozenError: problems.NOT_RESOURCE_OWNER,
    # Auth
    InvalidTokenError: problems.NOT_AUTHENTICATED,
    InvalidWebhookSignatureError: problems.INVALID_WEBHOOK_SIGNATURE,
}


def problem_for(exc: Exception) -> Problem | None:
    """Return the problem type for `exc`, or None if it isn't mapped.

    Exact class only, deliberately. Matching a base class would silently
    fold a new subclass into whatever its parent maps to, which is how a
    specific condition quietly starts answering with the wrong status.
    """
    return DOMAIN_PROBLEMS.get(type(exc))


def detail_for(exc: Exception, problem: Problem) -> str:
    """The sentence shown for this occurrence.

    Almost always the problem's own written default. The exceptions are
    cases where the useful part is a value the error carries — never its
    message, which is developer-facing and stays in the log.
    """
    if isinstance(exc, UsernameChangedTooRecentlyError):
        return (
            "Your username can be changed again on "
            f"{exc.allowed_at.date().isoformat()}."
        )
    return problem.detail


def extensions_for(exc: Exception) -> dict[str, Any]:
    """Extra members a client needs in order to act on the error.

    RFC 9457 permits extension members and requires clients to ignore
    unrecognised ones, so adding to this is always backward compatible.
    """
    if isinstance(exc, DuplicateVenueNearbyError):
        # The client offers "did you mean this one?" and needs the id to
        # resolve to. Previously this was stuffed into `detail` as an
        # object, which the RFC requires to be a string.
        return {"nearby_venue_id": str(exc.nearby_venue_id)}
    if isinstance(exc, UsernameChangedTooRecentlyError):
        return {"retry_at": exc.allowed_at.isoformat()}
    return {}
