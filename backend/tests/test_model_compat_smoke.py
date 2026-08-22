"""Offline tests for the explicit model/tool compatibility smoke runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SMOKE_DIR = Path(__file__).parent / "model_compat"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(SMOKE_DIR))

from run_smoke import (  # noqa: E402
    DeerFlowRuntime,
    isolate_client_config,
    make_runtime,
)
from smoke import (  # noqa: E402
    CaseName,
    ErrorCategory,
    ExitCode,
    SmokeResult,
    build_parser,
    evaluate_case,
    observe_events,
    redact_text,
    run_cli,
    select_models,
)


class Event:
    def __init__(self, event_type: str, data: dict):
        self.type = event_type
        self.data = data


class FakeRuntime:
    def __init__(self, models: tuple[str, ...] = ("alpha", "beta")):
        self.models = models
        self.calls: list[tuple[str, CaseName, str, str]] = []
        self.cleaned: list[tuple[str, str]] = []

    def list_models(self) -> list[str]:
        return list(self.models)

    def run_case(self, model: str, case, thread_id: str, user_id: str) -> SmokeResult:
        self.calls.append((model, case.name, thread_id, user_id))
        return SmokeResult(model=model, case=case.name, passed=True, detail="ok")

    def cleanup(self, thread_id: str, user_id: str) -> None:
        self.cleaned.append((thread_id, user_id))


def test_parser_requires_an_explicit_model_selection() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(["--model", "alpha", "--model", "beta"])

    assert args.models == ["alpha", "beta"]
    assert args.all_models is False


def test_select_models_rejects_unknown_and_preserves_configuration_order() -> None:
    assert select_models(["beta", "alpha", "beta"], False, ["alpha", "beta"]) == ["beta", "alpha"]
    assert select_models([], True, ["alpha", "beta"]) == ["alpha", "beta"]

    with pytest.raises(ValueError, match="unknown model"):
        select_models(["missing"], False, ["alpha"])


def test_observer_records_first_content_latency_tool_order_and_error_metadata() -> None:
    times = iter([10.0, 10.025, 10.040, 10.050, 10.060])
    events = [
        Event("messages-tuple", {"type": "ai", "content": "", "id": "a1"}),
        Event("messages-tuple", {"type": "ai", "content": "hello", "id": "a1"}),
        Event(
            "messages-tuple",
            {"type": "ai", "content": "", "id": "a2", "tool_calls": [{"id": "c1", "name": "read_file", "args": {"file_path": "/missing"}}]},
        ),
        Event("messages-tuple", {"type": "tool", "id": "t1", "tool_call_id": "c1", "name": "read_file", "content": "Error: not found"}),
        Event(
            "values",
            {
                "messages": [
                    {
                        "type": "tool",
                        "id": "t1",
                        "tool_call_id": "c1",
                        "name": "read_file",
                        "content": "Error: not found",
                        "additional_kwargs": {"deerflow_tool_meta": {"status": "error", "error_type": "not_found"}},
                    }
                ]
            },
        ),
    ]

    observation = observe_events(events, clock=lambda: next(times))

    assert observation.first_content_ms == pytest.approx(25.0)
    assert observation.text == "hello"
    assert [call.name for call in observation.tool_calls] == ["read_file"]
    assert observation.tool_results[0].status == "error"
    assert observation.tool_results[0].error_type == "not_found"


@pytest.mark.parametrize(
    ("case", "events", "artifact", "passed", "category"),
    [
        (CaseName.BASIC_CHAT, [Event("messages-tuple", {"type": "ai", "content": "DEERFLOW_SMOKE_CHAT_OK", "id": "a"})], None, True, None),
        (CaseName.STREAMING, [Event("messages-tuple", {"type": "ai", "content": "stream", "id": "a"}), Event("end", {})], None, True, None),
        (
            CaseName.WRITE_FILE,
            [
                Event("messages-tuple", {"type": "ai", "content": "", "id": "a", "tool_calls": [{"id": "c", "name": "write_file", "args": {}}]}),
                Event("messages-tuple", {"type": "tool", "id": "t", "tool_call_id": "c", "name": "write_file", "content": "ok"}),
            ],
            b"DEERFLOW_SMOKE_WRITE_OK",
            True,
            None,
        ),
        (
            CaseName.WRITE_READ,
            [
                Event("messages-tuple", {"type": "ai", "content": "", "id": "a1", "tool_calls": [{"id": "c1", "name": "write_file", "args": {}}]}),
                Event("messages-tuple", {"type": "tool", "id": "t1", "tool_call_id": "c1", "name": "write_file", "content": "ok"}),
                Event("messages-tuple", {"type": "ai", "content": "", "id": "a2", "tool_calls": [{"id": "c2", "name": "read_file", "args": {}}]}),
                Event("messages-tuple", {"type": "tool", "id": "t2", "tool_call_id": "c2", "name": "read_file", "content": "DEERFLOW_SMOKE_CHAIN_OK"}),
            ],
            b"DEERFLOW_SMOKE_CHAIN_OK",
            True,
            None,
        ),
        (
            CaseName.TOOL_ERROR_RECOVERY,
            [
                Event("messages-tuple", {"type": "ai", "content": "", "id": "a1", "tool_calls": [{"id": "c1", "name": "read_file", "args": {}}]}),
                Event(
                    "messages-tuple",
                    {
                        "type": "tool",
                        "id": "t1",
                        "tool_call_id": "c1",
                        "name": "read_file",
                        "content": "Error: not found",
                        "additional_kwargs": {"deerflow_tool_meta": {"status": "error", "error_type": "not_found"}},
                    },
                ),
                Event("messages-tuple", {"type": "ai", "content": "", "id": "a2", "tool_calls": [{"id": "c2", "name": "write_file", "args": {}}]}),
                Event("messages-tuple", {"type": "tool", "id": "t2", "tool_call_id": "c2", "name": "write_file", "content": "ok"}),
            ],
            b"DEERFLOW_SMOKE_RECOVERY_OK",
            True,
            None,
        ),
    ],
)
def test_case_contracts_are_evaluated_offline(case, events, artifact, passed, category) -> None:
    result = evaluate_case("alpha", case, observe_events(events), artifact=artifact)

    assert result.passed is passed
    assert result.category is category


def test_missing_tool_call_is_model_incompatibility_but_failed_tool_is_tool_failure() -> None:
    missing = evaluate_case("alpha", CaseName.WRITE_FILE, observe_events([]), artifact=None)
    failed = evaluate_case(
        "alpha",
        CaseName.WRITE_FILE,
        observe_events(
            [
                Event("messages-tuple", {"type": "ai", "content": "", "tool_calls": [{"id": "c", "name": "write_file", "args": {}}]}),
                Event(
                    "messages-tuple",
                    {
                        "type": "tool",
                        "name": "write_file",
                        "tool_call_id": "c",
                        "content": "Error: denied",
                        "additional_kwargs": {"deerflow_tool_meta": {"status": "error", "error_type": "permission"}},
                    },
                ),
            ]
        ),
        artifact=None,
    )

    assert missing.category is ErrorCategory.MODEL_INCOMPATIBLE
    assert failed.category is ErrorCategory.TOOL_FAILURE


def test_recovery_reports_parallel_read_and_write_as_a_distinct_incompatibility() -> None:
    observation = observe_events(
        [
            Event(
                "messages-tuple",
                {
                    "type": "ai",
                    "content": "",
                    "tool_calls": [
                        {"id": "read", "name": "read_file", "args": {}},
                        {"id": "write", "name": "write_file", "args": {}},
                    ],
                },
            ),
            Event(
                "messages-tuple",
                {
                    "type": "tool",
                    "name": "read_file",
                    "tool_call_id": "read",
                    "content": "Error: not found",
                    "additional_kwargs": {"deerflow_tool_meta": {"status": "error"}},
                },
            ),
            Event(
                "messages-tuple",
                {
                    "type": "tool",
                    "name": "write_file",
                    "tool_call_id": "write",
                    "content": "ok",
                },
            ),
        ]
    )

    result = evaluate_case(
        "alpha",
        CaseName.TOOL_ERROR_RECOVERY,
        observation,
        artifact=b"DEERFLOW_SMOKE_RECOVERY_OK",
    )

    assert result.category is ErrorCategory.MODEL_INCOMPATIBLE
    assert "parallel" in result.detail


def test_artifact_mismatch_reports_size_without_echoing_content() -> None:
    secret_content = b"wrong-model-output-that-must-not-be-printed"
    observation = observe_events(
        [
            Event(
                "messages-tuple",
                {
                    "type": "ai",
                    "content": "",
                    "tool_calls": [{"id": "write", "name": "write_file", "args": {}}],
                },
            ),
            Event(
                "messages-tuple",
                {
                    "type": "tool",
                    "name": "write_file",
                    "tool_call_id": "write",
                    "content": "ok",
                },
            ),
        ]
    )

    result = evaluate_case(
        "alpha",
        CaseName.WRITE_FILE,
        observation,
        artifact=secret_content,
    )

    assert f"{len(secret_content)} bytes" in result.detail
    assert secret_content.decode() not in result.detail


def test_provider_fallback_is_configuration_error() -> None:
    observation = observe_events(
        [
            Event(
                "messages-tuple",
                {
                    "type": "ai",
                    "content": "provider failed",
                    "id": "a",
                    "additional_kwargs": {"deerflow_error_fallback": True, "error_type": "AuthenticationError"},
                },
            )
        ]
    )

    result = evaluate_case("alpha", CaseName.BASIC_CHAT, observation)

    assert result.category is ErrorCategory.CONFIGURATION


def test_cli_is_fail_closed_in_ci_and_without_opt_in(capsys) -> None:
    runtime = FakeRuntime()

    no_opt_in = run_cli(["--model", "alpha"], environ={}, runtime_factory=lambda: runtime)
    in_ci = run_cli(
        ["--model", "alpha"],
        environ={"DEER_FLOW_RUN_LIVE_TESTS": "1", "CI": "true"},
        runtime_factory=lambda: runtime,
    )

    assert no_opt_in == ExitCode.CONFIGURATION
    assert in_ci == ExitCode.CONFIGURATION
    assert runtime.calls == []
    assert "real model" in capsys.readouterr().err.lower()


def test_cli_rejects_ci_variable_even_when_its_value_is_empty() -> None:
    runtime = FakeRuntime()

    exit_code = run_cli(
        ["--model", "alpha"],
        environ={"DEER_FLOW_RUN_LIVE_TESTS": "1", "CI": ""},
        runtime_factory=lambda: runtime,
    )

    assert exit_code == ExitCode.CONFIGURATION
    assert runtime.calls == []


def test_cli_runs_all_cases_with_unique_isolation_and_cleanup(tmp_path: Path) -> None:
    runtime = FakeRuntime(("alpha",))

    exit_code = run_cli(
        ["--model", "alpha", "--json-output", str(tmp_path / "result.json")],
        environ={"DEER_FLOW_RUN_LIVE_TESTS": "1"},
        runtime_factory=lambda: runtime,
        id_factory=iter([f"id-{index}" for index in range(20)]).__next__,
    )

    assert exit_code == ExitCode.OK
    assert [call[1] for call in runtime.calls] == list(CaseName)
    assert len({call[2] for call in runtime.calls}) == len(CaseName)
    assert len({call[3] for call in runtime.calls}) == len(CaseName)
    assert runtime.cleaned == [(call[2], call[3]) for call in runtime.calls]
    payload = json.loads((tmp_path / "result.json").read_text())
    assert payload["summary"] == {"passed": 5, "failed": 0, "total": 5}


def test_cli_exit_codes_distinguish_check_failures_and_runner_errors() -> None:
    class FailedRuntime(FakeRuntime):
        def run_case(self, model, case, thread_id, user_id):
            return SmokeResult(model=model, case=case.name, passed=False, category=ErrorCategory.MODEL_INCOMPATIBLE, detail="no tool call")

    class BrokenRuntime(FakeRuntime):
        def run_case(self, model, case, thread_id, user_id):
            raise RuntimeError("runner exploded")

    class ConfigurationRuntime(FakeRuntime):
        def run_case(self, model, case, thread_id, user_id):
            return SmokeResult(
                model=model,
                case=case.name,
                passed=False,
                category=ErrorCategory.CONFIGURATION,
                detail="provider authentication failed",
            )

    env = {"DEER_FLOW_RUN_LIVE_TESTS": "1"}

    assert run_cli(["--model", "alpha"], environ=env, runtime_factory=FailedRuntime) == ExitCode.CHECK_FAILED
    assert run_cli(["--model", "alpha"], environ=env, runtime_factory=ConfigurationRuntime) == ExitCode.CONFIGURATION
    assert run_cli(["--model", "alpha"], environ=env, runtime_factory=BrokenRuntime) == ExitCode.RUNNER_ERROR


def test_cleanup_failure_replaces_case_result_without_double_counting(tmp_path: Path) -> None:
    class CleanupRuntime(FakeRuntime):
        def cleanup(self, thread_id, user_id):
            raise RuntimeError("cleanup exploded")

    output = tmp_path / "result.json"

    exit_code = run_cli(
        ["--model", "alpha", "--case", "basic_chat", "--json-output", str(output)],
        environ={"DEER_FLOW_RUN_LIVE_TESTS": "1"},
        runtime_factory=CleanupRuntime,
    )

    payload = json.loads(output.read_text())
    assert exit_code == ExitCode.RUNNER_ERROR
    assert payload["summary"] == {"passed": 0, "failed": 1, "total": 1}
    assert len(payload["results"]) == 1
    assert payload["results"][0]["category"] == "runner_error"
    assert "original check: passed" in payload["results"][0]["detail"]


def test_json_report_redacts_result_strings_at_serialization_boundary(tmp_path: Path) -> None:
    class SecretRuntime(FakeRuntime):
        def run_case(self, model, case, thread_id, user_id):
            return SmokeResult(
                model="model?api_key=sk-1234567890",
                case=case.name,
                passed=False,
                category=ErrorCategory.RUNNER,
                detail="Authorization: Bearer abc.def",
            )

    output = tmp_path / "result.json"

    run_cli(
        ["--model", "alpha", "--case", "basic_chat", "--json-output", str(output)],
        environ={"DEER_FLOW_RUN_LIVE_TESTS": "1"},
        runtime_factory=SecretRuntime,
    )

    report = output.read_text()
    assert "sk-1234567890" not in report
    assert "abc.def" not in report
    assert report.count("<redacted>") >= 2


def test_output_redaction_masks_common_credentials(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_PROVIDER_API_KEY", "provider-secret-value-123")
    text = "Authorization: Bearer abc.def api_key=sk-1234567890 https://user:pass@example.test?q=1&token=secret provider-secret-value-123"

    redacted = redact_text(text)

    assert "abc.def" not in redacted
    assert "sk-1234567890" not in redacted
    assert "user:pass" not in redacted
    assert "token=secret" not in redacted
    assert "provider-secret-value-123" not in redacted
    assert "<redacted>" in redacted


def test_deerflow_adapter_uses_isolated_user_and_verifies_artifact() -> None:
    events = [
        Event("messages-tuple", {"type": "ai", "content": "", "tool_calls": [{"id": "c", "name": "write_file", "args": {}}]}),
        Event("messages-tuple", {"type": "tool", "name": "write_file", "tool_call_id": "c", "content": "ok"}),
    ]
    created_for: list[str | None] = []
    context_events: list[tuple[str, object]] = []

    class Client:
        def list_models(self):
            return {"models": [{"name": "alpha"}]}

        def stream(self, prompt, *, thread_id, user_id):
            assert "DEERFLOW_SMOKE_WRITE_OK" in prompt
            assert thread_id == "thread-1"
            assert user_id == "user-1"
            return iter(events)

        def get_artifact(self, thread_id, path):
            assert path.endswith("model_compat_write.txt")
            return b"DEERFLOW_SMOKE_WRITE_OK", "text/plain"

    runtime = DeerFlowRuntime(
        client_factory=lambda model: created_for.append(model) or Client(),
        set_user=lambda user: context_events.append(("set", user.id)) or "token",
        reset_user=lambda token: context_events.append(("reset", token)),
        delete_thread=lambda thread_id, user_id: context_events.append(("delete", (thread_id, user_id))),
    )
    case = next(spec for spec in runtime.cases if spec.name is CaseName.WRITE_FILE)

    result = runtime.run_case("alpha", case, "thread-1", "user-1")
    runtime.cleanup("thread-1", "user-1")

    assert result.passed is True
    assert runtime.list_models() == ["alpha"]
    assert created_for == ["alpha", None]
    assert context_events == [("set", "user-1"), ("reset", "token"), ("delete", ("thread-1", "user-1"))]


def test_client_config_is_copied_and_disables_auxiliary_model_and_memory_paths() -> None:
    class Node:
        def __init__(self, **values):
            self.__dict__.update(values)

        def model_copy(self, *, deep=False, update=None):
            import copy

            copied = copy.deepcopy(self) if deep else copy.copy(self)
            copied.__dict__.update(update or {})
            return copied

    original = Node(
        title=Node(enabled=True, model_name="title-model"),
        summarization=Node(enabled=True, model_name="summary-model"),
        memory=Node(enabled=True, injection_enabled=True),
    )
    client = Node(_app_config=original)

    isolate_client_config(client)

    assert client._app_config is not original
    assert client._app_config.title.enabled is False
    assert client._app_config.title.model_name is None
    assert client._app_config.summarization.enabled is False
    assert client._app_config.summarization.model_name is None
    assert client._app_config.memory.enabled is False
    assert client._app_config.memory.injection_enabled is False
    assert original.title.enabled is True
    assert original.summarization.enabled is True
    assert original.memory.enabled is True


@pytest.mark.parametrize(
    ("exception_type", "category"),
    [
        (type("AuthenticationError", (Exception,), {}), ErrorCategory.CONFIGURATION),
        (type("SandboxUnavailable", (Exception,), {}), ErrorCategory.TOOL_FAILURE),
        (RuntimeError, ErrorCategory.RUNNER),
    ],
)
def test_adapter_classifies_invocation_exceptions_by_boundary(exception_type, category) -> None:
    class Client:
        def stream(self, *args, **kwargs):
            raise exception_type("failed")

    runtime = DeerFlowRuntime(
        client_factory=lambda model: Client(),
        set_user=lambda user: "token",
        reset_user=lambda token: None,
        delete_thread=lambda thread_id, user_id: None,
    )
    case = next(spec for spec in runtime.cases if spec.name is CaseName.BASIC_CHAT)

    result = runtime.run_case("alpha", case, "thread-1", "user-1")

    assert result.category is category


def test_make_runtime_fails_before_importing_when_config_is_missing(tmp_path: Path) -> None:
    imported = False

    def importer():
        nonlocal imported
        imported = True
        raise AssertionError("must not import")

    with pytest.raises(Exception, match="config.yaml"):
        make_runtime(tmp_path / "config.yaml", importer=importer)

    assert imported is False


def test_make_runtime_applies_auxiliary_model_isolation_to_every_client(tmp_path: Path) -> None:
    import copy

    class Node:
        def __init__(self, **values):
            self.__dict__.update(values)

        def model_copy(self, *, deep=False, update=None):
            copied = copy.deepcopy(self) if deep else copy.copy(self)
            copied.__dict__.update(update or {})
            return copied

    original = Node(
        title=Node(enabled=True, model_name="title-model"),
        summarization=Node(enabled=True, model_name="summary-model"),
        memory=Node(enabled=True, injection_enabled=True),
    )
    clients = []

    class Client:
        def __init__(self, **kwargs):
            self._app_config = original
            clients.append(self)

        def list_models(self):
            return {"models": [{"name": "alpha"}]}

    class Paths:
        def delete_thread_dir(self, thread_id, *, user_id):
            pass

    config_path = tmp_path / "config.yaml"
    config_path.write_text("models: []\n")
    runtime = make_runtime(
        config_path,
        importer=lambda: (Client, object, lambda: Paths(), lambda user: "token", lambda token: None),
    )

    assert runtime.list_models() == ["alpha"]
    assert clients[0]._app_config.title.enabled is False
    assert clients[0]._app_config.summarization.enabled is False
    assert clients[0]._app_config.memory.enabled is False
    assert clients[0]._app_config.memory.injection_enabled is False
    assert original.title.enabled is True
    assert original.summarization.enabled is True
    assert original.memory.enabled is True


@pytest.mark.parametrize(
    ("extra_env", "expected"),
    [({}, "set DEER_FLOW_RUN_LIVE_TESTS=1"), ({"DEER_FLOW_RUN_LIVE_TESTS": "1", "CI": "true"}, "disabled in CI")],
)
def test_script_refuses_live_execution_before_loading_deerflow(extra_env, expected) -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        **extra_env,
    }

    result = subprocess.run(
        [sys.executable, str(SMOKE_DIR / "run_smoke.py"), "--model", "alpha"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == ExitCode.CONFIGURATION
    assert expected in result.stderr
    assert "config.yaml not found" not in result.stderr


def test_default_pytest_collection_does_not_collect_manual_runner() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(SMOKE_DIR),
        ],
        cwd=BACKEND_ROOT,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED
    assert "no tests collected" in output
    assert "run_smoke" not in output


def test_make_target_is_explicit_and_default_target_stays_offline() -> None:
    default = subprocess.run(["make", "-n", "test"], cwd=BACKEND_ROOT, capture_output=True, text=True, check=False)
    smoke = subprocess.run(
        ["make", "-n", "model-smoke", "ARGS=--model alpha"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert default.returncode == 0
    assert smoke.returncode == 0
    assert "DEER_FLOW_RUN_LIVE_TESTS" not in default.stdout
    assert 'pytest -m "not live"' in default.stdout
    assert "DEER_FLOW_RUN_LIVE_TESTS=1" in smoke.stdout
    assert "tests/model_compat/run_smoke.py --model alpha" in smoke.stdout
    assert "pytest" not in smoke.stdout


def test_smoke_documentation_warns_about_costs_and_default_exclusion() -> None:
    dedicated = (SMOKE_DIR / "README.md").read_text(encoding="utf-8")
    backend_readme = (BACKEND_ROOT / "README.md").read_text(encoding="utf-8")
    backend_agents = (BACKEND_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    for docs in (dedicated, backend_readme, backend_agents, contributing):
        assert "make model-smoke" in docs
        assert "DEER_FLOW_RUN_LIVE_TESTS" in docs
        assert "API" in docs
    assert "exit code" in dedicated.lower()
    assert "CI" in dedicated
    assert "--model" in dedicated
    assert "--json-output" in dedicated
