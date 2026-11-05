"""Keep tutorial tool examples aligned with the configuration schema."""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter

from deerflow.config.tool_config import ToolConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_GUIDES = (
    Path("frontend/src/content/en/tutorials/use-tools-and-skills.mdx"),
    Path("frontend/src/content/zh/tutorials/use-tools-and-skills.mdx"),
)


@pytest.mark.parametrize("path", TOOL_GUIDES, ids=str)
def test_tutorial_tool_examples_are_valid(path: Path) -> None:
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)\n```", content, flags=re.DOTALL)
    examples = [yaml.safe_load(block) for block in blocks]
    tool_examples = [example["tools"] for example in examples if isinstance(example, dict) and "tools" in example]
    assert tool_examples, f"no tool configuration example in {path}"

    for tools in tool_examples:
        assert tools, f"empty tool configuration example in {path}"
        TypeAdapter(list[ToolConfig]).validate_python(tools)
