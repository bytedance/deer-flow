import logging
import re
from pathlib import Path

import yaml

from .types import Skill

logger = logging.getLogger(__name__)


def parse_skill_file(skill_file: Path, category: str, relative_path: Path | None = None) -> Skill | None:
    """Parse a SKILL.md file and extract metadata.

    Args:
        skill_file: Path to the SKILL.md file.
        category: Category of the skill ('public' or 'custom').
        relative_path: Relative path from the category root to the skill
            directory.  Defaults to the skill directory name when omitted.

    Returns:
        Skill object if parsing succeeds, None otherwise.
    """
    if not skill_file.exists() or skill_file.name != "SKILL.md":
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")

        # Extract YAML front-matter block between leading ``---`` fences.
        front_matter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not front_matter_match:
            return None

        front_matter_text = front_matter_match.group(1)

        try:
            metadata = yaml.safe_load(front_matter_text)
        except yaml.YAMLError as exc:
            logger.error("Invalid YAML front-matter in %s: %s", skill_file, exc)
            return None

        if not isinstance(metadata, dict):
            logger.error("Front-matter in %s is not a YAML mapping", skill_file)
            return None

        # Extract required fields.  Both must be non-empty strings.
        name = metadata.get("name")
        description = metadata.get("description")

        if not name or not isinstance(name, str):
            return None
        if not description or not isinstance(description, str):
            return None

        # Normalise: strip surrounding whitespace that YAML may preserve.
        name = name.strip()
        description = description.strip()

        if not name or not description:
            return None

        license_text = metadata.get("license")
        if license_text is not None:
            license_text = str(license_text).strip() or None

        return Skill(
            name=name,
            description=description,
            license=license_text,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            relative_path=relative_path or Path(skill_file.parent.name),
            category=category,
            enabled=True,  # Actual state comes from the extensions config file.
        )

    except Exception:
        logger.exception("Unexpected error parsing skill file %s", skill_file)
        return None
