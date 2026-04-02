from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from src.config.paths import Paths
from src.tools.builtins.setup_agent_tool import setup_agent


def test_setup_agent_persists_display_name_for_custom_agent(tmp_path: Path):
    runtime = SimpleNamespace(
        context={
            "agent_name": "agent-347704096c",
            "agent_display_name": "研究助手",
        },
        tool_call_id="tool-1",
    )

    with patch("src.tools.builtins.setup_agent_tool.get_paths", return_value=Paths(base_dir=tmp_path)):
        result = setup_agent.func(
            soul="你是研究助手",
            description="帮助用户做研究",
            runtime=runtime,
        )

    assert result.update["created_agent_name"] == "agent-347704096c"

    config = yaml.safe_load((tmp_path / "agents" / "agent-347704096c" / "config.yaml").read_text(encoding="utf-8"))
    assert config == {
        "name": "agent-347704096c",
        "display_name": "研究助手",
        "description": "帮助用户做研究",
    }
