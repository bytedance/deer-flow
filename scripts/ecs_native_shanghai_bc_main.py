"""One installed native goal C-to-B-to-C main, using existing notification machinery."""

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
    completed_c = json.loads(private(ROOT / "proof/c-repair-main.json").read_text())
    assert (
        completed_c["c_main"] == "PASS"
        and completed_c["run_id"] == "86a41bdc-a550-4557-81d9-1165e91ae8c7"
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
    assert not (OPERATOR / "bc-thread.json").exists()
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

    def api(path, payload=None, method=None):
        req = urllib.request.Request(
            ORIGIN + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        with client.open(req, timeout=30) as response:
            assert response.status in [200, 201]
            return json.load(response)

    assert api("/api/v1/auth/me")["id"] == owner
    thread = "native-bc-820d7a3429d9-" + uuid.uuid4().hex
    assert api("/api/threads", {"thread_id": thread})["thread_id"] == thread
    write(OPERATOR / "bc-thread.json", {"owner": owner, "thread_id": thread})
    objective = "Submit the delegated B command once; when its actual output is available, read the B output file and deliver it with native present_files. The delivered file must contain dependency-proof-338350."
    original_goal = api(
        f"/api/threads/{thread}/goal", {"objective": objective}, method="PUT"
    )["goal"]
    prompt = (
        "Use the ecs submit tool (discover it via tool_search if necessary) ONCE with request_key='bc-main', profile='small', "
        "argv=['sh','-c','sleep 20; printf dependency-proof-338350 > /output/b.txt']. This job executes outside your current native run. "
        "End this turn immediately after durable submission; do not poll, sleep or simulate its output. Wait for the automatic terminal notification. "
        "On that later notification, find its published /mnt/user-data/outputs/<job-id>/files/b.txt using native tools, read it and present_files that exact file to achieve the active goal."
    )
    admitted = api(
        f"/api/threads/{thread}/runs",
        {
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "context": {"model_name": "deepseek-chat"},
            "on_disconnect": "continue",
            "config": {"recursion_limit": 100},
        },
    )
    source_id = admitted["run_id"]
    uuid.UUID(source_id)
    write(
        ROOT / "proof/bc-admission.json",
        {
            "thread_id": thread,
            "source_run_id": source_id,
            "native_goal": True,
            "one_round": True,
        },
    )
    runs_sql = f"SELECT coalesce(json_agg(json_build_object('run_id',run_id,'status',status,'goal_verdict',goal_verdict) ORDER BY created_at),'[]'::json) FROM runs WHERE thread_id='{thread}';"
    jobs_sql = f"SELECT coalesce(json_agg(record),'[]'::json) FROM ecs_execution_jobs WHERE record->'native'->>'thread_id'='{thread}' OR record->>'thread_id'='{thread}';"
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        runs = json.loads(query("deerflow", runs_sql))
        jobs = json.loads(query("deerflow_execution", jobs_sql))
        if len(runs) >= 2 and all(
            run["status"] not in ["pending", "running"] for run in runs
        ):
            break
        time.sleep(2)
    else:
        raise TimeoutError("Native BC continuation terminal result not observed")
    assert len(runs) == 2 and all(run["status"] == "success" for run in runs)
    source = next(
        job
        for job in jobs
        if job.get("kind") == "C" and job["native"]["run_id"] == source_id
    )
    delegated = next(job for job in jobs if job.get("kind", "B") == "B")
    continuation = next(
        job
        for job in jobs
        if job.get("kind") == "C" and job["native"]["run_id"] != source_id
    )
    assert len(jobs) == 3
    assert (
        source["dependency_wait"]["goal"]["created_at"] == original_goal["created_at"]
    )
    assert (
        source["physical_stopped"]
        and delegated["started_at"] >= source["physical_stopped_at"]
    )
    assert (
        source["node_id"]
        == delegated["node_id"]
        == continuation["node_id"]
        == "native-820d7a3429d9"
    )
    assert delegated["attempt"] == 1
    wait_goal = source["dependency_wait"]["goal"]
    assert continuation["native"]["goal"] == wait_goal
    assert (
        runs[-1]["goal_verdict"]["continuations"] >= wait_goal["continuation_count"] + 1
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        jobs = json.loads(query("deerflow_execution", jobs_sql))
        if all(
            job.get("physical_stopped") and not job.get("cleanup_pending")
            for job in jobs
        ):
            break
        time.sleep(2)
    assert all(
        job.get("physical_stopped")
        and not job.get("cleanup_pending")
        and job["state"] == "completed"
        for job in jobs
    )
    task_sql = f"SELECT coalesce(json_agg(json_build_object('id',id,'remote_task_id',remote_task_id,'status',status,'notification_status',notification_status,'notification_run_id',notification_run_id)),'[]'::json) FROM mcp_tasks WHERE user_id='{owner}' AND thread_id='{thread}';"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        tasks = json.loads(query("deerflow", task_sql))
        if len(tasks) == 1 and tasks[0]["notification_status"] == "delivered":
            break
        time.sleep(2)
    assert (
        len(tasks) == 1
        and tasks[0]["status"] == "completed"
        and tasks[0]["notification_status"] == "delivered"
    )
    assert tasks[0]["remote_task_id"] == delegated["id"]
    assert tasks[0]["notification_run_id"] == continuation["native"]["run_id"]
    assert (
        query(
            "deerflow",
            "SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');",
        )
        == "0"
    )
    output = (
        Path("/srv/deerflow-native-test/users")
        / owner
        / "threads"
        / thread
        / "user-data/outputs"
        / delegated["id"]
        / "files/b.txt"
    )
    assert output.read_text() == "dependency-proof-338350"
    state = api(f"/api/threads/{thread}/state")["values"]
    tools = {
        call["name"]
        for message in state["messages"]
        for call in message.get("tool_calls", [])
    }
    assert "read_file" in tools and "present_files" in tools and not state.get("goal")
    receipt = {
        "bc_main": "PASS",
        "native_mcp_task_id": tasks[0]["id"],
        "notification_status": "delivered",
        "pending_notifications": 0,
        "thread_id": thread,
        "source_run_id": source_id,
        "continuation_run_id": continuation["native"]["run_id"],
        "delegated_job_id": delegated["id"],
        "native_run_count": len(runs),
        "node_id": delegated["node_id"],
        "b_attempt": delegated["attempt"],
        "source_physical_stop_before_B": True,
        "native_goal_preserved": True,
        "goal_completed_and_cleared": True,
        "automatic_native_continuation": True,
        "shared_nas_delivered": True,
        "all_physical_stopped": True,
        "ledger_job_ids": [job["id"] for job in jobs],
        "model": "deepseek-chat",
        "scope": "one_installed_native_C_B_C_main",
    }
    write(ROOT / "proof/bc-main.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "bc_main_failed": True,
                    "exception_class": type(error).__name__,
                    "owned_work_retained": True,
                }
            ),
            flush=True,
        )
        raise SystemExit(
            "Native BC main failed; private details withheld, do not blindly rerun"
        ) from None
