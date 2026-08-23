"""Defaults for the identity fields Obur owns rather than the auth provider.

`USER.username` and `USER.display_name` are both required, but the auth
provider doesn't guarantee either one: Clerk's `username` is optional
unless the application is configured to demand it, and a user may sign
up with no name at all. Both of the paths that can create a `User` — the
Clerk webhook and the auth dependency's JIT fallback — derive their
defaults here rather than each inventing their own, so a user provisioned
by whichever path happens to win the race gets identical values.

These are seeds, not permanent values: `username` and `display_name` are
edited through Obur's own profile endpoint afterwards, and the webhook
deliberately never overwrites them on a later `user.updated` (see
app/api/v1/webhooks.py).
"""

import uuid

# Prefix for a generated handle, so a fallback username is visibly a
# placeholder the user is expected to replace.
USERNAME_FALLBACK_PREFIX = "user_"

# Hex characters of the derived UUID kept as the handle's suffix. 12 hex
# characters is 48 bits: with a unique input per user the values are
# effectively collision-free at any scale this platform will reach, while
# staying short enough to read and type. `username` is UNIQUE either way,
# so a collision would surface as an integrity error rather than two
# users sharing a handle.
_FALLBACK_SUFFIX_LENGTH = 12

# Fixed namespace for deriving handles, used the same way
# `uuid.NAMESPACE_DNS` is used by `uuid.uuid5`. It must never change once
# any user has been provisioned, since changing it would change the
# handle every existing fallback resolves to.
_USERNAME_NAMESPACE = uuid.UUID("3f2b1c4e-9d7a-5e18-8c06-2a4b6d0f9e33")


def fallback_username(auth_provider: str, auth_provider_id: str) -> str:
    """Return a deterministic placeholder handle for a user the provider
    gave no username for.

    Derived from the provider identity pair, which is already unique
    (`uq_user_auth_identity`), so the same user always resolves to the
    same handle no matter which creation path runs first — the webhook
    and the JIT fallback can race without producing two different
    handles for one person.
    """
    derived = uuid.uuid5(_USERNAME_NAMESPACE, f"{auth_provider}:{auth_provider_id}")
    return f"{USERNAME_FALLBACK_PREFIX}{derived.hex[:_FALLBACK_SUFFIX_LENGTH]}"


def default_display_name(
    *, first_name: str | None, last_name: str | None, username: str
) -> str:
    """Return the display name to seed a new user with.

    Prefers the provider's real name, falling back to the handle so the
    field is never empty — it's shown everywhere, and a blank one would
    leave the user invisible in feeds and listings until they edit their
    profile.
    """
    parts = [part.strip() for part in (first_name, last_name) if part and part.strip()]
    return " ".join(parts) if parts else username
