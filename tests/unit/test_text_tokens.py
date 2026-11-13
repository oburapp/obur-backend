"""Unit tests for app.core.text_tokens: the mention and hashtag rules from
ADR-0019 in obur-docs, exhaustively, since they are pure functions.
"""

import unicodedata
from uuid import uuid4

import pytest

from app.core.text_tokens import (
    MAX_HASHTAG_LENGTH,
    MAX_HASHTAGS_PER_ITEM,
    MAX_MENTIONS_PER_CHECKIN,
    hashtag_key,
    mention_token,
    parse_hashtags,
    parse_mention_ids,
)
from app.exceptions import (
    HashtagTooLongError,
    TooManyHashtagsError,
    TooManyMentionsError,
)


def test_mention_tokens_parse_in_order_once_each() -> None:
    first, second = uuid4(), uuid4()
    text = f"{mention_token(first)} and {mention_token(second)} {mention_token(first)}"

    assert parse_mention_ids(text) == [first, second]


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "@eren",
        "@[not-a-uuid-but-thirty-six-chars-xx]",
        # Matches the token shape (36 hex digits and dashes) but is no UUID.
        "@[" + "-" * 36 + "]",
        "@[]",
    ],
)
def test_text_without_a_valid_token_has_no_mentions(text: str | None) -> None:
    assert parse_mention_ids(text) == []


def test_more_mentions_than_the_limit_is_rejected() -> None:
    text = " ".join(mention_token(uuid4()) for _ in range(MAX_MENTIONS_PER_CHECKIN + 1))

    with pytest.raises(TooManyMentionsError):
        parse_mention_ids(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("great #kahve", ["kahve"]),
        ("#kahve, #tatlı.", ["kahve", "tatlı"]),
        ("#AnadoluMutfağı!", ["AnadoluMutfağı"]),
        ("#snake_case_tag", ["snake_case_tag"]),
        ("#kahve☕ next", ["kahve"]),
        ("#2026 #2026yazı", ["2026yazı"]),
        ("abc#def #ok", ["ok"]),
        ("# alone ##double", ["double"]),
        ("#東京 #café", ["東京", "café"]),
        ("#नमस्ते", ["नमस्ते"]),
    ],
)
def test_hashtags_follow_instagrams_character_rules(
    text: str, expected: list[str]
) -> None:
    assert parse_hashtags(text) == expected


def test_a_repeated_tag_in_any_casing_counts_once_as_first_typed() -> None:
    assert parse_hashtags("#Kahve #KAHVE #kahve") == ["Kahve"]


def test_decomposed_and_composed_letters_are_the_same_tag() -> None:
    decomposed = unicodedata.normalize("NFD", "#tatlı #çay")

    assert parse_hashtags(decomposed) == ["tatlı", "çay"]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Kahve", "kahve"),
        ("İstanbul", "istanbul"),
        ("ISTANBUL", "istanbul"),
        ("IPA", "ipa"),
        ("ÇAY", "çay"),
    ],
)
def test_case_variants_share_a_key(a: str, b: str) -> None:
    assert hashtag_key(a) == hashtag_key(b)


def test_dotted_capital_i_folds_to_a_plain_i() -> None:
    assert hashtag_key("İ") == "i"


def test_a_tag_longer_than_the_limit_is_rejected() -> None:
    with pytest.raises(HashtagTooLongError):
        parse_hashtags("#" + "a" * (MAX_HASHTAG_LENGTH + 1))


def test_a_tag_at_the_limit_is_accepted() -> None:
    tag = "a" * MAX_HASHTAG_LENGTH

    assert parse_hashtags(f"#{tag}") == [tag]


def test_more_distinct_tags_than_the_limit_is_rejected() -> None:
    text = " ".join(f"#tag{n}x" for n in range(MAX_HASHTAGS_PER_ITEM + 1))

    with pytest.raises(TooManyHashtagsError):
        parse_hashtags(text)


def test_a_mention_token_is_not_mistaken_for_a_hashtag() -> None:
    assert parse_hashtags(f"{mention_token(uuid4())} #ok") == ["ok"]


def test_dotless_turkish_uppercase_stays_a_different_tag() -> None:
    """The limitation ADR-0019 accepts: which lowercase `I` stands for
    depends on the word's language, which isn't known, so `#IŞIK` folds to
    `işik`, not `ışık`.
    """
    assert hashtag_key("IŞIK") != hashtag_key("ışık")
