"""Regression coverage for the standalone LangGraph graph entrypoint."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_langgraph_config_loads_the_repository_environment_file():
    """Standalone Studio should reuse the root environment used by DeerFlow."""
    import json

    config = json.loads((BACKEND_DIR / "langgraph.json").read_text(encoding="utf-8"))

    assert (BACKEND_DIR / config["env"]).resolve() == BACKEND_DIR.parent / ".env"


def test_langgraph_graph_factory_is_a_concrete_lazy_module_export():
    """Match LangGraph Server's direct ``module.__dict__`` entrypoint lookup."""
    script = textwrap.dedent(
        """
        import importlib
        import json
        import sys
        from pathlib import Path
        from types import ModuleType

        config = json.loads(Path("langgraph.json").read_text(encoding="utf-8"))
        module_name, variable_name = config["graphs"]["lead_agent"].split(":", 1)
        module = importlib.import_module(module_name)

        factory = module.__dict__.get(variable_name)
        assert callable(factory), (
            f"{module_name}:{variable_name} must be a concrete module export "
            "for LangGraph Server"
        )
        assert "deerflow.agents.lead_agent" not in sys.modules, (
            "publishing the graph factory must keep heavyweight agent imports lazy"
        )

        calls = []
        fake_lead_agent = ModuleType("deerflow.agents.lead_agent")
        fake_lead_agent.__path__ = []
        fake_lead_agent.make_lead_agent = lambda config: calls.append(("factory", config)) or "graph"
        fake_prompt = ModuleType("deerflow.agents.lead_agent.prompt")
        fake_prompt.prime_enabled_skills_cache = lambda: calls.append(("prime", None))
        sys.modules[fake_lead_agent.__name__] = fake_lead_agent
        sys.modules[fake_prompt.__name__] = fake_prompt

        config_arg = {"configurable": {"thread_id": "test-thread"}}
        assert factory(config_arg) == "graph"
        assert calls == [("prime", None), ("factory", config_arg)]
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
