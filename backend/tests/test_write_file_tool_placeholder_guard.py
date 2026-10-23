"""Placeholder-guard tests for write_file_tool (issue #7319).

The tool-output budget middleware elides a superseded ``write_file`` payload in
the model-bound request and replaces it with a deterministic placeholder. That
placeholder is visible in the model's own history, so the model can imitate it
and submit it as real content: #7319 reports a delivered file that was 194 bytes
of placeholder text, written 16 s after the previous step with a character count
that matched no earlier write.

These tests pin the guard that refuses that write. Like the size-guard tests
they run against the tool's internal check with the sandbox stubbed out, so the
rejection path never touches a filesystem.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.sandbox import tools as tools_module
from deerflow.sandbox.tools import write_file_tool

# Spelled out rather than imported so the rejection tests fail on base for the
# right reason (no guard) instead of erroring on a missing import. The last test
# below pins this literal to the framework constant that renders the placeholder.
PLACEHOLDER = "[content elided: {chars} chars; this write_file call succeeded and the file was read or modified again afterwards, so the on-disk file is the current version; call read_file on its path to see it]"


def _call_write_file(*, content: str, append: bool = False) -> str:
    """Invoke write_file_tool with the sandbox initialisation chain stubbed out."""
    fn = getattr(write_file_tool, "func", write_file_tool)
    runtime = MagicMock()

    with (
        patch.object(tools_module, "ensure_sandbox_initialized") as mock_ensure,
        patch.object(tools_module, "ensure_thread_directories_exist"),
        patch.object(tools_module, "is_local_sandbox", return_value=False),
        patch.object(tools_module, "get_file_operation_lock") as mock_lock,
    ):
        sandbox = MagicMock()
        sandbox.write_file = MagicMock()
        mock_ensure.return_value = sandbox
        mock_lock.return_value.__enter__ = MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        result = fn(
            runtime=runtime,
            description="test write",
            path="/tmp/report.md",
            content=content,
            append=append,
        )
        return result


@pytest.mark.parametrize("chars", [0, 194, 10686])
def test_exact_placeholder_is_rejected(chars):
    """The reported failure: the model writes back the placeholder verbatim."""
    placeholder = PLACEHOLDER.format(chars=chars)

    result = _call_write_file(content=placeholder)

    assert result.startswith("Error:")
    assert "placeholder" in result
    # The message has to tell the model how to recover, not just refuse.
    assert "read_file" in result


def test_placeholder_with_surrounding_whitespace_is_rejected():
    """Trailing newlines from a heredoc-style call must not slip past the guard."""
    result = _call_write_file(content="\n  " + PLACEHOLDER.format(chars=5000) + "\n\n")

    assert result.startswith("Error:")


def test_placeholder_inside_a_document_is_left_alone():
    """A document that merely quotes the placeholder is real work, not the failure.

    The reported bug is a deliverable that *is* the placeholder. A substring
    guard would also block editing this repo's own ``constants.py`` and
    persistence docs, which contain the template verbatim.
    """
    body = "# Report\n\n" + PLACEHOLDER.format(chars=5000) + "\n\ntail\n"

    assert _call_write_file(content=body) == "OK"


@pytest.mark.parametrize(
    "content",
    [
        "[content elided: example for a user guide]\nThis is real file content.\n",
        PLACEHOLDER.format(chars=5000) + "\nThis is real file content.\n",
        PLACEHOLDER.format(chars=5000) + " additional text",
        PLACEHOLDER,
        PLACEHOLDER.format(chars=""),
        PLACEHOLDER.format(chars="-1"),
        PLACEHOLDER.format(chars="1.5"),
        PLACEHOLDER.format(chars="example"),
        PLACEHOLDER.format(chars="１２３"),
        PLACEHOLDER.format(chars=5000)[:-1],
    ],
    ids=["prefix-only", "leading-quote", "trailing-text", "template", "empty-count", "negative-count", "decimal-count", "text-count", "unicode-count", "missing-suffix"],
)
def test_placeholder_prefix_in_real_content_is_allowed(content: str) -> None:
    assert tools_module._reject_elision_placeholder_content(content) is None


def test_rejection_does_not_reach_the_sandbox():
    """The guard runs before any filesystem work, so a rejected write leaves no trace."""
    fn = getattr(write_file_tool, "func", write_file_tool)
    runtime = MagicMock()

    with (
        patch.object(tools_module, "ensure_sandbox_initialized") as mock_ensure,
        patch.object(tools_module, "ensure_thread_directories_exist"),
        patch.object(tools_module, "is_local_sandbox", return_value=False),
        patch.object(tools_module, "get_file_operation_lock") as mock_lock,
    ):
        sandbox = MagicMock()
        mock_ensure.return_value = sandbox
        mock_lock.return_value.__enter__ = MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        result = fn(
            runtime=runtime,
            description="test write",
            path="/tmp/report.md",
            content=PLACEHOLDER.format(chars=5000),
            append=False,
        )

    assert result.startswith("Error:")
    sandbox.write_file.assert_not_called()
    mock_lock.assert_not_called()


def test_append_mode_is_guarded_too():
    """``append=True`` bypasses the size cap, not the placeholder guard."""
    result = _call_write_file(content=PLACEHOLDER.format(chars=9000), append=True)

    assert result.startswith("Error:")


@pytest.mark.parametrize(
    "content",
    [
        "content elided: 5000 chars",  # no leading bracket
        "[content elided 5000 chars]",  # no colon
        "[Content Elided: 5000 chars]",  # different case
        "# Report\n\nNormal prose that mentions elision.\n",
        "See constants.py for WRITE_ELISION_PLACEHOLDER_TEMPLATE.",
    ],
    ids=["no-bracket", "no-colon", "different-case", "ordinary-prose", "mentions-the-name"],
)
def test_near_miss_content_still_passes(content):
    """The guard matches the framework's exact sentinel, not a loose ``elided`` keyword."""
    assert _call_write_file(content=content) == "OK"


def test_literal_matches_the_constant_the_middleware_renders():
    """The guard is only useful if it matches what the middleware actually writes.

    ``PLACEHOLDER`` is a local copy so the rejection tests can fail on base for
    the right reason; this pins it to the shared constant the middleware uses to
    render the placeholder, so the two cannot drift.
    """
    from deerflow.agents.middlewares.tool_output_budget_middleware import _ELIDED_WRITE_CONTENT_TEMPLATE
    from deerflow.constants import WRITE_ELISION_PLACEHOLDER_TEMPLATE

    assert PLACEHOLDER == WRITE_ELISION_PLACEHOLDER_TEMPLATE
    assert _ELIDED_WRITE_CONTENT_TEMPLATE == WRITE_ELISION_PLACEHOLDER_TEMPLATE
