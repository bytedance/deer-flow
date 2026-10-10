"""Host-path-free diagnostics for skill management, never the agent catalog."""

from dataclasses import dataclass
from typing import Literal

import yaml


@dataclass(frozen=True)
class SkillLoadDiagnostic:
    package: str
    path: Literal["SKILL.md"] = "SKILL.md"
    code: Literal["invalid_frontmatter"] = "invalid_frontmatter"
    hint: Literal["quote_colon_value"] | None = None
    line: int | None = None
    column: int | None = None


def yaml_load_diagnostic(package: str, exc: yaml.YAMLError, source: str, line_offset: int) -> SkillLoadDiagnostic:
    """Project parser details into stable codes without serializing the exception."""
    mark = getattr(exc, "problem_mark", None)
    hint = None
    lines = source.splitlines()
    if mark is not None and 0 <= mark.line < len(lines) and getattr(exc, "problem", "") == "mapping values are not allowed here":
        offending = lines[mark.line]
        _, separator, value = offending.partition(":")
        value = value.strip()
        if separator and value and value[0] not in {'"', "'", "|", ">", "[", "{"} and mark.column > offending.index(":") and offending[mark.column : mark.column + 2] == ": ":
            hint = "quote_colon_value"
    return SkillLoadDiagnostic(
        package=package,
        hint=hint,
        line=mark.line + line_offset + 1 if mark is not None else None,
        column=mark.column + 1 if mark is not None else None,
    )
