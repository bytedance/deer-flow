import logging
import re
from pathlib import Path

import yaml

from .types import SKILL_MD_FILE, SecretRequirement, Skill, SkillCategory

logger = logging.getLogger(__name__)

# Valid POSIX environment-variable name.
_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _format_yaml_error(skill_file: Path, exc: yaml.YAMLError, source: str) -> str:
    """Render a developer-friendly explanation of a YAML front-matter error."""

    lines = [f"Invalid YAML front-matter in {skill_file}: {exc}"]

    mark = getattr(exc, "problem_mark", None)
    source_lines = source.splitlines()
    if mark is not None and 0 <= mark.line < len(source_lines):
        offending = source_lines[mark.line]

        # mark.line is 0-based within the front-matter body; +1 makes it
        # 1-based, +1 more accounts for the leading `---` fence that the
        # front-matter regex strips before yaml.safe_load sees it. The
        # result matches the line number an author sees in their editor.
        file_line_number = mark.line + 2
        lines.append(f"  line {file_line_number}: {offending}")

        # Targeted hint for the most common authoring mistake: an unquoted
        # scalar value whose body contains ``: ``. We only surface the hint
        # when we are confident it applies, to avoid misleading authors who
        # hit unrelated YAML errors.
        if getattr(exc, "problem", "") == "mapping values are not allowed here" and ":" in offending:
            key, _, value = offending.partition(":")
            value = value.strip()
            if value and value[0] not in {'"', "'", "|", ">", "[", "{"}:
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'  hint: values containing ":" must be quoted, e.g. {key}: "{escaped}"')

    return "\n".join(lines)


def parse_allowed_tools(raw: object, skill_file: Path) -> list[str] | None:
    """Parse the optional allowed-tools frontmatter field.

    Returns None when the field is omitted. Returns a list when the field is a
    YAML sequence of strings, including an empty list for explicit no-tool
    skills. Raises ValueError for malformed values.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"allowed-tools in {skill_file} must be a list of strings")

    allowed_tools: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"allowed-tools in {skill_file} must contain only strings")
        tool_name = item.strip()
        if not tool_name:
            raise ValueError(f"allowed-tools in {skill_file} cannot contain empty tool names")
        allowed_tools.append(tool_name)
    return allowed_tools


def parse_required_secrets(raw: object, skill_file: Path) -> list[SecretRequirement]:
    """Parse the optional required-secrets frontmatter field (issue #3861).

    Accepts a YAML sequence whose items are either a string (the secret / env
    variable name) or a mapping (``{name, optional}``). Returns an empty list
    when the field is omitted. Entries whose name is missing or is not a valid
    environment-variable name are dropped with a warning, so one malformed
    declaration does not invalidate the whole skill. Raises ValueError only when
    the field is present but is not a list.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"required-secrets in {skill_file} must be a list")

    secrets: list[SecretRequirement] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            name, optional = item.strip(), False
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            optional = bool(item.get("optional", False))
        else:
            logger.warning("Ignoring malformed required-secrets entry in %s: %r", skill_file, item)
            continue

        if not _ENV_VAR_NAME_RE.match(name):
            logger.warning("Ignoring required-secrets entry with invalid env var name in %s: %r", skill_file, name)
            continue
        if name in seen:
            continue
        seen.add(name)
        secrets.append(SecretRequirement(name=name, optional=optional))
    return secrets


def parse_skill_file(skill_file: Path, category: SkillCategory, relative_path: Path | None = None) -> Skill | None:
    """Parse a SKILL.md file and extract metadata.

    Args:
        skill_file: Path to the SKILL.md file.
        category: Category of the skill.
        relative_path: Relative path from the category root to the skill
            directory.  Defaults to the skill directory name when omitted.

    Returns:
        Skill object if parsing succeeds, None otherwise.
    """
    if not skill_file.exists() or skill_file.name != SKILL_MD_FILE:
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
            logger.error("%s", _format_yaml_error(skill_file, exc, front_matter_text))
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

        try:
            allowed_tools = parse_allowed_tools(metadata.get("allowed-tools"), skill_file)
        except ValueError as exc:
            logger.error("Invalid allowed-tools in %s: %s", skill_file, exc)
            return None

        try:
            required_secrets = parse_required_secrets(metadata.get("required-secrets"), skill_file)
        except ValueError as exc:
            logger.error("Invalid required-secrets in %s: %s", skill_file, exc)
            return None

        return Skill(
            name=name,
            description=description,
            license=license_text,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            relative_path=relative_path or Path(skill_file.parent.name),
            category=category,
            allowed_tools=allowed_tools,
            enabled=True,  # Actual state comes from the extensions config file.
            required_secrets=required_secrets,
        )

    except Exception:
        logger.exception("Unexpected error parsing skill file %s", skill_file)
        return None
