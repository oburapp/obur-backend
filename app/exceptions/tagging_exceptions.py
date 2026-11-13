"""Custom exceptions for mentions and hashtags (ADR-0019 in obur-docs)."""


class TaggingError(Exception):
    """Base class for mention and hashtag errors."""


class TooManyMentionsError(TaggingError):
    """Raised when a note mentions more people than allowed."""


class MentionNotAllowedError(TaggingError):
    """Raised when a note newly mentions someone who isn't eligible: not
    a mutual follower, or not someone who can see the check-in.
    """


class TooManyHashtagsError(TaggingError):
    """Raised when a text carries more distinct hashtags than allowed."""


class HashtagTooLongError(TaggingError):
    """Raised when a hashtag exceeds the length limit."""
