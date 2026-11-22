"""Shared utilities for skill-creator scripts."""

from pathlib import Path

import yaml


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning (name, description, full_content)."""
    # utf-8-sig strips the BOM that Windows editors prepend, matching the
    # runtime parser and quick_validate.py.
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8-sig")
    lines = content.split("\n")

    if lines[0].strip() != "---":
        raise ValueError("SKILL.md missing frontmatter (no opening ---)")

    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("SKILL.md missing frontmatter (no closing ---)")

    # Use the same YAML semantics as quick_validate.py and the runtime loader.
    # Stripping quotes manually changes escaped strings, comments and block scalars.
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end_idx]))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in SKILL.md frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML dictionary")

    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError("SKILL.md name and description must be strings")
    return name.strip(), description.strip(), content
