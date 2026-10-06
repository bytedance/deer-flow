"""What the RAG role entries do with the resolver (spec 2026-09-23 default model D3/D6).

Task 1 pinned the resolver in isolation. This module pins the wiring around it: the
extraction role through both of its consumers (the ingestion path and the retrieval-time
``graph_search`` tool, R12), the eval judge through its three levels plus the CLI's explicit
argument, and the snapshot rule — one config object both resolves the name and builds the
model, so a check can never judge a different target than the one that gets constructed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig, RagConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.eval.factory import build_judge_llm
from deerflow.knowledge.graph.extractor import get_extract_llm

SANDBOX = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")
GRAPH_SEARCH_SOURCE = Path(__file__).resolve().parents[2] / "packages" / "harness" / "deerflow" / "tools" / "builtins" / "graph_search_tool.py"


def _model(name: str, *, vision: bool = False, api_key: str | None = "test-key", base_url: str | None = "https://ui.example/v1") -> ModelConfig:
    """``model=`` is distinct from ``name`` so a built client identifies its entry.

    ``api_key`` / ``base_url`` are parameters because the strict target rule (spec
    2026-09-23 D10.1) turns exactly those two into its verdicts for a UI entry.
    """
    extra: dict = {}
    if api_key is not None:
        extra["api_key"] = api_key
    if base_url is not None:
        extra["base_url"] = base_url
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use="langchain_openai:ChatOpenAI",
        model=f"{name}-wire",
        supports_thinking=False,
        supports_vision=vision,
        **extra,
    )


def _ui_config(*entries: ModelConfig, rag: RagConfig | None = None) -> AppConfig:
    """A config whose entries came from the API-writable file: the strict rule's scope."""
    config = AppConfig(models=list(entries), sandbox=SANDBOX, rag=rag or RagConfig())
    config._ui_model_names = {entry.name for entry in entries}
    return config


def _config(*names: str, default_model: str | None = None, extract_model: str | None = None, judge_model: str | None = None) -> AppConfig:
    return AppConfig(
        models=[_model(name) for name in names],
        sandbox=SANDBOX,
        rag=RagConfig(default_model=default_model, extract_model=extract_model, judge_model=judge_model),
    )


@pytest.fixture
def factory_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str | None, object]]:
    """Record what the RAG entries hand to the real factory, without building a client."""
    seen: list[tuple[str | None, object]] = []

    def _fake(name=None, *, app_config=None, **_kwargs):
        seen.append((name, app_config))
        return SimpleNamespace(name=name)

    monkeypatch.setattr("deerflow.models.factory.create_chat_model", _fake)
    return seen


# ── extraction role (ingestion + retrieval) ──────────────────────────────


@pytest.mark.parametrize(
    ("extract_model", "default_model", "expected"),
    [
        ("extract-entry", "B", "extract-entry"),  # the role declaration wins
        (None, "B", "B"),  # ... then the RAG default
        (None, None, "A"),  # ... then the first configured model
        ("ghost", "B", "ghost"),  # an explicit wrong name is NOT replaced
    ],
)
def test_extraction_priority(factory_spy, extract_model, default_model, expected):
    config = _config("A", "B", default_model=default_model, extract_model=extract_model)

    get_extract_llm(config)

    assert factory_spy[-1][0] == expected


def test_extraction_passes_the_same_config_snapshot_it_resolved_from(factory_spy):
    """One snapshot: the name is resolved against the object the factory then receives."""
    config = _config("A", "B", default_model="B")

    get_extract_llm(config)

    assert factory_spy[-1] == ("B", config)


def test_extraction_refuses_when_there_is_no_model_at_all(factory_spy):
    """A None target must not reach the factory, which would index ``models[0]``."""
    config = _config()

    with pytest.raises(RagConfigurationError):
        get_extract_llm(config)

    assert factory_spy == []


def test_an_explicit_wrong_name_still_reaches_the_factory(factory_spy):
    """The not-found error is the factory's to raise (and Task 9's to refuse earlier)."""
    config = _config("A", extract_model="ghost", default_model="B")

    get_extract_llm(config)

    assert factory_spy[-1][0] == "ghost"  # never silently replaced by B


def test_extraction_reads_the_process_config_when_none_is_given(monkeypatch: pytest.MonkeyPatch, factory_spy):
    """The parameter is optional on purpose: omitting it still means the process config,
    which is what keeps ``graph_search``'s unchanged call site working (R12)."""
    from deerflow.config import app_config as app_config_module

    config = _config("A", "B", default_model="B")
    monkeypatch.setattr(app_config_module, "get_app_config", lambda: config)

    get_extract_llm()

    assert factory_spy[-1] == ("B", config)


def test_resolution_is_per_call_and_never_repoints_a_built_model(factory_spy):
    """No cross-task cache: each build reads the configuration of its moment.

    A snapshot swap must not reach back into an already-built role — the extraction leg
    builds once per ingest, so a model that was handed out stays what it was.
    """
    first = get_extract_llm(_config("A", "B", default_model="A"))
    second = get_extract_llm(_config("A", "B", default_model="B"))

    assert (first.name, second.name) == ("A", "B")
    assert first is not second


# ── the retrieval-time consumer (R12) ────────────────────────────────────


async def test_graph_search_query_extraction_goes_through_get_extract_llm(monkeypatch: pytest.MonkeyPatch):
    """``graph_search`` builds its query-entity model from the *extract* role.

    Driven through the core implementation with the retrieval IO stubbed, so the only thing
    under test is which llm the query-entity step reaches for. It must come from
    ``get_extract_llm()`` — the tool takes no config of its own (R12).
    """
    from deerflow.tools.builtins import graph_search_tool

    calls: list[tuple] = []
    sentinel = RuntimeError("reached the query-entity extraction")

    def _recording_llm(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(ainvoke=_raise(sentinel))

    monkeypatch.setattr(graph_search_tool, "get_extract_llm", _recording_llm)
    monkeypatch.setattr(graph_search_tool, "resolve_kb_scope", lambda runtime: ("kb-1", "user-1"))

    async def _allowed(*_args, **_kwargs):
        return True

    monkeypatch.setattr(graph_search_tool, "can_access", _allowed)

    with pytest.raises(RuntimeError) as excinfo:
        await graph_search_tool._graph_search_impl("q", SimpleNamespace(), store=SimpleNamespace(_sf=object()))

    assert excinfo.value is sentinel
    # Called with no arguments at all: the tool does not inject a config snapshot, so the
    # role follows whatever the process config says (which is the point of the R12 pin).
    assert calls == [((), {})]


def test_graph_search_tool_source_is_untouched():
    """R12's other half: the second consumer works through the optional parameter alone."""
    source = GRAPH_SEARCH_SOURCE.read_text(encoding="utf-8")

    assert "llm = llm or get_extract_llm()" in source
    # If this file ever grows a RAG-default lookup of its own, this pins where it went.
    assert "default_model" not in source


# ── the runtime half of the target rule (spec 2026-09-23 D10.1) ───────────
# The build entrances refuse a *declared* target whose UI entry is unusable, and they refuse
# it before the factory is asked. A target the system would pick itself (a blank role falling
# back to the first model) is never refused here -- that is R2's tooth: the failure stays at
# request time, as it always was, instead of turning a save or an ingest into a hard error.


def test_extraction_refuses_a_declared_ui_target_with_no_key(factory_spy):
    from deerflow.knowledge.embedder import RagConfigurationError

    config = _ui_config(_model("A", api_key=None), rag=RagConfig(extract_model="A"))

    with pytest.raises(RagConfigurationError) as excinfo:
        get_extract_llm(config)

    assert "A" in str(excinfo.value) and "api_key" in str(excinfo.value)
    assert factory_spy == []  # refused before the factory was asked


def test_extraction_does_not_refuse_a_fallback_target(factory_spy):
    """A blank role resolves to the first model; that pick is not judged (D3/R2)."""
    config = _ui_config(_model("A", api_key=None), rag=RagConfig())

    get_extract_llm(config)

    assert factory_spy[-1][0] == "A"


def test_the_judge_refuses_a_declared_ui_target_with_no_key(factory_spy):
    from deerflow.knowledge.embedder import RagConfigurationError

    config = _ui_config(_model("A", api_key=None), rag=RagConfig(judge_model="A"))

    with pytest.raises(RagConfigurationError) as excinfo:
        build_judge_llm(None, config=config)

    assert "api_key" in str(excinfo.value)
    assert factory_spy == []


async def test_the_retrieval_time_consumer_refuses_the_same_target(monkeypatch: pytest.MonkeyPatch, factory_spy):
    """R12/R14: `graph_search` reaches the same entrance, so it inherits the refusal."""
    from deerflow.config import app_config as app_config_module
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.tools.builtins import graph_search_tool

    config = _ui_config(_model("A", api_key=None), rag=RagConfig(extract_model="A"))
    monkeypatch.setattr(app_config_module, "get_app_config", lambda: config)
    monkeypatch.setattr(graph_search_tool, "resolve_kb_scope", lambda runtime: ("kb-1", "user-1"))

    async def _allowed(*_args, **_kwargs):
        return True

    monkeypatch.setattr(graph_search_tool, "can_access", _allowed)

    with pytest.raises(RagConfigurationError):
        await graph_search_tool._graph_search_impl("q", SimpleNamespace(), store=SimpleNamespace(_sf=object()))

    assert factory_spy == []


# ── eval judge ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("explicit", "judge_model", "default_model", "expected"),
    [
        ("D", "C", "B", "D"),  # the CLI argument / explicit call wins outright
        (None, "C", "B", "C"),  # ... then the role declaration
        (None, None, "B", "B"),  # ... then the RAG default
        (None, None, None, "A"),  # ... then the first configured model
    ],
)
def test_judge_priority(factory_spy, explicit, judge_model, default_model, expected):
    config = _config("A", "B", default_model=default_model, judge_model=judge_model)

    build_judge_llm(explicit, config=config)

    assert factory_spy[-1][0] == expected


def test_judge_passes_the_same_config_snapshot_it_resolved_from(factory_spy):
    config = _config("A", "B", default_model="B")

    build_judge_llm(None, config=config)

    assert factory_spy[-1] == ("B", config)


def test_judge_refuses_when_there_is_no_model_at_all(factory_spy):
    config = _config()

    with pytest.raises(RagConfigurationError):
        build_judge_llm(None, config=config)

    assert factory_spy == []


def test_judge_does_not_let_the_rag_default_override_an_explicit_name(factory_spy):
    config = _config("A", "B", default_model="B")

    build_judge_llm("A", config=config)

    assert factory_spy[-1][0] == "A"


def test_the_dashscope_prefix_is_an_ordinary_entry_name(factory_spy):
    """Reversed pin (was: "the direct branch survives until Task 7"): the branch is gone.

    A ``dashscope:``-looking judge name is now resolved like any other name — here it happens
    to name a configured entry, and the factory receives exactly that name. The retired
    behaviour (an env key picking a hardcoded endpoint while bypassing ``models:``) is gone,
    which is what spec 2026-09-23 D9 asked for.
    """
    config = _config("dashscope:qwen3.8-max")

    build_judge_llm("dashscope:qwen3.8-max", config=config)

    assert factory_spy[-1][0] == "dashscope:qwen3.8-max"


# ── the two roles that had no field at all (spec 2026-09-26 D2/D4) ───────
# Both follow the same chain as extraction and the judge: role field -> RAG default ->
# first configured model. The manual wiki leg and the synthesis factory take no snapshot
# argument (their callers already own the injection seam through ``llm=`` / ``llm_factory=``),
# so these patch the process config — the same seam the extraction case above uses.


def _patch_process_config(monkeypatch: pytest.MonkeyPatch, config: AppConfig) -> None:
    from deerflow.config import app_config as app_config_module

    monkeypatch.setattr(app_config_module, "get_app_config", lambda: config)


def _role_config(point: str, *names: str, role: str | None = None, default_model: str | None = None) -> AppConfig:
    """A config whose role field is the one that point owns (``wiki_model`` / ``synthesis_model``)."""
    return AppConfig(
        models=[_model(name) for name in names],
        sandbox=SANDBOX,
        rag=RagConfig(**{"default_model": default_model, f"{point}_model": role}),
    )


def _resolve_manual_wiki() -> None:
    from deerflow.knowledge.wiki.generator import _default_llm

    _default_llm()


def _resolve_synthesis() -> None:
    from deerflow.knowledge.eval.synthesis import _default_llm_factory

    _default_llm_factory()


NEW_ROLE_POINTS = [
    pytest.param("wiki", _resolve_manual_wiki, id="wiki-manual"),
    pytest.param("synthesis", _resolve_synthesis, id="synthesis"),
]


@pytest.mark.parametrize("point, resolve", NEW_ROLE_POINTS)
@pytest.mark.parametrize(
    "role, default_model, expected",
    [
        ("C", "B", "C"),  # the role declaration wins
        (None, "B", "B"),  # blank role -> the RAG default (④甲: these points follow it now)
        (None, None, "A"),  # both blank -> the first configured model, as today
        ("", "B", "B"),  # a blank spelling is not a declaration
    ],
)
def test_the_new_roles_follow_the_same_chain(monkeypatch: pytest.MonkeyPatch, factory_spy, point: str, resolve, role, default_model, expected):
    config = _role_config(point, "A", "B", "C", role=role, default_model=default_model)
    _patch_process_config(monkeypatch, config)

    resolve()

    assert factory_spy[-1] == (expected, config)


@pytest.mark.parametrize("point, resolve", NEW_ROLE_POINTS)
def test_the_new_roles_do_not_replace_an_explicit_name(monkeypatch: pytest.MonkeyPatch, factory_spy, point: str, resolve):
    """A wrong name is the factory's error (D9), never silently swapped for the default."""
    config = _role_config(point, "A", "B", role="ghost", default_model="B")
    _patch_process_config(monkeypatch, config)

    resolve()

    assert factory_spy[-1][0] == "ghost"


@pytest.mark.parametrize("point, resolve", NEW_ROLE_POINTS)
def test_the_new_roles_fall_back_with_a_warning_when_the_default_is_stale(monkeypatch: pytest.MonkeyPatch, factory_spy, caplog, point: str, resolve):
    """Only the default itself may be superseded — and it names itself when it is."""
    config = _role_config(point, "A", "B", default_model="ghost")
    _patch_process_config(monkeypatch, config)

    with caplog.at_level("WARNING"):
        resolve()

    assert factory_spy[-1][0] == "A"
    assert "ghost" in caplog.text


@pytest.mark.parametrize("point, resolve", NEW_ROLE_POINTS)
def test_the_new_roles_refuse_when_there_is_no_model_at_all(monkeypatch: pytest.MonkeyPatch, factory_spy, point: str, resolve):
    config = _role_config(point)
    _patch_process_config(monkeypatch, config)

    with pytest.raises(RagConfigurationError):
        resolve()

    assert factory_spy == [], "a missing model must not reach the factory at all"


@pytest.mark.parametrize("point, resolve", NEW_ROLE_POINTS)
def test_the_new_roles_refuse_a_declared_ui_target_with_no_key(monkeypatch: pytest.MonkeyPatch, factory_spy, point: str, resolve):
    """Same runtime rule as extraction and the judge: a *declared* UI target must be usable."""
    config = _ui_config(_model("A", api_key=None), rag=RagConfig(**{f"{point}_model": "A"}))
    _patch_process_config(monkeypatch, config)

    with pytest.raises(RagConfigurationError):
        resolve()


@pytest.mark.parametrize("point, resolve", NEW_ROLE_POINTS)
def test_the_new_roles_do_not_refuse_a_fallback_target(monkeypatch: pytest.MonkeyPatch, factory_spy, point: str, resolve):
    """R2's teeth: a target the system picked itself is never judged — it degrades instead."""
    config = _ui_config(_model("A", api_key=None), rag=RagConfig())
    _patch_process_config(monkeypatch, config)

    resolve()

    assert factory_spy[-1][0] == "A"


def _raise(exc: BaseException):
    async def _ainvoke(*_args, **_kwargs):
        raise exc

    return _ainvoke
