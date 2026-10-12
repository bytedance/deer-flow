"""Fixed installed lifecycle slice: worker native CLI; controller host Compose."""

import argparse
import hashlib
import importlib.util
import json
import os
import ssl
import stat
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
NAS = Path("/srv/deerflow-native-test")
IMAGE = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
NODE = "native-820d7a3429d9"
PREFIX = "deer-native-aio-820d7a3429d9-"


def run(args, timeout=300):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("Owned lifecycle command refused; private output withheld")
    return r.stdout


def private(path):
    s = path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    return path


def preflight(role):
    assert os.getuid() == 0
    for p in [PRIVATE, *PRIVATE.parents]:
        assert not p.is_symlink()
    assert PRIVATE.stat().st_uid == 0 and stat.S_IMODE(PRIVATE.stat().st_mode) == 0o700
    assert os.path.ismount(NAS) and not NAS.is_symlink()
    mount = json.loads(run(["findmnt", "--json", "--target", str(NAS), "-o", "TARGET,SOURCE,FSTYPE"]))["filesystems"][0]
    assert mount["target"] == str(NAS) and mount["fstype"] == "nfs4"
    assert mount["source"].startswith("031sp6l7o6sh4hzha32-jow11.cn-shanghai.nas.aliyuncs.com:/")
    assert (NAS / "pool/pool-mount-id").read_text().strip() == "820d7a3429d9"
    ops = json.loads(private(PRIVATE / (role + "-ops.json")).read_text())
    assert ops["image"] == IMAGE and ops["node_id"] == NODE and ops["role"] == role
    assert ops["project"] == "deer-native-820d7a3429d9-" + role
    assert ops["private_dir"] == str(PRIVATE) and ops["nas_root"] == str(NAS)
    canonical = ROOT / "source/examples/ecs-native/deploy" / (role + ".compose.yaml")
    expected = ROOT / "frontend-build/source/examples/ecs-native/deploy/controller.compose.yaml" if role == "controller" else canonical
    assert ops["compose_file"] == str(expected)
    for path in [expected, canonical]:
        assert stat.S_ISREG(path.lstat().st_mode)
        assert all(not ancestor.is_symlink() for ancestor in [path, *path.parents])
    assert hashlib.sha256(expected.read_bytes()).digest() == hashlib.sha256(canonical.read_bytes()).digest()
    assert ops["sandbox_prefix"] + "-" == PREFIX
    private(PRIVATE / (role + ".env"))
    return ops


def containers(role):
    names = ["resident"] if role == "worker" else ["gateway", "mcp", "frontend", "proxy", "postgres", "redis"]
    values = []
    for service in names:
        name = "deer-native-820d7a3429d9-" + role + "-" + service + "-1"
        x = json.loads(run(["docker", "inspect", name]))[0]
        labels = x["Config"]["Labels"]
        assert labels["com.docker.compose.project"] == "deer-native-820d7a3429d9-" + role
        assert labels["com.docker.compose.service"] == service
        if service in ["resident", "gateway", "mcp"]:
            assert x["Image"] == IMAGE
        socket = any(m["Source"] == "/var/run/docker.sock" for m in x["Mounts"])
        assert socket == (service == "resident")
        values.append(
            {
                "service": service,
                "id": x["Id"],
                "image": x["Image"],
                "running": x["State"]["Running"],
                "health": x["State"].get("Health", {}).get("Status"),
                "volumes": sorted(m["Name"] for m in x["Mounts"] if m["Type"] == "volume"),
                "cpu": x["HostConfig"]["NanoCpus"],
                "memory": x["HostConfig"]["Memory"],
            }
        )
    return values


def controller_fence():
    spec = importlib.util.spec_from_file_location("cleanup", ROOT / "bootstrap/ecs_native_shanghai_b_cleanup_recovery.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.query("deerflow_execution", "SELECT record->>'operator_drain' FROM ecs_execution_nodes WHERE id='native-820d7a3429d9';") == "true"
    assert m.query("deerflow", "SELECT count(*) FROM runs WHERE status NOT IN ('success','error','timeout','interrupted');") == "0"
    assert m.query("deerflow", "SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');") == "0"
    assert m.query("deerflow_execution", "SELECT count(*) FROM ecs_execution_jobs WHERE coalesce((record->>'physical_stopped')::boolean,false)=false OR coalesce((record->>'cleanup_pending')::boolean,false)=true;") == "0"
    hashes = {}
    for db, table in [("deerflow", "runs"), ("deerflow", "mcp_tasks"), ("deerflow_execution", "ecs_execution_jobs")]:
        # Terminal history only. Hash all persisted rows; never emit SQL contents.
        value = m.query(db, "SELECT coalesce(json_agg(v ORDER BY v::text),'[]'::json)::text FROM (SELECT row_to_json(t) AS v FROM " + table + " t) s;")
        hashes[table] = hashlib.sha256(value.encode()).hexdigest()
    for name in ["bc-repair-main.json", "c-repair-main.json", "b-cleanup.json"]:
        hashes[name] = hashlib.sha256(private(ROOT / "proof" / name).read_bytes()).hexdigest()
    owner = json.loads(private(PRIVATE.parent / "operator/owner.json").read_text())["owner_id"]
    output = NAS / "users" / owner / "threads/native-bc-repair-820d7a3429d9-06c502b422e54e648ba3a4216b0c1fde/user-data/outputs/28aa3063aaf4490f881e2b039efdb752/files/b.txt"
    for path in [output, *output.parents]:
        assert not path.is_symlink()
    info = output.stat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    hashes["bc_nas_output"] = hashlib.sha256(output.read_bytes()).hexdigest()
    return hashes


def physical():
    b = run(["docker", "ps", "-aq", "--filter", "label=deerflow.execution.node=" + NODE]).split()
    assert not b
    ids = run(["docker", "ps", "-aq", "--filter", "name=" + PREFIX]).split()
    for container in ids:
        x = json.loads(run(["docker", "inspect", container.decode()]))[0]
        assert x["Name"].lstrip("/").startswith(PREFIX) and x["Config"]["Labels"].get("deerflow.role") == "sandbox"
    return len(ids)


def worker_cli(action):
    # Trusted oneoff admin env is never mounted into the resident. No listener.
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
        str(private(PRIVATE / "worker.env")),
        "--env-file",
        str(private(PRIVATE.parent / "operator/operator.env")),
        "-v",
        str(PRIVATE) + ":/run/operator:ro",
        "-v",
        str(PRIVATE) + ":" + str(PRIVATE) + ":ro",
        "-v",
        str(ROOT / "source") + ":" + str(ROOT / "source") + ":ro",
        "-v",
        str(NAS) + ":" + str(NAS),
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        "/usr/libexec/docker/cli-plugins/docker-compose:/root/.docker/cli-plugins/docker-compose:ro",
        IMAGE,
        "python",
        "-m",
        "ecs_executor.operations",
        action,
        "--config",
        "/run/operator/worker-ops.json",
    ]
    result = run(args, timeout=600)
    if action == "status":
        assert json.loads(result) == {"operator_drain": True, "unreleased": 0}


def compose(action):
    args = ["docker", "compose", "--project-name", "deer-native-820d7a3429d9-controller", "--env-file", str(PRIVATE / "controller.env"), "-f", str(ROOT / "source/examples/ecs-native/deploy/controller.compose.yaml")]
    if action == "stop":
        args += ["stop", "--timeout", "240", "gateway", "mcp", "frontend", "proxy"]
    else:
        args += ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180", "gateway", "mcp", "frontend", "proxy"]
    run(args, timeout=600)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["controller", "worker"])
    p.add_argument("action", choices=["snapshot", "stop", "start", "restart"])
    a = p.parse_args()
    preflight(a.role)
    history = controller_fence() if a.role == "controller" else None
    before = containers(a.role)
    count = physical() if a.role == "worker" else None
    if a.action != "snapshot":
        if a.role == "worker":
            worker_cli("preflight")
            worker_cli("status")
            worker_cli(a.action)
            worker_cli("status")
        else:
            assert a.action in ["stop", "start"]
            compose(a.action)
    after = containers(a.role)
    running = a.action != "stop"
    for x in after:
        expected = True if x["service"] in ["postgres", "redis"] else running
        assert x["running"] is expected
        if expected and x["service"] != "mcp":
            assert x["health"] in [None, "healthy"]
        if x["service"] == "resident":
            assert x["cpu"] == 500000000 and x["memory"] == 1073741824
    if a.role == "controller":
        assert history == controller_fence()
        for service in ["postgres", "redis"]:
            assert next(x for x in before if x["service"] == service) == next(x for x in after if x["service"] == service)
        if running:
            with urllib.request.urlopen("https://192.168.0.190:2026/health/ready", context=ssl.create_default_context(cafile=str(private(PRIVATE / "ca.crt"))), timeout=20) as r:
                assert r.status == 200
    else:
        if a.action in ["stop", "restart"]:
            assert physical() == 0
        if running:
            with urllib.request.urlopen("https://192.168.0.190:2026/health/ready", context=ssl.create_default_context(cafile=str(private(PRIVATE / "ca.crt"))), timeout=20) as r:
                assert r.status == 200
    print(
        json.dumps(
            {"role": a.role, "action": a.action, "before": before, "after": after, "history_sha256": history, "idle_aio_before": count, "operator_drain": True, "models_called": False, "scope": "worker_native_CLI_controller_host_Compose"}
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"lifecycle_refused": True, "exception_class": type(e).__name__, "models_called": False}), flush=True)
        raise SystemExit(1) from None
