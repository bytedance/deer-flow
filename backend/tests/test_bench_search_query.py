"""Offline tests of the search-query benchmark using synthetic backstories."""

import csv
import hashlib
import json
import sys
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from deerflow_extension_api import AgentAssemblyDescriptor
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime.assembly_evidence import project_assembly_evidence
from deerflow.runtime.serialization import serialize_channel_values_for_api
from scripts.benchmark.search_query import run
from scripts.benchmark.search_query.metrics import lexical


def test_parse_quoted_backstories_and_separate_references(tmp_path):
    path = tmp_path / "synthetic.csv"
    data = b'UQV100Id,Backstory,Top 5 SpelledNormQueries\r\ns1,"First line,\nsecond line", moon rock |lunar rock|  \r\n'
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert run.load_cases(path, digest) == [run.Case("s1", "First line,\nsecond line", ["moon rock", "lunar rock"])]
    with pytest.raises(ValueError, match="SHA-256"):
        run.load_cases(path, "0" * 64)


def test_lexical_metric():
    assert lexical.similarity("Rock, ROCK! 🌙", "moon rock") == 0.5
    assert lexical.similarity("lunar", "moon") == 0
    assert lexical.similarity("cost of tea", "TEA OF COST") == 1


class FixtureModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def assembly(thread_id, run_id):
    descriptor = AgentAssemblyDescriptor(
        namespace="deerflow",
        agent_name="synthetic",
        requested_model=None,
        effective_model="fixture-model",
        model_parameters={"temperature": 0, "seed": 42, "api_key": "private-provider-key"},
        thinking_enabled=False,
        reasoning_effort=None,
        base_prompt_hash="synthetic-prompt",
        tools=(),
        middlewares=(),
        deferred_tool_names=(),
        enabled_skills=(),
        effective_policies={},
    )
    return project_assembly_evidence(descriptor, thread_id=thread_id, run_id=run_id)


def test_first_search_and_per_backstory_report(tmp_path):
    executed = []

    @tool
    def web_search(query: str) -> str:
        """Synthetic search tool."""
        pytest.fail("The captured search batch must never execute")

    @tool
    def lookup(query: str) -> str:
        """Synthetic preparatory tool."""
        executed.append(query)
        return "Prepared"

    def call(name, query, identifier):
        return {"id": identifier, "name": name, "args": {"query": query}}

    search = AIMessage(content="", tool_calls=[call("web_search", "moon rock", "search")])
    preparation = AIMessage(content="", tool_calls=[call("lookup", "prepare", "lookup")])
    responses = [
        [AIMessage(content="", tool_calls=[call("lookup", "not executed", "a"), call("web_search", "moon rock", "b"), call("web_search", "ignored", "c")])],
        [preparation, search],
        [AIMessage(content="An answer.")],
        [AIMessage(content="", tool_calls=[call("lookup", "prepare", f"loop-{i}")]) for i in range(3)],
        [AIMessage(content="", tool_calls=[call("web_search", " ", "e"), call("web_search", "later", "f")])],
        [search],  # Gateway error before checkpoint.
        [preparation, AIMessage(content="An answer after preparation.")],
    ]
    cases = [run.Case(f"s{i}", f"Synthetic story {i}", ["moon rock", "stone"]) for i in range(len(responses))]
    threads = []
    graphs = {}
    records = {}
    invocations = {}

    def transport(request):
        if request.method == "GET":
            return httpx.Response(200, json=list(reversed(records[threads[-1]])))
        body = json.loads(request.content)
        if request.url.path == "/api/threads":
            assert body == {}
            threads.append(str(len(threads)))
            model = FixtureModel(responses=[message.model_copy(deep=True) for message in responses[len(threads) - 1]])
            graphs[threads[-1]] = create_agent(model, tools=[lookup, web_search], checkpointer=InMemorySaver(), interrupt_before=["tools"])
            records[threads[-1]] = []
            invocations[threads[-1]] = 0
            return httpx.Response(200, json={"thread_id": threads[-1]})
        assert request.url.path == f"/api/threads/{threads[-1]}/runs/wait"
        case = cases[len(threads) - 1]
        count = invocations[threads[-1]]
        assert body["input"] == ({"messages": [{"role": "user", "content": case.backstory}]} if count == 0 else None)
        assert body["context"] == {"model_name": "fixture-model", "subagent_enabled": False}
        assert body["interrupt_before"] == ["tools"]
        assert "interrupt_after" not in body
        invocations[threads[-1]] += 1
        if case == cases[5]:
            return httpx.Response(200, json={"status": "error", "__error__": {"message": "sensitive detail"}})
        state = graphs[threads[-1]].invoke(body["input"], {"configurable": {"thread_id": threads[-1]}})
        identifier = f"run-{threads[-1]}-{count}"
        proof = assembly(threads[-1], identifier)
        records[threads[-1]].append({"run_id": identifier, "metadata": {"deerflow_assembly_evidence": proof}, "kwargs": {"api_key": "private-provider-key"}})
        return httpx.Response(200, json=serialize_channel_values_for_api(state))

    class Encoder:
        def encode(self, strings, *, normalize_embeddings, show_progress_bar):
            assert normalize_embeddings
            assert strings == ["moon rock", "moon rock", "stone"]
            return np.array([[1, 0], [1, 0], [0, 1]])

    output = tmp_path / "run"
    with httpx.Client(base_url="http://benchmark.test/api/", transport=httpx.MockTransport(transport)) as client:
        summary = run.run(cases, client, "fixture-model", Encoder(), output, {"synthetic": True}, max_decisions=3)
    assert executed == ["prepare"] * 4
    assert len(threads) == len(cases)
    assert list(invocations.values()) == [1, 2, 1, 3, 1, 1, 2]
    with (output / "results.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    first = rows[0]
    assert first["backstory"] == cases[0].backstory
    assert json.loads(first["human_queries"]) == cases[0].references
    assert (first["case_id"], first["generated_query"], first["reference_count"]) == ("s0", "moon rock", "2")
    assert float(first["semantic_mean"]) == float(first["lexical_jaccard_mean"]) == 0.5
    assert "style_mean" not in first
    assert first["model"] == "fixture-model"
    assert [row["outcome"] for row in rows] == ["scored", "scored", "direct_answer", "decision_limit", "error", "error", "direct_answer"]
    assert all(row["semantic_mean"] == row["lexical_jaccard_mean"] == "" for row in rows[2:])
    assert set(summary) == {"backstories", "outcomes", "coverage", "provenance"}
    assert summary["coverage"] == 2 / 7
    assert summary["outcomes"] == {"scored": 2, "direct_answer": 2, "decision_limit": 1, "error": 2}
    assert json.loads((output / "summary.json").read_text()) == summary
    configuration = json.loads((output / "configuration.json").read_text())
    assert configuration["max_decisions"] == 3
    assert configuration["model_selection"] == "fixture-model"
    runtime = json.loads((output / "runtime-0001.json").read_text())
    assert runtime["thread_id"] == rows[1]["thread_id"]
    assert len(runtime["runs"]) == 2
    assert runtime["runs"][0]["assembly"]["parameters"] == {"temperature": 0, "seed": 42}
    assert len(runtime["runs"][0]["checkpoint_sha256"]) == 64
    assert "private-provider-key" not in "".join(path.read_text(encoding="utf-8") for path in output.iterdir())


@pytest.mark.parametrize("failure", ["missing", "wrong_run", "http"])
def test_runtime_evidence_failures_are_not_scored(failure):
    def transport(request):
        if request.method == "GET":
            if failure == "http":
                return httpx.Response(503)
            proof = assembly("thread", "other" if failure == "wrong_run" else "run")
            return httpx.Response(200, json=[{"run_id": "run", "metadata": {} if failure == "missing" else {"deerflow_assembly_evidence": proof}}])
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"thread_id": "thread"})
        return httpx.Response(200, json={"messages": [{"type": "ai", "content": "answer"}]})

    runtime = []
    with httpx.Client(base_url="http://benchmark.test/api/", transport=httpx.MockTransport(transport)) as client:
        row = run.evaluate(run.Case("synthetic", "story", ["query"]), client, None, None, runtime=runtime)
    assert row.outcome == "error"
    assert row.thread_id == "thread"
    assert row.error
    if failure != "http":
        assert runtime[0]["run_id"] == "run"
        assert "assembly" not in runtime[0]


def test_runtime_artifacts_are_content_addressed_without_copying_secrets(tmp_path):
    path = tmp_path / "config.yaml"
    content = b"api_key: private-provider-key\n"
    path.write_bytes(content)
    expected = {"config": {"sha256": hashlib.sha256(content).hexdigest()}}
    assert run.runtime_artifacts([f"config={path}"]) == expected
    with pytest.raises(ValueError, match="unique NAME=PATH"):
        run.runtime_artifacts([f"config={path}", f"config={path}"])
    with pytest.raises(ValueError, match="NAME=PATH"):
        run.runtime_artifacts([str(path)])


@pytest.mark.parametrize("change_snapshot", [False, True])
def test_cli_records_deployment_configuration_and_rejects_snapshot_drift(tmp_path, monkeypatch, change_snapshot):
    dataset = tmp_path / "synthetic.csv"
    dataset.write_bytes(b"UQV100Id,Backstory,Top 5 SpelledNormQueries\ns1,Synthetic need,query\n")
    artifact = tmp_path / "deployment.yaml"
    artifact.write_bytes(b"api_key: private-key\n")
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--dataset",
            str(dataset),
            "--dataset-sha256",
            hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "--gateway-revision",
            "deployed-revision",
            "--runtime-artifact",
            f"config={artifact}",
            "--output-dir",
            str(output),
            "--max-decisions",
            "2",
        ],
    )
    monkeypatch.setenv("DEERFLOW_BENCHMARK_URL", "http://benchmark.test/api")
    monkeypatch.setenv("DEERFLOW_BENCHMARK_TOKEN", "private-token")
    monkeypatch.setattr(run.semantic, "load_encoder", lambda: None)
    monkeypatch.setattr(run, "version", lambda package: "synthetic-version")
    monkeypatch.setattr(run.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="runner-revision\n"))

    def transport(request):
        assert request.headers["Authorization"] == "Bearer private-token"
        if request.method == "GET":
            return httpx.Response(200, json=[{"run_id": "run", "metadata": {"deerflow_assembly_evidence": assembly("thread", "run")}}])
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"thread_id": "thread"})
        if change_snapshot:
            artifact.write_bytes(b"changed snapshot\n")
        return httpx.Response(200, json={"messages": [{"type": "human", "content": "Synthetic need"}, {"type": "ai", "content": "An answer"}]})

    client_type = httpx.Client
    monkeypatch.setattr(run.httpx, "Client", lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(transport)))
    if change_snapshot:
        with pytest.raises(ValueError, match="snapshots changed"):
            run.main()
    else:
        assert run.main() == 0
    config = json.loads((output / "configuration.json").read_text())
    assert config["case_ids"] == ["s1"]
    assert config["max_decisions"] == 2
    assert config["provenance"]["gateway_revision"] == {"value": "deployed-revision", "source": "operator"}
    assert config["provenance"]["git_revision"] == "runner-revision"
    saved = "".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert "private-key" not in saved
    assert "private-token" not in saved
