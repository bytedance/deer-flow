"""Makefile-equivalent gates over a verified public source in writable /tmp."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import signal
import sys
import threading
import re
import tarfile
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def live_group(pgid):
    # Only this isolated container's owned gate process group; zombies do not run.
    result = []
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            value = (path / "stat").read_text()
            fields = value[value.rindex(")") + 2 :].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                result.append(int(path.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def retire_group(process):
    # start_new_session creates this exact group. Never signal other processes.
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        if live_group(process.pid):
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 6
        while live_group(process.pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if not live_group(process.pid):
            break
    process.wait(timeout=3)
    assert not live_group(process.pid), "Owned gate process group not retired"


def run_gate(name, command, budget, backend, env, home):
    started = time.monotonic()
    print(
        "\n" + json.dumps({"gate_start": name, "timeout_seconds": budget}), flush=True
    )
    log = home / (name + ".log")
    process = subprocess.Popen(
        command,
        cwd=backend,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    reader_errors = []

    def copy_output():
        try:
            with log.open("xb") as stream:
                for line in iter(process.stdout.readline, b""):
                    stream.write(line)
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
        except Exception as error:
            reader_errors.append(type(error).__name__)

    reader = threading.Thread(target=copy_output, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=budget)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        retire_group(process)
        reader.join(timeout=3)
    assert not reader.is_alive() and not reader_errors, "Owned gate output incomplete"
    summaries = []
    counts = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.search(
            r"\d+ (?:passed|failed|skipped|error|errors).* in \d+(?:\.\d+)?s", line
        ):
            summaries.append(line.strip("= "))
            counts = {
                kind: int(value)
                for value, kind in re.findall(
                    r"(\d+) (passed|failed|skipped|deselected|errors|error|warnings|warning)",
                    line,
                )
            }
    result = {
        "gate": name,
        "command": command,
        "exit": process.returncode,
        "timed_out": timed_out,
        "timeout_seconds": budget,
        "seconds": round(time.monotonic() - started, 3),
        "process_group_retired": True,
        "counts": counts,
        "summaries": summaries,
        "log_sha256": sha(log.read_bytes()),
    }
    print("\n" + json.dumps({"gate_result": result}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_sha256")
    parser.add_argument("manifest_sha256")
    args = parser.parse_args()
    archive = Path("/run/public-source.tar.gz")
    root = Path("/tmp/native-final-code-source")
    root.mkdir(mode=0o700)
    with tarfile.open(archive, mode="r:gz") as bundle:
        members = bundle.getmembers()
        assert len({m.name for m in members}) == len(members)
        manifests = [
            m for m in members if m.name == "native-source-entry-manifest.json"
        ]
        assert len(manifests) == 1 and manifests[0].isfile()
        raw = bundle.extractfile(manifests[0]).read()
        assert sha(raw) == args.manifest_sha256
        manifest = json.loads(raw)
        assert manifest["source_sha256"] == args.source_sha256
        rows = manifest["files"]
        assert len(members) == len(rows) + 1
        assert (
            sha("\n".join(n + ":" + rows[n]["sha256"] for n in sorted(rows)).encode())
            == args.source_sha256
        )
        assert sum(m.size for m in members) < 256 * 1024**2
        for member in members:
            name = member.name
            path = PurePosixPath(name)
            assert (
                name == path.as_posix()
                and not path.is_absolute()
                and ".." not in path.parts
                and "\\" not in name
            )
            assert member.isfile() and not member.islnk() and not member.issym()
            if name == "native-source-entry-manifest.json":
                continue
            assert (
                name in rows
                and member.size == rows[name]["bytes"]
                and member.mode == rows[name]["mode"]
            )
            data = bundle.extractfile(member).read()
            assert sha(data) == rows[name]["sha256"]
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            target.chmod(member.mode)
    home = Path("/tmp/native-final-code-home")
    home.mkdir(mode=0o700)
    backend = root / "backend"
    paths = [
        backend,
        backend / "packages/harness",
        backend / "packages/extension-api",
        backend / "packages/ecs-executor",
        root / "scripts",
    ]
    env = dict(
        os.environ,
        PYTHONPATH=":".join(map(str, paths)),
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        HOME=str(home),
        DEER_FLOW_HOME=str(home / ".deer-flow"),
        PYTHONPYCACHEPREFIX=str(home / "pycache"),
    )
    for key in ("UV_PROJECT_ENVIRONMENT", "UV_NO_SYNC", "UV_OFFLINE"):
        env.pop(key, None)
    # Create only this fixture's public synthetic repository; no feature Git metadata.
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    assert not (root / ".git").exists()
    git_commands = [
        ["init", "--quiet", "--initial-branch=codex/fixture"],
        ["config", "--local", "user.name", "Native Offline Fixture"],
        ["config", "--local", "user.email", "native-offline-fixture@example.invalid"],
        ["config", "--local", "core.hooksPath", "/dev/null"],
        ["config", "--local", "commit.gpgsign", "false"],
        ["add", "--all", "--force", "."],
        ["commit", "--quiet", "-m", "Synthetic public offline fixture"],
    ]
    for arguments in git_commands:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        assert result.returncode == 0, (
            "Public synthetic Git fixture initialization failed"
        )
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    ).strip()
    assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
    assert (
        subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], env=env, timeout=10
        )
        == b""
    )
    print(
        json.dumps(
            {
                "synthetic_git_head": revision,
                "feature_git_metadata_copied": False,
                "source_sha256": args.source_sha256,
            }
        ),
        flush=True,
    )
    # Before pytest collection, prove all editable packages resolve the refreshed source.
    probe = (
        "import importlib.util,json,pathlib;root=pathlib.Path("
        + repr(str(root))
        + ");v={};\n"
    )
    probe += "for name in ['app','deerflow','ecs_executor','deerflow_extension_api']:\n s=importlib.util.find_spec(name);p=pathlib.Path(s.origin).resolve();assert p.is_relative_to(root),name;v[name]=str(p)\nprint(json.dumps(v))"
    r = subprocess.run(
        ["/app/backend/.venv/bin/python", "-c", probe],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r.returncode == 0, "Latest source import provenance failed"
    imports = json.loads(r.stdout)
    commands = [
        (
            "ruff-check",
            ["/app/backend/.venv/bin/ruff", "check", "."],
            120,
        ),
        (
            "ruff-format",
            ["/app/backend/.venv/bin/ruff", "format", "--check", "."],
            120,
        ),
    ]
    # Cover every changed existing test file; rerun environment-damaged groups.
    repaired_files = [
        "tests/test_migration_0024_project_documents.py",
        "tests/test_migration_0025_repair_run_change_seq.py",
        "tests/test_migration_0026_mcp_task_lease_tokens.py",
        "tests/test_migration_0027_0028_notification_outbox.py",
        "tests/test_thread_regenerate_prepare.py",
        "tests/test_deploy_uv_extras.py",
        "tests/test_gateway_services.py",
        "tests/test_persistence_bootstrap.py",
        "tests/test_wait_disconnect_handling.py",
        "tests/test_agent_guidance_check.py",
        "tests/test_ecs_schema_compatibility.py",
    ]
    commands.append(
        (
            "repaired-whole-files",
            [
                "/app/backend/.venv/bin/python",
                "-m",
                "pytest",
                "-m",
                "not live",
                *repaired_files,
                "-q",
                "--tb=short",
            ],
            900,
        )
    )
    # Shards 1/2 unchanged passed cases reuse the preserved original FAIL receipt.
    for group in (3, 4):
        commands.append(
            (
                "offline-shard-" + str(group),
                [
                    "/app/backend/.venv/bin/python",
                    "-m",
                    "pytest",
                    "-m",
                    "not live",
                    "--ignore=tests/blocking_io",
                    "--splits",
                    "4",
                    "--group",
                    str(group),
                    "--splitting-algorithm",
                    "least_duration",
                    "--durations-path=.test_durations",
                    "tests/",
                    "-q",
                    "--tb=short",
                ],
                900,
            )
        )
    commands.append(
        (
            "blocking-io",
            [
                "/app/backend/.venv/bin/python",
                "-m",
                "pytest",
                "tests/blocking_io",
                "-q",
                "--tb=short",
            ],
            300,
        )
    )
    results = []
    for name, command, budget in commands:
        results.append(run_gate(name, command, budget, backend, env, home))
        # All existing groups run even when a prior gate fails or times out.
    print(
        json.dumps(
            {
                "envfix_code_gates": "PASS"
                if len(results) == 6
                and all(x["exit"] == 0 and not x["timed_out"] for x in results)
                else "FAIL",
                "source_sha256": args.source_sha256,
                "manifest_sha256": args.manifest_sha256,
                "source_imports": imports,
                "uid": os.getuid(),
                "synthetic_git_head": revision,
                "feature_git_metadata_copied": False,
                "results": results,
                "gate_scope": "revalidate_changed_wholefiles_and_unverified_shards",
                "repaired_whole_files": repaired_files,
                "shard_groups": [3, 4],
                "full_default_run": False,
                "prior_full_run_result": "FAIL",
                "prior_build": 60,
                "prior_receipt_sha256": "7fb4e535a96bc1bf553138fb4f153d55001fbf3e3adb44f30484bf0713354896",
                "prior_source_sha256": "19a944d78aab4c04607452f81264f257f74a3a5e333c92b9a2e2626e53db65a8",
                "reused_unmodified_passed_shards": [1, 2],
                "prior_shard_log_sha256": {
                    "1": "53df292acafdd3f628ceef15aae23f1ba540cc8a3fc733f73a94d39bd7ff2805",
                    "2": "9f031639c3678e1d5e3069a2b3033ea824e5817607787f1d53a12ddf83d400c0",
                },
            }
        ),
        flush=True,
    )
    assert len(results) == 6 and all(
        x["exit"] == 0 and not x["timed_out"] for x in results
    )


if __name__ == "__main__":
    main()
