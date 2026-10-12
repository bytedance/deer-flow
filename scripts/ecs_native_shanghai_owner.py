"""Initialize the owned native user through the actual API, then rebind idle maps."""

import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
ORIGIN = "https://192.168.0.190:2026"


def checked(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return path


def write(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def replace(path, value):
    checked(path)
    candidate = path.with_name(path.name + ".owner-new")
    write(candidate, (json.dumps(value, indent=2) + "\n").encode())
    os.replace(candidate, path)


def main():
    assert os.getuid() == 0
    for p in [PRIVATE, OPERATOR, *PRIVATE.parents]:
        assert not p.is_symlink()
    for directory in [PRIVATE, OPERATOR]:
        assert (
            directory.stat().st_uid == 0
            and stat.S_IMODE(directory.stat().st_mode) == 0o700
        )
    # This fixed initial bootstrap refuses any prior run/task/job, even terminal.
    base = [
        "docker",
        "compose",
        "--project-name",
        "deer-native-820d7a3429d9-controller",
        "--env-file",
        str(checked(PRIVATE / "controller.env")),
        "-f",
        str(ROOT / "source/examples/ecs-native/deploy/controller.compose.yaml"),
    ]
    for db, sql in [
        (
            "deerflow",
            "SELECT (SELECT count(*) FROM runs)+(SELECT count(*) FROM mcp_tasks);",
        ),
        ("deerflow_execution", "SELECT count(*) FROM ecs_execution_jobs;"),
    ]:
        r = subprocess.run(
            [
                *base,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                db,
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ],
            capture_output=True,
            timeout=30,
        )
        assert r.returncode == 0 and r.stdout.strip() == b"0"
    init = json.loads(checked(OPERATOR / "owner-init.json").read_text())
    jars = http.cookiejar.MozillaCookieJar(str(OPERATOR / "owner.cookies"))
    client = urllib.request.build_opener(
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=str(checked(PRIVATE / "ca.crt")))
        ),
        urllib.request.HTTPCookieProcessor(jars),
    )
    payload = {k: init[k] for k in ["email", "password", "remember_me"]}
    request = urllib.request.Request(
        ORIGIN + "/api/v1/auth/initialize",
        data=json.dumps(payload).encode(),
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    try:
        with client.open(request, timeout=30) as r:
            assert r.status == 201
            user = json.load(r)
        recovery = False
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise RuntimeError("Native initialization refused") from None
        # Never create another admin or patch SQL. Authenticate the same owned account.
        form = urllib.parse.urlencode(
            {
                "username": init["email"],
                "password": init["password"],
                "remember_me": "false",
            }
        ).encode()
        with client.open(
            urllib.request.Request(
                ORIGIN + "/api/v1/auth/login/local",
                data=form,
                headers={
                    "Origin": ORIGIN,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ),
            timeout=30,
        ) as r:
            assert r.status == 200
        with client.open(ORIGIN + "/api/v1/auth/me", timeout=30) as r:
            user = json.load(r)
        recovery = True
    owner = str(uuid.UUID(user["id"]))
    assert user["email"] == init["email"] and user["system_role"] == "admin"
    assert any(c.name == "csrf_token" for c in jars)
    cookie_path = OPERATOR / "owner.cookies"
    if cookie_path.exists() or cookie_path.is_symlink():
        checked(cookie_path)
    else:
        write(cookie_path, b"")
    cookie_new = OPERATOR / "owner.cookies.new"
    write(cookie_new, b"")
    jars.save(str(cookie_new), ignore_discard=True, ignore_expires=True)
    os.chmod(cookie_new, 0o600)
    os.replace(cookie_new, cookie_path)
    for name in ["executor.json", "extensions.json"]:
        value = json.loads(checked(PRIVATE / name).read_text())
        if name == "executor.json":
            assert value["user_profiles"] in [
                {init["placeholder_owner"]: ["small"]},
                {owner: ["small"]},
            ]
            assert value["user_credential_env"] in [
                {init["placeholder_owner"]: "ECS_OWNER_TOKEN"},
                {owner: "ECS_OWNER_TOKEN"},
            ]
            value["user_profiles"] = {owner: ["small"]}
            value["user_credential_env"] = {owner: "ECS_OWNER_TOKEN"}
        else:
            auth = value["mcpServers"]["ecs"]["user_auth"]
            assert auth["users"] in [
                {init["placeholder_owner"]: "$ECS_OWNER_HEADER"},
                {owner: "$ECS_OWNER_HEADER"},
            ]
            auth["users"] = {owner: "$ECS_OWNER_HEADER"}
        replace(PRIVATE / name, value)
    envelope_path = checked(OPERATOR / "worker-envelope.json")
    envelope = json.loads(envelope_path.read_text())
    for name in ["executor.json", "extensions.json"]:
        envelope["files"][name] = checked(PRIVATE / name).read_text()
    replace(envelope_path, envelope)
    receipt = {
        "owner_id": owner,
        "same_account_recovery": recovery,
        "native_api_session": True,
        "csrf_cookie": True,
        "initial_idle": True,
        "models_called": False,
    }
    path = OPERATOR / "owner.json"
    if path.exists() or path.is_symlink():
        prior = json.loads(checked(path).read_text())
        assert prior["owner_id"] == owner
        replace(path, receipt)
    else:
        write(path, (json.dumps(receipt) + "\n").encode())
    print(
        json.dumps(
            {
                **receipt,
                "envelope_sha256": hashlib.sha256(
                    envelope_path.read_bytes()
                ).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Owned owner initialization/rebind refused; private files retained, details withheld"
        ) from None
