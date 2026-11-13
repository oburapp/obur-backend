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

from fastapi import status

# Re-exported so `from app.core.problems import Problem, ProblemError`
# keeps working; the classes themselves live in app.core.problem_details.
from app.core.problem_details import CONTENT_TYPE, Problem, ProblemError

__all__ = ["CONTENT_TYPE", "Problem", "ProblemError"]

# --- Not found -------------------------------------------------------------
# A resource hidden from the caller returns the same problem a nonexistent
# id would, never one that confirms it exists — see app.core.authz.
CHECKIN_NOT_FOUND = Problem(
    "checkin-not-found",
    "Checkin not found",
    status.HTTP_404_NOT_FOUND,
    "No check-in with that id is visible to you.",
)
CHECKIN_DRAFT_NOT_FOUND = Problem(
    "checkin-draft-not-found",
    "Check-in draft not found",
    status.HTTP_404_NOT_FOUND,
    "No unexpired draft with that id belongs to you.",
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
CONTENT_REPORT_NOT_FOUND = Problem(
    "content-report-not-found",
    "Content report not found",
    status.HTTP_404_NOT_FOUND,
    "No content report with that id exists.",
)
VENUE_REPORT_NOT_FOUND = Problem(
    "venue-report-not-found",
    "Venue report not found",
    status.HTTP_404_NOT_FOUND,
    "No venue report with that id exists.",
)
USER_NOT_FOUND = Problem(
    "user-not-found",
    "User not found",
    status.HTTP_404_NOT_FOUND,
    "No user with that id exists.",
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
# Status codes for the idempotency problems follow the IETF
# Idempotency-Key header draft (draft-ietf-httpapi-idempotency-key-header),
# see ADR-0018 in obur-docs.
IDEMPOTENCY_REQUEST_IN_PROGRESS = Problem(
    "idempotency-request-in-progress",
    "A request with this idempotency key is still being processed",
    status.HTTP_409_CONFLICT,
    "Retry once the earlier request with this key has finished.",
)

# --- Rejected input --------------------------------------------------------
# Mentions and hashtags, ADR-0019 in obur-docs.
TOO_MANY_MENTIONS = Problem(
    "too-many-mentions",
    "Too many mentions",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "A check-in can mention at most 10 people.",
)
MENTION_NOT_ALLOWED = Problem(
    "mention-not-allowed",
    "That person can't be mentioned here",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "Only mutual followers who can see this check-in can be mentioned.",
)
TOO_MANY_HASHTAGS = Problem(
    "too-many-hashtags",
    "Too many hashtags",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "A check-in or list can carry at most 5 hashtags.",
)
HASHTAG_TOO_LONG = Problem(
    "hashtag-too-long",
    "Hashtag too long",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "A hashtag can be at most 50 characters.",
)
IDEMPOTENCY_KEY_MISSING = Problem(
    "idempotency-key-missing",
    "Idempotency-Key header is required",
    status.HTTP_400_BAD_REQUEST,
    "Send a client-generated UUID in the Idempotency-Key header.",
)
IDEMPOTENCY_KEY_INVALID = Problem(
    "idempotency-key-invalid",
    "Idempotency-Key header is not a UUID",
    status.HTTP_400_BAD_REQUEST,
    "The Idempotency-Key header must be a UUID.",
)
IDEMPOTENCY_KEY_REUSED = Problem(
    "idempotency-key-reused",
    "Idempotency key was already used with different content",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "This idempotency key belongs to a different submission. Generate a new "
    "key for a new submission.",
)
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
SELF_BLOCK = Problem(
    "self-block",
    "Cannot block yourself",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "You cannot block your own account.",
)
SELF_MUTE = Problem(
    "self-mute",
    "Cannot mute yourself",
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "You cannot mute your own account.",
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
