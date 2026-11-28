"""Shared SKILL.md frontmatter parsing helpers.

The runtime parser, install-time validator, and review core all use this module
as the schema source for DeerFlow SKILL.md metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

ALLOWED_FRONTMATTER_PROPERTIES = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "argument-hint",
    "required-secrets",
    "secrets-autonomous",
    "metadata",
    "compatibility",
    "version",
    "author",
}

# `\ufeff` is the UTF-8 byte-order mark that Windows Notepad and PowerShell's
# `Set-Content -Encoding UTF8` prepend to a saved file. It is consumed by the match, so
# neither the front matter nor the body carries it downstream.
# Delimiter whitespace must stay on its own line; do not consume body
# indentation or accept a closing line that merely starts with three hyphens.
_FRONTMATTER_RE = re.compile(r"^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_YAML_MERGE_TAG = "tag:yaml.org,2002:merge"
_YAML_MERGE_KEY = object()
_EXPLICIT_MAPPING_VALUE = "_deerflow_explicit_value"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""

    def flatten_mapping(self, node: yaml.MappingNode) -> None:
        """Expand merge keys only after their source mappings are validated."""
        _validate_mapping_before_flatten(self, node)
        super().flatten_mapping(node)


def _assert_unique_explicit_keys(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    explicit_value: list[tuple[yaml.Node, yaml.Node]],
    deep: bool = False,
) -> None:
    """Assert that a mapping's original YAML keys are unique."""
    seen: set[Any] = set()
    for key_node, _ in explicit_value:
        if key_node.tag == _YAML_MERGE_TAG:
            key = _YAML_MERGE_KEY
        else:
            key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
        except TypeError:
            # Let SafeLoader report non-hashable mapping keys itself.
            continue
        if duplicate:
            key_name = "<<" if key is _YAML_MERGE_KEY else key
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key_name!r}",
                key_node.start_mark,
            )
        seen.add(key)


def _validate_mapping_before_flatten(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> None:
    """Validate explicit keys before PyYAML mutates shared merge sources."""
    explicit_value = getattr(node, _EXPLICIT_MAPPING_VALUE, None)
    if explicit_value is None:
        explicit_value = node.value
        setattr(node, _EXPLICIT_MAPPING_VALUE, explicit_value)
        _assert_unique_explicit_keys(loader, node, explicit_value, deep=deep)

    for key_node, value_node in explicit_value:
        if key_node.tag != _YAML_MERGE_TAG:
            continue
        if isinstance(value_node, yaml.MappingNode):
            _validate_mapping_before_flatten(loader, value_node, deep=deep)
        elif isinstance(value_node, yaml.SequenceNode):
            for merge_source in value_node.value:
                if isinstance(merge_source, yaml.MappingNode):
                    _validate_mapping_before_flatten(loader, merge_source, deep=deep)


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    """Construct a mapping only when every original key is unique."""
    _validate_mapping_before_flatten(loader, node, deep=deep)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_skill_frontmatter(frontmatter_text: str) -> Any:
    """Load SKILL.md YAML with deterministic duplicate-key rejection."""
    return yaml.load(  # noqa: S506 - fixed safe loader subclass
        frontmatter_text,
        Loader=_UniqueKeySafeLoader,
    )


@dataclass(frozen=True)
class SkillMarkdownParts:
    """Parsed pieces of a SKILL.md document."""

    metadata: dict[str, Any]
    frontmatter_text: str
    body: str


def split_skill_markdown(content: str) -> tuple[SkillMarkdownParts | None, str | None]:
    """Split a SKILL.md document into frontmatter and body.

    Returns ``(parts, None)`` on success and ``(None, message)`` on failure. The
    message intentionally avoids host paths so callers can reuse it in
    deterministic review output.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None, "No YAML frontmatter found"

    frontmatter_text = match.group(1)
    try:
        metadata = load_skill_frontmatter(frontmatter_text)
    except (yaml.YAMLError, ValueError) as exc:
        return None, f"Invalid YAML in frontmatter: {exc}"
    except AttributeError:
        # PyYAML's explicit timestamp constructor assumes its pattern matched.
        return None, "Invalid YAML in frontmatter: invalid scalar value"

    if not isinstance(metadata, dict):
        return None, "Frontmatter must be a YAML dictionary"

    # YAML permits non-string keys, but downstream validation expects field
    # names to be strings.
    metadata = {str(key): value for key, value in metadata.items()}

    return (
        SkillMarkdownParts(
            metadata=metadata,
            frontmatter_text=frontmatter_text,
            body=content[match.end() :],
        ),
        None,
    )
