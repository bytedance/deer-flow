import logging
import re
from pathlib import Path

from .types import Skill

logger = logging.getLogger(__name__)


def parse_skill_file(skill_file: Path, category: str, relative_path: Path | None = None) -> Skill | None:
    """
    Parse a SKILL.md file and extract metadata.

    Args:
        skill_file: Path to the SKILL.md file
        category: Category of the skill ('public' or 'custom')

    Returns:
        Skill object if parsing succeeds, None otherwise
    """
    if not skill_file.exists() or skill_file.name != "SKILL.md":
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")

        # Extract YAML front matter
        # Pattern: ---\nkey: value\n---
        front_matter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)

        if not front_matter_match:
            return None

        front_matter = front_matter_match.group(1)

        # Parse YAML front matter with basic multiline string support
        metadata = {}
        lines = front_matter.split("\n")
        current_key = None
        current_value = []
        is_multiline = False
        multiline_style = None
        indent_level = None

        for line in lines:
            if is_multiline:
                if not line.strip():
                    current_value.append("")
                    continue

                current_indent = len(line) - len(line.lstrip())

                if indent_level is None:
                    if current_indent > 0:
                        indent_level = current_indent
                        current_value.append(line[indent_level:])
                        continue
                elif current_indent >= indent_level:
                    current_value.append(line[indent_level:])
                    continue

            # If we reach here, it's either a new key or the end of multiline
            if current_key and is_multiline:
                if multiline_style == "|":
                    metadata[current_key] = "\n".join(current_value).rstrip()
                else:
                    text = "\n".join(current_value).rstrip()
                    # Replace single newlines with spaces for folded blocks
                    metadata[current_key] = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

                current_key = None
                current_value = []
                is_multiline = False
                multiline_style = None
                indent_level = None

            if not line.strip():
                continue

            if ":" in line:
                # Handle nested dicts simply by ignoring indentation for now,
                # or just extracting top-level keys
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                if value in (">", "|"):
                    current_key = key
                    is_multiline = True
                    multiline_style = value
                    current_value = []
                    indent_level = None
                else:
                    metadata[key] = value

        if current_key and is_multiline:
            if multiline_style == "|":
                metadata[current_key] = "\n".join(current_value).rstrip()
            else:
                text = "\n".join(current_value).rstrip()
                metadata[current_key] = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

        # Extract required fields
        name = metadata.get("name")
        description = metadata.get("description")

        if not name or not description:
            return None

        license_text = metadata.get("license")

        return Skill(
            name=name,
            description=description,
            license=license_text,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            relative_path=relative_path or Path(skill_file.parent.name),
            category=category,
            enabled=True,  # Default to enabled, actual state comes from config file
        )

    except Exception as e:
        logger.error("Error parsing skill file %s: %s", skill_file, e)
        return None
