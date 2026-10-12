"""Fixed zero-model B fixture config; preserve signed task snapshot outside resident."""

import argparse
import json
import os
from pathlib import Path
import stat

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
GROUPS = [
    {
        "name": "execution",
        "submit_tool": "submit",
        "status_tool": "status",
        "cancel_tool": "cancel",
    }
]
INTERCEPTORS = ["ecs_executor.interceptor:build_execution_scope_interceptor"]


def load(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return json.loads(path.read_text())


def write(path, value, replace=False):
    temp = path.with_name(path.name + ".b-new") if replace else path
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, indent=2)
        f.write("\n")
    if replace:
        os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "bind"])
    phase = parser.parse_args().phase
    assert os.getuid() == 0
    for directory in [PRIVATE, OPERATOR]:
        assert all(not p.is_symlink() for p in [directory, *directory.parents])
        assert (
            directory.stat().st_uid == 0
            and stat.S_IMODE(directory.stat().st_mode) == 0o700
        )
    native = load(PRIVATE / "native.json")
    extensions = load(PRIVATE / "extensions.json")
    assert native["mcp_tasks"]["enabled"] is False
    server = extensions["mcpServers"]["ecs"]
    assert (
        server["user_auth"]["enabled"] and server["user_auth"]["on_missing"] == "deny"
    )
    snapshot_path = OPERATOR / "b-extensions.json"
    if phase == "prepare":
        if snapshot_path.exists() or snapshot_path.is_symlink():
            snapshot = load(snapshot_path)
            expected = json.loads(json.dumps(snapshot))
            expected["mcpInterceptors"] = []
            expected["mcpServers"]["ecs"]["task_toolsets"] = []
            assert extensions == snapshot or extensions == expected
        else:
            assert (
                server["task_toolsets"] == GROUPS
                and extensions["mcpInterceptors"] == INTERCEPTORS
            )
            write(snapshot_path, extensions)
            snapshot = extensions
        extensions = json.loads(json.dumps(snapshot))
        extensions["mcpInterceptors"] = []
        extensions["mcpServers"]["ecs"]["task_toolsets"] = []
        write(PRIVATE / "extensions.json", extensions, replace=True)
        envelope = load(OPERATOR / "worker-envelope.json")
        envelope["files"]["extensions.json"] = json.dumps(extensions, indent=2) + "\n"
        envelope["files"]["native.json"] = json.dumps(native, indent=2) + "\n"
        write(OPERATOR / "worker-envelope.json", envelope, replace=True)
    else:
        snapshot = load(snapshot_path)
        assert (
            snapshot["mcpInterceptors"] == INTERCEPTORS
            and snapshot["mcpServers"]["ecs"]["task_toolsets"] == GROUPS
        )
        owner = load(OPERATOR / "owner.json")["owner_id"]
        assert server["user_auth"]["users"] == {owner: "$ECS_OWNER_HEADER"}
        snapshot["mcpServers"]["ecs"]["user_auth"]["users"] = server["user_auth"][
            "users"
        ]
        write(snapshot_path, snapshot, replace=True)
    print(
        json.dumps(
            {
                "b_fixture_phase": phase,
                "gateway_notification_enabled": False,
                "gateway_scope_interceptor": False,
                "gateway_task_toolsets": False,
                "b_snapshot_signed_interceptor": True,
                "models_called": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned B fixture configuration refused; private state retained"
        ) from None
