"""Unit tests for the share snapshot builder (#4548).

The builder reuses ``_scan_thread_message_page``; here that canonical scan is
stubbed so the mapping/filters are pinned independently: only visible human/
AI text survives, hidden/control rows are dropped even when the scan let them
through, ids are snapshot-local, and backward pages are flipped to
chronological order.

The stubs mirror the canonical helper's contract exactly (``_scan_visible_
thread_messages`` returns each page ascending by ``seq``; backward pages
arrive newest-page-first) — diverging stubs previously masked a page-order
regression in the builder.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.gateway.shares.snapshot import (
    ShareSnapshotTooLarge,
    _neutralize_private_references,
    build_share_snapshot,
    resolve_share_title,
    sanitize_share_title,
)

pytestmark = pytest.mark.anyio


def _row(seq: int, content: dict) -> dict:
    return {"seq": seq, "run_id": f"run-{seq}", "content": content}


async def test_snapshot_keeps_only_visible_human_and_ai_text():
    # Canonical helper contract: newest backward page first, each page
    # internally ascending by seq.
    pages = [
        [_row(2, {"type": "remove", "content": ""}), _row(3, {"type": "ai", "name": "summary", "content": "summary text"}), _row(4, {"type": "ai", "content": "final answer"})],
        [_row(0, {"type": "ai", "content": "", "additional_kwargs": {"hide_from_ui": True}}), _row(1, {"type": "human", "content": "hello"})],
    ]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        assert before_seq in (None, 2)  # next cursor is the page's oldest seq
        return (pages[0] if before_seq is None else pages[1]), before_seq is None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["version"] == 1
    assert snapshot["messages"] == [
        {"id": "m1", "role": "user", "content": "hello"},
        {"id": "m2", "role": "assistant", "content": "final answer"},
    ]


async def test_snapshot_preserves_order_across_many_pages():
    """Pages flip order only as wholes; rows inside a page stay ascending."""
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (7, 8)],
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (4, 5, 6)],
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (1, 2, 3)],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == [f"m{seq}" for seq in range(1, 9)]


async def test_snapshot_skips_empty_text_messages():
    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return ([_row(1, {"type": "human", "content": "   "})], False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["messages"] == []


async def test_snapshot_excludes_reasoning_and_tool_content_blocks():
    pages = [
        [
            _row(
                1,
                {
                    "type": "ai",
                    "content": [
                        {"type": "thinking", "text": "private chain of thought"},
                        {"type": "reasoning", "text": "private reasoning"},
                        {"type": "tool_call", "text": "private tool args", "args": {"secret": True}},
                        {"type": "text", "text": "public answer"},
                        {"type": "output_text", "text": "public follow-up"},
                    ],
                },
            ),
            _row(2, {"type": "ai", "content": {"type": "thinking", "text": "top-level private thought"}}),
            _row(3, {"type": "ai", "content": "<think>inline private thought</think>visible answer"}),
        ]
    ]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return pages[0], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["messages"] == [
        {"id": "m1", "role": "assistant", "content": "public answer\npublic follow-up"},
        {"id": "m2", "role": "assistant", "content": "visible answer"},
    ]
    serialized = str(snapshot)
    assert "private" not in serialized


async def test_snapshot_preserves_literal_think_tags_inside_markdown_code():
    visible = "\n".join(
        [
            "Use `<think>text</think>` markers.",
            "```xml",
            "<think>literal fenced example</think>",
            "```",
            "<think>private reasoning</think>Visible answer.",
        ]
    )

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "ai", "content": visible})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    assert "`<think>text</think>`" in content
    assert "<think>literal fenced example</think>" in content
    assert "private reasoning" not in content
    assert "Visible answer." in content


async def test_snapshot_neutralizes_private_artifact_paths_and_urls():
    private_text = "\n".join(
        [
            "![private image](/mnt/user-data/outputs/secret.svg)",
            "[download](/api/threads/thread-secret/artifacts/mnt/user-data/outputs/report.pdf)",
            "raw path: /mnt/user-data/uploads/private.csv",
            "[encoded](%2Fapi%2Fthreads%2Fthread-secret%2Fartifacts%2Fmnt%2Fuser-data%2Foutputs%2Fencoded.pdf)",
            "[public source](https://example.com/report)",
        ]
    )

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "ai", "content": private_text})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    assert "/mnt/user-data" not in content
    assert "thread-secret" not in content
    assert "%2Fapi%2Fthreads" not in content
    assert "[private artifact omitted]" in content
    assert "[public source](https://example.com/report)" in content


async def test_snapshot_neutralizes_json_escaped_private_references():
    """JSON-escaped separators (``\\/``) must normalize before classification.

    P1 review finding: classification saw doubled separators (``/api//threads//``)
    after the backslash-to-slash swap and matched no private pattern, exposing
    the thread id and the owner-only artifact path.
    """
    private_text = "artifact: \\/api\\/threads\\/thread-secret\\/artifacts\\/mnt\\/user-data\\/report.pdf [encoded](%5C%2Fapi%5C%2Fthreads%5C%2Fthread-secret%5C%2Fartifacts%5C%2Freport.pdf) public stays verbatim: \\/api\\/v1\\/status"

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "ai", "content": private_text})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    assert "thread-secret" not in content
    assert "/mnt/user-data" not in content
    assert "%5C%2Fapi" not in content
    assert "[private artifact omitted]" in content
    # otherwise-public escaped content keeps its exact form
    assert "\\/api\\/v1\\/status" in content


async def test_neutralize_json_escaped_references():
    neutralize = _neutralize_private_references
    # raw JSON-escaped absolute references (reviewer's example) and the
    # relative form with no leading separator
    assert neutralize("\\/api\\/threads\\/thread-secret\\/artifacts\\/mnt\\/user-data\\/report.pdf") == "[private artifact omitted]"
    assert neutralize("\\/mnt\\/user-data\\/report.pdf") == "[private artifact omitted]"
    assert neutralize("mnt\\/user-data\\/report.pdf") == "[private artifact omitted]"


async def test_neutralize_multiply_encoded_json_escapes():
    neutralize = _neutralize_private_references
    # percent-encoded escape sequences (one and two layers)
    assert neutralize("%5C%2Fapi%5C%2Fthreads%5C%2Fthread-secret%5C%2Fartifacts%5C%2Freport.pdf") == "[private artifact omitted]"
    assert neutralize("%255C%252Fapi%255C%252Fthreads%255C%252Fthread-secret%255C%252Fartifacts%255C%252Freport.pdf") == "[private artifact omitted]"
    # double JSON-escaping: the slash escape's backslash is itself escaped
    assert neutralize("\\\\/api\\\\/threads\\\\/thread-secret\\\\/artifacts\\\\/report.pdf") == "[private artifact omitted]"
    # relative forms with encoded separators must classify from the "mnt"
    # prefix, not from the first percent unit
    assert neutralize("mnt%5C%2Fuser-data%2Freport.pdf") == "[private artifact omitted]"
    assert neutralize("mnt%255C%252Fuser-data%252Freport.pdf") == "[private artifact omitted]"


async def test_neutralize_backslash_separators():
    neutralize = _neutralize_private_references
    assert neutralize("\\api\\threads\\thread-secret\\artifacts\\report.pdf") == "[private artifact omitted]"
    assert neutralize("mnt\\user-data\\report.pdf") == "[private artifact omitted]"


async def test_neutralize_separator_runs():
    """Runs of raw forward slashes classify like their escaped forms.

    ``\\/`` at any depth collapses (round 5), but raw ``//`` and
    percent-encoded ``%2F%2F`` runs did not — and the shipped nginx keeps
    ``merge_slashes`` on, so ``/api//threads//…`` resolves to the real
    owner-scoped route in a browser. Public doubled paths keep their
    original bytes; only classification sees the collapse.
    """
    neutralize = _neutralize_private_references
    assert neutralize("/api//threads//thread-secret//artifacts//x.png") == "[private artifact omitted]"
    assert neutralize("//mnt//user-data//x.png") == "[private artifact omitted]"
    assert neutralize("mnt%2F%2Fuser-data/x.png") == "[private artifact omitted]"
    # public separator runs are not rewritten in the output
    assert neutralize("see //example.com//docs next") == "see //example.com//docs next"


async def test_neutralize_terminator_joined_private_paths():
    """Whitespace-free tokens may carry several private paths joined by
    prose/markdown terminators (tool-style comma lists). Every private item
    is cut; the joining terminator bytes are public and stay; a public tail
    after the terminator survives too."""
    neutralize = _neutralize_private_references
    assert neutralize("/mnt/user-data/a.txt,/mnt/user-data/b.txt") == "[private artifact omitted],[private artifact omitted]"
    assert neutralize("/api/threads/thread-secret/artifacts/a.png;/mnt/user-data/b.png") == "[private artifact omitted];[private artifact omitted]"
    assert neutralize("(/mnt/user-data/a.txt),(/mnt/user-data/b.txt)") == "([private artifact omitted]),([private artifact omitted])"
    # terminator followed by public content keeps both sides
    assert neutralize("/mnt/user-data/a.txt, see the docs") == "[private artifact omitted], see the docs"
    assert neutralize("/mnt/user-data/a.txt,/etc/hosts") == "[private artifact omitted],/etc/hosts"


async def test_neutralize_encoded_letters_in_private_phrases():
    """Character references and unicode escapes decode anywhere in the
    phrase, not only in separator position — the frontend's CommonMark
    renderer (micromark via streamdown) renders ``&#45;`` back into the
    path exactly as readily as ``&#47;``, including as clickable links."""
    neutralize = _neutralize_private_references
    # decimal/hex entities: letters and the mnt hyphen
    assert neutralize("see /mnt/user&#45;data/x.csv now") == "see [private artifact omitted] now"
    assert neutralize("see /&#109;nt/user-data/x.csv now") == "see [private artifact omitted] now"
    assert neutralize("see /api/thre&#97;ds/t1/uploads/f.pdf now") == "see [private artifact omitted] now"
    assert neutralize("x /api/threads/t&#49;/uploads/f.pdf y") == "x [private artifact omitted] y"
    # markdown destination and label leak
    assert neutralize("grab [the export](/mnt/user&#x2D;data/x.csv)") == "grab the export [private artifact omitted]"
    assert neutralize("grab [the export](/api/thre&#x61;ds/t1/uploads/f.pdf)") == "grab the export [private artifact omitted]"
    assert neutralize("[file at /mnt/user&#45;data](https://example.com)") == "[private artifact omitted]"
    # bare relative form with one encoded letter (no leading separator)
    assert neutralize("report at api/thre&#97;ds/t1/uploads/f.pdf") == "report at [private artifact omitted]"
    # unicode-escaped letters (JSON consumers decode \\uXXXX everywhere)
    assert neutralize("x /\\u0061pi/threads/t1/uploads/f.pdf y") == "x [private artifact omitted] y"
    assert neutralize("x /mnt/user\\u002Ddata/f.pdf y") == "x [private artifact omitted] y"
    # joined tail whose private item carries one encoded byte
    assert neutralize("x /api/threads/t1/uploads,/mnt/user&#45;data y") == "x [private artifact omitted],[private artifact omitted] y"
    assert neutralize("x /mnt/user-data/a.txt,%6Dnt%2Fuser%2Ddata%2Fb y") == "x [private artifact omitted],[private artifact omitted] y"
    # public entity/escape text keeps its original bytes
    assert neutralize("fish &amp; chips &#65; ok") == "fish &amp; chips &#65; ok"
    assert neutralize("unicode \\u0041 stays") == "unicode \\u0041 stays"


async def test_neutralize_public_head_and_middle_in_joined_tokens():
    """A public first item may not shield a private relative tail joined
    behind it in one whitespace-free token; a public middle item between
    two private ones survives the segment-precise cut."""
    neutralize = _neutralize_private_references
    assert neutralize("report at /docs,api/threads/8f3a/uploads/q4.pdf") == "report at /docs,[private artifact omitted]"
    assert neutralize("see /docs,mnt/user-data/report.pdf") == "see /docs,[private artifact omitted]"
    assert neutralize("x /api/threads/t1/uploads,https://example.com/pub,/mnt/user-data y") == "x [private artifact omitted],https://example.com/pub,/[private artifact omitted] y"


async def test_neutralize_scheme_separator_stays_uncollapsed():
    """The ``//`` of a URL scheme is not a path separator: a public host
    keeps its bytes while only a private-shaped subpath is cut
    (origin-blind classification of /mnt/user-data is the pre-existing
    design, single- and doubled-slash alike)."""
    neutralize = _neutralize_private_references
    assert neutralize("go https://example.com/?u=/mnt/user-data now") == "go https://example.com/?u=/[private artifact omitted] now"
    assert neutralize("see https://example.com/mnt//user-data/x") == "see https://example.com/[private artifact omitted]"
    # public doubled paths keep their bytes
    assert neutralize("see //example.com//docs next") == "see //example.com//docs next"
    assert neutralize("file:///mnt/public/readme.txt") == "file:///mnt/public/readme.txt"


async def test_neutralize_stable_under_rerun_and_heals_overlap_drops():
    """One application leaves no private bytes (re-running is a no-op), and
    a markdown edit that shadows a raw match in the same pass is healed by
    the bounded re-application instead of persisting into the snapshot."""
    neutralize = _neutralize_private_references
    once = neutralize("[x](/api/threads/t1/uploads),/mnt/user-data")
    assert once == "x [private artifact omitted],[private artifact omitted]"
    assert neutralize(once) == once
    pathological = "/mnt/user-data/a," + ",xx/mnt/user-data/b" * 200
    result = neutralize(pathological)
    assert "user-data" not in result
    assert "xx" in result  # public middle bytes between the cuts survive


async def test_neutralize_junk_shielded_percent_tails():
    """Junk items between the join and a percent-encoded private tail must
    not shield it (round-10 regression): the walker's anchored probe sees
    only the first tail item, so the unconsumed gaps are classified too and
    the residual is cut when its decoded form carries a private phrase —
    at mint time, not just across bounded re-runs."""
    neutralize = _neutralize_private_references
    attack = "/mnt/user-data" + ",/x" * 5 + ",%2Fapi%2Fthreads%2F2f0c9a34-9d1e-4f30-b1c2-7c21e6b0a55d%2Fartifacts"
    out = neutralize(attack)
    assert "2f0c9a34" not in out
    assert "%2Fapi" not in out
    assert "[private artifact omitted]" in out
    assert neutralize(out) == out
    # percent middle between two shadow-visible phrases
    out = neutralize("/mnt/user-data/a,%6Dnt%2Fuser%2Ddata%2Fb,/mnt/user-data/c")
    assert "user" not in out.replace("[private artifact omitted]", "")
    # public junk between visible phrases stays public (the separator that
    # introduces a later phrase after junk is public structure, same as the
    # pinned middle-item case)
    assert neutralize("/mnt/user-data/a,/x,/mnt/user-data/c") == "[private artifact omitted],/x,/[private artifact omitted]"
    # title path is covered identically
    from app.gateway.shares.snapshot import sanitize_share_title

    title = sanitize_share_title("Export,/x,%2Fapi%2Fthreads%2F2f0c9a34%2Fuploads%2Fq.pdf")
    assert "2f0c9a34" not in title
    assert "%2F" not in title


async def test_neutralize_dot_segment_resolution():
    """``.``/``..``/``%2E`` segments resolve away at the same layers that
    merge ``//`` (browser URL shortening, nginx URI normalization), so
    ``/api/x/../threads/…`` reaches the owner-scoped route."""
    neutralize = _neutralize_private_references
    assert neutralize("/api/x/../threads/th1/artifacts") == "[private artifact omitted]"
    assert neutralize("/api/./threads/th1/artifacts") == "[private artifact omitted]"
    assert neutralize("/api/%2E/threads/th1/artifacts") == "[private artifact omitted]"
    assert neutralize("/mnt/./user-data") == "[private artifact omitted]"
    assert neutralize("/mnt/x/../user-data") == "[private artifact omitted]"
    assert neutralize("[doc](/api/x/../threads/th1/artifacts)") == "doc [private artifact omitted]"
    # a lone ``..`` cancels one segment only: ``ab/cd/..`` resolves to
    # ``ab/…``, not the owner-scoped surface — and dot paths that resolve
    # somewhere public stay public likewise
    assert neutralize("/api/ab/cd/../threads/th1/artifacts") == "/api/ab/cd/../threads/th1/artifacts"
    assert neutralize("see /api/threads-guide/../docs next") == "see /api/threads-guide/../docs next"


async def test_neutralize_wordlike_public_prefixes_stay_public():
    """``foo.api``/``foo-mnt`` are longer public identifiers or hosts, same
    as the pinned ``foo_api`` form — the phrase must not match across a
    dot/hyphen adjacency."""
    neutralize = _neutralize_private_references
    assert neutralize("see foo.api/threads/th1/artifacts") == "see foo.api/threads/th1/artifacts"
    assert neutralize("see foo-mnt/user-data") == "see foo-mnt/user-data"
    assert neutralize("see foo_api/threads/th1/artifacts") == "see foo_api/threads/th1/artifacts"


async def test_neutralize_large_joined_tokens_stay_tractable():
    """A hostile joined list must stay linear: every private item is cut,
    the public junk between them survives, and the walk does not rescan
    the token per item."""
    neutralize = _neutralize_private_references
    pathological = "/mnt/user-data/a," + ",/x,/mnt/user-data/b" * 3000
    result = neutralize(pathological)
    assert "user-data" not in result
    assert "user" not in result.replace("[private artifact omitted]", "")
    assert ",/x," in result  # public junk between the cuts survives


async def test_neutralize_preserves_public_content_with_separators():
    neutralize = _neutralize_private_references
    # normalization exists only for classification; public text is emitted
    # byte-for-byte, including escapes and backslashes
    assert neutralize("\\/api\\/v1\\/status") == "\\/api\\/v1\\/status"
    assert neutralize("regex \\s+ and latex \\section stay") == "regex \\s+ and latex \\section stay"
    assert neutralize("C:\\Users\\name\\file.txt") == "C:\\Users\\name\\file.txt"
    assert neutralize("docs at https://example.com/threads-guide/metadata") == ("docs at https://example.com/threads-guide/metadata")


async def test_neutralize_markdown_link_with_json_escaped_target():
    neutralize = _neutralize_private_references
    assert neutralize("[report](\\/api\\/threads\\/thread-secret\\/artifacts\\/f.pdf)") == "report [private artifact omitted]"
    assert neutralize("![img](\\/mnt\\/user-data\\\\/secret.svg)") == "img [private artifact omitted]"
    # a match ending on a collapsed separator must not leave stray bytes
    assert neutralize("see \\/mnt\\/user-data\\/ next") == "see [private artifact omitted] next"


async def test_sanitize_share_title_neutralizes_json_escaped_reference():
    title = sanitize_share_title("Report: \\/mnt\\/user-data\\/secret.csv")
    assert "user-data" not in title
    assert "secret.csv" not in title


async def test_snapshot_cap_rejects_instead_of_truncating(caplog):
    """The first public message beyond the cap must fail loudly."""
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(2, 12)],
        [_row(1, {"type": "human", "content": "m1"})],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 10)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with caplog.at_level(logging.WARNING, logger="app.gateway.shares.snapshot"):
            with pytest.raises(ShareSnapshotTooLarge) as excinfo:
                await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.cap == 10
    assert excinfo.value.hit == 11
    assert any("refusing partial share" in record.message for record in caplog.records)


async def test_snapshot_rejects_when_terminal_page_pushes_public_count_over_cap():
    """A mixed terminal page may cross the cap even when no older page exists."""

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(1, 5)], False

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 3)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with pytest.raises(ShareSnapshotTooLarge) as excinfo:
            await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.cap == 3
    assert excinfo.value.hit == 4


async def test_snapshot_at_cap_scans_older_non_public_page_before_deciding():
    """Canonical ``has_more`` can mean only older non-public rows remain."""
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(2, 5)],
        [_row(1, {"type": "tool", "content": "tool-only"})],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 3)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert calls["n"] == 2
    assert [message["content"] for message in snapshot["messages"]] == ["m2", "m3", "m4"]


async def test_tool_heavy_thread_does_not_hit_the_cap_early():
    """The cap counts sanitized public messages, not raw rows: tool output
    and hidden rows must not consume share budget (#4548 review)."""
    tool_row = lambda seq: _row(seq, {"type": "tool", "content": '{"args": 1}'})  # noqa: E731
    pages = [
        [tool_row(seq) for seq in range(201, 401)] + [_row(200, {"type": "human", "content": "hi"})],
        [tool_row(seq) for seq in range(1, 200)] + [_row(0, {"type": "human", "content": "hello"})],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    with pytest.MonkeyPatch.context() as mp:
        # A cap that the 400 raw tool rows would exceed, but the 2 public
        # messages must not.
        mp.setattr("app.gateway.shares.snapshot._SNAPSHOT_MAX_MESSAGES", 100)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == ["hello", "hi"]


async def test_raw_scan_bound_counts_rows_consumed_inside_canonical_pager():
    """Rows filtered inside the canonical pager still consume raw budget."""

    class FakeEventStore:
        def __init__(self):
            self.rows = [
                {
                    "seq": seq,
                    "run_id": "hidden-run",
                    "content": {"type": "human", "content": f"hidden-{seq}"},
                    "metadata": {},
                }
                for seq in range(1, 6)
            ]
            self.raw_rows_returned = 0

        async def list_messages(self, thread_id, *, limit, before_seq=None, after_seq=None, user_id=None):
            assert after_seq is None
            eligible = [row for row in self.rows if before_seq is None or row["seq"] < before_seq]
            page = eligible[-limit:]
            self.raw_rows_returned += len(page)
            return page

    class FakeRunManager:
        async def list_successful_regenerate_sources(self, thread_id, *, user_id):
            return {"hidden-run"}

        async def list_edit_replay_visibility(self, thread_id, *, user_id):
            return SimpleNamespace(hidden_source_run_ids=set(), hidden_attempt_run_ids=set())

    from app.gateway.routers import thread_runs
    from app.gateway.shares import snapshot as snapshot_module

    event_store = FakeEventStore()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                run_event_store=event_store,
                run_manager=FakeRunManager(),
            )
        )
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_SCANNED_ROWS", 3)
        mp.setattr(thread_runs, "THREAD_MESSAGE_PAGE_SCAN_BATCH", 2)
        with pytest.raises(ShareSnapshotTooLarge) as excinfo:
            await build_share_snapshot("thread-1", request=request, user_id="user-1")

    assert excinfo.value.cap == 3
    assert excinfo.value.hit == 4
    # One sentinel row beyond the cap proves that older raw history exists;
    # the lower-level scan must stop there instead of walking all five rows.
    assert event_store.raw_rows_returned == 4


async def test_snapshot_exactly_at_cap_with_no_more_rows_shares_completely():
    """At-cap scans with no older rows remaining are complete, not rejected.

    Pins the loop's check order: the ``has_more`` exit must win over the cap
    rejection, or exactly-at-cap conversations would flip from shareable to
    413 on a refactor that swaps the two branches.
    """
    # Canonical helper contract: newest backward page first, each page
    # internally ascending.
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (5, 6)],
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (1, 2, 3, 4)],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 6)  # == total rows
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == [f"m{seq}" for seq in range(1, 7)]


async def test_resolve_share_title_uses_thread_meta_with_fallback():
    class _Store:
        async def get(self, thread_id, **_kwargs):
            return {"title": "  Project sync  "}

    class _Empty:
        async def get(self, thread_id, **_kwargs):
            return None

    # deps.get_thread_store(request) reads request.app.state.thread_store
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=_Store())))
    assert await resolve_share_title("thread-1", request=request) == "Project sync"
    request_empty = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=_Empty())))
    assert await resolve_share_title("thread-1", request=request_empty) == "Shared conversation"


async def test_resolve_share_title_reads_real_thread_meta_display_name():
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    user = SimpleNamespace(id="user-1")
    store = MemoryThreadMetaStore(InMemoryStore())
    await store.create("thread-1", user_id=user.id, display_name="Real conversation title")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=store)))

    context_token = set_current_user(user)
    try:
        title = await resolve_share_title("thread-1", request=request)
    finally:
        reset_current_user(context_token)

    assert title == "Real conversation title"


async def test_resolve_share_title_neutralizes_private_artifact_reference():
    private_title = "/api/threads/thread-secret/artifacts/mnt/user-data/outputs/report.pdf"

    class _Store:
        async def get(self, thread_id):
            return {"display_name": private_title}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=_Store())))

    title = await resolve_share_title("thread-1", request=request)

    assert "thread-secret" not in title
    assert "/mnt/user-data" not in title
    assert title == "[private artifact omitted]"


def test_trailing_punctuation_no_longer_defeats_reference_redaction():
    """Sentence punctuation after a private reference must neither defeat
    classification nor be swallowed by the marker (round-6 P1)."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("Downloaded it from /api/threads/thread-2f9c/artifacts.") == "Downloaded it from [private artifact omitted]."
    assert neutralize("You can list /api/threads/thread-2f9c/uploads, or fetch files.") == "You can list [private artifact omitted], or fetch files."
    # Escaped separators with trailing punctuation classify identically.
    assert neutralize("See \\/api\\/threads\\/thread-2f9c/artifacts.") == "See [private artifact omitted]."
    # A public URL with trailing punctuation passes through byte-for-byte.
    assert neutralize("Visit https://example.com/page.") == "Visit https://example.com/page."


def test_markdown_labels_keep_original_bytes():
    """A private-target link whose label contains backslashes publishes the
    label's ORIGINAL bytes, not the separator-normalized shadow (round-6 P3)."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("[C:\\Users\\\\bob](/api/threads/t1/uploads/x)") == "C:\\Users\\\\bob [private artifact omitted]"


def test_markdown_label_and_structural_adjacency_are_redacted():
    """Round 7: references hidden inside markdown labels, closing backticks,
    and emphasis markers must classify private — the structural bytes stay
    in the public output around the marker."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    # Private reference inside the LABEL of a public-target link.
    assert neutralize("[see /api/threads/t1/uploads](https://example.com/public)") == "[private artifact omitted]"
    # Inline-code shape (assistants habitually wrap shell paths in backticks).
    assert neutralize("run `ls /api/threads/t1/uploads` to list files") == "run `ls [private artifact omitted]` to list files"
    # Emphasis adjacency.
    assert neutralize("**/api/threads/t1/uploads** is where the files are") == "**[private artifact omitted]** is where the files are"
    # Bracket adjacency from the markdown shape itself.
    assert "thread" not in neutralize("[see /api/threads/t1/uploads](https://example.com/public)")


def test_markdown_private_label_collapses_the_link_even_with_private_destination():
    """Round-9 P1: a link whose LABEL is private must collapse entirely even
    when the destination is private too — the destination-private branch
    would otherwise republish the private label verbatim beside the marker,
    leaking the thread route through shared messages."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    collapsed = neutralize("[/api/threads/t1/uploads/x](/api/threads/t1/uploads/x)")
    assert collapsed == "[private artifact omitted]"
    assert "api/threads" not in collapsed
    # Control: a public label with a private destination still publishes the
    # label next to the marker (round-6 P3 behavior is unchanged).
    assert neutralize("[report](/api/threads/t1/uploads/x)") == "report [private artifact omitted]"


def test_neutralize_html_entity_separators():
    """Round 8 P1: HTML character references decode to real separators before
    display, so classification must collapse them in the shadow while the
    original entity bytes stay cut out of the public output."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("see &#47;api&#47;threads&#47;thread-secret&#47;uploads&#47;q4.pdf now") == "see [private artifact omitted] now"
    assert neutralize("hex form &#x2F;api&#x2F;threads&#x2F;thread-secret&#x2F;uploads&#x2F;q.pdf") == "hex form [private artifact omitted]"
    assert neutralize("&sol;mnt&sol;user-data&sol;x.tsv") == "[private artifact omitted]"
    assert neutralize("backslash entity &#92;api&#92;threads&#92;t1&#92;uploads&#92;f.pdf") == "backslash entity [private artifact omitted]"
    # Non-separator entities are public markup and pass through verbatim.
    assert neutralize("fish &amp; chips &#65; ok") == "fish &amp; chips &#65; ok"


def test_neutralize_unicode_escaped_separators():
    """Round 8 P2: JSON/JS ``\\uXXXX`` separator escapes must not survive
    classification — they decode to a real path in any JSON consumer."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("see \\u002Fapi\\u002Fthreads\\u002Fthread-secret\\u002Fuploads\\u002Fq4.pdf") == "see [private artifact omitted]"
    assert neutralize("\\u005Capi\\u005Cthreads\\u005Ct1\\u005Cuploads\\u005Cf.pdf") == "[private artifact omitted]"
    # The doubled-backslash form (a literal backslash before the escape).
    assert neutralize("\\\\u002Fmnt\\\\u002Fuser-data\\\\u002Fx.pdf") == "[private artifact omitted]"
    # Non-separator escapes are public text and pass through verbatim.
    assert neutralize("unicode \\u0041 stays") == "unicode \\u0041 stays"


def test_cut_stops_at_first_structural_terminator():
    """Round 8 P2: the cut must end at the first structural terminator after
    the private path instead of eating the whole greedy regex token — public
    suffix bytes would otherwise be frozen out of the immutable snapshot."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("Check `/api/threads/t1/uploads`'s contents.") == "Check `[private artifact omitted]`'s contents."
    assert neutralize("See /api/threads/t1/uploads,then continue.") == "See [private artifact omitted],then continue."
    # URL structure continues the path: nested private paths inside a query
    # string must not survive the earlier cut boundary.
    assert neutralize("go /api/threads/t1/uploads?next=/api/threads/t2/uploads/x") == "go [private artifact omitted]"


def test_neutralize_references_without_leading_separator():
    """Round 8 P2: a relative reference with no leading separator classifies
    the same way, so a live-looking Markdown destination cannot publish the
    owner's thread id and artifact path."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("report at api/threads/8f3a/uploads/q4.pdf") == "report at [private artifact omitted]"
    assert neutralize("[report](api/threads/8f3a/uploads/q4.pdf)") == "report [private artifact omitted]"
    # The word-initial trigger needs a token boundary: mid-word lookalikes
    # are public text, not references (a separator-led prefix still catches
    # the real path on its own shape).
    assert neutralize("see fooapi/threads/8f3a/uploads") == "see fooapi/threads/8f3a/uploads"


def test_owner_scoped_thread_routes_are_redacted():
    """Round 8 P3: every ``/api/threads/{id}/<segment>`` route carries the
    internal thread id (and some are owner-only exports), so the private set
    is no longer limited to the artifacts/uploads pair."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    assert neutralize("/api/threads/8f3a/subagent-batches/b1/results.jsonl exported") == "[private artifact omitted] exported"
    assert neutralize("state at /api/threads/8f3a/state, ok") == "state at [private artifact omitted], ok"
    assert neutralize("history /api/threads/8f3a/history.") == "history [private artifact omitted]."
    # A bare thread path names no owner-scoped subresource and stays public.
    assert neutralize("thread /api/threads/8f3a mentioned") == "thread /api/threads/8f3a mentioned"


async def test_snapshot_neutralizes_entity_and_unicode_escaped_private_references():
    """Message-level regression for both round-8 separator-encoding forms."""
    private_text = " ".join(
        [
            "entity: &#47;api&#47;threads&#47;thread-secret&#47;uploads&#47;q4.pdf",
            "named: &sol;mnt&sol;user-data&sol;x.csv",
            "unicode: \\u002Fapi\\u002Fthreads\\u002Fthread-secret\\u002Fartifacts\\u002Fa.pdf",
            "public &#65; stays",
        ]
    )

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "ai", "content": private_text})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    assert "thread-secret" not in content
    assert "user-data" not in content
    assert "q4.pdf" not in content
    assert "x.csv" not in content
    assert "a.pdf" not in content
    assert "[private artifact omitted]" in content
    assert "&#65;" in content


def test_sanitize_share_title_neutralizes_entity_and_unicode_separators():
    title = sanitize_share_title("Report &#47;mnt&#47;user-data&#47;x.csv and \\u002Fmnt\\u002Fuser-data\\u002Fy.csv")
    assert "user-data" not in title
    assert "x.csv" not in title
    assert "y.csv" not in title


def test_neutralize_composed_separator_encodings():
    """Round-8 adversarial pass: encodings compose. An entity-encoded percent
    introducer, nested ampersand entities, and an escaped unicode escape must
    classify exactly like their decoded forms — while ordinary percent and
    ampersand text stays byte-identical."""
    from app.gateway.shares.snapshot import _neutralize_private_references as neutralize

    # Entity-encoded percent introducer: &#37;2F → %2F → / (the percent path
    # finishes the decoding the entity pass started).
    assert neutralize("see &#37;2Fapi&#37;2Fthreads&#37;2Fthread-secret&#37;2Fuploads&#37;2Fq4.pdf") == "see [private artifact omitted]"
    assert neutralize("see &#37;5Capi&#37;5Cthreads&#37;5Ct1&#37;5Cuploads&#37;5Cf.pdf") == "see [private artifact omitted]"
    # Nested entities: &amp;#47; (and the numeric &#38;#47;) → &#47; → /.
    assert neutralize("see &amp;#47;api&amp;#47;threads&amp;#47;t1&amp;#47;uploads&amp;#47;f.pdf") == "see [private artifact omitted]"
    assert neutralize("see &#38;#47;api&#38;#47;threads&#38;#47;t1&#38;#47;uploads&#38;#47;f.pdf") == "see [private artifact omitted]"
    # Escaped unicode escape: \u005c is a backslash, so u002f after it
    # collapses on the next pass.
    assert neutralize("\\u005Cu002fapi\\u005Cu002fthreads\\u005Cu002ft1\\u005Cu002fuploads\\u005Cu002ff.pdf") == "[private artifact omitted]"
    # ES6 code-point escapes compose with the same machinery.
    assert neutralize(r"es6 \u{2F}api\u{2F}threads\u{2F}t1\u{2F}uploads\u{2F}f.pdf") == "es6 [private artifact omitted]"
    assert neutralize(r"es6 \u{5C}api\u{5C}threads\u{5C}t1\u{5C}uploads\u{5C}f.pdf") == "es6 [private artifact omitted]"
    # A legitimate non-separator codepoint reference stays public.
    assert neutralize(r"cjk block U+2F8CB written \u{2F8CB} stays") == r"cjk block U+2F8CB written \u{2F8CB} stays"
    # Public percent/ampersand content passes through verbatim, including a
    # public API path whose separators are entity-encoded.
    assert neutralize("save &#37;20 today &amp; enjoy") == "save &#37;20 today &amp; enjoy"
    assert neutralize("public API at &#37;2Fapi&#37;2Fv1&#37;2Fstatus stays") == "public API at &#37;2Fapi&#37;2Fv1&#37;2Fstatus stays"
