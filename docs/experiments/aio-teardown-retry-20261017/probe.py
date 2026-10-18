"""Real AIO containers, with one simulated stop timeout per isolated case.

No models, network credentials or daemon-wide mutations. Cleanup is restricted
to immutable IDs created by this invocation. Run once per selected checkout.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument(
    "--case",
    choices=[
        "explicit",
        "shutdown-active",
        "shutdown-warm",
        "shutdown-held",
        "replacement",
    ],
)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)

if args.case is None:
    results = []
    for case in [
        "explicit",
        "shutdown-active",
        "shutdown-warm",
        "shutdown-held",
        "replacement",
    ]:
        result = subprocess.run(
            [
                sys.executable,
                __file__,
                "--root",
                str(args.root),
                "--output",
                str(args.output),
                "--case",
                case,
            ],
            cwd=args.output,
            capture_output=True,
            text=True,
            timeout=240,
        )
        (args.output / f"{case}.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        print(case, result.returncode, result.stdout, flush=True)
        if result.returncode:
            print(result.stderr, flush=True)
            raise SystemExit(result.returncode)
        results.append(json.loads((args.output / f"{case}.json").read_text()))
    (args.output / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    raise SystemExit(0)

root = args.root.resolve()
backend = root / "backend"
sys.path[:0] = [
    str(backend),
    str(backend / "packages/harness"),
    str(backend / "packages/extension-api"),
]
case_dir = args.output / args.case
case_dir.mkdir(exist_ok=True)
os.environ["DEER_FLOW_HOME"] = str(case_dir / "home")
os.environ["DEER_FLOW_CONFIG_PATH"] = str(case_dir / "config.yaml")
(case_dir / ".env").write_text("", encoding="utf-8")
os.chdir(case_dir)

# Import only after selecting the checkout and isolated configuration above.
from deerflow.config.app_config import AppConfig, set_app_config  # noqa: E402
from deerflow.community.aio_sandbox import aio_sandbox_provider as aio  # noqa: E402
from deerflow.sandbox import sandbox_provider as registry  # noqa: E402

assert Path(aio.__file__).resolve().is_relative_to(root)
prefix = "df-retry-" + args.case + "-" + uuid.uuid4().hex[:8]
image = (
    "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"
)
config = {
    "models": [],
    "tools": [],
    "tool_groups": [],
    "memory": {"enabled": False},
    "sandbox": {
        "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
        "image": image,
        "container_prefix": prefix,
        "port": 18800,
        "idle_timeout": 0,
        "replicas": 4,
        "ownership": {"type": "memory"},
    },
    "skills": {"path": str(root / "skills"), "container_path": "/mnt/skills"},
}
# Construct the full typed production configuration, including network defaults.
set_app_config(AppConfig.model_validate(config))
(case_dir / "config.yaml").write_text(json.dumps(config, indent=2), encoding="utf-8")
provider = aio.AioSandboxProvider()
saved = []
original_stop = provider._backend._stop_container
attempts = []
result = {
    "case": args.case,
    "checkout": str(root),
    "imported": aio.__file__,
    "prefix": prefix,
    "revision": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip(),
    "injection": "one simulated TimeoutExpired at real LocalContainerBackend._stop_container",
    "models_called": 0,
}
result["source_sha256"] = {
    str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [
        Path(aio.__file__),
        Path(aio.__file__).with_name("local_backend.py"),
        Path(registry.__file__),
    ]
}


def call(action):
    try:
        return {"returned": action()}
    except Exception as exc:
        return {"raised": type(exc).__name__, "message": str(exc)}


def inventory():
    proc = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=" + prefix + "-",
            "--format",
            "{{.ID}} {{.Names}} {{.Status}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip().splitlines()


try:
    bad_id = provider.acquire("bad", user_id="probe")
    bad = provider._sandbox_infos[bad_id]
    saved.append(bad)
    if args.case.startswith("shutdown"):
        good_id = provider.acquire("good", user_id="probe")
        good = provider._sandbox_infos[good_id]
        saved.append(good)
        provider.release(bad_id if args.case == "shutdown-warm" else good_id)
        assert len(provider._warm_pool) == 1
        registry.set_sandbox_provider(provider)
        if args.case == "shutdown-held":
            from deerflow.sandbox.lease import get_sandbox_lease_manager

            manager = get_sandbox_lease_manager(provider)
            manager.retain("unfinished", bad_id, thread_id="bad", user_id="probe")

    injected = False

    def fail_once(target):
        global injected
        if target in {info.container_id for info in saved}:
            attempts.append(target)
        if target == bad.container_id and not injected:
            injected = True
            raise subprocess.TimeoutExpired(["docker", "stop", target], 0.001)
        original_stop(target)

    provider._backend._stop_container = fail_once
    action = (
        registry.shutdown_sandbox_provider
        if args.case.startswith("shutdown")
        else lambda: provider.destroy(bad_id)
    )
    result["first"] = call(action)
    assert injected, "probe never entered the target stop operation"
    result["after_first"] = {
        "bad_absent": provider._backend.is_absent(bad_id),
        "inventory": inventory(),
        "quarantined": provider._quarantine_store().contains(bad),
        "singleton_retained": registry.get_initialized_sandbox_provider() is provider,
        "stop_attempts": len(attempts),
    }
    assert result["after_first"]["bad_absent"] is False
    if args.case == "shutdown-held":
        result["after_first"]["execution_still_bound"] = (
            manager.binding_for("unfinished") == bad_id
        )
    if args.case == "replacement":
        original_stop(bad.container_id)
        replacement = provider._backend.create(None, bad_id)
        saved.append(replacement)
        result["replacement_generation"] = replacement.container_id
        assert replacement.container_id != bad.container_id
    result["second"] = call(action)
    result["after_second"] = {
        "bad_absent": provider._backend.is_absent(bad_id),
        "inventory": inventory(),
        "quarantined": provider._quarantine_store().contains(bad),
        "singleton_retained": registry.get_initialized_sandbox_provider() is provider,
        "stop_attempts": len(attempts),
    }
    if args.case == "replacement":
        current = provider._backend.inspect_runtime(bad_id)
        result["replacement_survived"] = (
            current is not None and current.container_id == replacement.container_id
        )
        assert result["replacement_survived"]
    result["attempted_generations"] = attempts
finally:
    provider._backend._stop_container = original_stop
    for info in reversed(saved):
        try:
            original_stop(info.container_id)
        except Exception:
            if not provider._backend.is_absent(info.sandbox_id):
                raise
        cleanup = call(
            lambda: provider._backend.complete_absent_teardown(info.sandbox_id)
        )
        if "raised" in cleanup:
            result.setdefault("cleanup_errors", []).append(cleanup)
    result["final_shutdown"] = call(provider.shutdown)
    atexit.unregister(provider.shutdown)
    registry._default_sandbox_provider = None
    # This isolated process owns the signal registrations; restore originals.
    signal.signal(signal.SIGTERM, provider._original_sigterm)
    signal.signal(signal.SIGINT, provider._original_sigint)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, provider._original_sighup)
    result["final_inventory"] = inventory()
    assert result["final_inventory"] == [], (
        "owned containers leaked after probe cleanup"
    )

(args.output / f"{args.case}.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(json.dumps(result), flush=True)
