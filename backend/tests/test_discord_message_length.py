"""Discord measures message content in UTF-16 code units, like its clients."""

from __future__ import annotations

from app.channels.discord import _DISCORD_MAX_MESSAGE_LEN, DiscordChannel

EMOJI = "😀"


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def test_split_text_keeps_every_chunk_within_the_utf16_limit() -> None:
    text = "a" * (_DISCORD_MAX_MESSAGE_LEN - 1) + EMOJI * 1500 + "b" * 50

    chunks = DiscordChannel._split_text(text)

    assert "".join(chunks) == text
    assert len(chunks) > 1
    assert all(utf16_units(chunk) <= _DISCORD_MAX_MESSAGE_LEN for chunk in chunks)


def test_split_text_does_not_put_a_non_bmp_character_over_the_limit() -> None:
    # 1999 ASCII characters plus one emoji is 2000 code points but 2001 UTF-16
    # code units, so Discord would reject it as one message.
    text = "x" * (_DISCORD_MAX_MESSAGE_LEN - 1) + EMOJI

    assert DiscordChannel._split_text(text) == ["x" * (_DISCORD_MAX_MESSAGE_LEN - 1), EMOJI]


def test_split_text_still_slices_bmp_text_at_the_limit() -> None:
    assert DiscordChannel._split_text("a" * _DISCORD_MAX_MESSAGE_LEN + "b" * 100) == ["a" * _DISCORD_MAX_MESSAGE_LEN, "b" * 100]
    assert DiscordChannel._split_text("") == [""]


def test_split_text_prefers_newline_boundaries_within_the_budget() -> None:
    text = "a" * 1900 + "\n" + "b" * 200

    chunks = DiscordChannel._split_text(text)

    assert chunks[0].endswith("\n")
    assert "".join(chunks) == text
    assert all(utf16_units(chunk) <= _DISCORD_MAX_MESSAGE_LEN for chunk in chunks)


def test_emoji_heavy_reply_is_split_even_when_code_points_fit() -> None:
    text = EMOJI * 1500  # 1500 code points, 3000 UTF-16 code units.

    chunks = DiscordChannel._split_text(text)

    assert len(chunks) == 2
    assert "".join(chunks) == text
    assert all(utf16_units(chunk) <= _DISCORD_MAX_MESSAGE_LEN for chunk in chunks)
