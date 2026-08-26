"""Custom exceptions for follow, close friends, lists, likes, and
bookmarks.
"""


class SocialError(Exception):
    """Base class for social-graph errors."""


class SelfFollowError(SocialError):
    """Raised when a user tries to follow themselves."""


class FollowNotFoundError(SocialError):
    """Raised when the given follow relationship doesn't exist —
    unfollowing, or removing a follower, when it was never there.
    """


class NotAFollowerError(SocialError):
    """Raised when trying to add someone as a close friend who doesn't
    currently follow the person adding them.
    """


class CloseFriendNotFoundError(SocialError):
    """Raised when removing someone who isn't currently a close friend."""


class ListError(Exception):
    """Base class for list-domain errors."""


class ListNotFoundError(ListError):
    """Raised when a list id doesn't match any (visible) row."""


class NotListOwnerError(ListError):
    """Raised when a non-owner, non-admin user attempts to modify or
    delete a list.
    """


class ListItemNotFoundError(ListError):
    """Raised when a list item id doesn't match any row on the given
    list.
    """


class DuplicateListItemError(ListError):
    """Raised when a venue is added to a list it's already on."""


class LikeNotFoundError(SocialError):
    """Raised when unliking something that wasn't liked."""


class BookmarkNotFoundError(SocialError):
    """Raised when unbookmarking something that wasn't bookmarked."""


class SelfBlockError(SocialError):
    """Raised when a user tries to block themselves."""


class BlockNotFoundError(SocialError):
    """Raised when the given block relationship doesn't exist. Unlike
    `follows`/`close_friends`, only the blocker's own identity can ever
    reach this check (PDD §11: unblocking is the blocker's action
    alone), so there's no separate "wrong actor" case to distinguish:
    `blocks_delete`'s RLS policy (blocker-or-admin only, not widened
    the way `follows_delete` is) already makes that the only shape of
    request that reaches the service layer at all.
    """


class SelfMuteError(SocialError):
    """Raised when a user tries to mute themselves."""


class MuteNotFoundError(SocialError):
    """Raised when the given mute relationship doesn't exist."""
