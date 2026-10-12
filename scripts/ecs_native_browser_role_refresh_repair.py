"""Same-host private provider/tool overlay and exact role refresh while admission is drained."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OLD = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
PROVIDER = {"provider": "ecs_executor.browser:build_browser_control_provider"}
ACTIONS = [
    "navigate",
    "snapshot",
    "click",
    "type",
    "get_text",
    "back",
    "screenshot",
    "close",
]
TOOLS = [
    {
        "name": "browser_" + action,
        "group": "browser",
        "use": "deerflow.community.browser_automation.tools:browser_"
        + action
        + "_tool",
        **(
            {"allow_private_addresses": False, "allow_unguarded_cdp": False}
            if action == "navigate"
            else {}
        ),
    }
    for action in ACTIONS
]


def checked(args, timeout=120):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    assert r.returncode == 0, (
        "Owned browser refresh command failed; private output withheld"
    )
    return r.stdout


def data(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return path.read_bytes()


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def main(role, image):
    assert (
        os.getuid() == 0
        and re.fullmatch(r"sha256:[0-9a-f]{64}", image)
        and image != OLD
    )
    assert all(not p.is_symlink() for p in [PRIVATE, *PRIVATE.parents])
    for directory in [PRIVATE, PRIVATE.parent]:
        entry = directory.lstat()
        assert (
            stat.S_ISDIR(entry.st_mode)
            and entry.st_uid == 0
            and stat.S_IMODE(entry.st_mode) == 0o700
        )
    outer = (ROOT / "private").lstat()
    assert (
        stat.S_ISDIR(outer.st_mode)
        and outer.st_uid == 0
        and stat.S_IMODE(outer.st_mode) & 0o022 == 0
    )
    installed = json.loads(checked(["docker", "image", "inspect", image]))[0]
    assert (
        installed["Id"] == installed["Descriptor"]["digest"] == image
        and installed["Architecture"] == "amd64"
    )
    paths = [
        PRIVATE / name
        for name in [
            "central.json",
            "worker.json",
            "native.json",
            role + ".env",
            "worker-ops.json",
        ]
    ]
    if role == "controller":
        paths.append(PRIVATE / "controller-ops.json")
    before = {p: data(p) for p in paths}
    after = {}
    for path, raw in before.items():
        if path.name in ["central.json", "worker.json"]:
            value = json.loads(raw)
            assert value["enabled"] is True and value["role"] == (
                "central" if path.name == "central.json" else "worker"
            )
            assert (
                "browser_control" not in value or value["browser_control"] == PROVIDER
            )
            if path.name == "central.json":
                node = value["nodes"]["native-820d7a3429d9"]
                assert (
                    node["max_concurrency"] == 1
                    and node["resident_cpu_millis"] == 1500
                    and node["resident_memory_mib"] == 2048
                )
                assert (
                    node["cpu_millis"] == 2000
                    and node["memory_mib"] == 4096
                    and "C" in node["kinds"]
                )
            else:
                assert (
                    value["node_id"] == "native-820d7a3429d9"
                    and value["executor_url"] == "https://192.168.0.190:2026"
                )
            value["browser_control"] = PROVIDER
            assert {k: v for k, v in value.items() if k != "browser_control"} == {
                k: v for k, v in json.loads(raw).items() if k != "browser_control"
            }
            after[path] = encoded(value)
        elif path.name == "native.json":
            value = json.loads(raw)
            existing = [v for v in value["tools"] if v["name"].startswith("browser_")]
            assert existing in [[], TOOLS]
            if not existing:
                value["tools"].extend(TOOLS)
            if not any(v["name"] == "browser" for v in value["tool_groups"]):
                value["tool_groups"].append({"name": "browser"})
            assert all(
                v.get("headless", True) is True
                and not v.get("channel")
                and not v.get("cdp_url")
                for v in value["tools"]
                if v["name"].startswith("browser_")
            )
            assert (
                next(v for v in value["tools"] if v["name"] == "browser_navigate")[
                    "allow_private_addresses"
                ]
                is False
            )
            assert {
                k: v for k, v in value.items() if k not in ["tools", "tool_groups"]
            } == {
                k: v
                for k, v in json.loads(raw).items()
                if k not in ["tools", "tool_groups"]
            }
            after[path] = encoded(value)
        elif path.suffix == ".env":
            lines = raw.splitlines(keepends=True)
            hits = [
                i for i, line in enumerate(lines) if line.startswith(b"ECS_ROLE_IMAGE=")
            ]
            assert len(hits) == 1
            i = hits[0]
            assert lines[i].strip().split(b"=", 1)[1].decode() == OLD
            ending = (
                b"\r\n"
                if lines[i].endswith(b"\r\n")
                else b"\n"
                if lines[i].endswith(b"\n")
                else b""
            )
            lines[i] = b"ECS_ROLE_IMAGE=" + image.encode() + ending
            after[path] = b"".join(lines)
        else:
            value = json.loads(raw)
            assert value["image"] == OLD and value["node_id"] == "native-820d7a3429d9"
            assert value["sandbox_prefix"] == "deer-native-aio-820d7a3429d9"
            value["image"] = image
            after[path] = encoded(value)
    # Validate every input before any replacement; preserve private bytes on this host only.
    for path, raw in before.items():
        assert data(path) == raw
        backup = path.with_name(path.name + ".before-browser-control")
        assert not backup.exists() and not backup.is_symlink()
        fd = os.open(
            backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        temporary = path.with_name(path.name + ".browser-control-new")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(after[path])
            stream.flush()
            os.fsync(stream.fileno())
    for path in paths:
        os.replace(path.with_name(path.name + ".browser-control-new"), path)
    services = ["gateway", "mcp"] if role == "controller" else ["resident"]
    compose = [
        "docker",
        "compose",
        "--project-name",
        "deer-native-820d7a3429d9-" + role,
        "--env-file",
        str(PRIVATE / (role + ".env")),
        "-f",
        str(ROOT / "source/examples/ecs-native/deploy" / (role + ".compose.yaml")),
    ]
    checked(
        [
            *compose,
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "180",
            *services,
        ],
        timeout=240,
    )
    results = []
    for service in services:
        ids = checked([*compose, "ps", "-q", service]).decode().splitlines()
        assert len(ids) == 1
        c = json.loads(checked(["docker", "inspect", ids[0]]))[0]
        assert c["Image"] == image and c["State"]["Running"]
        if service != "mcp":
            assert c["State"]["Health"]["Status"] == "healthy"
        socket = any(v["Destination"] == "/var/run/docker.sock" for v in c["Mounts"])
        assert socket == (role == "worker")
        result = {
            "role": role,
            "service": service,
            "container_id": c["Id"],
            "image_id": image,
            "docker_socket": socket,
            "health": c["State"].get("Health", {}).get("Status", "no_healthcheck"),
        }
        if service == "resident":
            h = c["HostConfig"]
            assert (
                h["NanoCpus"] == 500000000
                and h["Memory"] == 1073741824
                and h["MemorySwap"] == 2147483648
            )
            kernel = (
                checked(
                    [
                        "docker",
                        "exec",
                        c["Id"],
                        "cat",
                        "/sys/fs/cgroup/cpu.max",
                        "/sys/fs/cgroup/memory.max",
                    ]
                )
                .decode()
                .splitlines()
            )
            assert kernel == ["50000 100000", "1073741824"]
            result.update(
                nano_cpus=h["NanoCpus"],
                memory=h["Memory"],
                memory_swap=h["MemorySwap"],
                kernel_limits=kernel,
            )
        results.append(result)
    print(
        json.dumps(
            {
                "browser_role_refresh": results,
                "provider_enabled": True,
                "private_backups_preserved": True,
                "private_config_sha256": {
                    path.name: {
                        "before": hashlib.sha256(before[path]).hexdigest(),
                        "after": hashlib.sha256(after[path]).hexdigest(),
                    }
                    for path in paths
                },
                "unchanged_model_and_credentials": True,
                "resource_caps_changed": False,
                "admission_resumed": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["controller", "worker"])
    parser.add_argument("image")
    args = parser.parse_args()
    try:
        main(args.role, args.image)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "browser_role_refresh_failed": True,
                    "exception_class": type(exc).__name__,
                    "admission_resumed": False,
                }
            ),
            flush=True,
        )
        raise SystemExit(
            "Owned browser role refresh failed; retain private backups and admission drain"
        ) from None
