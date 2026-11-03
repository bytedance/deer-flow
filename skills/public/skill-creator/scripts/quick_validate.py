#!/usr/bin/env python3
"""
Quick validation script for skills - minimal version
"""

import sys
import re
import yaml
from pathlib import Path

def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"

    # Read and validate frontmatter. ``utf-8-sig`` decodes plain UTF-8 unchanged
    # and strips the BOM that Windows editors prepend, matching the runtime parser.
    try:
        content = skill_md.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return False, "SKILL.md is not valid UTF-8"
    if not content.startswith('---'):
        return False, "No YAML frontmatter found"

    # Extract frontmatter. Allow trailing whitespace on the delimiters, like
    # the runtime parser in backend/packages/harness/deerflow/skills/frontmatter.py.
    match = re.match(r'^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)', content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter_text = match.group(1)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary"
        # YAML permits non-string keys; downstream validation expects strings.
        frontmatter = {str(key): value for key, value in frontmatter.items()}
    except yaml.YAMLError as e:
        return False, f"Invalid YAML in frontmatter: {e}"

    # Define allowed properties. Keep this in sync with the runtime schema in
    # backend/packages/harness/deerflow/skills/frontmatter.py and the field
    # rules in backend/packages/harness/deerflow/skills/validation.py: a skill
    # that the runtime accepts must not be rejected here before packaging.
    ALLOWED_PROPERTIES = {
        'name', 'description', 'license', 'allowed-tools', 'argument-hint',
        'required-secrets', 'secrets-autonomous', 'metadata', 'compatibility',
        'version', 'author',
    }

    # Check for unexpected properties (excluding nested keys under metadata)
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    # Check required fields
    if 'name' not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if 'description' not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    # Extract name for validation
    name = frontmatter.get('name', '')
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if not name:
        return False, "Name cannot be empty"
    # Check naming convention (kebab-case: lowercase with hyphens)
    if not re.match(r'^[a-z0-9-]+$', name):
        return False, f"Name '{name}' should be kebab-case (lowercase letters, digits, and hyphens only)"
    if name.startswith('-') or name.endswith('-') or '--' in name:
        return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
    # Check name length (max 64 characters per spec)
    if len(name) > 64:
        return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    # Extract and validate description
    description = frontmatter.get('description', '')
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if not description:
        return False, "Description cannot be empty"
    # Check for angle brackets
    if '<' in description or '>' in description:
        return False, "Description cannot contain angle brackets (< or >)"
    # Check description length (max 1024 characters per spec)
    if len(description) > 1024:
        return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    # The runtime validator does not inspect `compatibility` (export.py only
    # coerces it), so this script must not reject values the runtime accepts.

    # Validate allowed-tools with the same shape rules as the runtime parser
    # (backend/packages/harness/deerflow/skills/parser.py).
    allowed_tools = frontmatter.get('allowed-tools')
    if allowed_tools is not None:
        if isinstance(allowed_tools, str):
            depth = 0
            quote = None
            escaped = False
            for char in allowed_tools:
                if escaped:
                    escaped = False
                    continue
                if char == '\\':
                    escaped = True
                    continue
                if quote is not None:
                    if char == quote:
                        quote = None
                    continue
                if char in {'"', "'"}:
                    quote = char
                    continue
                if char == '(':
                    depth += 1
                elif char == ')':
                    if depth == 0:
                        return False, "allowed-tools contains an unmatched closing parenthesis"
                    depth -= 1
            if quote is not None:
                return False, "allowed-tools contains an unclosed quote"
            if depth > 0:
                return False, "allowed-tools contains an unclosed parenthesized pattern"
        elif isinstance(allowed_tools, list):
            for item in allowed_tools:
                if not isinstance(item, str):
                    return False, "allowed-tools must contain only strings"
                if not item.strip():
                    return False, "allowed-tools cannot contain empty tool names"
        else:
            return False, "allowed-tools must be a space-separated string or list of strings"

    # Validate the DeerFlow-specific declarations with the same shapes the
    # runtime validator enforces, so a malformed skill fails before packaging.
    required_secrets = frontmatter.get('required-secrets')
    if required_secrets is not None and not isinstance(required_secrets, list):
        return False, "required-secrets must be a list"
    if required_secrets is not None:
        for item in required_secrets:
            if isinstance(item, dict) and not isinstance(item.get('optional', False), bool):
                if item.get('name') is None:
                    return False, "required-secrets entry without a name has an optional field that must be a boolean"
                return False, f"required-secrets entry {item.get('name')!r} optional must be a boolean"

    secrets_autonomous = frontmatter.get('secrets-autonomous')
    if secrets_autonomous is not None and not isinstance(secrets_autonomous, bool):
        return False, "secrets-autonomous must be a boolean"

    return True, "Skill is valid!"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)
    
    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
