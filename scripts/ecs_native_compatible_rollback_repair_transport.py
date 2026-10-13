"""One same-generation rollback and restoration; no models or admission resume."""

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import signal
import stat
from pathlib import Path

WORK = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
HOST_SHA = "70551649aad0baf84e7ec80430c199598ac208bf3c34d90c7d68529771de49cd"
REMOTE = "/srv/deerflow-native-task6b/56636cebddc6/bootstrap/ecs_native_compatible_rollback_repair_host.py"
FULL = "sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e"
CORE = "sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1"
CONTROLLER, WORKER = "192.168.0.190", "192.168.0.189"


def private(path):
    s = path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o600
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore-only", action="store_true")
    args = parser.parse_args()
    marker = WORK / "proof/compatible-rollback-started.json"
    proof = WORK / "proof/compatible-rollback.json"
    if args.restore_only and not marker.exists():
        assert not marker.is_symlink()
        print(json.dumps({"compatible_rollback_post": "NO_STARTED_MARKER", "remote_actions": False, "models_called": False}), flush=True)
        return
    if not args.restore_only:
        assert not proof.exists() and not proof.is_symlink()
        assert not marker.exists() and not marker.is_symlink()
    browser = private(WORK / "proof/browser-control-repair-main.json").read_bytes()
    assert hashlib.sha256(browser).hexdigest() == "1bdab66abb7e06788320818ca3b0f33e949a1316338f5a827722c009ad333f09"
    value = json.loads(browser)
    assert value["browser_control_main"] == "PASS" and value["image_id"] == FULL
    assert value["owned_browser_retired"] and value["history_preserved"] and value["same_native_scope_and_browser_pid"]
    assert value["models_called"] is False and value["admission_resumed"] is False
    helper = WORK / "scripts/ecs_native_shanghai_bootstrap.py"
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
    spec = importlib.util.spec_from_file_location("bootstrap", helper)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for host in [CONTROLLER, WORKER]:
        m.copy_public(host, WORK / "scripts/ecs_native_compatible_rollback_repair_host.py", REMOTE, HOST_SHA)
    steps = []

    def invoke(role, action):
        host = CONTROLLER if role == "controller" else WORKER
        raw = m.run(["ssh", *m.OPTIONS, "root@" + host, "python3 " + shlex.quote(REMOTE) + " " + role + " " + action], timeout=750)
        v = json.loads(raw)
        assert not v.get("compatible_rollback_refused") and v["operator_drain"] and v["models_called"] is False
        steps.append(v)
        print(json.dumps({"compatible_rollback_step": role + "_" + action, "passed": True, "models_called": False}), flush=True)
        return v

    def save(path, value):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(value, f)
            print(file=f)
            f.flush()
            os.fsync(f.fileno())

    def restore():
        # Fixed ordered recovery; per-host locks wait for any orphaned RPC.
        invoke("worker", "stop")
        invoke("controller", "stop")
        invoke("controller", "select-full")
        invoke("worker", "select-full")
        invoke("controller", "start")
        invoke("worker", "start")

    def verify_restored(before_c, before_w):
        after_c = invoke("controller", "snapshot")
        after_w = invoke("worker", "snapshot")
        assert after_c["image_id"] == after_w["image_id"] == FULL
        assert before_c["history_sha256"] == after_c["history_sha256"]
        for before, after in [(before_c, after_c), (before_w, after_w)]:
            assert before["configuration_sha256"] == after["configuration_sha256"]
            assert before["unchanged_private_sha256"] == after["unchanged_private_sha256"]
            for old in before["containers"]:
                new = next(x for x in after["containers"] if x["service"] == old["service"])
                assert old["volumes"] == new["volumes"]
                if old["service"] in ["postgres", "redis", "frontend", "proxy"]:
                    assert old == new

    if args.restore_only:
        started = json.loads(private(marker).read_bytes())
        assert started["host_sha256"] == HOST_SHA and started["hosts"] == [CONTROLLER, WORKER]
        assert started["image_id"] == FULL and started["models_called"] is False
        before_c, before_w = started["before_controller"], started["before_worker"]
        already = None
        if proof.exists() or proof.is_symlink():
            already = json.loads(private(proof).read_bytes())
            assert already["compatible_rollback"] in ["PASS", "FAIL"] and already["models_called"] is False
        if already and already["restoration_completed"]:
            verify_restored(before_c, before_w)
            print(json.dumps({"compatible_rollback_post": "ALREADY_RESTORED_VERIFIED", "roles_stopped_again": False, "models_called": False}), flush=True)
            return
        restored = WORK / "proof/compatible-rollback-post-restored.json"
        if restored.exists() or restored.is_symlink():
            value = json.loads(private(restored).read_bytes())
            assert value["host_sha256"] == HOST_SHA and value["restoration_completed"] and value["models_called"] is False
            verify_restored(before_c, before_w)
            return
        # Exactly one post recovery attempt; an unknown/partial attempt is retained.
        save(WORK / "proof/compatible-rollback-post-started.json", {"host_sha256": HOST_SHA, "models_called": False})
        restore()
        verify_restored(before_c, before_w)
        save(restored, {"compatible_rollback_post": "RESTORED", "host_sha256": HOST_SHA, "steps": steps, "restoration_completed": True, "operator_drain": True, "models_called": False})
        print(json.dumps({"compatible_rollback_post": "RESTORED", "operator_drain": True, "models_called": False}), flush=True)
        return

    # Both restoration generations exist and are verified before the first stop.
    invoke("controller", "prepare")
    invoke("worker", "prepare")
    before_c = invoke("controller", "snapshot")
    before_w = invoke("worker", "snapshot")
    save(marker, {"host_sha256": HOST_SHA, "hosts": [CONTROLLER, WORKER], "image_id": FULL, "before_controller": before_c, "before_worker": before_w, "models_called": False})
    started = False
    failure = None
    recovery = False
    try:
        started = True
        invoke("worker", "stop")
        invoke("controller", "stop")
        invoke("controller", "select-core")
        invoke("worker", "select-core")
        invoke("controller", "start")
        invoke("worker", "start")
        core_c = invoke("controller", "snapshot")
        core_w = invoke("worker", "snapshot")
        assert core_c["image_id"] == core_w["image_id"] == CORE
        assert core_c["history_sha256"] == before_c["history_sha256"]
        for old in before_c["containers"]:
            if old["service"] in ["postgres", "redis"]:
                assert old == next(x for x in core_c["containers"] if x["service"] == old["service"])
    except Exception as exc:
        failure = type(exc).__name__
    finally:
        if started:
            # One fixed recovery sequence, no retries, no force/prune/volumes.
            # Any refusal retains drained state and prepared private snapshots.
            try:
                restore()
                recovery = True
            except Exception as exc:
                failure = failure or type(exc).__name__
    if failure or not recovery:
        fd = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"compatible_rollback": "FAIL", "exception_class": failure, "steps": steps, "restoration_completed": recovery, "operator_drain": True, "models_called": False, "retry_permitted": False}, f)
            print(file=f)
    assert recovery, "Restoration refused; retain drain and prepared generation"
    verify_restored(before_c, before_w)
    assert failure is None, "Rollback failed; restoration completed without model calls"
    out = {
        "compatible_rollback": "PASS",
        "sequence": [FULL, CORE, FULL],
        "steps": steps,
        "worker_installed_select_version": True,
        "controller_host_selection": True,
        "controller_native_selector_verified": False,
        "same_schema_generation": True,
        "history_and_NAS_preserved": True,
        "unchanged_private_material_preserved": True,
        "database_time_rollback": False,
        "OS_reboot_verified": False,
        "operator_drain": True,
        "models_called": False,
        "admission_resumed": False,
        "restoration_completed": recovery,
    }
    fd = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(out, f)
        print(file=f)
    print(json.dumps({"compatible_rollback": "PASS", "restoration_completed": True, "operator_drain": True, "models_called": False}), flush=True)


if __name__ == "__main__":

    def interrupted(signum, frame):
        raise RuntimeError("Owned rollback interrupted; invoke fixed restoration")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except Exception as exc:
        print(json.dumps({"compatible_rollback_failed": True, "exception_class": type(exc).__name__, "models_called": False, "retry_permitted": False}), flush=True)
        raise SystemExit(1) from None
