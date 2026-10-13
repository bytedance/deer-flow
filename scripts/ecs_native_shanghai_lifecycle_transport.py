"""One reviewed installed lifecycle slice; no models, admission resume or config edits."""

import hashlib
import importlib.util
import json
import os
import shlex
import stat
from pathlib import Path

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6/bootstrap/ecs_native_shanghai_lifecycle_host_repair.py"
HOST_SHA = "098b6105a26abea10eed62e31b15c0a634daec468fd41c88f037d403b23fc89a"
CONTROLLER = "192.168.0.190"
WORKER = "192.168.0.189"


def main():
    proof = ROOT / "proof/installed-lifecycle.json"
    assert not proof.exists() and not proof.is_symlink()
    previous = ROOT / "proof/bc-repair-verification.json"
    s = previous.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o600
    v = json.loads(previous.read_bytes())
    assert v["publication_image_id"] == "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
    assert v["bc_main"] == "PASS" and v["operator_drain"] and v["all_physical_stopped"] and v["pending_notifications"] == 0
    helper = ROOT / "scripts/ecs_native_shanghai_bootstrap.py"
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
    spec = importlib.util.spec_from_file_location("fixed_bootstrap", helper)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for host in [CONTROLLER, WORKER]:
        m.copy_public(host, ROOT / "scripts/ecs_native_shanghai_lifecycle_host.py", REMOTE, HOST_SHA)
    steps = []

    def invoke(host, role, action):
        # Only fixed enum arguments; remote helper withholds command output.
        data = m.run(["ssh", *m.OPTIONS, "root@" + host, "python3 " + shlex.quote(REMOTE) + " " + role + " " + action], timeout=750)
        value = json.loads(data)
        assert not value.get("lifecycle_refused") and value["operator_drain"] and value["models_called"] is False
        steps.append(value)
        print(json.dumps({"lifecycle_step": role + "_" + action, "passed": True, "models_called": False}), flush=True)
        return value

    before_c = invoke(CONTROLLER, "controller", "snapshot")
    before_w = invoke(WORKER, "worker", "snapshot")
    invoke(WORKER, "worker", "stop")
    invoke(CONTROLLER, "controller", "stop")
    # DB/Redis never stop. If restore fails, preserve drain/resources and stop
    # this phase; no retry, volume deletion, image selection or model call.
    invoke(CONTROLLER, "controller", "start")
    invoke(WORKER, "worker", "start")
    invoke(WORKER, "worker", "restart")
    after_c = invoke(CONTROLLER, "controller", "snapshot")
    after_w = invoke(WORKER, "worker", "snapshot")
    assert before_c["history_sha256"] == after_c["history_sha256"]
    for before, after in [(before_c, after_c), (before_w, after_w)]:
        assert before["before"] == after["after"]
    value = {
        "installed_lifecycle": "PASS",
        "scope": "worker_installed_operations_stop_start_restart_controller_host_Compose_stop_start",
        "controller_native_CLI_verified": False,
        "steps": steps,
        "history_preserved": True,
        "volumes_and_container_ids_preserved": True,
        "image_id": v["publication_image_id"],
        "operator_drain": True,
        "models_called": False,
        "config_changed": False,
        "image_selection_or_rollback": False,
    }
    fd = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
    print(json.dumps({"installed_lifecycle": "PASS", "scope": value["scope"], "operator_drain": True, "models_called": False}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"installed_lifecycle_failed": True, "exception_class": type(e).__name__, "models_called": False, "retry_permitted": False}), flush=True)
        raise SystemExit(1) from None
