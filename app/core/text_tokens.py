"""Parsing mentions and hashtags out of free text (ADR-0019 in obur-docs).

Both are written inline, Instagram-style. Pure functions only: no
database access, so the rules can be tested exhaustively on their own.

A mention is stored in the text as an id token, `@[<user_id>]`, and
rendered by clients as the person's current username, so a rename
updates every past mention.

A hashtag is `#` followed by Unicode letters, combining marks, digits,
and underscore. Anything else (whitespace, punctuation, emoji) ends it.
Tags match case-insensitively and display as typed; `hashtag_key` is the
match key.
"""

import re
import unicodedata
import uuid

from app.exceptions import (
    HashtagTooLongError,
    TooManyHashtagsError,
    TooManyMentionsError,
)

MAX_HASHTAGS_PER_ITEM = 5
MAX_HASHTAG_LENGTH = 50
MAX_MENTIONS_PER_CHECKIN = 10

_MENTION_TOKEN = re.compile(r"@\[([0-9a-fA-F-]{36})\]")
_HASHTAG_SIGIL = "#"
_UNDERSCORE = "_"
# Unicode general category prefix for combining marks, which several
# scripts need inside a word (e.g. Devanagari vowel signs).
_MARK_CATEGORY = "M"
_UNICODE_FORM = "NFC"
# Unicode default case folding turns `İ` into `i` plus a combining dot,
# which would make `#İstanbul` and `#istanbul` different tags. Folding it
# to a plain `i` first is the one Turkish-specific rule (ADR-0019).
_DOTTED_CAPITAL_I = "İ"
_PLAIN_SMALL_I = "i"


def mention_token(user_id: uuid.UUID) -> str:
    """The text a client writes into a note to mention `user_id`."""
    return f"@[{user_id}]"


def parse_mention_ids(text: str | None) -> list[uuid.UUID]:
    """Every mentioned user id in `text`, in order of first appearance,
    each once. A bracketed value that isn't a UUID is plain text.

    Raises `TooManyMentionsError` above `MAX_MENTIONS_PER_CHECKIN`.
    """
    ids: list[uuid.UUID] = []
    for raw in _MENTION_TOKEN.findall(text or ""):
        try:
            user_id = uuid.UUID(raw)
        except ValueError:
            continue
        if user_id not in ids:
            ids.append(user_id)
    if len(ids) > MAX_MENTIONS_PER_CHECKIN:
        raise TooManyMentionsError(
            f"{len(ids)} mentions, at most {MAX_MENTIONS_PER_CHECKIN} allowed"
        )
    return ids


def hashtag_key(tag: str) -> str:
    """The case-insensitive match key for a tag, without the `#`. Also
    what a tag page shows as its heading.
    """
    normalised = unicodedata.normalize(_UNICODE_FORM, tag)
    return normalised.replace(_DOTTED_CAPITAL_I, _PLAIN_SMALL_I).casefold()


def _is_tag_char(char: str) -> bool:
    return (
        char.isalnum()
        or char == _UNDERSCORE
        or unicodedata.category(char).startswith(_MARK_CATEGORY)
    )


def _raw_hashtags(text: str) -> list[str]:
    """Every `#tag` run in `text`. A `#` directly after a tag character
    (as in `abc#def`) does not start a tag.
    """
    tags: list[str] = []
    index = 0
    while (index := text.find(_HASHTAG_SIGIL, index)) != -1:
        end = index + 1
        while end < len(text) and _is_tag_char(text[end]):
            end += 1
        starts_word = index == 0 or not _is_tag_char(text[index - 1])
        if starts_word and end > index + 1:
            tags.append(text[index + 1 : end])
        index = end
    return tags


def parse_hashtags(text: str | None) -> list[str]:
    """Every distinct hashtag in `text`, as first typed, without the `#`.
    A tag made only of digits is not a tag.

    Raises `HashtagTooLongError` for a tag over `MAX_HASHTAG_LENGTH` and
    `TooManyHashtagsError` above `MAX_HASHTAGS_PER_ITEM` distinct tags.
    """
    normalised = unicodedata.normalize(_UNICODE_FORM, text or "")
    tags: dict[str, str] = {}
    for tag in _raw_hashtags(normalised):
        if tag.isdigit():
            continue
        if len(tag) > MAX_HASHTAG_LENGTH:
            raise HashtagTooLongError(f"hashtag longer than {MAX_HASHTAG_LENGTH}")
        tags.setdefault(hashtag_key(tag), tag)
    if len(tags) > MAX_HASHTAGS_PER_ITEM:
        raise TooManyHashtagsError(
            f"{len(tags)} hashtags, at most {MAX_HASHTAGS_PER_ITEM} allowed"
        )
    return list(tags.values())
