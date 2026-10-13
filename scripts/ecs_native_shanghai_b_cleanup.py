"""Recover the deleted thread notification through Gateway; retain terminal audit."""

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import traceback
import sys

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
    if path.exists() or path.is_symlink():
        private(path)
        assert json.loads(path.read_text()) == value
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
        f.write("\n")


def query(db, sql):
    base = [
        "docker",
        "compose",
        "--project-name",
        "deer-native-820d7a3429d9-controller",
        "--env-file",
        str(private(PRIVATE / "controller.env")),
        "-f",
        str(ROOT / "source/examples/ecs-native/deploy/controller.compose.yaml"),
    ]
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
    assert r.returncode == 0
    return r.stdout.decode().strip()


def main():
    assert os.getuid() == 0
    request = json.loads(private(OPERATOR / "b-thread.json").read_text())
    owner = json.loads(private(OPERATOR / "owner.json").read_text())["owner_id"]
    assert request["owner"] == owner
    thread = request["thread_id"]
    assert re.fullmatch(r"native-b-820d7a3429d9-[0-9a-f]{32}", thread)
    stages = []
    for line in private(OPERATOR / "b-main.log").read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("b_stage") == "native_persisted" or d.get("b_main") == "PASS":
            stages.append(d)
    assert (
        len(stages) == 2
        and stages[0]["thread_id"] == thread
        and stages[1]["b_main"] == "PASS"
    )
    task = stages[1]["task_id"]
    job = stages[1]["job_id"]
    assert stages[0]["task_id"] == task and stages[0]["job_id"] == job
    assert re.fullmatch(r"mcp-task-[0-9a-f]{32}", task) and re.fullmatch(
        r"[0-9a-f]{32}", job
    )
    native = query(
        "deerflow",
        f"SELECT status FROM mcp_tasks WHERE id='{task}' AND user_id='{owner}' AND thread_id='{thread}';",
    )
    physical = json.loads(
        query(
            "deerflow_execution",
            f"SELECT json_build_object('state',record->>'state','attempt',record->'attempt','node_id',record->>'node_id','physical_stopped',record->'physical_stopped','cleanup_pending',record->'cleanup_pending') FROM ecs_execution_jobs WHERE id='{job}';",
        )
    )
    assert native == "completed" and physical == {
        "state": "completed",
        "attempt": 1,
        "node_id": "native-820d7a3429d9",
        "physical_stopped": True,
        "cleanup_pending": False,
    }
    proof = ROOT / "proof/b-main.json"
    write(
        proof,
        {
            "stages": stages,
            "native_sql_status": native,
            "ledger_sql": physical,
            "models_called": False,
            "live_b_container_cgroups": "not_captured",
            "jenkins24_result": "FAILURE_outer_blankline_parser",
        },
    )
    assert (
        query(
            "deerflow", f"SELECT count(*) FROM threads_meta WHERE thread_id='{thread}';"
        )
        == "0"
    )
    assert query("deerflow", "SELECT count(*) FROM runs;") == "0"
    assert (
        query(
            "deerflow_execution",
            "SELECT record->>'operator_drain' FROM ecs_execution_nodes WHERE id='native-820d7a3429d9';",
        )
        == "true"
    )
    assert (
        query(
            "deerflow_execution",
            "SELECT count(*) FROM ecs_execution_jobs WHERE coalesce((record->>'physical_stopped')::boolean,false)=false;",
        )
        == "0"
    )
    state = query(
        "deerflow",
        f"SELECT notification_status FROM mcp_tasks WHERE id='{task}' AND user_id='{owner}' AND thread_id='{thread}' AND status='completed';",
    )
    pending = int(
        query(
            "deerflow",
            "SELECT count(*) FROM mcp_tasks WHERE notification_status NOT IN ('none','delivered','dead_letter');",
        )
    )
    if sys.argv[1:] == ["--prepare-notifications"]:
        assert state == "pending" and pending == 1
        config_path = private(PRIVATE / "native.json")
        config = json.loads(config_path.read_text())
        extensions = json.loads(private(PRIVATE / "extensions.json").read_text())
        assert extensions["mcpServers"]["ecs"]["task_toolsets"] == []
        assert extensions.get("mcpInterceptors", []) == []
        assert type(config["mcp_tasks"]["enabled"]) is bool
        if not config["mcp_tasks"]["enabled"]:
            config["mcp_tasks"]["enabled"] = True
            temporary = config_path.with_name("native.cleanup-notifications.tmp")
            write(temporary, config)
            os.replace(temporary, config_path)
        print(
            json.dumps(
                {
                    "normal_notification_service_prepared": True,
                    "deleted_thread_confirmed": True,
                    "native_runs": 0,
                    "admission_drained": True,
                    "models_called": False,
                }
            )
        )
        return
    assert sys.argv[1:] == []
    assert state == "dead_letter" and pending == 0
    assert (
        query("deerflow", f"SELECT count(*) FROM mcp_tasks WHERE thread_id='{thread}';")
        == "1"
    )
    assert (
        query(
            "deerflow_execution",
            f"SELECT count(*) FROM ecs_execution_jobs WHERE id='{job}';",
        )
        == "1"
    )
    receipt = {
        "thread_id": thread,
        "native_api_deleted": True,
        "retained_terminal_mcp_tasks": 1,
        "notification_status": "dead_letter",
        "native_runs": 0,
        "pending_notifications": 0,
        "ledger_history_preserved": True,
        "models_called": False,
    }
    write(ROOT / "proof/b-cleanup.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        frames = traceback.extract_tb(error.__traceback__)
        lines = [
            frame.lineno
            for frame in frames
            if Path(frame.filename).name == Path(__file__).name
        ]
        print(
            json.dumps(
                {
                    "cleanup_failed": True,
                    "exception_class": type(error).__name__,
                    "helper_lines": lines,
                }
            ),
            flush=True,
        )
        raise SystemExit(
            "Owned native B cleanup refused; receipt/work retained, no forced SQL cleanup"
        ) from None
