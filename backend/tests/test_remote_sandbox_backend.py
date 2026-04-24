import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

agent_sandbox_mock = MagicMock()
agent_sandbox_mock.Sandbox = MagicMock
sys.modules.setdefault("agent_sandbox", agent_sandbox_mock)


def _remote_backend_cls():
    return importlib.import_module("deerflow.community.aio_sandbox.remote_backend").RemoteSandboxBackend


def test_provisioner_create_sends_configured_mounts():
    RemoteSandboxBackend = _remote_backend_cls()
    backend = RemoteSandboxBackend(
        "http://provisioner:8002/",
        config_mounts=[
            SimpleNamespace(
                host_path="/host/shared",
                container_path="/mnt/shared",
                read_only=True,
            )
        ],
    )

    with patch("deerflow.community.aio_sandbox.remote_backend.requests.post") as post:
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"sandbox_url": "http://sandbox.local"}

        backend.create("thread-1", "sandbox-1")

    assert post.call_args.kwargs["json"] == {
        "sandbox_id": "sandbox-1",
        "thread_id": "thread-1",
        "extra_mounts": [
            {
                "host_path": "/host/shared",
                "container_path": "/mnt/shared",
                "read_only": True,
            }
        ],
    }


def test_provisioner_create_normalizes_configured_mounts():
    RemoteSandboxBackend = _remote_backend_cls()
    backend = RemoteSandboxBackend(
        "http://provisioner:8002/",
        config_mounts=[
            SimpleNamespace(
                host_path="/host/user-data",
                container_path="/mnt/user-data/workspace",
                read_only=False,
            ),
            SimpleNamespace(
                host_path="/host/skills",
                container_path="/mnt/skills",
                read_only=True,
            ),
            SimpleNamespace(
                host_path="/host/shared",
                container_path="/mnt/shared/",
                read_only=True,
            ),
            SimpleNamespace(
                host_path="/host/duplicate",
                container_path="/mnt/shared",
                read_only=False,
            ),
        ],
    )

    with patch("deerflow.community.aio_sandbox.remote_backend.requests.post") as post:
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"sandbox_url": "http://sandbox.local"}

        backend.create("thread-1", "sandbox-1")

    assert post.call_args.kwargs["json"]["extra_mounts"] == [
        {
            "host_path": "/host/shared",
            "container_path": "/mnt/shared",
            "read_only": True,
        }
    ]


def test_provisioner_create_sends_runtime_mounts_not_already_created_by_provisioner():
    RemoteSandboxBackend = _remote_backend_cls()
    backend = RemoteSandboxBackend("http://provisioner:8002")

    with patch("deerflow.community.aio_sandbox.remote_backend.requests.post") as post:
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"sandbox_url": "http://sandbox.local"}

        backend.create(
            "thread-1",
            "sandbox-1",
            extra_mounts=[
                ("/host/thread/workspace", "/mnt/user-data/workspace", False),
                ("/host/skills", "/mnt/skills", True),
                ("/host/acp", "/mnt/acp-workspace", True),
            ],
        )

    assert post.call_args.kwargs["json"]["extra_mounts"] == [
        {
            "host_path": "/host/acp",
            "container_path": "/mnt/acp-workspace",
            "read_only": True,
        }
    ]
