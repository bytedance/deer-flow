"""Whole-response and streaming MindIE decoding must protect the same fences."""

import pytest

from deerflow.models.mindie_provider import (
    _decode_escaped_newlines_outside_fences,
    _EscapedNewlineStreamDecoder,
)


@pytest.fixture(params=["```", "~~~"], ids=["backticks", "tildes"])
def fence_delimiters(request):
    outer = request.param
    inner = "~~~" if outer == "```" else "```"
    return outer, inner


@pytest.fixture(params=["", r"intro\n"], ids=["at-start", "after-prose"])
def prefix(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["unterminated", "closed"])
def fenced_reply(request, fence_delimiters, prefix):
    outer, inner = fence_delimiters
    # The inner pair must never close or escape an outer fence of either kind.
    code = f"{outer}python\\nouter\\n{inner}json\\ninner\\n{inner}\\ntail\\n"
    suffix = ""
    if request.param:
        code += outer
        suffix = r"\noutro\nend"
    raw = prefix + code + suffix
    expected = prefix.replace("\\n", "\n") + code + suffix.replace("\\n", "\n")
    return raw, expected


def test_complete_and_unterminated_fences_keep_literal_escapes(fenced_reply):
    raw, expected = fenced_reply

    assert _decode_escaped_newlines_outside_fences(raw) == expected


def test_stream_matches_whole_reply_at_every_chunk_boundary(fenced_reply):
    raw, expected = fenced_reply
    chunkings = [[raw[:split], raw[split:]] for split in range(len(raw) + 1)]
    chunkings.append(list(raw))

    for chunks in chunkings:
        decoder = _EscapedNewlineStreamDecoder()
        streamed = "".join(decoder.push(chunk) for chunk in chunks) + decoder.flush()

        assert streamed == expected, chunks
        assert streamed == _decode_escaped_newlines_outside_fences(raw), chunks
