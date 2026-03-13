"""PoC tests for trusted-link attachment resolver middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from src.agents.middlewares.attachments_resolver_middleware import AttachmentsResolverMiddleware

THREAD_ID = "thread-xyz"


def _runtime(thread_id: str = THREAD_ID) -> MagicMock:
    rt = MagicMock()
    rt.context = {"thread_id": thread_id}
    return rt


def test_before_agent_resolves_trusted_link_into_files_metadata() -> None:
    mw = AttachmentsResolverMiddleware()

    message = HumanMessage(
        content="analyze this",
        additional_kwargs={
            "attachments": [
                {
                    "type": "trusted_link",
                    "url": "https://cdn.example.com/path/image.png",
                    "filename": "image.png",
                    "mime_type": "image/png",
                }
            ]
        },
    )
    state = {"messages": [message]}

    backend = MagicMock()
    with (
        patch.object(mw, "_fetch_bytes", return_value=b"png-bytes"),
        patch("src.agents.middlewares.attachments_resolver_middleware.get_thread_file_backend", return_value=backend),
        patch("src.agents.middlewares.attachments_resolver_middleware.materialize_upload_to_local_cache"),
    ):
        update = mw.before_agent(state, _runtime())

    assert update is not None
    updated_msg = update["messages"][-1]
    files = updated_msg.additional_kwargs.get("files")
    assert isinstance(files, list)
    assert len(files) == 1
    assert files[0]["filename"] == "image.png"
    assert files[0]["path"] == "/mnt/user-data/uploads/image.png"
    assert files[0]["size"] == len(b"png-bytes")

    backend.put_virtual_file.assert_called_once_with(THREAD_ID, "/mnt/user-data/uploads/image.png", b"png-bytes")


def test_before_agent_raises_on_trusted_link_without_url() -> None:
    mw = AttachmentsResolverMiddleware()

    message = HumanMessage(
        content="analyze this",
        additional_kwargs={"attachments": [{"type": "trusted_link", "filename": "x.png"}]},
    )
    state = {"messages": [message]}

    try:
        mw.before_agent(state, _runtime())
    except RuntimeError as exc:
        assert "requires non-empty url" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing trusted link url")
