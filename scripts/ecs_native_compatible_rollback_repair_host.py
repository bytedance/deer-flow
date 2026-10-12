"""Fixed same-schema 52ce/core/52ce selection; private recovery prepared first."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
GEN = PRIVATE.parent / "operator/compatible-rollback-52ce"
FULL = "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
CORE = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
LIFECYCLE_SHA = "098b6105a26abea10eed62e31b15c0a634daec468fd41c88f037d403b23fc89a"
REFRESH_SHA = "529f7a931e051300b84e921643b4b47364b2e0b95fd92866acb8f985a8f345ea"
FILES = ["central.json", "executor.json", "worker.json", "b-worker.json", "extensions.json", "native.json"]


def module(name, filename, digest):
    path = ROOT / "bootstrap" / filename
    assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


m = module("lifecycle", "ecs_native_shanghai_lifecycle_host_repair.py", LIFECYCLE_SHA)
r = module("browser_refresh", "ecs_native_browser_role_refresh_repair.py", REFRESH_SHA)


def owned(directory):
    assert all(not p.is_symlink() for p in [directory, *directory.parents])
    s = directory.lstat()
    assert stat.S_ISDIR(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o700


def write(path, raw):
    owned(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def image():
    value = json.loads(m.private(PRIVATE / (ROLE + "-ops.json")).read_bytes())["image"]
    assert value in [FULL, CORE]
    return value


def containers():
    names = ["resident"] if ROLE == "worker" else ["gateway", "mcp", "frontend", "proxy", "postgres", "redis"]
    result = []
    for service in names:
        name = "deer-native-820d7a3429d9-" + ROLE + "-" + service + "-1"
        x = json.loads(m.run(["docker", "inspect", name]))[0]
        assert x["Config"]["Labels"]["com.docker.compose.project"] == "deer-native-820d7a3429d9-" + ROLE
        assert x["Config"]["Labels"]["com.docker.compose.service"] == service
        if service in ["resident", "gateway", "mcp"]:
            assert x["Image"] in [FULL, CORE]
        assert any(v["Source"] == "/var/run/docker.sock" for v in x["Mounts"]) == (service == "resident")
        kernel = None
        if service == "resident" and x["State"]["Running"]:
            kernel = m.run(["docker", "exec", x["Id"], "cat", "/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/memory.max"]).decode().splitlines()
            assert kernel == ["50000 100000", "1073741824"]
        result.append(
            {
                "kernel_limits": kernel,
                "service": service,
                "id": x["Id"],
                "image": x["Image"],
                "running": x["State"]["Running"],
                "health": x["State"].get("Health", {}).get("Status"),
                "volumes": sorted(v["Name"] for v in x["Mounts"] if v["Type"] == "volume"),
                "cpu": x["HostConfig"]["NanoCpus"],
                "memory": x["HostConfig"]["Memory"],
            }
        )
    return result


def verify_image(value):
    x = json.loads(m.run(["docker", "image", "inspect", value]))[0]
    assert x["Id"] == x["Descriptor"]["digest"] == value and x["Architecture"] == "amd64"
    labels = x["Config"]["Labels"]
    assert labels["org.deerflow.native.native_revision"] == "0035_native_fork_compatibility"
    assert labels["org.deerflow.native.executor_revision"] == "e0001_execution_ledger"


def fingerprint(directory):
    h = hashlib.sha256()
    for name in FILES + [ROLE + ".env"]:
        h.update(name.encode("ascii") + b"\0" + m.private(directory / name).read_bytes() + b"\0")
    return h.hexdigest()


def unchanged_hash():
    h = hashlib.sha256()
    changed = {"central.json", "worker.json", "native.json", ROLE + ".env", "worker-ops.json", "controller-ops.json"}
    for path in sorted(PRIVATE.iterdir()):
        if path.name in changed:
            continue
        raw = m.private(path).read_bytes()
        h.update(path.name.encode() + b"\0" + raw + b"\0")
    return h.hexdigest()


def chrome_absent(checked, resident):
    assert resident["image"] == "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
    assert resident["running"] and resident["health"] == "healthy"
    code = """import json,os,pathlib
assert os.geteuid()==0
names=[]
for entry in pathlib.Path('/proc').iterdir():
 if not entry.name.isdigit():continue
 try:name=pathlib.Path(os.readlink(entry/'exe')).name
 except (FileNotFoundError,ProcessLookupError):continue
 if name.startswith(('chrome','chromium','headless_shell')):names.append(name)
print(json.dumps({'chrome_process_count':len(names)}))
"""
    value = json.loads(checked(["docker", "exec", resident["id"], "python", "-c", code], timeout=30))
    assert value == {"chrome_process_count": 0}


def schemas():
    spec = importlib.util.spec_from_file_location("schema_query", ROOT / "bootstrap/ecs_native_shanghai_b_cleanup_recovery.py")
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    assert q.query("deerflow", "SELECT version_num FROM alembic_version;") == "0035_native_fork_compatibility"
    assert q.query("deerflow_execution", "SELECT version_num FROM ecs_executor_alembic_version;") == "e0001_execution_ledger"


def prepare():
    owned(PRIVATE)
    owned(PRIVATE.parent)
    owned(GEN.parent)
    m.IMAGE = FULL
    m.preflight(ROLE)
    assert all(x["running"] and (x["service"] not in ["resident", "gateway", "mcp"] or x["image"] == FULL) for x in containers())
    verify_image(FULL)
    verify_image(CORE)
    if ROLE == "controller":
        schemas()
        m.controller_fence()
    if ROLE == "worker":
        assert m.physical() == 0
        resident = next(x for x in containers() if x["service"] == "resident")
        chrome_absent(m.run, resident)
    assert not GEN.exists() and not GEN.is_symlink()
    # Validate the existing backups against only the reviewed browser/image overlay.
    current = {name: m.private(PRIVATE / name).read_bytes() for name in FILES + [ROLE + ".env"]}
    old = dict(current)
    for name in ["central.json", "worker.json", "native.json", ROLE + ".env"]:
        old[name] = m.private(PRIVATE / (name + ".before-browser-control")).read_bytes()
    for name in ["central.json", "worker.json"]:
        expected = json.loads(old[name])
        assert "browser_control" not in expected
        expected["browser_control"] = r.PROVIDER
        assert expected == json.loads(current[name])
    expected = json.loads(old["native.json"])
    assert not any(t.get("group") == "browser" for t in expected.get("tools", []))
    expected.setdefault("tools", []).extend(r.TOOLS)
    if not any(g.get("name") == "browser" for g in expected.get("tool_groups", [])):
        expected.setdefault("tool_groups", []).append({"name": "browser"})
    assert expected == json.loads(current["native.json"])
    needle = ("ECS_ROLE_IMAGE=" + CORE + "\n").encode()
    assert old[ROLE + ".env"].count(needle) == 1
    assert current[ROLE + ".env"] == old[ROLE + ".env"].replace(needle, ("ECS_ROLE_IMAGE=" + FULL + "\n").encode(), 1)
    ops_names = ["worker-ops.json"] + (["controller-ops.json"] if ROLE == "controller" else [])
    ops = {}
    for name in ops_names:
        raw = m.private(PRIVATE / name).read_bytes()
        before = json.loads(m.private(PRIVATE / (name + ".before-browser-control")).read_bytes())
        assert before["image"] == CORE
        before["image"] = FULL
        assert before == json.loads(raw)
        ops[name] = raw
    lock = PRIVATE.parent / "operator/compatible-rollback.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
    GEN.mkdir(mode=0o700)
    for label, values, selected in [("full", current, FULL), ("core", old, CORE)]:
        directory = GEN / label
        directory.mkdir(mode=0o700)
        for name, raw in values.items():
            write(directory / name, raw)
        for name, raw in ops.items():
            write(directory / name, raw)
        manifest = {
            "unchanged_private_sha256": unchanged_hash(),
            "image": selected,
            "native_revision": "0035_native_fork_compatibility",
            "executor_revision": "e0001_execution_ledger",
            "generation": "compatible-820d7a3429d9-" + label,
            "config_sha256": fingerprint(directory),
        }
        write(directory / "manifest.json", encoded(manifest))
    return {"prepared": True, "role": ROLE, "two_immutable_images_verified": True, "restoration_prepared": True, "browser_only_backup_delta_verified": True}


def cli(action, manifest=None):
    # Independent trusted worker operator: directory rw is required for the
    # installed selector's atomic replacement. Admin sibling stays readonly.
    args = [
        "docker",
        "run",
        "--rm",
        "--cpus",
        "0.5",
        "--memory",
        "1g",
        "--network",
        "host",
        "--env-file",
        str(m.private(PRIVATE / "worker.env")),
        "--env-file",
        str(m.private(PRIVATE.parent / "operator/operator.env")),
        "-v",
        str(PRIVATE) + ":/run/operator",
        "-v",
        str(PRIVATE) + ":" + str(PRIVATE),
        "-v",
        str(ROOT / "source") + ":" + str(ROOT / "source") + ":ro",
        "-v",
        str(m.NAS) + ":" + str(m.NAS),
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        "/usr/libexec/docker/cli-plugins/docker-compose:/root/.docker/cli-plugins/docker-compose:ro",
        "-v",
        str(GEN) + ":" + str(GEN) + ":ro",
        FULL,
        "python",
        "-m",
        "ecs_executor.operations",
        action,
        "--config",
        "/run/operator/worker-ops.json",
    ]
    if manifest:
        args += ["--manifest", str(manifest)]
    out = m.run(args, timeout=600)
    if action == "status":
        assert json.loads(out) == {"operator_drain": True, "unreleased": 0}


def select(label):
    owned(GEN)
    target = FULL if label == "full" else CORE
    directory = GEN / label
    owned(directory)
    assert all(not x["running"] or x["service"] in ["postgres", "redis"] for x in containers())
    if ROLE == "worker":
        assert m.physical() == 0
    else:
        m.controller_fence()
        schemas()
    for name in ["worker-ops.json"] + (["controller-ops.json"] if ROLE == "controller" else []):
        active = json.loads(m.private(PRIVATE / name).read_bytes())
        baseline = json.loads(m.private(GEN / "full" / name).read_bytes())
        assert active["image"] in [CORE, FULL]
        active.pop("image")
        baseline.pop("image")
        if active.get("generation") in ["compatible-820d7a3429d9-full", "compatible-820d7a3429d9-core"]:
            active.pop("generation")
            baseline.pop("generation", None)
        assert active == baseline
    manifest = json.loads(m.private(directory / "manifest.json").read_bytes())
    assert manifest["image"] == target and manifest["config_sha256"] == fingerprint(directory)
    assert manifest["unchanged_private_sha256"] == unchanged_hash()
    verify_image(target)
    # Only values from the two previously verified generations can be replaced.
    for name in FILES + [ROLE + ".env"]:
        raw = m.private(PRIVATE / name).read_bytes()
        assert raw in [m.private(GEN / x / name).read_bytes() for x in ["full", "core"]]
    for name in FILES + [ROLE + ".env"]:
        raw = m.private(directory / name).read_bytes()
        if raw != m.private(PRIVATE / name).read_bytes():
            temp = PRIVATE / (name + ".compatible-selection.tmp")
            write(temp, raw)
            os.replace(temp, PRIVATE / name)
    assert fingerprint(PRIVATE) == manifest["config_sha256"]
    if ROLE == "worker":
        cli("select-version", directory / "manifest.json")
        cli("status")
    else:
        # Controller DB/Redis deliberately stay alive: host selection, no
        # claim that its installed all-project-stopped selector was exercised.
        for name in ["controller-ops.json", "worker-ops.json"]:
            saved = json.loads(m.private(GEN / "full" / name).read_bytes())
            active = json.loads(m.private(PRIVATE / name).read_bytes())
            assert active == {**saved, "image": active["image"]}
            assert active["image"] in [FULL, CORE]
            saved["image"] = target
            temp = PRIVATE / (name + ".compatible-selection.tmp")
            write(temp, encoded(saved))
            os.replace(temp, PRIVATE / name)
    assert image() == target
    return {"selected": label, "role": ROLE, "image_id": target, "config_sha256": fingerprint(PRIVATE), "worker_installed_select_version": ROLE == "worker", "controller_native_selector_verified": False}


def main():
    global ROLE
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["controller", "worker"])
    p.add_argument("action", choices=["prepare", "snapshot", "stop", "start", "select-core", "select-full"])
    a = p.parse_args()
    ROLE = a.role
    m.IMAGE = image()
    if a.action == "prepare":
        value = prepare()
    elif a.action.startswith("select-"):
        value = select(a.action.removeprefix("select-"))
    else:
        m.preflight(ROLE)
        history = m.controller_fence() if ROLE == "controller" else None
        if a.action in ["stop", "start"]:
            if ROLE == "worker":
                cli("preflight")
                cli(a.action)
                cli("status")
            else:
                m.compose(a.action)
        rows = containers()
        for x in rows:
            assert x["running"] is (a.action != "stop" or x["service"] in ["postgres", "redis"])
            if x["running"] and x["service"] in ["resident", "gateway", "mcp"]:
                assert x["image"] == m.IMAGE
            if x["running"] and x["service"] in ["resident", "gateway"]:
                assert x["health"] == "healthy"
            if x["service"] == "resident":
                assert x["cpu"] == 500000000 and x["memory"] == 1073741824
        if ROLE == "worker" and a.action == "stop":
            assert m.physical() == 0
        if history is not None:
            assert history == m.controller_fence()
        if a.action != "stop":
            with m.urllib.request.urlopen("https://192.168.0.190:2026/health/ready", context=m.ssl.create_default_context(cafile=str(m.private(PRIVATE / "ca.crt"))), timeout=20) as response:
                assert response.status == 200
        value = {"role": ROLE, "action": a.action, "containers": rows, "history_sha256": history, "image_id": m.IMAGE, "unchanged_private_sha256": unchanged_hash(), "configuration_sha256": fingerprint(PRIVATE)}
    print(json.dumps({**value, "operator_drain": True, "models_called": False}), flush=True)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[2] == "prepare":
            main()
        else:
            lock = m.private(PRIVATE.parent / "operator/compatible-rollback.lock")
            with os.fdopen(os.open(lock, os.O_RDWR | os.O_NOFOLLOW), "r+") as lock_file:
                entry = os.fstat(lock_file.fileno())
                assert stat.S_ISREG(entry.st_mode) and entry.st_uid == 0 and stat.S_IMODE(entry.st_mode) == 0o600
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                main()
    except Exception as exc:
        print(json.dumps({"compatible_rollback_refused": True, "exception_class": type(exc).__name__, "models_called": False}), flush=True)
        raise SystemExit(1) from None
