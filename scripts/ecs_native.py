#!/usr/bin/env python3
"""Generate reference-only private role files, or delegate native operator actions.

Run with backend/.venv/bin/python; generation itself uses only the standard library.
No credential source is read and no shell/env file is evaluated.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def generate(args):
    for role in ("controller", "worker"):
        if (args.project + "-" + role + "-").startswith(args.sandbox_prefix + "-"):
            raise ValueError("AIO sandbox prefix must not select role containers")
    private = Path(args.private_dir).resolve()
    if not private.is_dir() or private.is_symlink() or private.stat().st_mode & 0o077:
        raise ValueError("Create the private directory with mode 0700 first")
    nas = Path(args.nas_root)
    if not nas.is_absolute() or not nas.is_dir() or nas.is_symlink():
        raise ValueError("NAS must already exist at its canonical absolute path")
    if not args.owned_local_fixture and not os.path.ismount(nas):
        raise ValueError("Production NAS mount must be established first")
    marker = nas / "pool/pool-mount-id"
    if not marker.is_file() or marker.is_symlink():
        raise ValueError("Provision the shared pool marker on the verified mount first")
    if not args.central_url.startswith("https://"):
        raise ValueError("A TLS central URL is mandatory")
    node = {
        "cpu_millis": 2000,
        "memory_mib": 4096,
        "resident_cpu_millis": 1500,
        "resident_memory_mib": 2048,
        "max_concurrency": 1,
        "profiles": ["native", "small"],
        "kinds": ["B", "C"],
    }
    central = {
        "enabled": True,
        "role": "central",
        "artifact_root": str(nas / "pool"),
        "database_url_env": "ECS_EXECUTOR_DATABASE_URL",
        "native_node": args.node_id,
        "profile": "native",
        "profiles": {"native": {"cpu_millis": 500, "memory_mib": 1024}},
        "nodes": {args.node_id: node},
        "worker_credential_env": {args.node_id: "ECS_NODE_TOKEN"},
        "remote_all": True,
        "remote_origins": ["schedule", "mcp_notification"],
    }
    worker = {
        "enabled": True,
        "role": "worker",
        "artifact_root": str(nas / "pool"),
        "executor_url": args.central_url,
        "node_id": args.node_id,
        "credential_env": "ECS_NODE_TOKEN",
    }
    if args.browser:
        browser = {"provider": "ecs_executor.browser:build_browser_control_provider"}
        central["browser_control"] = browser
        worker["browser_control"] = browser
    executor = {
        "mode": "pool",
        "database_url_env": "ECS_EXECUTOR_DATABASE_URL",
        "metadata_database_url_env": "ECS_NATIVE_METADATA_DATABASE_URL",
        "audience": "executor",
        "profiles": {
            "small": {
                "image": args.b_image,
                "cpu_millis": 500,
                "memory_mib": 128,
                "network": "none",
                "user": "65534:65534",
                "pids_limit": 64,
                "max_execution_seconds": 60,
                "max_output_bytes": 1048576,
            }
        },
        "nodes": central["nodes"],
        "worker_credential_env": central["worker_credential_env"],
        "user_profiles": {args.owner: ["small"]},
        "user_credential_env": {args.owner: "ECS_OWNER_TOKEN"},
        "discovery_credential_env": "ECS_DISCOVERY_TOKEN",
        "allowed_networks": ["none"],
        "artifact_root": str(nas / "pool"),
        "workspace_root": str(nas),
        "artifact_base_url": args.central_url,
        "bind_host": "0.0.0.0",
        "port": 8003,
    }
    b_worker = {
        "node_id": args.node_id,
        "credential_env": "ECS_NODE_TOKEN",
        "executor_url": args.central_url + "/execution",
        "artifact_root": str(nas / "pool"),
        "workspace_root": str(nas),
        "metadata_database_url_env": "ECS_NATIVE_METADATA_DATABASE_URL",
    }
    extensions = {
        "mcpInterceptors": [
            "ecs_executor.interceptor:build_execution_scope_interceptor"
        ],
        "mcpServers": {
            "ecs": {
                "type": "http",
                "url": args.central_url + "/execution/mcp",
                "headers": {"Authorization": "$ECS_DISCOVERY_HEADER"},
                "user_auth": {
                    "enabled": True,
                    "on_missing": "deny",
                    "users": {args.owner: "$ECS_OWNER_HEADER"},
                },
                "task_toolsets": [
                    {
                        "name": "execution",
                        "submit_tool": "submit",
                        "status_tool": "status",
                        "cancel_tool": "cancel",
                    }
                ],
            }
        },
        "skills": {},
    }
    names = {
        "ls": "ls_tool",
        "read_file": "read_file_tool",
        "glob": "glob_tool",
        "grep": "grep_tool",
        "write_file": "write_file_tool",
        "str_replace": "str_replace_tool",
        "bash": "bash_tool",
    }
    tools = [
        {
            "name": name,
            "group": "bash"
            if name == "bash"
            else "file:write"
            if name in {"write_file", "str_replace"}
            else "file:read",
            "use": "deerflow.sandbox.tools:" + use,
        }
        for name, use in names.items()
    ]
    if args.browser:
        for action in (
            "navigate",
            "snapshot",
            "click",
            "type",
            "get_text",
            "back",
            "screenshot",
            "close",
        ):
            tools.append(
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
            )
    native = {
        "models": [
            {
                "name": "operator-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "$ECS_MODEL_NAME",
                "api_key": "$ECS_MODEL_KEY",
                "base_url": "$ECS_MODEL_URL",
            }
        ],
        "tool_groups": [
            {"name": group} for group in ("file:read", "file:write", "bash", "browser")
        ],
        "tools": tools,
        "sandbox": {
            "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
            "image": args.aio_image,
            "replicas": 1,
            "hard_capacity": True,
            "container_prefix": args.sandbox_prefix,
            "ownership": {"type": "redis", "redis_url": "$REDIS_URL"},
        },
        "database": {"backend": "postgres", "postgres_url": "$DATABASE_URL"},
        "deployment": {"multi_instance": True},
        "agent_storage": {"backend": "db"},
        "run_events": {"backend": "db"},
        "run_ownership": {"heartbeat_enabled": True, "lease_seconds": 120},
        "stream_bridge": {"type": "redis", "redis_url": "$REDIS_URL"},
        "memory": {
            "enabled": True,
            "manager_class": "deermem",
            "mode": "tool",
            "backend_config": {
                "retrieval_index_path": "$DEER_FLOW_MEMORY_INDEX_PATH",
                "token_counting": "char",
            },
        },
        "scheduler": {"enabled": True, "tool_enabled": True, "multi_instance": True},
        "mcp_tasks": {"enabled": True, "poll_interval_seconds": 1},
    }
    for name, value in {
        "central.json": central,
        "worker.json": worker,
        "executor.json": executor,
        "b-worker.json": b_worker,
        "extensions.json": extensions,
        "native.json": native,
    }.items():
        write_private(private / name, value)
    for role in ("controller", "worker"):
        write_private(
            private / (role + "-ops.json"),
            {
                "scope": "owned-local-fixture"
                if args.owned_local_fixture
                else "production",
                "nas_root": str(nas),
                "mount_id": marker.read_text(encoding="ascii").strip(),
                "private_dir": str(private),
                "image": args.image,
                "node_id": args.node_id,
                "sandbox_prefix": args.sandbox_prefix,
                "role": role,
                "compose_file": str(
                    ROOT / "examples/ecs-native/deploy" / (role + ".compose.yaml")
                ),
                "project": args.project + "-" + role,
                "native_database_url_env": "ECS_NATIVE_METADATA_DATABASE_URL",
            },
        )
    print(
        "Private reference-only role configuration generated; supply private environment/TLS files before start"
    )


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        parser = argparse.ArgumentParser()
        parser.add_argument("generate")
        for name in (
            "private-dir",
            "nas-root",
            "central-url",
            "node-id",
            "owner",
            "image",
            "project",
            "sandbox-prefix",
        ):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--b-image", default="alpine:3.20")
        parser.add_argument(
            "--aio-image",
            default="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0",
        )
        parser.add_argument("--browser", action="store_true")
        parser.add_argument("--owned-local-fixture", action="store_true")
        try:
            generate(parser.parse_args())
        except Exception:
            raise SystemExit(
                "Private config generation refused; no credentials or private paths printed"
            ) from None
    else:
        sys.path.insert(0, str(ROOT / "backend/packages/ecs-executor"))
        from ecs_executor.operations import main as operations

        operations()


if __name__ == "__main__":
    main()
