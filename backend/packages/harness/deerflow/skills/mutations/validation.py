"""Strict P0 authority-preserving validation; never activate the candidate."""

from __future__ import annotations

import json

import yaml

from deerflow.skills.frontmatter import _FRONTMATTER_RE, ALLOWED_FRONTMATTER_PROPERTIES
from deerflow.skills.validation import validate_skill_frontmatter_text

MAX_MAIN_BYTES = 128 * 1024
PARSER_VERSION = "skill-mutation-frontmatter-v1"


class _StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("INVALID_FRONTMATTER")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _metadata(content: str) -> dict:
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_MAIN_BYTES:
        raise ValueError("QUOTA_EXCEEDED")
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        raise ValueError("INVALID_FRONTMATTER")
    source = match.group(1)
    try:
        depth = 0
        for count, event in enumerate(yaml.parse(source, Loader=yaml.SafeLoader)):
            if count > 4096 or isinstance(event, yaml.events.AliasEvent):
                raise ValueError("INVALID_FRONTMATTER")
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
            if depth > 24:
                raise ValueError("INVALID_FRONTMATTER")
        metadata = yaml.load(source, Loader=_StrictLoader)
        if not isinstance(metadata, dict):
            raise ValueError("INVALID_FRONTMATTER")
        # Reject values without stable JSON/type semantics (dates, sets, NaN).
        json.dumps(metadata, allow_nan=False)
        return metadata
    except (yaml.YAMLError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("INVALID_FRONTMATTER") from exc


def _typed(value):
    if isinstance(value, dict):
        return (dict, tuple(sorted((key, _typed(item)) for key, item in value.items())))
    if isinstance(value, list):
        return (list, tuple(_typed(item) for item in value))
    return (type(value), value)


def validate_candidate(baseline: str, candidate: str, name: str) -> None:
    """Only body and description can differ; unknown declarations stay intact."""
    before, after = _metadata(baseline), _metadata(candidate)
    if _typed({k: v for k, v in before.items() if k != "description"}) != _typed({k: v for k, v in after.items() if k != "description"}):
        raise ValueError("FRONTMATTER_CHANGED")
    # Reuse runtime/install field validation without discarding unknown values
    # from the actual candidate: comparison above already preserves them.
    known = {k: v for k, v in after.items() if k in ALLOWED_FRONTMATTER_PROPERTIES}
    valid, _, declared_name = validate_skill_frontmatter_text("---\n" + yaml.safe_dump(known) + "---\n")
    if not valid or declared_name != name:
        raise ValueError("INVALID_FRONTMATTER")
