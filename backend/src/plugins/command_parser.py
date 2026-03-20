"""Parser for plugin command markdown files."""

import logging
import re
from pathlib import Path

from .types import Command

logger = logging.getLogger(__name__)


def parse_command_file(command_file: Path, plugin_name: str) -> Command | None:
    """Parse a command .md file and extract metadata.

    Command files have YAML frontmatter with 'description' (required) and
    optional 'argument-hint', followed by a markdown body with instructions.

    Args:
        command_file: Path to the command .md file.
        plugin_name: Name of the plugin this command belongs to.

    Returns:
        Command object if parsing succeeds, None otherwise.
    """
    if not command_file.exists() or command_file.suffix != ".md":
        return None

    try:
        content = command_file.read_text(encoding="utf-8")

        # Extract YAML front matter
        front_matter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not front_matter_match:
            return None

        front_matter = front_matter_match.group(1)

        # Parse YAML front matter (simple key-value parsing)
        metadata = {}
        for line in front_matter.split("\n"):
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                value = value.strip()
                # Strip surrounding quotes
                if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                    value = value[1:-1]
                elif len(value) >= 2 and value[0] == "'" and value[-1] == "'":
                    value = value[1:-1]
                metadata[key.strip()] = value

        # Description is required
        description = metadata.get("description")
        if not description:
            return None

        argument_hint = metadata.get("argument-hint", "")

        # Extract body (everything after frontmatter)
        body = content[front_matter_match.end():].strip()

        # Derive command name from filename (minus .md extension)
        name = command_file.stem

        return Command(
            name=name,
            description=description,
            argument_hint=argument_hint,
            content=body,
            plugin_name=plugin_name,
        )

    except Exception as e:
        logger.error("Error parsing command file %s: %s", command_file, e)
        return None
