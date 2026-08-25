"""RFC 9457 Problem Details — the API's single error shape.

Every error response, including FastAPI's own validation failures, is
serialised as `application/problem+json`. One shape means a client writes
one parser. See ADR-0015 in obur-docs.

`type` is the machine-readable discriminator. It is a URN rather than an
HTTPS URL for two reasons: there is no production domain yet, and a `type`
value cannot be changed later without breaking every client branching on it
— so committing to a domain here would turn that choice into a breaking API
change. A URN identifies without promising to resolve.

`title` and `detail` are English, like the rest of this repository. They are
advisory: RFC 9457 requires clients not to parse `detail`, and user-facing
copy is the client's, produced by mapping `type` to its own wording in the
reader's own language.
"""

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

CONTENT_TYPE = "application/problem+json"

_URN_PREFIX = "urn:obur:problem:"


class Problem:
    """A problem type: its URN, its human-readable title, and its status.

    Instances are module-level constants below, so a type is declared once
    and referenced everywhere rather than spelled out at each raise site.
    """

    def __init__(
        self, slug: str, title: str, status_code: int, detail: str = ""
    ) -> None:
        self.type = f"{_URN_PREFIX}{slug}"
        self.title = title
        self.status = status_code
        # The sentence shown when nothing more specific is known. Written
        # once here rather than repeated at every raise site, which is what
        # kept exception text leaking into responses before.
        self.detail = detail or title

    def response(
        self,
        *,
        detail: str,
        request_id: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> JSONResponse:
        """Render this problem as a response body.

        Extension members are permitted by the RFC and clients are required
        to ignore ones they don't recognise, so adding a field here is
        always backward compatible.
        """
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": detail,
        }
        if request_id is not None:
            body["request_id"] = request_id
        body.update(extensions)

        return JSONResponse(
            status_code=self.status,
            content=body,
            media_type=CONTENT_TYPE,
            headers=headers,
        )


class ProblemError(Exception):
    """Raised by a route to return a problem response.

    Carries the problem type and, where one occurrence differs from the
    next, its own detail. Omitting `detail` uses the problem's own written
    text — which is the common case, so requiring it would make every raise
    site repeat the constant it just named.

    The handler in app/main.py turns this into a response and attaches the
    request id, so no route needs to know how correlation works.
    """

    def __init__(
        self,
        problem: Problem,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        self.problem = problem
        self.detail = detail if detail is not None else problem.detail
        self.headers = headers
        self.extensions = extensions
        super().__init__(f"{problem.type}: {self.detail}")


# --- Not found -------------------------------------------------------------
# A resource hidden from the caller returns the same problem a nonexistent
# id would, never one that confirms it exists — see app.core.authz.
CHECKIN_NOT_FOUND = Problem(
    "checkin-not-found",
    "Checkin not found",
    status.HTTP_404_NOT_FOUND,
    "No check-in with that id is visible to you.",
)
LIST_NOT_FOUND = Problem(
    "list-not-found",
    "List not found",
    status.HTTP_404_NOT_FOUND,
    "No list with that id is visible to you.",
)
VENUE_NOT_FOUND = Problem(
    "venue-not-found",
    "Venue not found",
    status.HTTP_404_NOT_FOUND,
    "No venue with that id exists.",
)
VENUE_NOT_ELIGIBLE_FOR_VERIFICATION = Problem(
    "venue-not-eligible-for-verification",
    "Venue not yet eligible for verification",
    status.HTTP_409_CONFLICT,
    "This venue hasn't reached the required number of independent check-ins yet.",
)
VENUE_SAVE_NOT_FOUND = Problem(
    "venue-save-not-found",
    "Venue save not found",
    status.HTTP_404_NOT_FOUND,
    "No saved venue with that id is visible to you.",
)
LIST_ITEM_NOT_FOUND = Problem(
    "list-item-not-found",
    "List item not found",
    status.HTTP_404_NOT_FOUND,
    "That list does not contain the item.",
)
VENUE_CATEGORY_NOT_FOUND = Problem(
    "venue-category-not-found",
    "Venue category not found",
    status.HTTP_404_NOT_FOUND,
    "No venue category with that id exists.",
)
RELATIONSHIP_NOT_FOUND = Problem(
    "relationship-not-found",
    "Relationship not found",
    status.HTTP_404_NOT_FOUND,
    "That relationship does not exist.",
)

# --- Authorisation ---------------------------------------------------------
NOT_RESOURCE_OWNER = Problem(
    "not-resource-owner",
    "Not the owner of this resource",
    status.HTTP_403_FORBIDDEN,
    "You can only change your own content.",
)
ADMIN_REQUIRED = Problem(
    "admin-required",
    "Admin privileges required",
    status.HTTP_403_FORBIDDEN,
    "This endpoint requires an administrator.",
)
ACCOUNT_SUSPENDED = Problem(
    "account-suspended",
    "This account is suspended",
    status.HTTP_403_FORBIDDEN,
    "This account is suspended.",
)
NOT_AUTHENTICATED = Problem(
    "not-authenticated",
    "Invalid or expired session",
    status.HTTP_401_UNAUTHORIZED,
    "Sign in to continue.",
)
INVALID_WEBHOOK_SIGNATURE = Problem(
    "invalid-webhook-signature",
    "Invalid webhook signature",
    status.HTTP_401_UNAUTHORIZED,
    "The webhook signature did not verify.",
)

# --- Conflict --------------------------------------------------------------
USERNAME_TAKEN = Problem(
    "username-taken",
    "Username already taken",
    status.HTTP_409_CONFLICT,
    "That username belongs to another account.",
)
DUPLICATE_VENUE_NEARBY = Problem(
    "duplicate-venue-nearby",
    "A venue already exists nearby",
    status.HTTP_409_CONFLICT,
    "A venue already exists within 50 metres. Resubmit with confirm_duplicate "
    "to add it anyway.",
)
DUPLICATE_LIST_ITEM = Problem(
    "duplicate-list-item",
    "Venue is already in this list",
    status.HTTP_409_CONFLICT,
    "That venue is already in this list.",
)

# --- Rejected input --------------------------------------------------------
VALIDATION_FAILED = Problem(
    "validation-failed",
    "Request validation failed",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "One or more fields are invalid.",
)
FUTURE_VISIT_DATE = Problem(
    "future-visit-date",
    "Visit date is in the future",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "A visit cannot be dated in the future.",
)
SELF_FOLLOW = Problem(
    "self-follow",
    "Cannot follow yourself",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "You cannot follow your own account.",
)
NOT_A_FOLLOWER = Problem(
    "not-a-follower",
    "That user does not follow you",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "That user does not follow you.",
)

# --- Too many requests -----------------------------------------------------
# Two distinct conditions share this status, which is why the discriminator
# has to live in the body at all — see ADR-0015.
RATE_LIMITED = Problem(
    "rate-limited",
    "Too many requests",
    status.HTTP_429_TOO_MANY_REQUESTS,
    "Too many requests. Try again shortly.",
)
USERNAME_CHANGED_TOO_RECENTLY = Problem(
    "username-changed-too-recently",
    "Username changed too recently",
    status.HTTP_429_TOO_MANY_REQUESTS,
    "Your username was changed too recently to change again.",
)

# --- Framework-raised ------------------------------------------------------
# Starlette produces these before any handler runs; mapping them keeps
# routing failures inside the same contract as everything else.
ROUTE_NOT_FOUND = Problem(
    "route-not-found",
    "No such endpoint",
    status.HTTP_404_NOT_FOUND,
    "No endpoint matches that path.",
)
METHOD_NOT_ALLOWED = Problem(
    "method-not-allowed",
    "Method not allowed for this endpoint",
    status.HTTP_405_METHOD_NOT_ALLOWED,
    "That method is not allowed on this endpoint.",
)

# --- Server ----------------------------------------------------------------
RATE_LIMITER_UNAVAILABLE = Problem(
    "rate-limiter-unavailable",
    "Cannot verify request limits right now",
    status.HTTP_503_SERVICE_UNAVAILABLE,
    "Request limits cannot be verified. Try again shortly.",
)
INTERNAL_ERROR = Problem(
    "internal-error",
    "Something went wrong",
    status.HTTP_500_INTERNAL_SERVER_ERROR,
    "An unexpected error occurred.",
)
