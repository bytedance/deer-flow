"""Run with the pinned backend dependencies and a built DSH_CHECKOUT (README)."""

import json
import os
import re
import shutil
import subprocess

import pytest
import yaml

RECEIPT = r"PASS-[0-9a-f]{24}"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    env = {
        "HOME": str(home),
        "DEER_FLOW_HOME": str(tmp_path / "gateway"),
        "DEER_FLOW_PROJECT_ROOT": str(tmp_path),
        "DEER_FLOW_SKILLS_PATH": str(tmp_path / "skills"),
        "DEER_FLOW_CONFIG_PATH": str(tmp_path / "config.yaml"),
        "DEER_FLOW_EXTENSIONS_CONFIG_PATH": str(tmp_path / "extensions_config.json"),
        "DEER_FLOW_AUTH_DISABLED": "1",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    (tmp_path / "extensions_config.json").write_text("{}")
    (tmp_path / "skills/public").mkdir(parents=True)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "config_version": 67,
                "models": [
                    {
                        "name": "offline",
                        "model": "offline",
                        "use": "support.workflow_gateway:AcceptanceModel",
                    }
                ],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "memory": {"enabled": False},
                "title": {"enabled": False},
                "summarization": {"enabled": False},
                "database": {
                    "backend": "sqlite",
                    "sqlite_dir": str(tmp_path / "sqlite"),
                },
            }
        )
    )

    from fastapi.testclient import TestClient
    from app.gateway.app import create_app
    from deerflow.config.app_config import reset_app_config
    from probe import install_probe

    reset_app_config()
    app = create_app()
    work = tmp_path / "toy-repo"
    work.mkdir()
    observations = install_probe(app, work, home)
    with TestClient(app, base_url="http://localhost") as client:
        yield client, observations, work
    reset_app_config()


def thread(client, assistant=None):
    response = client.post("/api/threads", json={"assistant_id": assistant})
    assert response.status_code == 200, response.text
    return response.json()["thread_id"]


def turn(client, conversation, prompt):
    response = client.post(
        f"/api/experiment/threads/{conversation}/turn", json={"prompt": prompt}
    )
    assert response.status_code == 200, response.text
    return response.json()


def check_native_turn(client, native, prompt):
    state = turn(client, native, prompt)
    assert "messages" in state, state
    message = state["messages"][-1]
    assert message["type"] == "ai" and json.loads(message["content"]) == {
        "echo": prompt
    }, message
    runs = client.get(f"/api/threads/{native}/runs")
    assert runs.status_code == 200, runs.text
    assert [r["status"] for r in runs.json()] == ["success"]


def test_native_path(gateway):
    client, observations, _ = gateway
    check_native_turn(client, thread(client), "Native conversation control")
    assert not observations


@pytest.mark.parametrize("test_executor", ["dsh-shell", "host-control"])
def test_routing_restart_and_history(gateway, test_executor):
    client, observations, work = gateway
    node = shutil.which("node")
    assert node and os.environ.get("DSH_CHECKOUT"), (
        "Set DSH_CHECKOUT and install Node.js."
    )
    subprocess.run(["git", "init", "--quiet", work], check=True)
    source = work / "sum.cjs"
    source.write_text("module.exports = (a, b) => a - b\n")
    (work / "test.cjs").write_text(
        "require('node:assert/strict').equal(require('./sum.cjs')(2, 3), 5)\n"
        "console.log('PASS-' + require('node:crypto').randomBytes(12).toString('hex'))\n"
    )
    subprocess.run(["git", "-C", work, "add", "sum.cjs", "test.cjs"], check=True)

    def run_test():
        return subprocess.run(
            [node, "test.cjs"], cwd=work, capture_output=True, text=True, check=False
        )

    baseline = run_test()
    assert baseline.returncode and "ERR_ASSERTION" in baseline.stderr
    coding, native, clean = (
        thread(client, "dsh-coding"),
        thread(client),
        thread(client, "dsh-coding"),
    )

    shell = test_executor == "dsh-shell"
    answer = turn(client, coding, "Probe: fix and test" if shell else "Probe: fix only")
    _, pid1, session1, frames = observations[-1]
    calls = [f["tool"] for f in frames if f["type"] == "tool_call"]
    results = [f for f in frames if f["type"] == "tool_result"]
    assert calls == (["write", "bash"] if shell else ["write"]), (calls, results)
    assert len(results) == len(calls) and results[0]["status"] == "completed", results
    assert source.read_text() == "module.exports = (a, b) => a + b\n"
    changed = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=work, text=True
    )
    assert changed.splitlines() == ["sum.cjs"]
    host_check = run_test()
    assert host_check.returncode == 0
    if shell:
        assert results[1]["status"] == "completed", results[1]
        assert answer == {"answer": "Tests passed."}, results
        receipt = re.search(RECEIPT, results[1]["result"])[0]
    else:
        assert answer == {"answer": "Edit requested."}
        receipt = re.fullmatch(RECEIPT, host_check.stdout.strip())[0]
        receipt_file = work / "receipt.txt"
        receipt_file.write_text(receipt)
        assert turn(client, coding, "Probe: record test receipt") == {
            "answer": "Receipt recorded."
        }
        _, read_pid, read_session, read_frames = observations[-1]
        assert read_session == session1 and read_pid != pid1
        read_calls = [f["tool"] for f in read_frames if f["type"] == "tool_call"]
        assert read_calls == ["read"]
        receipt_file.unlink()
        with pytest.raises(ProcessLookupError):
            os.kill(read_pid, 0)
    assert not any(receipt.encode() in p.read_bytes() for p in work.glob("*.cjs"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid1, 0)

    check_native_turn(client, native, "Native thread between two coding turns")
    assert len(observations) == (1 if shell else 2)
    follow_up = "Probe: recall the test receipt"
    assert turn(client, coding, follow_up) == {"answer": receipt}
    _, pid2, session2, resumed = observations[-1]
    assert pid1 != pid2 and session1 == session2
    assert not any(f["type"] == "tool_call" for f in resumed)
    assert turn(client, clean, follow_up) == {"answer": "No test receipt in history."}
    assert observations[-1][2] != session1
    assert not any(f["type"] == "tool_call" for f in observations[-1][3])
