"""A UTF-8 BOM in SKILL.md / SOUL.md is an editor artifact, not content.

Windows Notepad and PowerShell 5.1 (``Set-Content``) write a UTF-8 byte-order
mark (``U+FEFF``) at the start of the file. The frontmatter path already
tolerates it (``skills/frontmatter.py`` matches ``^<U+FEFF>?---``), so a
BOM-prefixed SKILL.md parses and installs normally. The *content* delivery
paths read the same file again with plain ``utf-8``, which keeps the BOM, so:

- the model is handed a body whose first character is an invisible ``U+FEFF``,
- the published ``sha256`` digest fingerprints the BOM instead of the text.

``str.strip()`` does not remove ``U+FEFF`` (it is not whitespace in Python), so
the ``.strip()``-based SOUL.md reads are equally affected. Reading these files
as ``utf-8-sig`` drops exactly the leading BOM, matching the convention already
used by ``credential_loader`` / ``file_outline`` / ``acceptance_checks``.

Covered read sites (#6983, #6985):

- ``SkillActivationMiddleware._read_skill_content``
- ``LocalSkillStorage.read_custom_skill``
- ``deerflow.config.agents_config.load_agent_soul`` (default agent)
- ``deerflow.persistence.agents.file.FileAgentStore.get_soul`` (named agent)
"""

from __future__ import annotations

from pathlib import Path

from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.types import SKILL_MD_FILE

# U+FEFF, the UTF-8 byte-order mark. Kept as chr() so no invisible character
# sits in the source; it is the exact editor artifact under test.
_BOM = chr(0xFEFF)

_BODY = "---\nname: bom-demo\ndescription: demo skill\n---\n\n# Body\n"


def test_skill_activation_read_strips_bom(tmp_path: Path) -> None:
    skill_dir = tmp_path / "custom" / "bom-demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / SKILL_MD_FILE
    skill_file.write_text(_BOM + _BODY, encoding="utf-8")

    content = SkillActivationMiddleware._read_skill_content(skill_file, tmp_path)

    assert content == _BODY
    assert not content.startswith(_BOM)


def test_local_skill_storage_read_custom_skill_strips_bom(tmp_path: Path) -> None:
    storage = LocalSkillStorage(host_path=str(tmp_path))
    skill_dir = tmp_path / "custom" / "bom-demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / SKILL_MD_FILE).write_text(_BOM + _BODY, encoding="utf-8")

    content = storage.read_custom_skill("bom-demo")

    assert content == _BODY
    assert not content.startswith(_BOM)


def test_load_agent_soul_default_strips_bom(tmp_path: Path, monkeypatch) -> None:
    from deerflow.config.agents_config import load_agent_soul
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: Paths(base_dir=tmp_path))
    (tmp_path / "SOUL.md").write_text(_BOM + "You are the default agent.", encoding="utf-8")

    assert load_agent_soul(None) == "You are the default agent."


def test_file_agent_store_get_soul_strips_bom(tmp_path: Path, monkeypatch) -> None:
    from deerflow.config.paths import Paths
    from deerflow.persistence.agents.file import FileAgentStore

    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: Paths(base_dir=tmp_path))
    agent_dir = tmp_path / "agents" / "bom-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text("name: bom-agent\n", encoding="utf-8")
    (agent_dir / "SOUL.md").write_text(_BOM + "You are a brave agent.", encoding="utf-8")

    assert FileAgentStore().get_soul("bom-agent", user_id="default") == "You are a brave agent."
