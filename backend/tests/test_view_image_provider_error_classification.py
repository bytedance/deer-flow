import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

from deerflow.agents.thread_state import ViewedImageData
from deerflow.tools.builtins.view_image_tool import _is_file_not_found_error, view_image_tool

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class _HttpNotFoundError(Exception):
    status_code = 404


class _ProviderFileNotFoundError(Exception):
    pass


_ProviderFileNotFoundError.__name__ = "FileNotFoundError"


class _HttpMissingSandbox:
    id = "remote-new"

    def __init__(self) -> None:
        self.downloads: list[str] = []

    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        try:
            raise _HttpNotFoundError("not found")
        except _HttpNotFoundError as error:
            raise OSError(f"cannot read '{path}' from remote provider") from error


class _Provider:
    def __init__(self, sandbox: _HttpMissingSandbox) -> None:
        self.sandbox = sandbox

    def get(self, sandbox_id: str):
        return self.sandbox if sandbox_id == self.sandbox.id else None


def _thread_data(tmp_path: Path) -> dict[str, str]:
    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    workspace = user_data / "workspace"
    uploads = user_data / "uploads"
    outputs = user_data / "outputs"
    for directory in (workspace, uploads, outputs):
        directory.mkdir(parents=True)
    return {
        "workspace_path": str(workspace),
        "uploads_path": str(uploads),
        "outputs_path": str(outputs),
    }


def test_classifier_accepts_explicit_http_404_cause():
    try:
        try:
            raise _HttpNotFoundError("not found")
        except _HttpNotFoundError as cause:
            raise OSError("wrapped remote read failure") from cause
    except OSError as error:
        assert _is_file_not_found_error(error)


def test_classifier_accepts_provider_defined_file_not_found_type():
    try:
        raise _ProviderFileNotFoundError("not found")
    except _ProviderFileNotFoundError as error:
        assert _is_file_not_found_error(error)


def test_classifier_ignores_implicit_exception_context():
    try:
        try:
            raise FileNotFoundError("unrelated cleanup miss")
        except FileNotFoundError:
            raise OSError("transport timeout")
    except OSError as error:
        assert error.__cause__ is None
        assert isinstance(error.__context__, FileNotFoundError)
        assert not _is_file_not_found_error(error)


def test_http_404_replacement_sandbox_recovers_verified_host_copy(tmp_path, monkeypatch):
    thread_data = _thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _HttpMissingSandbox()
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: _Provider(sandbox),
    )
    runtime = SimpleNamespace(
        state={
            "thread_data": thread_data,
            "sandbox": {"sandbox_id": sandbox.id},
            "viewed_images": {
                "/mnt/user-data/outputs/plot.png": {
                    "mime_type": "image/png",
                    "size": len(PNG_BYTES),
                    "actual_path": str(host_path),
                    "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
                    "source_sandbox_id": "remote-old",
                }
            },
        },
        context={"thread_id": "thread-1"},
        config={},
    )

    result = view_image_tool.func(
        runtime=runtime,
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-http-not-found",
    )

    assert result.update["messages"][0].content == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/outputs/plot.png"]
    assert viewed["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert "source_sandbox_id" not in viewed
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_viewed_image_state_contract_includes_provenance_keys():
    assert "sha256" in ViewedImageData.__required_keys__
    assert "source_sandbox_id" in ViewedImageData.__optional_keys__
