"""Offline Makefile-equivalent gates over a verified public source in writable /tmp."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


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
        UV_PROJECT_ENVIRONMENT="/app/backend/.venv",
        UV_NO_SYNC="1",
        UV_OFFLINE="1",
        PYTHONPATH=":".join(map(str, paths)),
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        HOME=str(home),
        DEER_FLOW_HOME=str(home / ".deer-flow"),
        PYTHONPYCACHEPREFIX=str(home / "pycache"),
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
        ("ruff-check", ["uv", "run", "ruff", "check", "."]),
        ("ruff-format", ["uv", "run", "ruff", "format", "--check", "."]),
    ]
    # Exact four duration-balanced Makefile shards, TEST_JOBS=1, no sync or downloads.
    for group in range(1, 5):
        commands.append(
            (
                "offline-shard-" + str(group),
                [
                    "uv",
                    "run",
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
                ],
            )
        )
    commands.append(
        (
            "blocking-io",
            ["uv", "run", "pytest", "tests/blocking_io", "-q", "--tb=short"],
        )
    )
    results = []
    for name, command in commands:
        started = time.monotonic()
        print(json.dumps({"gate_start": name}), flush=True)
        r = subprocess.run(command, cwd=backend, env=env, timeout=900)
        results.append(
            {
                "gate": name,
                "exit": r.returncode,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
        # Match make -k: all four shard results are collected even after one failure.
        if r.returncode and name.startswith("ruff-"):
            break
    print(
        json.dumps(
            {
                "offline_code_gates": "PASS"
                if len(results) == 7 and all(x["exit"] == 0 for x in results)
                else "FAIL",
                "source_sha256": args.source_sha256,
                "manifest_sha256": args.manifest_sha256,
                "source_imports": imports,
                "uid": os.getuid(),
                "results": results,
            }
        ),
        flush=True,
    )
    assert len(results) == 7 and all(x["exit"] == 0 for x in results)


if __name__ == "__main__":
    main()
