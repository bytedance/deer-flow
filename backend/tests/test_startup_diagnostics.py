"""Offline startup probes: real bind checks, controlled Docker/process responses."""

from __future__ import annotations

import errno
import json
import socket
import subprocess
import zipfile

import pytest


@pytest.fixture
def probes(monkeypatch):
    import startup_diagnostics

    monkeypatch.setattr(startup_diagnostics.shutil, "which", lambda name: name)
    monkeypatch.setattr(startup_diagnostics.platform, "system", lambda: "Windows")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    return startup_diagnostics


def command_double(monkeypatch, probes, *, engine=1, endpoint="npipe:////./pipe/dockerDesktopLinuxEngine", desktop=False, compose=0):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs["timeout"] <= 5
        assert not kwargs.get("shell", False)
        if args[1] == "info":
            if engine == "timeout":
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            return subprocess.CompletedProcess(args, engine, '"linux"' if engine == 0 else "", "Bearer secret-not-for-report")
        if args[1:3] == ["context", "inspect"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(endpoint), "")
        if args[1:3] == ["compose", "version"]:
            return subprocess.CompletedProcess(args, compose, "2.24.0", "")
        if args[0] == "tasklist.exe":
            text = '"Docker Desktop.exe","123","Console","1","100 K"' if desktop else "INFO: no tasks"
            return subprocess.CompletedProcess(args, 0, text, "")
        raise AssertionError(args)

    monkeypatch.setattr(probes.subprocess, "run", run)
    return calls


def test_missing_cli_does_not_run_docker(probes, monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", lambda _: None)
    monkeypatch.setattr(probes.subprocess, "run", lambda *a, **k: pytest.fail("must not spawn"))
    results, local = probes.check_docker()
    assert results[0]["code"] == "docker_cli_missing"
    assert results[0]["status"] == "fail"


@pytest.mark.parametrize("desktop,code", [(False, "docker_desktop_not_running"), (True, "docker_engine_unavailable")])
def test_distinguishes_desktop_from_engine(probes, monkeypatch, desktop, code):
    command_double(monkeypatch, probes, desktop=desktop)
    results, local = probes.check_docker()
    assert local is True
    assert results[0]["code"] == code
    assert results[0]["fix"]
    assert "secret-not-for-report" not in json.dumps(results)


@pytest.mark.parametrize("endpoint", ["tcp://user:password@remote.example:2376", "ssh://user@remote.example", "npipe:////remote-server/pipe/docker_engine"])
def test_remote_engine_does_not_blame_desktop(probes, monkeypatch, endpoint):
    calls = command_double(monkeypatch, probes, endpoint=endpoint)
    results, local = probes.check_docker()
    assert local is False
    assert results[0]["code"] == "docker_engine_unavailable"
    assert not any(args[0] == "tasklist.exe" for args, _ in calls)
    assert "password" not in json.dumps(results)
    monkeypatch.setattr(probes, "check_port", lambda *a: pytest.fail("remote ingress is not local"))
    assert probes.collect_startup_diagnostics("docker")["checks"][-1]["code"] == "port_check_skipped"


def test_docker_host_override_and_context_precedence(probes, monkeypatch):
    command_double(monkeypatch, probes)
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote.example")
    assert probes.check_docker()[1] is False
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    assert probes.check_docker()[1] is True


def test_engine_timeout_is_bounded_and_actionable(probes, monkeypatch):
    command_double(monkeypatch, probes, engine="timeout", desktop=True)
    results, _ = probes.check_docker()
    assert results[0]["code"] == "docker_engine_unavailable"
    assert "timed out" in results[0]["detail"]


@pytest.mark.parametrize("compose,status", [(0, "ok"), (1, "fail")])
def test_successful_engine_checks_compose(probes, monkeypatch, compose, status):
    command_double(monkeypatch, probes, engine=0, compose=compose)
    results, _ = probes.check_docker()
    assert results[0]["status"] == "ok"
    assert results[1]["code"] == "docker_compose"
    assert results[1]["status"] == status


@pytest.mark.parametrize("output,status", [('"windows"', "fail"), ("unknown", "warn")])
def test_wrong_container_platform_is_not_ready(probes, monkeypatch, output, status):
    command_double(monkeypatch, probes, engine=0)
    original = probes.subprocess.run

    def run(args, **kwargs):
        if args[1] == "info":
            return subprocess.CompletedProcess(args, 0, output, "")
        return original(args, **kwargs)

    monkeypatch.setattr(probes.subprocess, "run", run)
    assert probes.check_docker()[0][0]["status"] == status


def test_real_occupied_port_is_advisory_and_released(probes, monkeypatch):
    monkeypatch.setattr(probes.platform, "system", lambda: "Linux")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = probes.check_port("127.0.0.1", port)
        assert result["code"] == "port_in_use"
        assert result["status"] == "warn"
        assert "DeerFlow" in result["detail"]
    assert probes.check_port("127.0.0.1", port)["code"] == "port_available"
    # The diagnostic must close its own temporary socket too.
    with socket.socket() as retry:
        retry.bind(("127.0.0.1", port))


def test_windows_listener_pid_is_filtered_by_address_and_state(probes, monkeypatch):
    def run(args, **kwargs):
        assert args == ["netstat.exe", "-ano"]
        return subprocess.CompletedProcess(
            args,
            0,
            "\n".join(
                [
                    "TCP 192.0.2.1:2026 0.0.0.0:0 LISTENING 777",
                    "TCP 127.0.0.1:2026 127.0.0.1:9 ESTABLISHED 888",
                    "TCP 0.0.0.0:2026 0.0.0.0:0 LISTENING 123",
                    "TCP [::]:2026 [::]:0 LISTENING 456",
                ]
            ),
            "",
        )

    monkeypatch.setattr(probes.subprocess, "run", run)
    assert probes.listener_pids("127.0.0.1", 2026) == [123]
    assert probes.listener_pids("::1", 2026) == [456]


def test_access_denied_is_not_reported_as_a_busy_port(probes, monkeypatch):
    class DeniedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, *args):
            pass

        def bind(self, *args):
            raise OSError(errno.EACCES, "private host detail")

    monkeypatch.setattr(probes.socket, "socket", lambda *args: DeniedSocket())
    monkeypatch.setattr(probes, "listener_pids", lambda *args: [])
    result = probes.check_port("127.0.0.1", 2026)
    assert result["code"] == "port_access_denied"
    assert "excludedportrange" in result["fix"]
    assert "private host detail" not in json.dumps(result)


def test_windows_exclusive_listener_access_denied_is_reported_as_in_use(probes, monkeypatch):
    class ExclusiveSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, *args):
            pass

        def bind(self, *args):
            raise OSError(errno.EACCES, "exclusive listener")

    monkeypatch.setattr(probes.socket, "socket", lambda *args: ExclusiveSocket())
    monkeypatch.setattr(probes, "listener_pids", lambda *args: [123])
    result = probes.check_port("127.0.0.1", 2026)
    assert result["code"] == "port_in_use"
    assert result["status"] == "warn"
    assert "123" in result["detail"]


def test_local_mode_does_not_require_docker(probes, monkeypatch):
    ports = []
    monkeypatch.setattr(probes, "check_docker", lambda: pytest.fail("local mode must not probe Docker"))
    monkeypatch.setattr(probes, "check_port", lambda host, port: ports.append((host, port)) or {"status": "ok"})
    probes.collect_startup_diagnostics("local", host="::1")
    assert ports == [("::1", 2026), ("127.0.0.1", 3000), ("127.0.0.1", 8001)]


@pytest.mark.parametrize("kwargs", [{"mode": "invalid"}, {"mode": "docker", "port": 0}, {"mode": "docker", "port": 65536}, {"mode": "local", "port": 3001}, {"mode": "docker", "host": "user:secret@host"}])
def test_invalid_probe_targets_are_rejected_before_commands(probes, monkeypatch, kwargs):
    monkeypatch.setattr(probes.subprocess, "run", lambda *a, **k: pytest.fail("must validate first"))
    with pytest.raises(ValueError):
        probes.collect_startup_diagnostics(**kwargs)


def test_doctor_renders_shared_findings_and_failure_exit(probes, monkeypatch, capsys, tmp_path):
    import doctor

    monkeypatch.setattr(doctor, "__file__", str(tmp_path / "scripts" / "doctor.py"))
    monkeypatch.setattr(doctor, "resolve_config_path", lambda: (tmp_path / "missing.yaml", None))
    names = (
        "check_python",
        "check_node",
        "check_pnpm",
        "check_uv",
        "check_nginx",
        "check_env_file",
        "check_frontend_env",
        "check_config_exists",
        "check_config_version",
        "check_config_loadable",
        "check_models_configured",
        "check_web_search",
        "check_web_fetch",
        "check_web_capture",
        "check_image_search",
    )
    for name in names:
        monkeypatch.setattr(doctor, name, lambda *a: doctor.CheckResult("fixture", "ok"))
    for name in ("check_llm_api_key", "check_llm_auth", "check_llm_package", "check_sandbox"):
        monkeypatch.setattr(doctor, name, lambda *a: [])
    monkeypatch.setattr(probes, "collect_startup_diagnostics", lambda *a, **k: {"checks": [probes._finding("docker_engine_unavailable", "fail", "Docker engine", "CLI found, engine unavailable", "Check Docker Desktop Troubleshoot.")]})
    assert doctor.main(startup_mode="docker") == 1
    output = capsys.readouterr().out
    assert "Startup (docker)" in output
    assert "CLI found, engine unavailable" in output
    assert "Check Docker Desktop Troubleshoot." in output
    assert "1 error(s)" in output


def test_bundle_contains_the_same_probes_and_actionable_summary(probes, monkeypatch, tmp_path):
    import support_bundle

    project = tmp_path / "checkout"
    project.mkdir()
    command_double(monkeypatch, probes, desktop=False)
    monkeypatch.setattr(probes, "check_port", lambda *a: probes._finding("port_in_use", "warn", "TCP bind", "PID 123; may be DeerFlow", "Inspect PID 123 before stopping anything."))
    monkeypatch.setattr(support_bundle, "collect_environment", lambda *a: {"platform": {}, "commands": []})
    monkeypatch.setattr(support_bundle, "collect_git_summary", lambda *a: {})
    monkeypatch.setattr(support_bundle, "collect_doctor_output", lambda *a: pytest.fail("startup probes do not require full doctor"))
    output = support_bundle.create_support_bundle(project_root=project, out_path=tmp_path / "bundle.zip", startup_mode="docker")
    with zipfile.ZipFile(output) as bundle:
        startup = json.loads(bundle.read("startup.json"))
        triage = json.loads(bundle.read("triage.json"))
        manifest = json.loads(bundle.read("manifest.json"))
        assert triage["startup"] == startup
        assert startup["checks"][0]["code"] == "docker_desktop_not_running"
        assert manifest["includes"]["startup"] is True
        assert "startup.json" in {entry["path"] for entry in triage["evidence_files"]}
        assert any("Inspect PID 123" in step for step in triage["reporter_next_steps"])
        assert "docker_desktop_not_running" in bundle.read("issue-summary.md").decode()
        text = "\n".join(bundle.read(name).decode() for name in bundle.namelist())
        assert "secret-not-for-report" not in text


def test_bundle_defaults_do_not_probe_docker_or_ports(probes, monkeypatch, tmp_path):
    import support_bundle

    monkeypatch.setattr(probes, "collect_startup_diagnostics", lambda *a, **k: pytest.fail("must opt in"))
    monkeypatch.setattr(support_bundle, "collect_environment", lambda *a: {"commands": []})
    monkeypatch.setattr(support_bundle, "collect_git_summary", lambda *a: {})
    output = support_bundle.create_support_bundle(project_root=tmp_path, out_path=tmp_path / "bundle.zip")
    with zipfile.ZipFile(output) as bundle:
        assert "startup.json" not in bundle.namelist()


def test_bundle_forwards_startup_mode_to_included_doctor(probes, monkeypatch, tmp_path):
    import support_bundle

    command_double(monkeypatch, probes, engine=0)
    monkeypatch.setattr(probes, "check_port", lambda *a: probes._finding("port_available", "ok", "TCP bind"))
    monkeypatch.setattr(support_bundle, "collect_environment", lambda *a: {"commands": [{"name": "nginx", "ok": False, "error": "nginx not found"}]})
    monkeypatch.setattr(support_bundle, "collect_git_summary", lambda *a: {})
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        return {"ok": True, "returncode": 0, "stdout": "fixture"}

    monkeypatch.setattr(support_bundle, "_run_command", command)
    (tmp_path / "config.yaml").write_text("models: [{name: example}]", encoding="utf-8")
    (tmp_path / "extensions_config.json").write_text("{}", encoding="utf-8")
    output = support_bundle.create_support_bundle(project_root=tmp_path, out_path=tmp_path / "bundle.zip", startup_mode="docker", startup_host="0.0.0.0", startup_port=3026, include_doctor=True)
    assert calls[0][-6:] == ["--startup-mode", "docker", "--startup-host", "0.0.0.0", "--startup-port", "3026"]
    with zipfile.ZipFile(output) as bundle:
        triage = json.loads(bundle.read("triage.json"))
        assert triage["signals"]["nginx_missing"] is False
        assert triage["status"] == "ok"
