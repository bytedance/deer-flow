from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.policy import PolicyResult
from scripts.benchmark.deermem_eviction.pool import PreparedCase
from scripts.benchmark.deermem_eviction.provider import ProviderCallError, ProviderConfigurationError, ProviderSettings, build_client, request_answer, resolve_provider_settings
from scripts.benchmark.deermem_eviction.qa import build_answer_task, render_answer_messages
from scripts.benchmark.deermem_eviction.runner import ensure_run_config_identity, response_path, run_answer_calls, verify_run_identity

EVAL_ROOT = Path(__file__).parents[1] / "scripts" / "benchmark" / "deermem_eviction"


def _load_config():
    return load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")


def _template() -> str:
    return (EVAL_ROOT / "prompts" / "answer-v1.txt").read_text(encoding="utf-8")


def _case(case_id: str = "case-1", question_date: str | None = "2023/05/20 (Sat) 02:21") -> PreparedCase:
    config = _load_config()
    facts = [
        {"id": "fact-b", "content": "The cat sleeps in the study.", "category": "context", "confidence": 0.7, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"},
        {"id": "fact-a", "content": "The user moved to Lyon.", "category": "context", "confidence": 0.9, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"},
        {"id": "fact-c", "content": "The user has two bikes.", "category": "context", "confidence": 0.8, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"},
    ]
    return PreparedCase(
        case_id=case_id,
        source="synthetic",
        scenario="correction_reserve",
        question_type="synthetic-correction",
        question="Where does the user live?",
        answer="Lyon",
        question_date=question_date,
        evaluation_time=config.evaluation_time,
        facts=facts,
        usage={},
        support_fact_ids=("fact-a",),
    )


def _policy_result(case: PreparedCase, kept: tuple[str, ...], policy: str = "hybrid-v1") -> PolicyResult:
    return PolicyResult(
        case_id=case.case_id,
        source=case.source,
        scenario=case.scenario,
        question_type=case.question_type,
        policy=policy,  # type: ignore[arg-type]
        capacity=7,
        support_fact_ids=case.support_fact_ids,
        kept_fact_ids=kept,
        evicted=(),
        scores={},
        support_all_retained=True,
        support_recall=1.0,
        reserved_correction_slots=0,
    )


def test_rendering_pins_fact_order_date_line_and_block_format() -> None:
    messages = render_answer_messages(
        _template(),
        question="Where does the user live?",
        question_date="2023/05/20 (Sat) 02:21",
        retained_facts=[("fact-b", "The cat sleeps in the study."), ("fact-a", "The user moved to Lyon.")],
    )
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Answer using only the stored memory below. If the answer is not supported, output exactly INSUFFICIENT. For a YES/NO question, output only YES or NO. Otherwise give only the shortest direct answer."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == ("CURRENT DATE: 2023/05/20 (Sat) 02:21\nSTORED MEMORY:\n[fact-a]\nThe user moved to Lyon.\n\n[fact-b]\nThe cat sleeps in the study.\n\nQUESTION: Where does the user live?")


def test_rendering_omits_the_date_line_when_absent() -> None:
    messages = render_answer_messages(_template(), question="Q?", question_date=None, retained_facts=[("fact-a", "content")])
    assert messages[1]["content"].startswith("STORED MEMORY:\n")
    assert "CURRENT DATE" not in messages[1]["content"]


def test_rendering_rejects_empty_or_duplicate_facts() -> None:
    with pytest.raises(ValueError):
        render_answer_messages(_template(), question="Q?", question_date=None, retained_facts=[])
    with pytest.raises(ValueError):
        render_answer_messages(_template(), question="Q?", question_date=None, retained_facts=[("fact-a", "x"), ("fact-a", "y")])


def test_build_answer_task_renders_only_kept_facts() -> None:
    case = _case()
    task = build_answer_task(case, _policy_result(case, kept=("fact-a", "fact-c")), _template())
    assert task.row_id == "case-1__hybrid-v1"
    assert task.kept_fact_ids == ("fact-a", "fact-c")
    user = task.messages[1]["content"]
    assert "[fact-a]" in user and "[fact-c]" in user
    assert "fact-b" not in user
    with pytest.raises(ValueError):
        build_answer_task(_case(case_id="other"), _policy_result(case, kept=("fact-a",)), _template())


def test_provider_settings_errors_name_the_missing_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _load_config()
    monkeypatch.delenv(config.qa.api_key_env, raising=False)
    monkeypatch.delenv(config.qa.base_url_env, raising=False)
    with pytest.raises(ProviderConfigurationError) as excinfo:
        resolve_provider_settings(config.qa)
    assert config.qa.api_key_env in str(excinfo.value)
    assert config.qa.base_url_env in str(excinfo.value)
    monkeypatch.setenv(config.qa.api_key_env, "secret-key")
    monkeypatch.setenv(config.qa.base_url_env, "https://example.invalid/v1")
    settings = resolve_provider_settings(config.qa)
    assert settings.api_key == "secret-key"
    assert settings.base_url == "https://example.invalid/v1"


def _mock_client(handler, qa) -> httpx.Client:
    return httpx.Client(base_url="https://example.invalid/v1", headers={"Authorization": "Bearer secret-key"}, transport=httpx.MockTransport(handler), timeout=qa.timeout_seconds)


def _success_body(prediction: str = "Lyon") -> dict:
    return {"model": "deepseek-v4-flash", "choices": [{"message": {"role": "assistant", "content": prediction}}], "usage": {"prompt_tokens": 100, "completion_tokens": 3, "detail": "ignored"}}


def test_request_answer_parses_prediction_and_non_secret_metadata() -> None:
    qa = _load_config().qa
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_success_body())

    answer = request_answer(_mock_client(handler, qa), qa, ({"role": "system", "content": "s"}, {"role": "user", "content": "u"}), backoff_seconds=0)
    assert answer.prediction == "Lyon"
    assert answer.attempts == 1
    assert answer.usage == {"prompt_tokens": 100, "completion_tokens": 3}
    assert answer.response_model == "deepseek-v4-flash"
    payload = json.loads(seen[0].content)
    assert payload["model"] == qa.model
    assert payload["temperature"] == qa.temperature
    assert payload["max_tokens"] == qa.max_tokens
    assert payload["stream"] is qa.stream
    assert seen[0].url.path.endswith("/chat/completions")


def test_request_answer_retries_retryable_failures_and_gives_up() -> None:
    qa = _load_config().qa
    statuses = [429, 500]

    def flaky(request: httpx.Request) -> httpx.Response:
        if statuses:
            return httpx.Response(statuses.pop(0), json={})
        return httpx.Response(200, json=_success_body())

    answer = request_answer(_mock_client(flaky, qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)
    assert answer.attempts == 3

    def always_broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ProviderCallError, match="failed after 3 attempts"):
        request_answer(_mock_client(always_broken, qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)


def test_request_answer_rejects_non_retryable_and_malformed_responses() -> None:
    qa = _load_config().qa
    with pytest.raises(ProviderCallError, match="non-retryable status 401"):
        request_answer(_mock_client(lambda request: httpx.Response(401, json={}), qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)
    with pytest.raises(ProviderCallError, match="choices"):
        request_answer(_mock_client(lambda request: httpx.Response(200, json={"choices": []}), qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)


def test_build_client_uses_configured_timeout_and_bearer_header() -> None:
    config = _load_config()
    with build_client(ProviderSettings(base_url="https://example.invalid/v1", api_key="secret-key"), config.qa) as client:
        assert client.headers["Authorization"] == "Bearer secret-key"
        assert client.timeout.read == config.qa.timeout_seconds


def _tasks(count: int = 2) -> list:
    template = _template()
    tasks = []
    for index in range(count):
        case = _case(case_id=f"case-{index}")
        tasks.append(build_answer_task(case, _policy_result(case, kept=("fact-a", "fact-b")), template))
    return tasks


def test_run_answer_calls_persists_rows_and_resumes_without_new_calls(tmp_path: Path) -> None:
    config = _load_config()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    tasks = _tasks()
    with _mock_client(handler, config.qa) as client:
        first = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (first.reused, first.called, first.failed) == (0, 2, ())
        assert len(calls) == 2
        row = json.loads(response_path(tmp_path, tasks[0].row_id).read_text(encoding="utf-8"))
        assert set(row) == {"schema_version", "row_id", "case_id", "source", "scenario", "policy", "capacity", "kept_fact_ids", "prediction", "attempts", "request_fingerprint", "response_model", "usage", "created_at"}
        assert row["prediction"] == "Lyon"
        serialized = json.dumps(row)
        assert "Where does the user live" not in serialized
        assert "The user moved to Lyon." not in serialized
        assert "Bearer" not in serialized

        second = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (second.reused, second.called, second.failed) == (2, 0, ())
        assert len(calls) == 2

        response_path(tmp_path, tasks[0].row_id).write_text("{not json", encoding="utf-8")
        third = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (third.reused, third.called, third.failed) == (1, 1, ())
        assert len(calls) == 3


def test_run_answer_calls_refuses_to_reuse_a_row_bound_to_another_case(tmp_path: Path) -> None:
    config = _load_config()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    tasks = _tasks()
    with _mock_client(handler, config.qa) as client:
        run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert len(calls) == 2
        path = response_path(tmp_path, tasks[0].row_id)
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, value in (("case_id", tasks[1].case_id), ("source", f"not-{tasks[0].source}"), ("scenario", f"not-{tasks[0].scenario}")):
            path.write_text(json.dumps(dict(original, **{field: value})), encoding="utf-8")
            report = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
            assert (report.reused, report.called, report.failed) == (1, 1, ())
        assert len(calls) == 5


def test_run_answer_calls_reports_failures_without_writing_rows(tmp_path: Path) -> None:
    config = _load_config()

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    tasks = _tasks(count=1)
    with _mock_client(broken, config.qa) as client:
        report = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
    assert report.called == 0
    assert len(report.failed) == 1
    assert tasks[0].row_id in report.failed[0]
    assert not response_path(tmp_path, tasks[0].row_id).exists()


def test_run_directory_is_bound_to_the_full_protocol_identity(tmp_path: Path) -> None:
    config = _load_config()
    paths = {
        "config_path": EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml",
        "official_manifest_path": EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json",
        "synthetic_manifest_path": EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json",
        "prompt_path": EVAL_ROOT / "prompts" / "answer-v1.txt",
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")
    backend_root = Path(__file__).parents[1]
    output_dir = tmp_path / "run"

    ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=backend_root, **paths)
    marker = json.loads((output_dir / "qa_run.json").read_text(encoding="utf-8"))
    assert marker["qa"]["model"] == config.qa.model
    assert set(marker["artifacts"]) == {"config_sha256", "official_manifest_sha256", "synthetic_manifest_sha256", "answer_prompt_sha256", "dataset_sha256"}
    assert "secret" not in json.dumps(marker).lower()
    ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=backend_root, **paths)

    for changed_key, marker_field in (("config_path", "config_sha256"), ("synthetic_manifest_path", "synthetic_manifest_sha256"), ("prompt_path", "answer_prompt_sha256")):
        changed_paths = dict(paths)
        changed_file = tmp_path / f"changed-{changed_key}"
        changed_file.write_text(paths[changed_key].read_text(encoding="utf-8") + "\n", encoding="utf-8")
        changed_paths[changed_key] = changed_file
        with pytest.raises(ValueError, match=f"different protocol artifacts.*{marker_field}"):
            ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=backend_root, **changed_paths)


def test_verify_run_identity_is_read_only_and_names_the_changed_artifact(tmp_path: Path) -> None:
    config = _load_config()
    paths = {
        "config_path": EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml",
        "official_manifest_path": EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json",
        "synthetic_manifest_path": EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json",
        "prompt_path": EVAL_ROOT / "prompts" / "answer-v1.txt",
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")
    output_dir = tmp_path / "run"

    with pytest.raises(ValueError, match="missing"):
        verify_run_identity(output_dir, dataset_path=dataset_path, **paths)

    ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=Path(__file__).parents[1], **paths)
    verify_run_identity(output_dir, dataset_path=dataset_path, **paths)

    changed_prompt = tmp_path / "changed-prompt.txt"
    changed_prompt.write_text(paths["prompt_path"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to grade.*|answer_prompt_sha256"):
        verify_run_identity(output_dir, dataset_path=dataset_path, **{**paths, "prompt_path": changed_prompt})


def test_resume_revalidates_stored_rows_against_the_current_task(tmp_path: Path) -> None:
    config = _load_config()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    tasks = _tasks(count=1)
    with _mock_client(handler, config.qa) as client:
        run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert len(calls) == 1

        unchanged = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (unchanged.reused, unchanged.called) == (1, 0)
        assert len(calls) == 1

        changed_message = replace(tasks[0], messages=(tasks[0].messages[0], {"role": "user", "content": "a different question"}))
        after_message_change = run_answer_calls([changed_message], config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (after_message_change.reused, after_message_change.called) == (0, 1)
        assert len(calls) == 2

        changed_kept = replace(changed_message, kept_fact_ids=("fact-a",))
        after_kept_change = run_answer_calls([changed_kept], config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (after_kept_change.reused, after_kept_change.called) == (0, 1)
        assert len(calls) == 3


def test_cli_run_qa_fails_fast_without_provider_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scripts.benchmark.deermem_eviction.cli import main

    config = _load_config()
    monkeypatch.delenv(config.qa.api_key_env, raising=False)
    monkeypatch.delenv(config.qa.base_url_env, raising=False)
    with pytest.raises(ProviderConfigurationError) as excinfo:
        main(["run-qa", "--dataset", str(tmp_path / "missing.json"), "--output-dir", str(tmp_path / "out")])
    assert config.qa.api_key_env in str(excinfo.value)
