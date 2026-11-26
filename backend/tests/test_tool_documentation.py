"""Keep documented tool examples aligned with the configuration schema."""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter

from deerflow.config.tool_config import ToolConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_GUIDES = (
    "application/configuration.mdx",
    "harness/configuration.mdx",
    "harness/tools.mdx",
    "tutorials/create-your-first-harness.mdx",
    "tutorials/use-tools-and-skills.mdx",
)


@pytest.mark.parametrize("language", ("en", "zh"))
@pytest.mark.parametrize("guide", TOOL_GUIDES)
def test_tool_examples_are_valid(language: str, guide: str) -> None:
    path = REPO_ROOT / "frontend" / "src" / "content" / language / guide
    content = path.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)\n```", content, flags=re.DOTALL)
    examples = [yaml.safe_load(block) for block in blocks]
    tool_examples = [example["tools"] for example in examples if isinstance(example, dict) and "tools" in example]
    assert tool_examples, f"no tool configuration example in {path}"

    adapter = TypeAdapter(list[ToolConfig])
    for tools in tool_examples:
        assert tools, f"empty tool configuration example in {path}"
        adapter.validate_python(tools)
