"""Owned controller entry: native cookie API thread, then the reviewed oneoff ToolNode fixture."""

import http.cookiejar
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import urllib.request
import uuid

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
CORE = "sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338"
ORIGIN = "https://192.168.0.190:2026"


def private(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return path


def run(args, payload=None):
    r = subprocess.run(args, input=payload, capture_output=True, timeout=120)
    assert r.returncode == 0
    return r.stdout


def main():
    assert os.getuid() == 0
    owner = json.loads(private(OPERATOR / "owner.json").read_text())["owner_id"]
    snapshot = json.loads(private(OPERATOR / "b-extensions.json").read_text())
    assert snapshot["mcpServers"]["ecs"]["user_auth"]["users"] == {
        owner: "$ECS_OWNER_HEADER"
    }
    network = "deer-native-820d7a3429d9-controller_control"
    base = [
        "docker",
        "run",
        "--rm",
        "--cpus",
        "0.5",
        "--memory",
        "1g",
        "--network",
        network,
        "--env-file",
        str(private(PRIVATE / "controller.env")),
        "-e",
        "DEER_FLOW_HOME=/srv/deerflow-native-test",
        "-e",
        "DEER_FLOW_CONFIG_PATH=/run/operator/native.json",
        "-e",
        "DEER_FLOW_EXTENSIONS_CONFIG_PATH=/run/fixture/b-extensions.json",
        "-v",
        str(PRIVATE) + ":/run/operator:ro",
        "-v",
        str(PRIVATE) + ":" + str(PRIVATE) + ":ro",
        "-v",
        "/srv/deerflow-native-test:/srv/deerflow-native-test",
        "-v",
        str(private(OPERATOR / "b-extensions.json"))
        + ":/run/fixture/b-extensions.json:ro",
    ]
    # Existing operator admission commands need no Docker socket. Their private
    # config points at worker scope, while the original signed snapshot overlays
    # extensions solely for strict configuration_preflight in this oneoff.
    for action in ["preflight", "resume", "status"]:
        args = [
            *base,
            "-v",
            str(private(OPERATOR / "b-extensions.json"))
            + ":/run/operator/extensions.json:ro",
            "-v",
            str(private(OPERATOR / "b-extensions.json"))
            + ":"
            + str(PRIVATE / "extensions.json")
            + ":ro",
            CORE,
            "python",
            "-m",
            "ecs_executor.operations",
            action,
            "--config",
            "/run/operator/worker-ops.json",
        ]
        result = run(args)
        if action == "status":
            status = json.loads(result)
            print(json.dumps({"worker_operator_status": status}), flush=True)
    jar = http.cookiejar.MozillaCookieJar(str(private(OPERATOR / "owner.cookies")))
    jar.load(ignore_discard=True, ignore_expires=False)
    csrf = next(c.value for c in jar if c.name == "csrf_token" and not c.is_expired())
    client = urllib.request.build_opener(
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=str(private(PRIVATE / "ca.crt")))
        ),
        urllib.request.HTTPCookieProcessor(jar),
    )
    thread = "native-b-820d7a3429d9-" + uuid.uuid4().hex
    request = urllib.request.Request(
        ORIGIN + "/api/threads",
        data=json.dumps({"thread_id": thread}).encode(),
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    with client.open(request, timeout=30) as r:
        assert r.status in [200, 201] and json.load(r)["thread_id"] == thread
    request_path = OPERATOR / "b-thread.json"
    fd = os.open(
        request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    payload = json.dumps({"owner": owner, "thread_id": thread}).encode()
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    log_path = OPERATOR / "b-main.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        args = [
            *base,
            "-i",
            "-v",
            str(private(ROOT / "bootstrap/ecs_native_shanghai_b_main.py"))
            + ":/run/fixture/b-main.py:ro",
            CORE,
            "python",
            "/run/fixture/b-main.py",
        ]
        r = subprocess.run(
            args, input=payload, stdout=stream, stderr=stream, timeout=240
        )
    assert r.returncode == 0
    allowed = []
    for line in log_path.read_text().splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get("b_stage") == "native_persisted" or value.get("b_main") == "PASS":
            allowed.append(value)
    assert len(allowed) == 2 and allowed[-1]["b_main"] == "PASS"
    print(
        json.dumps(
            {
                "b_oneoff": allowed,
                "owned_thread_retained_for_native_cleanup": True,
                "models_called": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned B entry failed; logs/work retained, private details withheld"
        ) from None
