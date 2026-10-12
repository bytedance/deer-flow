"""Restore only the selected DeepSeek model and original signed native MCP groups."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

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
REFERENCE = "DEEPSEEK_API_KEY"


def load(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return json.loads(path.read_text())


def write(path, data, replace=False):
    if not replace and (path.exists() or path.is_symlink()):
        load(path)
        assert path.read_bytes() == data
        return
    if replace:
        s = path.lstat()
        assert (
            stat.S_ISREG(s.st_mode)
            and s.st_uid == 0
            and stat.S_IMODE(s.st_mode) == 0o600
        )
    temp = path.with_name(path.name + ".c-new") if replace else path
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if replace:
        os.replace(temp, path)


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def validate(value):
    assert set(value) == {"model", "environment"}
    model = value["model"]
    assert model["name"] == model["model"] == "deepseek-chat"
    assert model["use"] == "deerflow.models.patched_deepseek:PatchedChatDeepSeek"
    assert model["api_key"] == "$" + REFERENCE and "base_url" not in model
    assert set(re.findall(r'"\$([A-Za-z_][A-Za-z0-9_]*)"', json.dumps(model))) == {
        REFERENCE
    }
    assert set(value["environment"]) == {REFERENCE}
    key = value["environment"][REFERENCE]
    assert isinstance(key, str) and re.fullmatch(r"sk-[A-Za-z0-9_-]+", key)
    assert set(model) == {
        "api_key",
        "display_name",
        "max_tokens",
        "model",
        "name",
        "supports_thinking",
        "supports_vision",
        "use",
    }
    return value


def apply(value, role, owner):
    value = validate(value)
    native_path = PRIVATE / "native.json"
    native = load(native_path)
    extensions_path = PRIVATE / "extensions.json"
    extensions = load(extensions_path)
    server = extensions["mcpServers"]["ecs"]
    assert server["user_auth"]["users"] == {owner: "$ECS_OWNER_HEADER"}
    assert (
        server["user_auth"]["enabled"] and server["user_auth"]["on_missing"] == "deny"
    )
    assert server["task_toolsets"] in [[], GROUPS]
    assert extensions["mcpInterceptors"] in [[], INTERCEPTORS]
    native["models"] = [value["model"]]
    native["mcp_tasks"]["enabled"] = True
    server["task_toolsets"] = GROUPS
    extensions["mcpInterceptors"] = INTERCEPTORS
    env_path = PRIVATE / (role + ".env")
    s = env_path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    rows = env_path.read_text().splitlines()
    assert all("=" in line and "\x00" not in line and "\r" not in line for line in rows)
    names = [line.split("=", 1)[0] for line in rows]
    assert len(names) == len(set(names))
    if role == "worker":
        assert not (
            {
                "POSTGRES_PASSWORD",
                "ECS_EXECUTOR_DATABASE_URL",
                "ECS_NATIVE_EXECUTOR_DATABASE_URL",
            }
            & set(names)
        )
    rows = [line for line in rows if line.split("=", 1)[0] != REFERENCE]
    # Compose env_file accepts a JSON double-quoted string; no shell sourcing.
    rows.append(REFERENCE + "=" + json.dumps(value["environment"][REFERENCE]))
    write(native_path, encoded(native), replace=True)
    write(extensions_path, encoded(extensions), replace=True)
    write(env_path, ("\n".join(rows) + "\n").encode(), replace=True)


def main():
    phase = argparse.ArgumentParser()
    phase.add_argument(
        "phase", choices=["receive", "controller", "export-worker", "worker"]
    )
    action = phase.parse_args().phase
    assert os.getuid() == 0
    for directory in [PRIVATE, OPERATOR]:
        assert all(not p.is_symlink() for p in [directory, *directory.parents])
        assert (
            directory.stat().st_uid == 0
            and stat.S_IMODE(directory.stat().st_mode) == 0o700
        )
    if action == "receive":
        value = validate(json.load(sys.stdin))
        write(OPERATOR / "c-model-subset.json", encoded(value))
        print(
            json.dumps(
                {
                    "selected_model_received": True,
                    "environment_references": [REFERENCE],
                    "models_called": False,
                }
            )
        )
        return
    if action == "worker":
        payload = json.load(sys.stdin)
        assert set(payload) == {"selected", "owner", "task_toolsets", "interceptors"}
        assert (
            payload["task_toolsets"] == GROUPS
            and payload["interceptors"] == INTERCEPTORS
        )
        owner = payload["owner"]
        assert re.fullmatch(r"[0-9a-f-]{36}", owner)
        apply(payload["selected"], "worker", owner)
    else:
        proof = load(ROOT / "proof/b-cleanup.json")
        assert proof["pending_notifications"] == proof["native_runs"] == 0
        assert (
            proof["notification_status"] == "dead_letter"
            and proof["ledger_history_preserved"]
        )
        value = validate(load(OPERATOR / "c-model-subset.json"))
        owner = load(OPERATOR / "owner.json")["owner_id"]
        snapshot = load(OPERATOR / "b-extensions.json")
        assert snapshot["mcpServers"]["ecs"]["user_auth"]["users"] == {
            owner: "$ECS_OWNER_HEADER"
        }
        assert snapshot["mcpServers"]["ecs"]["task_toolsets"] == GROUPS
        assert snapshot["mcpInterceptors"] == INTERCEPTORS
        if action == "export-worker":
            # Captured in Jenkins process memory and sent directly to worker stdin;
            # this secret payload must never be printed by the coordinator.
            sys.stdout.buffer.write(
                encoded(
                    {
                        "selected": value,
                        "owner": owner,
                        "task_toolsets": GROUPS,
                        "interceptors": INTERCEPTORS,
                    }
                )
            )
            return
        apply(value, "controller", owner)
    print(
        json.dumps(
            {
                "native_configuration_restored": True,
                "role": action,
                "model": "deepseek-chat",
                "original_provider_retained": True,
                "signed_groups_restored": True,
                "owner_preserved": True,
                "models_called": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Selected native model configuration refused; private details withheld"
        ) from None
