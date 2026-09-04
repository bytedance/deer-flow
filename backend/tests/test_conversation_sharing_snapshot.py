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
    resanitize_share_snapshot,
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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == [f"m{seq}" for seq in range(1, 9)]


async def test_snapshot_skips_empty_text_messages():
    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return ([_row(1, {"type": "human", "content": "   "})], False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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


async def test_neutralize_multi_dot_segment_resolution():
    """Dot-segment removal is stack-shaped: N ``..`` cancel N preceding
    segments, in any mix with ``.`` — the classifier must see the resolved
    path, not just one cancellation."""
    neutralize = _neutralize_private_references
    assert neutralize("see /api/a/b/../../threads/t1/uploads/x.pdf now") == "see [private artifact omitted] now"
    assert neutralize("see /mnt/a/b/../../user-data/x.csv now") == "see [private artifact omitted] now"
    assert neutralize("see /api/x/./../threads/t1/artifacts now") == "see [private artifact omitted] now"
    assert neutralize("see /api/x/.././threads/t1/artifacts now") == "see [private artifact omitted] now"
    assert neutralize("see /api/a/b/%2e%2e/%2e%2e/threads/t1/u now") == "see [private artifact omitted] now"
    # one real segment + two dots cancels the surface name itself: public
    assert neutralize("see /api/x/%2e%2e/%2e%2e/threads/t1/u now") == "see /api/x/%2e%2e/%2e%2e/threads/t1/u now"
    assert neutralize("grab [the export](/api/a/b/../../threads/t1/uploads/q4.pdf)") == "grab the export [private artifact omitted]"
    assert neutralize("x /docs,/api/a/b/../../threads/t1/u y") == "x /docs,/[private artifact omitted] y"
    # bare relative form with dots must keep its round-8 protection
    assert neutralize("report at api/./threads/t1/uploads/q4.pdf") == "report at [private artifact omitted]"
    assert neutralize("report at api/a/../threads/t1/uploads/q4.pdf") == "report at [private artifact omitted]"
    # a ``..`` may cancel the surface name itself: the resolved path is public
    assert neutralize("/api/../threads/t1/u") == "/api/../threads/t1/u"
    assert neutralize("/mnt/../user-data/x") == "/mnt/../user-data/x"


async def test_neutralize_nonterminator_join_characters():
    """Any non-word character can join a public head to a private tail in
    one whitespace-free token — the boundary is "not a word/dot/hyphen
    char", not a fixed punctuation list (fullwidth and symbolic joins
    included)."""
    neutralize = _neutralize_private_references
    assert neutralize("report at /docs&api/threads/t1/uploads/q4.pdf now") == "report at /docs&[private artifact omitted] now"
    assert neutralize("report at /docs=api/threads/t1/uploads/q4.pdf now") == "report at /docs=[private artifact omitted] now"
    assert neutralize("report at /docs，api/threads/t1/uploads/q4.pdf now") == "report at /docs，[private artifact omitted] now"
    assert neutralize("grab [x](/docs&api/threads/t1/uploads/q.pdf)") == "grab x [private artifact omitted]"
    # word, dot, and hyphen adjacency still shields nothing (public identifiers)
    assert neutralize("see foo.api/threads/th1/artifacts") == "see foo.api/threads/th1/artifacts"
    assert neutralize("see foo-mnt/user-data") == "see foo-mnt/user-data"


async def test_neutralize_dots_after_phrase_do_not_erase_it():
    """Query strings and fragments are opaque to path resolution (browsers
    and nginx leave ``?/../..`` alone), and dot segments never pop across
    prose whitespace — a trailing ``?/../..``, ``#/../..``, or `` /../../..``
    after a private phrase must not erase it from the classification
    shadow (round-12 regression)."""
    neutralize = _neutralize_private_references
    assert neutralize("/mnt/user-data?/..") == "[private artifact omitted].."
    assert neutralize("/api/threads/th1/artifacts?/../../..") == "[private artifact omitted].."
    assert neutralize("/mnt/user-data#/../../..") == "[private artifact omitted].."
    assert neutralize("[x](/mnt/user-data?/../..)") == "x [private artifact omitted]"
    assert neutralize("see /mnt/user-data/f.csv and /../../..") == "see [private artifact omitted] and /../../.."
    assert neutralize("/docs,/mnt/user-data,/../..") == "/docs,/[private artifact omitted],/../.."
    from app.gateway.shares.snapshot import sanitize_share_title

    assert "user-data" not in sanitize_share_title("/mnt/user-data?/..").replace("[private artifact omitted]", "")
    # an empty ``//`` segment is poppable: WHATWG resolves
    # ``/api//../threads/…`` back to the owner-scoped surface
    assert neutralize("/api//../threads/th1/u") == "[private artifact omitted]"


async def test_neutralize_pchar_segments_cancel_whole():
    """A cancelled segment may contain any legal path character — sub-delims
    like ``,``/``;``/``:`` and the unreserved ``_``/``~`` — so cancellation
    is segment-bounded (pop to the previous separator), never stopped
    mid-segment by a character class. Dual-shadow classification: the
    phrase is cut if it appears in the resolved OR the as-written form, so
    aggressive resolution can never erase it."""
    neutralize = _neutralize_private_references
    assert neutralize("/api/x,y/../threads/t1/u") == "[private artifact omitted]"
    assert neutralize("/api/_/../threads/t1/u") == "[private artifact omitted]"
    assert neutralize("/mnt/a_b/../user-data") == "[private artifact omitted]"
    assert neutralize("http://h:8080/api/a:b/../threads/t1/u") == "http://h:8080/[private artifact omitted]"
    assert neutralize(",/api/x_y/../threads/t1/u") == ",[private artifact omitted]"
    assert neutralize("[x](/api/x,y/../threads/t1/u)") == "x [private artifact omitted]"
    assert neutralize("/api/x&#44;y/../threads/t1/u") == "[private artifact omitted]"
    assert neutralize("\\/api\\/x,y\\/..\\/threads/t1/u") == "[private artifact omitted]"
    # a literal-space segment cancels as one (browsers percent-encode it)
    assert neutralize("[x](</api/x y/../threads/t1/u>)") == "x [private artifact omitted]"
    # ``..`` cancelling the phrase's own final segment: round 11 lets the
    # resolved shadow pin the bare id precisely, so the id still publishes
    # no bytes — the cancelled ``/u/..`` tail is route structure without
    # identifiers and yields to the precise resolved cut (the as-written
    # wider cut must not swallow what resolution already positioned).
    assert neutralize("see /api/threads/t1/u/.. end") == "see [private artifact omitted]/u/.. end"


async def test_neutralize_split_layer_encodings():
    """``api`` may arrive raw/entity/unicode while ``threads`` arrives
    percent-encoded (or vice versa): the token anchor must fire on any
    separator-ish follower, and the classifier must never resolve entity
    dots into a cancellation that browsers — which do not entity-decode
    URLs — would not perform (dual-view classification)."""
    neutralize = _neutralize_private_references
    # split-layer anchor: api literal, threads percent-encoded
    assert neutralize("see api/%74%68%72%65%61%64%73/t1/u now") == "see [private artifact omitted] now"
    assert neutralize("see \\u0061\\u0070\\u0069/%74%68%72%65%61%64%73/t1/u now") == "see [private artifact omitted] now"
    assert neutralize("see &#97;&#112;&#105;/%74%68%72%65%61%64%73/t1/u now") == "see [private artifact omitted] now"
    # entity dot-tail on a percent phrase: href keeps &#46;&#46; literal
    assert neutralize("[x](api/%74%68%72%65%61%64%73/t1/u/&#46;&#46;)") == "x [private artifact omitted]"
    assert neutralize("see %6D%6E%74/%75%73%65%72%2D%64%61%74%61/&#46;&#46; now") == "see [private artifact omitted]&#46;&#46; now"
    # controls: a percent sign in prose does not make a private token
    assert neutralize("api%usage and 100%api notes") == "api%usage and 100%api notes"


async def test_neutralize_encoded_glue_before_phrase():
    """An encoded glue character immediately before a phrase decodes in the
    shadow to a word/dot/hyphen char and trips the phrase-boundary
    lookbehind into the pinned-public identifier shape — while the original
    bytes end in ``;``, a phrase boundary. The boundary is therefore judged
    in original coordinates, where the pre-decode byte decides."""
    neutralize = _neutralize_private_references
    # entity glue: original boundary is ';' — cut (the glue bytes decode to
    # a single harmless character and stay public, like any public head)
    assert neutralize("&#46;api/threads/t1/u") == "&#46;[private artifact omitted]"
    assert neutralize("&#46;mnt/user-data") == "&#46;[private artifact omitted]"
    assert neutralize("z9&#46;mnt/user-data") == "z9&#46;[private artifact omitted]"
    assert neutralize("&amp;#46;api/threads/t1/u") == "&amp;#46;[private artifact omitted]"
    assert neutralize("&#97;api/threads/t1/u") == "&#97;[private artifact omitted]"
    assert neutralize("x&sol;api/threads/t1/u") == "x[private artifact omitted]"
    # entity glue + unicode-encoded phrase
    assert neutralize("&#46;api/\\u0074hreads/1/") == "&#46;[private artifact omitted]"
    assert neutralize("&#46;mnt/\\u0075ser-data") == "&#46;[private artifact omitted]"
    # controls: the blocking char is real in every consumer view — keep
    assert neutralize("foo.api/threads/t1/u") == "foo.api/threads/t1/u"
    assert neutralize("\\u002eapi/threads/t1/u") == "\\u002eapi/threads/t1/u"
    assert neutralize("%2Eapi/threads/t1/u") == "%2Eapi/threads/t1/u"


def test_neutralize_langgraph_route_alias():
    """The bundled nginx rewrites ``/api/langgraph/*`` to ``/api/*``
    (docker/nginx/nginx.conf), so the prefixed form is a live alias of the
    owner-scoped thread route and must classify like the native one in
    every layer: raw, entity head, percent middle, fully-encoded head.
    ``mnt`` phrases are prefix-free and already cover the alias."""
    neutralize = _neutralize_private_references
    # raw alias: absolute and markdown forms
    assert neutralize("see /api/langgraph/threads/t1/u now") == "see [private artifact omitted] now"
    assert neutralize("[x](/api/langgraph/threads/t1/u)") == "x [private artifact omitted]"
    # layered forms ride the same machinery as the native route
    assert neutralize("see &#97;&#112;&#105;/langgraph/threads/t1/u now") == "see [private artifact omitted] now"
    assert neutralize("see api/lang%67raph/threads/t1/u now") == "see [private artifact omitted] now"
    assert neutralize("see %61%70%69/langgraph/threads/t1/u now") == "see [private artifact omitted] now"
    # controls: no thread id after the alias, or no api anchor at all
    assert neutralize("the /api/langgraph/threads/ route docs") == "the /api/langgraph/threads/ route docs"
    assert neutralize("langgraph/threads/t1/u without the api anchor") == "langgraph/threads/t1/u without the api anchor"


def test_resanitize_rebuilds_the_strict_public_dto():
    """The public read boundary reconstructs the allowlisted DTO rather
    than spreading stored fields: an older, malformed, or sanitizer-defect
    snapshot must not serialize tool_calls, reasoning, run ids, debug
    metadata, or any other non-contract field to anonymous callers.
    Stored ids are regenerated — a source event/run/thread identifier in
    ``message.id`` is not snapshot-local just because it is a string."""
    stored = {
        "version": 1,
        "debug": {"owner_user_id": "u-1"},
        "messages": [
            {
                "id": "run-source-id-9",
                "role": "user",
                "content": "see /api/threads/t-secret/u now",
                "tool_calls": [{"id": "call_1"}],
                "run_id": "run-9",
            },
            {"id": "m2", "role": "tool", "content": "raw tool output"},
            {"id": "m3", "role": "assistant", "content": [{"type": "text", "text": "block"}]},
            "not-even-a-dict",
        ],
    }
    rebuilt = resanitize_share_snapshot(stored)
    assert rebuilt == {
        "version": 1,
        "messages": [
            {"id": "m1", "role": "user", "content": "see [private artifact omitted] now"},
        ],
    }
    # the stored record is never mutated, and a non-int version falls back
    # to the only contract version
    assert stored["messages"][0]["content"] == "see /api/threads/t-secret/u now"
    assert resanitize_share_snapshot({"version": "x", "messages": [], "extra": 1}) == {"version": 1, "messages": []}


async def test_snapshot_reports_the_source_history_boundary():
    """The audit boundary is the highest raw seq the bounded scan consumed,
    observed before visibility filtering: when the newest rows are hidden
    (hidden run or middleware), the boundary still records them, not the
    newest row that survived into the public DTO."""

    class FakeEventStore:
        def __init__(self):
            self.rows = [
                {
                    "seq": seq,
                    "run_id": "hidden-run",
                    "content": {"type": "human", "content": f"hidden-{seq}"},
                    "metadata": {},
                }
                for seq in (10, 11, 12)
            ] + [
                {
                    "seq": 1,
                    "run_id": "visible-run",
                    "content": {"type": "human", "content": "hello"},
                    "metadata": {},
                }
            ]

        async def list_messages(self, thread_id, *, limit, before_seq=None, after_seq=None, user_id=None):
            assert after_seq is None
            eligible = [row for row in self.rows if before_seq is None or row["seq"] < before_seq]
            return eligible[-limit:]

    class FakeRunManager:
        async def list_successful_regenerate_sources(self, thread_id, *, user_id):
            return {"hidden-run"}

        async def list_edit_replay_visibility(self, thread_id, *, user_id):
            return SimpleNamespace(hidden_source_run_ids=set(), hidden_attempt_run_ids=set())

    from app.gateway.routers import thread_runs

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                run_event_store=FakeEventStore(),
                run_manager=FakeRunManager(),
            )
        )
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(thread_runs, "THREAD_MESSAGE_PAGE_SCAN_BATCH", 2)
        snapshot, source_last_seq = await build_share_snapshot("thread-1", request=request, user_id="user-1")

    assert [message["content"] for message in snapshot["messages"]] == ["hello"]
    # seq 12 is hidden — the boundary follows raw consumption, not the DTO.
    assert source_last_seq == 12


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


async def test_snapshot_rejects_few_huge_messages_by_rendered_bytes():
    """A thread far under the message count whose renderable text exceeds the
    byte budget must fail 413 too: the persisted snapshot duplicates the
    transcript and every anonymous read deserializes and re-sanitizes it."""

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "human", "content": "x" * 200}), _row(2, {"type": "ai", "content": "y" * 200})], False

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_RENDERED_BYTES", 256)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with pytest.raises(ShareSnapshotTooLarge) as excinfo:
            await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.limit_kind == "rendered-bytes"
    assert excinfo.value.cap == 256


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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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
    # Round 11: the bare path IS the owner-scoped GET/PATCH/DELETE route and
    # carries the internal thread id, so it redacts like the subresource
    # form — the id ends at a query/fragment/whitespace/end boundary.
    assert neutralize("thread /api/threads/8f3a mentioned") == "thread [private artifact omitted] mentioned"


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
        snapshot, _ = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

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


async def test_neutralize_redacts_thread_route_that_ends_at_the_id():
    """The owner-scoped route is equally valid without a trailing slash or
    subresource: the bare ID shape leaks the thread identifier exactly like
    the ``/<segment>`` form, so the ID must end at a path/query/fragment/
    whitespace/end boundary — never only at ``/``."""
    assert _neutralize_private_references("see /api/threads/thread-secret now") == "see [private artifact omitted] now"
    assert _neutralize_private_references("api/threads/thread-secret") == "[private artifact omitted]"
    assert _neutralize_private_references("/api/threads/thread-secret?tab=1") == "[private artifact omitted]"
    assert _neutralize_private_references("/api/threads/thread-secret#frag") == "[private artifact omitted]"
    # markdown destination and label shapes leak the same identifier
    destination = _neutralize_private_references("[link](/api/threads/thread-secret)")
    assert "thread-secret" not in destination
    assert "private artifact omitted" in destination
    assert _neutralize_private_references("[/api/threads/thread-secret](https://example.com/pub)") == "[private artifact omitted]"


async def test_neutralize_mount_name_requires_identifier_boundary():
    """A public sibling path must not be swallowed by an unbounded mount-name
    prefix: ``mnt/user-data`` classifies only when the name ends (end of
    token, query, fragment) or is followed by a path separator — identifier-
    continuing bytes (``user-database``, ``user-data-v2``, ``user-data.backup``)
    are a different, public name."""
    assert _neutralize_private_references("/mnt/user-database/report.md") == "/mnt/user-database/report.md"
    assert _neutralize_private_references("see mnt/user-data-v2/x.png here") == "see mnt/user-data-v2/x.png here"
    assert _neutralize_private_references("/mnt/user-data.backup") == "/mnt/user-data.backup"
    # the real mount still classifies at every accepted boundary
    assert _neutralize_private_references("/mnt/user-data") == "[private artifact omitted]"
    assert _neutralize_private_references("/mnt/user-data?x=1") == "[private artifact omitted]"
    assert _neutralize_private_references("/mnt/user-data#s") == "[private artifact omitted]"


async def test_snapshot_rendered_bytes_cap_counts_encoded_bytes():
    """The budget must measure encoded bytes, not code points: astral-plane
    characters occupy four UTF-8 bytes each, so a transcript far under the
    cap by character count still exceeds the byte budget the persisted
    snapshot actually pays."""

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        # 80 code points, 320 UTF-8 bytes — passes a code-point cap of 256.
        return [_row(1, {"type": "human", "content": "\U0001f389" * 80})], False

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_RENDERED_BYTES", 256)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with pytest.raises(ShareSnapshotTooLarge) as excinfo:
            await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.limit_kind == "rendered-bytes"
    assert excinfo.value.cap == 256


async def test_neutralize_decodes_named_entities_in_private_phrases():
    """Named character references are CommonMark-decoded exactly like the
    numeric forms: ``&period;`` renders as ``.`` and the browser resolves
    ``/api/a/&period;&period;/threads/SECRET`` onto the owner-scoped route,
    so the shadow must decode the ASCII-decoding named entities too."""
    out = _neutralize_private_references("[x](/api/a/&period;&period;/threads/thread-secret)")
    assert "thread-secret" not in out
    assert "private artifact omitted" in out
    assert _neutralize_private_references("raw /api/a/&period;&period;/threads/thread-secret end") == "raw [private artifact omitted] end"
    # named separators and boundaries compose with the numeric forms
    assert _neutralize_private_references("see /api&sol;threads&sol;thread-secret&num;x now") == "see [private artifact omitted] now"
    # a public path keeps its named-entity bytes verbatim
    assert _neutralize_private_references("temperature is 20&deg;C, humidity 50&percnt;") == "temperature is 20&deg;C, humidity 50&percnt;"


async def test_snapshot_does_not_preserve_reasoning_in_fake_code_spans():
    """The code-span protection must follow CommonMark, not just match
    backtick runs: escaped delimiters (``\\````), mismatched run lengths,
    and runs that never close before the paragraph ends do NOT open code
    spans — a renderer shows their content as plain text, so ``<think>``
    blocks hiding there are model reasoning and must be stripped, not
    preserved verbatim into the anonymous snapshot."""
    attacks = {
        "escaped delimiters": "answer \\`<think>secret-reasoning-escaped</think>\\` done",
        "mismatched run lengths": "```<think>secret-reasoning-mismatch</think>``tail",
        "span across paragraphs": "`intro\n\n<think>secret-reasoning-paragraph</think>\n\noutro`",
    }

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        content = "\n\n".join(attacks.values())
        return [_row(1, {"type": "ai", "content": content})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot, _source_last_seq = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    for secret in (
        "secret-reasoning-escaped",
        "secret-reasoning-mismatch",
        "secret-reasoning-paragraph",
    ):
        assert secret not in content, content
    # The visible prose around the attacks survives.
    assert "answer" in content
    assert "outro" in content


def test_resanitize_strips_stored_assistant_reasoning():
    """The read-time rebuild owes the same reasoning guarantee as create:
    an older or sanitizer-defect snapshot carrying a ``<think>`` block must
    not serve it to anonymous readers forever — the assistant filter runs
    again at the public boundary, while real code spans keep their literal
    tags."""
    from app.gateway.shares.snapshot import resanitize_share_snapshot

    stored = {
        "version": 1,
        "messages": [
            {"id": "m1", "role": "assistant", "content": "<think>secret-stored-reasoning</think>visible answer"},
            {"id": "m2", "role": "assistant", "content": "literal ``<think>`` tag in a real span"},
            {"id": "m3", "role": "user", "content": "user text <think>secret-user-side</think> kept raw"},
        ],
    }
    out = resanitize_share_snapshot(stored)
    contents = [message["content"] for message in out["messages"]]
    assert "secret-stored-reasoning" not in contents[0]
    assert "visible answer" in contents[0]
    # A genuinely balanced code span is preserved verbatim.
    assert contents[1] == stored["messages"][1]["content"]
    # The create path never strips user-side tags; the rebuild must not
    # start treating user messages as assistant reasoning either.
    assert contents[2] == stored["messages"][2]["content"]


async def test_snapshot_strips_reasoning_at_block_boundaries():
    """Round-13 adversarial review: a paragraph ends at every block-
    interrupting line (fence, blockquote, list), not only at blank lines —
    an inline span can never reach across one, so ``<think>`` content on
    the far side is reasoning and must be stripped."""
    attacks = {
        "fence interrupt": "a `\n```c\n```\n<think>secret-y</think> ` z",
        "blockquote interrupt": "a `\n> <think>secret-z</think> ` b",
        "list interrupt": "a `\n- item `x`\n<think>secret-t</think> ` y",
    }

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        content = "\n".join(attacks.values())
        return [_row(1, {"type": "ai", "content": content})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot, _seq = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    for secret in ("secret-y", "secret-z", "secret-t"):
        assert secret not in content, content
    # No internal marker bytes or fence destruction may ride along.
    assert "\x00" not in content
    assert "```c\n```" in content


async def test_snapshot_strips_reasoning_behind_fence_regex_divergences():
    """The fence recognizer must follow CommonMark, not one greedy regex:
    an info string containing a backtick is not a fence opener, a closer
    needs at least the opener's length, and fences inside raw-HTML blocks
    are not fences — in every case the swallowed ``<think>`` renders as
    prose and must be stripped."""
    attacks = {
        "info-string backtick": "``` ```\n<think>secret-w</think>\n```\nafter",
        "longer closer": "```\ncode\n`````\n<think>secret-v</think>\n```\ntail",
        "script raw block": "<script>\n```\n</script>\n<think>secret-u</think>\n```\ncode\n```\n",
    }

    # Each attack rides its own message: a preceding unclosed fence would
    # change the parse context of the next one (block structure is not
    # compositional across messages).
    for attack in attacks.values():

        async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None, _content=attack):
            return [_row(1, {"type": "ai", "content": _content})], False

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
            snapshot, _seq = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

        content = snapshot["messages"][0]["content"]
        assert "secret-w" not in content and "secret-v" not in content and "secret-u" not in content, content
        assert "\x00" not in content


def test_resanitize_drops_messages_that_restrip_to_empty():
    """Create-path parity: a stored message whose public text re-strips to
    nothing is dropped, not published as an empty shell."""
    from app.gateway.shares.snapshot import resanitize_share_snapshot

    out = resanitize_share_snapshot(
        {
            "version": 1,
            "messages": [
                {"id": "m1", "role": "assistant", "content": "<think>only-reasoning</think>"},
                {"id": "m2", "role": "assistant", "content": "kept"},
            ],
        }
    )
    assert [message["content"] for message in out["messages"]] == ["kept"]
    assert [message["id"] for message in out["messages"]] == ["m1"]


def test_resanitize_strips_reasoning_behind_hard_break_memo_edge():
    """A backslash hard break followed by a blank line starts a fresh
    paragraph: the later real code span must keep its literal ``<think>``
    tag even though an earlier same-length opener found no closer."""
    from app.gateway.shares.snapshot import resanitize_share_snapshot

    stored = {
        "version": 1,
        "messages": [
            {"id": "m1", "role": "assistant", "content": "``A\n\\\n\n``<think>keep-me</think>`` done"},
        ],
    }
    out = resanitize_share_snapshot(stored)
    assert "keep-me" in out["messages"][0]["content"]


def test_strip_html_blocks_do_not_bridge_spans_or_duplicate_regions():
    """Round-2 adversarial review: (A) an HTML block must terminate the
    paragraph its opener lived in — spans may not bridge it, and regions
    must not be re-appended (the corruption was doubled output); (B) type
    5/7 HTML blocks (CDATA, a complete tag alone) are raw blocks too."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    # A: leak repro — the think after the script block is prose.
    out = strip("a `\n<script>\n</script>\n<think>secret-html</think> ` b")
    assert "secret-html" not in out
    # A: corruption repro — each code span exactly once, no doubling.
    out = strip("x `AAAA`y\n<div>\n\nz `BBBB`w\n")
    assert out.count("AAAA") == 1, out
    assert out.count("BBBB") == 1, out
    # B: type 5 (CDATA) and type 7 (complete tag alone) are raw blocks.
    assert "secret-b7" not in strip("<span>\n`<think>secret-b7</think>`\ntail\n")
    assert "secret-cdata" not in strip("<![CDATA[\n`<think>secret-cdata</think>`\n]]>\n")
    assert "secret-sy" not in strip("<scripty>\n`<think>secret-sy</think>`\n")


def test_strip_preserves_code_in_heading_and_selfclosed_script_fence():
    """Round-2 over-strip fixes: a type-1 block that closes on its opening
    line does not swallow the rest of the document, and inline code inside
    a heading is still code."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    fence_after_selfclosed = strip("<script>x</script>\n```\n<think>in-code</think>\n```\n")
    assert "in-code" in fence_after_selfclosed
    assert "in-heading" in strip("# `x<think>in-heading</think>x`")


def test_strip_preserves_indented_code_blocks():
    """Four-space-indented lines after a blank line are an indented code
    block — the renderer shows them literally, so their tags survive."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    out = strip("intro\n\n    <think>in-indented</think>\n\noutro")
    assert "in-indented" in out


def test_strip_restore_is_linear_on_many_regions():
    """The restore must rejoin in one pass: ~131k regions from alternating
    fence lines used to cost a full-string scan per region (quadratic on
    every anonymous read)."""
    import time

    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    big = "```\ncode\n```\n" * 21_000  # ~294KB, ~42k protected regions
    started = time.monotonic()
    out = strip(big)
    elapsed = time.monotonic() - started
    assert out.count("```") == 42_000
    assert elapsed < 2.0, elapsed


async def test_snapshot_suppresses_document_protection_in_list_context():
    """Round-4 adversarial review: item indents approximate document indents
    badly, and every misread leaks — an item fence kept open past its item,
    a dedented fence line eaten as fence content, item-continuation indents
    taken as document code, a quote→list transition bridged, and a nested
    empty quote line missed as a paragraph split. Once a list or quote line
    is seen, document-level fence and indented protection is suppressed
    (strip instead — the module's leak-vs-loss asymmetry)."""
    attacks = {
        "item fence": "- i\n   ```\n<think>s-lf</think>\n   ```",
        "item indented": "- i\n\n    <think>s-li4</think>",
        "quote-to-list": "> `a\nplain <think>s-ql</think>x\n- `b`",
        "nested empty quote": "> `a\n  >\n<think>s-bq</think>b",
    }

    # Each attack rides its own message (block structure is not
    # compositional across concatenated attacks).
    for attack in attacks.values():

        async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None, _content=attack):
            return [_row(1, {"type": "ai", "content": _content})], False

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
            snapshot, _seq = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

        content = snapshot["messages"][0]["content"]
        for secret in ("s-lf", "s-li4", "s-ql", "s-bq"):
            assert secret not in content, (attack, content)
        assert "\x00" not in content


def test_strip_indented_eligible_after_selfclosed_html_block():
    """A self-closed HTML block is a leaf-block boundary: the indented line
    after it is an indented code block, not paragraph text."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    out = strip("<script>x</script>\n    <think>s-oc</think>")
    assert "s-oc" in out


def test_strip_quote_marker_depth_interrupts_and_dedent_continues():
    """Round-5: a deeper-nested quote line interrupts the outer quote's
    paragraph (its ``<think>`` is prose and must strip), while the dedent
    mirror is lazy continuation whose real span is preserved."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    deeper = strip("> `a\nplain <think>s-dq</think>x\n> > `b`")
    assert "s-dq" not in deeper
    dedent = strip("> > `a\nplain <think>s-keep</think>x\n> `b`")
    assert "s-keep" in dedent


def test_strip_cross_tag_raw_text_close_strips_reasoning():
    """CommonMark 0.31.2 §4.6: a raw-text block's end tag "need not match
    the start tag" — `</script>` closes an open `<pre>` (verified against
    the shipped renderer, micromark). The bot's per-tag reading is a
    misreading; the cross-tag close is a real paragraph boundary and the
    `<think>` behind it must strip, never ride a fence-desync protection."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    attack = "<pre>\n</script>\n```\n</pre>\n```\n<think>secret-cross-tag</think> plain\n```\n"
    out = strip(attack)
    assert "secret-cross-tag" not in out, out


def test_strip_invalid_type7_tags_do_not_open_html_blocks():
    """A type-7 HTML block requires a *complete* tag per the HTML grammar:
    a syntactically invalid opener such as ``<span =foo>`` is an ordinary
    paragraph line, the fence behind it is a real code fence whose closer
    ends the block, and the reasoning after the fence is stripped — not
    preserved behind a phantom HTML block. A well-formed tag with a quoted
    attribute carrying ``>`` still opens the block (markdown-it behavior)."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    invalid = "<span =foo>\n```\ncode\n\n```\n<think>secret-invalid-type7</think> visible"
    out = strip(invalid)
    assert "secret-invalid-type7" not in out, out
    assert "visible" in out

    valid = '<span data-x="a>b">\n```\ncode\n\n```\n<think>secret-real-html</think> after'
    kept = strip(valid)
    assert "secret-real-html" in kept, kept


def test_unmatched_backtick_scan_stays_linear_on_growing_runs():
    """Successively longer unmatched backtick runs must not rescan the
    paragraph once per distinct length: the span scan indexes delimiter
    runs in one pass, so a hostile paragraph near the share budget stays
    subsecond during creation and every anonymous resolution instead of
    blocking the ASGI event loop (80 KiB already cost ~1s pre-fix)."""
    from time import monotonic

    from app.gateway.shares.snapshot import _commonmark_inline_code_spans

    runs = " ".join("`" * length for length in range(2, 1200))
    text = runs + " `real` tail"

    started = monotonic()
    spans = _commonmark_inline_code_spans(text)
    elapsed = monotonic() - started

    # Every growing run is unmatched; the only real span is the trailing pair.
    assert [text[start:close] for start, close in spans] == ["`real`"]
    assert elapsed < 5.0


def test_strip_invalid_html_openers_do_not_open_blocks_all_types():
    """CommonMark opener sweep across every HTML block type: only a
    well-formed opener may open a block. An invalid opener is ordinary
    paragraph text — the fence behind it is a real code fence whose closer
    ends the block, and the reasoning after that closer is stripped. A
    valid opener consumes the first fence as HTML content, so the second
    fence opens a real code fence and the reasoning inside it is preserved
    (types 1-5 close on their own closer line; types 6-7 close on the
    blank line)."""
    from app.gateway.shares.snapshot import (
        _strip_think_blocks_outside_markdown_code as strip,
    )

    # (label, opener line, block-close line ("" = blank line), valid?)
    cases = (
        ("type1", "<script>", "</script>", True),
        ("type1-invalid", "<script=foo>", "</script>", False),
        ("type2", "<!-- x", "-->", True),
        ("type2-invalid", "<!-x", "-->", False),
        ("type3", "<?php echo;", "?>", True),
        ("type4", "<!DOCTYPE", ">", True),
        ("type4-invalid", "<!foo", ">", False),
        ("type5", "<![CDATA[x", "]]>", True),
        ("type5-invalid", "<![cdata[x", "]]>", False),
        ("type6", "<div>", "", True),
        ("type6-invalid", "<div=x>", "", False),
        ("type7", "<span>", "", True),
        ("type7-invalid", "<span =foo>", "", False),
    )
    for label, opener, closer, valid in cases:
        lines = [opener, "```", "code", closer if closer else "", "```", f"<think>secret-{label}</think> visible"]
        out = strip("\n".join(lines))
        if valid:
            assert f"secret-{label}" in out, (label, out)
        else:
            assert f"secret-{label}" not in out, (label, out)
