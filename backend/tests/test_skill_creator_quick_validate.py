from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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

            read_only = False
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"read_text", "write_text"}:
                operation = node.func.attr
                read_only = operation == "read_text"
            elif isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = node.args[1] if len(node.args) > 1 else next((keyword.value for keyword in node.keywords if keyword.arg == "mode"), None)
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value:
                    continue
                operation = "open"
                # ``utf-8-sig`` is the documented read encoding for SKILL.md
                # (it strips a leading BOM); writes must stay plain UTF-8.
                read_only = not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(flag in mode.value for flag in "wax+"))
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}
                text_mode = any(isinstance(keywords.get(name), ast.Constant) and keywords[name].value is True for name in ("text", "universal_newlines"))
                if not text_mode and "encoding" not in keywords:
                    continue
                operation = f"subprocess.{node.func.attr}"
            else:
                continue

            encoding = next((keyword.value for keyword in node.keywords if keyword.arg == "encoding"), None)
            allowed = {"utf-8", "utf-8-sig"} if read_only else {"utf-8"}
            if not isinstance(encoding, ast.Constant) or encoding.value not in allowed:
                relative_path = script_path.relative_to(SKILL_CREATOR_ROOT)
                missing_encoding.append(f"{relative_path}:{node.lineno} {operation}")

    assert not missing_encoding, f"text I/O must declare encoding='utf-8' (or 'utf-8-sig' for reads): {missing_encoding}"


def _write_skill(tmp_path: Path, content: str) -> Path:
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8", newline="")
    return skill_dir


def test_validate_skill_accepts_bom_prefixed_frontmatter(tmp_path: Path) -> None:
    validator = _load_validator()
    skill_dir = _write_skill(
        tmp_path,
        "﻿---\nname: demo-skill\ndescription: Handles BOM-prefixed files.\n---\n\n# Demo\n",
    )

    assert validator.validate_skill(skill_dir) == (True, "Skill is valid!")


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("name", "Name cannot be empty"),
        ("description", "Description cannot be empty"),
    ],
)
def test_validate_skill_rejects_empty_required_fields(tmp_path: Path, field: str, message: str) -> None:
    validator = _load_validator()
    values = {"name": "demo-skill", "description": "Handles empty fields."}
    values[field] = '""'
    content = "---\n" + "\n".join(f"{key}: {value}" for key, value in values.items()) + "\n---\n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (False, message)


@pytest.mark.parametrize(
    "extra",
    [
        'argument-hint: "[file]"',
        "required-secrets:\n  - API_KEY",
        "secrets-autonomous: false",
        "version: 1.0.0",
        "author: someone",
    ],
)
def test_validate_skill_accepts_runtime_frontmatter_fields(tmp_path: Path, extra: str) -> None:
    validator = _load_validator()
    content = f"---\nname: demo-skill\ndescription: Handles runtime fields.\n{extra}\n---\n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (True, "Skill is valid!")


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("required-secrets: API_KEY", "required-secrets must be a list"),
        (
            'required-secrets:\n  - name: API_KEY\n    optional: "no"',
            "required-secrets entry 'API_KEY' optional must be a boolean",
        ),
        ('secrets-autonomous: "yes"', "secrets-autonomous must be a boolean"),
    ],
)
def test_validate_skill_rejects_malformed_runtime_fields(tmp_path: Path, extra: str, message: str) -> None:
    validator = _load_validator()
    content = f"---\nname: demo-skill\ndescription: Handles malformed fields.\n{extra}\n---\n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (False, message)


def test_validate_skill_accepts_trailing_whitespace_on_delimiters(tmp_path: Path) -> None:
    validator = _load_validator()
    content = "--- \nname: demo-skill\ndescription: Handles padded delimiters.\n--- \n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (True, "Skill is valid!")


def test_validate_skill_reports_mixed_non_string_keys_without_crashing(tmp_path: Path) -> None:
    validator = _load_validator()
    content = "---\nname: demo-skill\ndescription: Handles odd keys.\n42: bad\ncustom-field: bad\n---\n\n# Demo\n"

    valid, message = validator.validate_skill(_write_skill(tmp_path, content))

    assert valid is False
    assert "Unexpected key(s)" in message
    assert "42" in message
    assert "custom-field" in message


def test_shared_skill_parser_accepts_bom_prefixed_frontmatter(tmp_path: Path) -> None:
    utils = _load_script("utils")
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "﻿---\nname: demo-skill\ndescription: Handles BOM-prefixed files.\n---\n\n# Demo\n",
        encoding="utf-8",
        newline="",
    )

    name, description, _ = utils.parse_skill_md(skill_dir)

    assert name == "demo-skill"
    assert description == "Handles BOM-prefixed files."


@pytest.mark.parametrize(
    ("allowed_tools", "message"),
    [
        ("[Read, 42]", "allowed-tools must contain only strings"),
        ('["Read", ""]', "allowed-tools cannot contain empty tool names"),
        ('"Bash(grep))"', "allowed-tools contains an unmatched closing parenthesis"),
        ('"Bash(\'grep)"', "allowed-tools contains an unclosed quote"),
        ('"Bash(grep"', "allowed-tools contains an unclosed parenthesized pattern"),
        ("42", "allowed-tools must be a space-separated string or list of strings"),
    ],
)
def test_validate_skill_rejects_malformed_allowed_tools(tmp_path: Path, allowed_tools: str, message: str) -> None:
    validator = _load_validator()
    content = f"---\nname: demo-skill\ndescription: Handles tools.\nallowed-tools: {allowed_tools}\n---\n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (False, message)


@pytest.mark.parametrize(
    "allowed_tools",
    ['"Read Bash(grep)"', '["Read", "Bash(grep)"]'],
)
def test_validate_skill_accepts_well_formed_allowed_tools(tmp_path: Path, allowed_tools: str) -> None:
    validator = _load_validator()
    content = f"---\nname: demo-skill\ndescription: Handles tools.\nallowed-tools: {allowed_tools}\n---\n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (True, "Skill is valid!")


@pytest.mark.parametrize("compatibility", ["123", '"' + "x" * 501 + '"'])
def test_validate_skill_accepts_compatibility_the_runtime_accepts(tmp_path: Path, compatibility: str) -> None:
    validator = _load_validator()
    content = f"---\nname: demo-skill\ndescription: Handles compatibility.\ncompatibility: {compatibility}\n---\n\n# Demo\n"

    assert validator.validate_skill(_write_skill(tmp_path, content)) == (True, "Skill is valid!")
