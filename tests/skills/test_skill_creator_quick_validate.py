from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "skills" / "public" / "skill-creator" / "scripts" / "quick_validate.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("deerflow_skill_creator_quick_validate", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_skill_reads_markdown_as_utf8(tmp_path: Path, monkeypatch) -> None:
    validator = _load_validator()
    skill_dir = tmp_path / "localized-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: localized-skill\ndescription: 处理中文内容\n---\n\n# 中文技能\n",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def require_explicit_encoding(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if self == skill_md and encoding is None:
            raise UnicodeDecodeError("gbk", b"\x80", 0, 1, "illegal multibyte sequence")
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", require_explicit_encoding)

    assert validator.validate_skill(skill_dir) == (True, "Skill is valid!")
