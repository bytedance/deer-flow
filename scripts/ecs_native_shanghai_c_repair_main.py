"""One real native Gateway C run on the existing two-ECS installation."""

import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import ssl
import stat
import time
import urllib.request
import uuid

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OPERATOR = PRIVATE.parent / "operator"
ORIGIN = "https://192.168.0.190:2026"


def private(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return path


def write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.write("\n")


def main():
    assert os.getuid() == 0
    central = json.loads(private(PRIVATE / "central.json").read_text())
    assert central["role"] == "central" and central["remote_all"] is True
    cleanup = json.loads(private(ROOT / "proof/b-cleanup.json").read_text())
    assert cleanup["pending_notifications"] == cleanup["native_runs"] == 0
    owner = json.loads(private(OPERATOR / "owner.json").read_text())["owner_id"]
    spec = importlib.util.spec_from_file_location(
        "owned_cleanup", ROOT / "bootstrap/ecs_native_shanghai_b_cleanup_recovery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    query = module.query
    assert (
        query(
            "deerflow",
            "SELECT count(*) FROM runs WHERE status NOT IN ('success','error','timeout','interrupted');",
        )
        == "0"
    )
    previous = json.loads(private(ROOT / "proof/c-admission.json").read_text())
    assert previous["run_id"] == "e69ab8b5-7cf7-4181-89a6-02e5f66af011"
    previous_thread = json.loads(private(OPERATOR / "c-thread.json").read_text())
    assert (
        previous_thread["owner"] == owner
        and previous_thread["thread_id"] == previous["thread_id"]
    )
    assert (
        query(
            "deerflow",
            "SELECT status FROM runs WHERE run_id='e69ab8b5-7cf7-4181-89a6-02e5f66af011';",
        )
        == "success"
    )
    assert (
        query(
            "deerflow_execution",
            "SELECT record->>'state' FROM ecs_execution_jobs WHERE id='20d31d4d1f874b5e897ebcdab10f4dc3';",
        )
        == "completed"
    )
    assert (
        json.loads(private(PRIVATE / "native.json").read_text())["sandbox"][
            "container_prefix"
        ]
        == "deer-native-aio-820d7a3429d9"
    )
    assert (
        query(
            "deerflow",
            "SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');",
        )
        == "0"
    )
    assert (
        query(
            "deerflow_execution",
            "SELECT record->>'operator_drain' FROM ecs_execution_nodes WHERE id='native-820d7a3429d9';",
        )
        == "false"
    )
    assert not (OPERATOR / "c-repair-thread.json").exists()
    jar = http.cookiejar.MozillaCookieJar(str(private(OPERATOR / "owner.cookies")))
    jar.load(ignore_discard=True, ignore_expires=False)
    csrf = next(
        cookie.value
        for cookie in jar
        if cookie.name == "csrf_token" and not cookie.is_expired()
    )
    client = urllib.request.build_opener(
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=str(private(PRIVATE / "ca.crt")))
        ),
        urllib.request.HTTPCookieProcessor(jar),
    )
    headers = {
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }

    def api(path, payload=None):
        req = urllib.request.Request(
            ORIGIN + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
        )
        with client.open(req, timeout=30) as response:
            assert response.status in [200, 201]
            return json.load(response)

    assert api("/api/v1/auth/me")["id"] == owner
    thread = "native-c-repair-820d7a3429d9-" + uuid.uuid4().hex
    assert api("/api/threads", {"thread_id": thread})["thread_id"] == thread
    write(OPERATOR / "c-repair-thread.json", {"owner": owner, "thread_id": thread})
    prompt = (
        "Use your native bash tool to write warm_native_c into /tmp/native_c_affinity.txt (container-local, not NAS), then run python3 in the sandbox. "
        "Calculate sum(i*i for i in range(1,101)), write the exact result and platform.system() to /mnt/user-data/outputs/native_c_main.txt. "
        "Read the file with your native read_file tool, then invoke native present_files on that exact output path to deliver it. "
        "Finally answer with its exact contents. You must actually execute the tool."
    )
    admitted = api(
        f"/api/threads/{thread}/runs",
        {
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "context": {"model_name": "deepseek-chat"},
            "stream_mode": ["values", "messages-tuple", "custom"],
            "on_disconnect": "continue",
            "config": {"recursion_limit": 100},
        },
    )
    run = admitted["run_id"]
    uuid.UUID(run)
    write(
        ROOT / "proof/c-repair-admission.json",
        {
            "thread_id": thread,
            "run_id": run,
            "model": "deepseek-chat",
            "native_gateway_api": True,
        },
    )
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        result = api(f"/api/threads/{thread}/runs/{run}")
        if result["status"] in ["success", "error", "timeout", "interrupted"]:
            break
        time.sleep(2)
    else:
        raise TimeoutError("Native C terminal result not observed")
    assert result["status"] == "success"
    state = api(f"/api/threads/{thread}/state")
    messages = state.get("values", {}).get("messages", [])
    tools = {
        call.get("name")
        for message in messages
        for call in message.get("tool_calls", [])
    }
    assert {"bash", "read_file", "present_files"} <= tools
    artifact = (
        Path("/srv/deerflow-native-test/users")
        / owner
        / "threads"
        / thread
        / "user-data/outputs/native_c_main.txt"
    )
    content = artifact.read_text()
    assert "338350" in content and "Linux" in content
    native = json.loads(
        query(
            "deerflow",
            f"SELECT json_build_object('status',status,'owner_worker_id',owner_worker_id) FROM runs WHERE run_id='{run}';",
        )
    )
    assert native["status"] == "success" and native["owner_worker_id"]
    sql = f"SELECT json_build_object('job_id',id,'kind',record->>'kind','state',record->>'state','attempt',record->'attempt','node_id',record->>'node_id','physical_stopped',record->'physical_stopped','cleanup_pending',record->'cleanup_pending') FROM ecs_execution_jobs WHERE record->'native'->>'run_id'='{run}';"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ledger = json.loads(query("deerflow_execution", sql))
        if ledger["physical_stopped"]:
            break
        time.sleep(2)
    assert (
        ledger["kind"] == "C"
        and ledger["attempt"] == 1
        and ledger["node_id"] == "native-820d7a3429d9"
    )
    assert ledger["state"] == "completed"
    assert ledger["physical_stopped"] and not ledger["cleanup_pending"]
    receipt = {
        "c_main": "PASS",
        "thread_id": thread,
        "run_id": run,
        "native_status": native["status"],
        "native_owner_worker_id": native["owner_worker_id"],
        "ledger": ledger,
        "tool_calls": sorted(tools & {"bash", "read_file", "present_files"}),
        "shared_nas_output_verified": True,
        "model": "deepseek-chat",
        "browser_acceptance": "pending_core_image",
        "scope": "one_native_C_main",
    }
    receipt["previous_run_id"] = previous["run_id"]
    receipt["previous_tool_delivery_failed"] = True
    write(ROOT / "proof/c-repair-main.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "c_main_failed": True,
                    "exception_class": type(error).__name__,
                    "owned_work_retained": True,
                }
            ),
            flush=True,
        )
        raise SystemExit(
            "Native C main failed; private details withheld, do not blindly rerun"
        ) from None
