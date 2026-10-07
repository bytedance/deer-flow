"""What the kept RAG role entry does with the resolver (spec 2026-09-23 default model D3/D6).

Trimmed to the kept chain in the first-phase slice: the extraction role
(``deerflow_knowledge.graph.extractor``), the eval judge (``deerflow_knowledge.eval.factory``),
the manual wiki role (``deerflow_knowledge.wiki.generator``) and the synthesis role
(``deerflow_knowledge.eval.synthesis``) were removed with their subsystems, and so were the
retrieval-time ``graph_search`` consumer and the snapshot-rule tests that rode them. What
remains of this file's subject is the vlm role — the caption legs' target — and the shared
chain behind every role: the role declaration, else the RAG default, else the first
configured model, with the refusal rule for a *declared* UI target and the never-replaced
explicit name.

Task 1 pinned the resolver in isolation (``test_model_target.py``); this module pins the
wiring around it: one config object both resolves the name and supplies the triple, so a
check can never judge a different target than the one that gets constructed.
"""

from __future__ import annotations

import pytest
from deerflow_knowledge.embedder import RagConfigurationError
from deerflow_knowledge.vlm_target import resolve_vlm_target

from deerflow.config.app_config import AppConfig, RagConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

SANDBOX = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")


def _model(name: str, *, vision: bool = False, api_key: str | None = "test-key", base_url: str | None = "https://ui.example/v1") -> ModelConfig:
    """``model=`` is distinct from ``name`` so a built target identifies its entry.

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


def _config(*names: str, default_model: str | None = None, vlm_model: str | None = None) -> AppConfig:
    return AppConfig(
        models=[_model(name) for name in names],
        sandbox=SANDBOX,
        rag=RagConfig(default_model=default_model, vlm_model=vlm_model),
    )


# ── the vlm role's chain (spec 2026-09-23 D3/D10.1) ───────────────────────


@pytest.mark.parametrize(
    ("vlm_model", "default_model", "expected"),
    [
        ("C", "B", "C"),  # the role declaration wins
        (None, "B", "B"),  # ... then the RAG default
        (None, None, "A"),  # ... then the first configured model
        ("", "B", "B"),  # a blank spelling is not a declaration
    ],
)
def test_the_vlm_role_follows_the_same_chain(vlm_model, default_model, expected):
    """One snapshot: the name is resolved against the object the target is then built from."""
    config = _config("A", "B", "C", default_model=default_model, vlm_model=vlm_model)

    target = resolve_vlm_target(config)

    assert target.model == f"{expected}-wire"


def test_the_vlm_role_does_not_replace_an_explicit_name():
    """A wrong name is the entrance's not-found error (D9), never silently swapped for the default."""
    config = _config("A", "B", vlm_model="ghost", default_model="B")

    with pytest.raises(RagConfigurationError) as excinfo:
        resolve_vlm_target(config)

    assert "ghost" in str(excinfo.value)


def test_the_vlm_role_falls_back_with_a_warning_when_the_default_is_stale(caplog):
    """Only the default itself may be superseded — and it names itself when it is."""
    config = _config("A", "B", default_model="ghost")

    with caplog.at_level("WARNING"):
        target = resolve_vlm_target(config)

    assert target.model == "A-wire"
    assert "ghost" in caplog.text


def test_the_vlm_role_refuses_when_there_is_no_model_at_all():
    config = _config()

    with pytest.raises(RagConfigurationError):
        resolve_vlm_target(config)


def test_the_vlm_role_refuses_a_declared_ui_target_with_no_key():
    """Same runtime rule as every other role: a *declared* UI target must be usable."""
    config = _ui_config(_model("A", api_key=None), rag=RagConfig(vlm_model="A"))

    with pytest.raises(RagConfigurationError) as excinfo:
        resolve_vlm_target(config)

    assert "api_key" in str(excinfo.value)


def test_the_vlm_role_does_not_refuse_a_fallback_target():
    """R2's teeth: a target the system picked itself is never judged — it degrades instead."""
    config = _ui_config(_model("A", api_key=None), rag=RagConfig())

    target = resolve_vlm_target(config)

    assert target.model == "A-wire"
    assert target.api_key is None
