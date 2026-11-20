"""Live tests for the boxd sandbox provider against real boxd machines.

Skipped unless explicitly enabled; they create and delete real machines:

    DEER_FLOW_RUN_LIVE_TESTS=1 BOXD_API_KEY=... PYTHONPATH=. uv run pytest tests/test_boxd_sandbox_live.py -v -s

Optional: ``BOXD_ORG``, ``BOXD_TEST_REGION`` (fra or nyc), ``BOXD_TEST_NAME_PREFIX``
(default ``deer-flow-test-``) and ``BOXD_TEST_LABELS`` (``key=value,key=value``).
The module shares one provider; its shutdown deletes every machine the tests
created and checks that each one is gone.
"""

from __future__ import annotations

import hashlib
import os
import time
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

_skip_reason = None
if os.environ.get("CI"):
    _skip_reason = "Live tests skipped in CI"
elif os.environ.get("DEER_FLOW_RUN_LIVE_TESTS") != "1":
    _skip_reason = "Set DEER_FLOW_RUN_LIVE_TESTS=1 to run live tests with real external APIs"
elif not os.environ.get("BOXD_API_KEY"):
    _skip_reason = "Set BOXD_API_KEY to run the boxd live tests"
if _skip_reason:
    pytest.skip(_skip_reason, allow_module_level=True)

pytest.importorskip("boxd")

from deerflow.community.boxd_sandbox import BoxdSandboxProvider  # noqa: E402
from deerflow.config.paths import Paths  # noqa: E402

THREAD = "live-thread"
USER = "live-user"


def _labels() -> dict[str, str]:
    raw = os.environ.get("BOXD_TEST_LABELS", "")
    return dict(item.split("=", 1) for item in raw.split(",") if "=" in item)


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory):
    paths = Paths(base_dir=tmp_path_factory.mktemp("deer-flow-home"))
    sandbox_options = {
        "use": "deerflow.community.boxd_sandbox:BoxdSandboxProvider",
        "org": os.environ.get("BOXD_ORG"),
        "region": os.environ.get("BOXD_TEST_REGION", "fra"),
        "vcpu": 1,
        "name_prefix": os.environ.get("BOXD_TEST_NAME_PREFIX", "deer-flow-test-"),
        "labels": _labels(),
        "idle_timeout": 0,
        "environment": {"DEERFLOW_LIVE": "static"},
    }
    config = types.SimpleNamespace(sandbox=types.SimpleNamespace(**sandbox_options), skills=types.SimpleNamespace(container_path="/mnt/skills"))
    patch = pytest.MonkeyPatch()
    patch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox_provider.get_app_config", lambda: config)
    patch.setattr("deerflow.config.paths.get_paths", lambda: paths)

    def no_shared_skills(*args, **kwargs):
        raise RuntimeError("shared skills are not part of this test")

    patch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", no_shared_skills)
    uploads = paths.sandbox_uploads_dir(THREAD, user_id=USER)
    uploads.mkdir(parents=True)
    (uploads / "input.csv").write_text("a,b\n1,2\n")

    provider = BoxdSandboxProvider()
    started = time.monotonic()
    sandbox_id = provider.acquire(THREAD, user_id=USER)
    sandbox = provider.get(sandbox_id)
    print(f"\nacquire (create, ready, bootstrap, restore): {time.monotonic() - started:.1f}s, machine {sandbox.machine_id}")
    machine_ids = {sandbox.machine_id}
    yield types.SimpleNamespace(provider=provider, paths=paths, sandbox_id=sandbox_id, machine_ids=machine_ids)

    client = provider._get_client()
    provider.shutdown()
    for machine_id in machine_ids:
        with pytest.raises(Exception) as excinfo:
            client.machines.get(machine_id, region=sandbox_options["region"])
        assert type(excinfo.value).__name__ == "NotFoundError"
        print(f"machine {machine_id} deleted by shutdown")
    patch.undo()


def _sandbox(live):
    return live.provider.get(live.sandbox_id)


def test_machine_is_isolated(live) -> None:
    client = live.provider._get_client()
    machine = client.machines.get(_sandbox(live).machine_id)
    assert machine.networking.isolated is True
    assert machine.labels["deer-flow-scope"] == live.sandbox_id


def test_restored_upload_is_visible(live) -> None:
    assert _sandbox(live).read_file("/mnt/user-data/uploads/input.csv") == "a,b\n1,2\n"


def test_exec_env_streams_and_exit_code(live) -> None:
    sandbox = _sandbox(live)
    started = time.monotonic()
    output = sandbox.execute_command('echo "$DEERFLOW_LIVE $REQUEST_TOKEN"; echo warn >&2; exit 3', env={"REQUEST_TOKEN": "per-call"})
    print(f"exec: {time.monotonic() - started:.2f}s")
    assert output == "static per-call\n\nwarn\n\nExit Code: 3"
    assert sandbox.execute_command("cat") == "(no output)"  # stdin is closed


def test_timeout_keeps_partial_output(live) -> None:
    output = _sandbox(live).execute_command("echo before; sleep 30; echo after", timeout=2)
    assert output.startswith("before") and "after" not in output
    assert output.endswith("Exit Code: 124")


def test_background_process_survives_between_calls(live) -> None:
    sandbox = _sandbox(live)
    sandbox.execute_command("nohup sleep 300 >/dev/null 2>&1 & echo $! > /mnt/user-data/workspace/bg.pid")
    output = sandbox.execute_command("kill -0 $(cat /mnt/user-data/workspace/bg.pid) && echo alive")
    assert output.strip() == "alive"


def test_five_mib_round_trip(live) -> None:
    sandbox = _sandbox(live)
    data = os.urandom(5 * 1024 * 1024)
    started = time.monotonic()
    sandbox.update_file("/mnt/user-data/workspace/blob.bin", data)
    got = sandbox.download_file("/mnt/user-data/workspace/blob.bin")
    print(f"5 MiB up + down: {time.monotonic() - started:.2f}s")
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256(data).hexdigest()
    with pytest.raises(OSError):
        sandbox.download_file("/mnt/user-data/workspace/blob.bin", max_bytes=1024)


def test_write_append_and_read(live) -> None:
    sandbox = _sandbox(live)
    sandbox.write_file("/mnt/user-data/workspace/new/appended.txt", "first\n", append=True)
    sandbox.write_file("/mnt/user-data/workspace/new/appended.txt", "second\n", append=True)
    assert sandbox.read_file("/mnt/user-data/workspace/new/appended.txt") == "first\nsecond\n"
    assert sandbox.read_file("/mnt/user-data/workspace/new/appended.txt", start_line=2, end_line=2) == "second"
    assert sandbox.read_file("/mnt/user-data/workspace/missing.txt").startswith("Error:")


def test_search_tools(live) -> None:
    sandbox = _sandbox(live)
    sandbox.write_file("/mnt/user-data/workspace/src/report:2026.txt", "alpha\nneedle here\n")
    sandbox.write_file("/mnt/user-data/workspace/src/main.py", "needle = 1\n")
    matches, _ = sandbox.grep("/mnt/user-data/workspace/src", "needle")
    assert sorted((Path(m.path).name, m.line_number) for m in matches) == [("main.py", 1), ("report:2026.txt", 2)]
    found, _ = sandbox.glob("/mnt/user-data/workspace", "**/*.py")
    assert found == ["/mnt/user-data/workspace/src/main.py"]
    assert "/mnt/user-data/workspace/src/main.py" in sandbox.list_dir("/mnt/user-data/workspace")


def test_release_mirrors_outputs_and_reclaims_same_machine(live) -> None:
    sandbox = _sandbox(live)
    machine_id = sandbox.machine_id
    sandbox.execute_command("mkdir -p /mnt/user-data/outputs/charts && echo '# Report' > /mnt/user-data/outputs/report.md && printf png > /mnt/user-data/outputs/charts/a.png")
    live.provider.release(live.sandbox_id)
    outputs = live.paths.sandbox_outputs_dir(THREAD, user_id=USER)
    assert (outputs / "report.md").read_text() == "# Report\n"
    assert (outputs / "charts" / "a.png").read_bytes() == b"png"
    started = time.monotonic()
    assert live.provider.acquire(THREAD, user_id=USER) == live.sandbox_id
    print(f"warm reclaim: {time.monotonic() - started:.2f}s")
    assert _sandbox(live).machine_id == machine_id


def test_stopped_machine_is_started_on_next_call(live) -> None:
    sandbox = _sandbox(live)
    client = live.provider._get_client()
    client.machines.stop(sandbox.machine_id)
    started = time.monotonic()
    # A command that meets a stopped machine starts it but is not repeated.
    assert "run it again" in sandbox.execute_command("echo once >> /mnt/user-data/workspace/ran.txt")
    print(f"start after stop: {time.monotonic() - started:.1f}s")
    assert sandbox.execute_command("cat /mnt/user-data/workspace/new/appended.txt") == "first\nsecond\n"
    assert sandbox.read_file("/mnt/user-data/workspace/ran.txt").startswith("Error:")
    client.machines.stop(sandbox.machine_id)
    # A file read is repeated once the machine runs again.
    assert sandbox.read_file("/mnt/user-data/workspace/new/appended.txt") == "first\nsecond\n"


def test_wrong_api_key_fails_clearly(live) -> None:
    from boxd import Boxd

    with pytest.raises(Exception) as excinfo:
        Boxd(api_key="not-a-real-key", region=os.environ.get("BOXD_TEST_REGION", "fra")).machines.get(_sandbox(live).machine_id)
    assert type(excinfo.value).__name__ == "AuthenticationError"
