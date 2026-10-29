"""Keep the user-facing memory guides aligned with DeerMem's real storage layout.

The guides once described the pre-abstraction layout (a shared
``{base_dir}/memory.json`` plus one ``agents/{agent_name}/memory.json`` per
agent). DeerMem scopes the memory manifest per user and keeps agent state in a
``facts`` directory beside it, and the host loader moved every DeerMem-private
knob under ``memory.backend_config``. Both guides are prose, so nothing in CI
noticed; this test derives the documented shape from the same functions the
runtime uses.
"""

import re
from pathlib import Path

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.paths import agent_facts_directory, memory_file_path
from deerflow.config.memory_config import MemoryConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_GUIDES = (
    Path("frontend/src/content/en/harness/memory.mdx"),
    Path("frontend/src/content/zh/harness/memory.mdx"),
)

# A root that never collides with the placeholders the guides spell out.
PROBE_ROOT = "/deer-flow-test-root"
PROBE_USER_ID = "probe-user"
PROBE_AGENT_NAME = "Probe-Agent"

# The pre-abstraction per-agent manifest file. DeerMem writes agent state under
# ``agents/{agent_name}/facts/`` instead, so a guide naming this path is stale.
LEGACY_PER_AGENT_FILE = "agents/{agent_name}/memory.json"


def _guide_text(path: Path) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _configuration_block(path: Path) -> str:
    """Return the first yaml example under the guide's Configuration heading."""
    lines = _guide_text(path).splitlines()
    starts = [index for index, line in enumerate(lines) if re.fullmatch(r"## (Configuration|配置)\s*", line)]
    assert len(starts) == 1, f"expected exactly one Configuration heading in {path}, found {len(starts)}"
    fences = [index for index in range(starts[0], len(lines)) if lines[index].strip().startswith("```yaml")]
    assert fences, f"no yaml example after the Configuration heading in {path}"
    end = next(index for index in range(fences[0] + 1, len(lines)) if lines[index].strip() == "```")
    return "\n".join(lines[fences[0] + 1 : end])


def _top_level_memory_keys(block: str) -> set[str]:
    """Keys written directly under ``memory:`` (two-space indent) in a yaml example."""
    keys = set()
    inside = False
    for line in block.splitlines():
        if line.startswith("memory:"):
            inside = True
            continue
        if not inside:
            continue
        if line and not line.startswith(("  ", " ", "\t", "#")):
            break
        match = re.fullmatch(r"  ([A-Za-z_][A-Za-z0-9_]*):.*", line)
        if match:
            keys.add(match.group(1))
    return keys


@pytest.fixture(scope="module")
def probe_layout() -> tuple[str, str]:
    """The per-user manifest and per-agent facts paths, as the runtime resolves them."""
    memory_path = memory_file_path(DeerMemConfig(storage_path=PROBE_ROOT), user_id=PROBE_USER_ID)
    facts_path = agent_facts_directory(memory_path, PROBE_AGENT_NAME)
    return str(memory_path.relative_to(PROBE_ROOT)), str(facts_path.relative_to(PROBE_ROOT))


@pytest.mark.parametrize("path", MEMORY_GUIDES, ids=str)
def test_guide_documents_the_scoped_manifest_and_facts_paths(path: Path, probe_layout: tuple[str, str]) -> None:
    content = _guide_text(path)
    memory_rel, facts_rel = probe_layout

    # Guides spell the resolved layout with placeholders, so re-spell the real paths
    # the same way before comparing. ``agent_facts_directory`` already folded the
    # mixed-case probe name, hence the lowercase replacement.
    def spelled(rel: str) -> str:
        return rel.replace(PROBE_USER_ID, "{user_id}").replace(PROBE_AGENT_NAME.lower(), "{agent_name}")

    scoped_manifest = spelled(memory_rel)
    agent_facts = spelled(facts_rel)
    assert scoped_manifest in content, f"{path} does not document the per-user manifest at {scoped_manifest}"
    assert agent_facts in content, f"{path} does not document the per-agent facts directory at {agent_facts}"
    assert LEGACY_PER_AGENT_FILE not in content, f"{path} still documents the pre-abstraction per-agent file {LEGACY_PER_AGENT_FILE}"


@pytest.mark.parametrize("path", MEMORY_GUIDES, ids=str)
def test_guide_keeps_backend_private_knobs_out_of_the_memory_top_level(path: Path) -> None:
    keys = _top_level_memory_keys(_configuration_block(path))
    assert keys, f"no keys parsed from the Configuration example in {path}"
    shared = set(MemoryConfig.model_fields)
    drift = sorted(keys - shared)
    assert not drift, f"{path} documents DeerMem-private keys at the memory top level: {drift} (they belong under backend_config)"
