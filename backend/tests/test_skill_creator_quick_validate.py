from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_CREATOR_ROOT = REPO_ROOT / "skills" / "public" / "skill-creator"
SCRIPTS_DIR = SKILL_CREATOR_ROOT / "scripts"
VALIDATOR_PATH = SCRIPTS_DIR / "quick_validate.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("deerflow_skill_creator_quick_validate", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"deerflow_skill_creator_{name}", path)
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


def test_validate_skill_reports_invalid_utf8_without_raising(tmp_path: Path) -> None:
    validator = _load_validator()
    skill_dir = tmp_path / "invalid-encoding"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_bytes(b"---\nname: invalid-encoding\ndescription: \xff\n---\n")

    assert validator.validate_skill(skill_dir) == (False, "SKILL.md is not valid UTF-8")


def test_package_skill_reports_invalid_utf8_without_traceback(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.syspath_prepend(str(SKILL_CREATOR_ROOT))
    packager = _load_script("package_skill")
    skill_dir = tmp_path / "invalid-encoding"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_bytes(b"---\nname: invalid-encoding\ndescription: \xff\n---\n")
    output_dir = tmp_path / "dist"

    assert packager.package_skill(skill_dir, output_dir) is None
    assert "Validation failed: SKILL.md is not valid UTF-8" in capsys.readouterr().out
    assert not list(tmp_path.rglob("*.skill"))


def test_shared_skill_parser_reads_markdown_as_utf8(tmp_path: Path, monkeypatch) -> None:
    utils = _load_script("utils")
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

    assert utils.parse_skill_md(skill_dir) == (
        "localized-skill",
        "处理中文内容",
        skill_md.read_text(encoding="utf-8"),
    )


def test_improve_description_uses_utf8_for_claude_text_io(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(SKILL_CREATOR_ROOT))
    improve_description = _load_script("improve_description")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="改进后的描述", stderr="")

    monkeypatch.setattr(improve_description.subprocess, "run", fake_run)

    assert improve_description._call_claude("处理中文内容🙂", None) == "改进后的描述"
    assert captured["input"] == "处理中文内容🙂"
    assert captured["encoding"] == "utf-8"


def test_skill_creator_text_io_declares_utf8() -> None:
    missing_encoding: list[str] = []

    for script_path in sorted(SKILL_CREATOR_ROOT.rglob("*.py")):
        tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if isinstance(node.func, ast.Attribute) and node.func.attr in {"read_text", "write_text"}:
                operation = node.func.attr
            elif isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = node.args[1] if len(node.args) > 1 else next((keyword.value for keyword in node.keywords if keyword.arg == "mode"), None)
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value:
                    continue
                operation = "open"
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}
                text_mode = any(isinstance(keywords.get(name), ast.Constant) and keywords[name].value is True for name in ("text", "universal_newlines"))
                if not text_mode and "encoding" not in keywords:
                    continue
                operation = f"subprocess.{node.func.attr}"
            else:
                continue

            encoding = next((keyword.value for keyword in node.keywords if keyword.arg == "encoding"), None)
            if not isinstance(encoding, ast.Constant) or encoding.value != "utf-8":
                relative_path = script_path.relative_to(SKILL_CREATOR_ROOT)
                missing_encoding.append(f"{relative_path}:{node.lineno} {operation}")

    assert not missing_encoding, f"text I/O must declare encoding='utf-8': {missing_encoding}"
