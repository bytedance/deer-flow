"""PromptComposer: assembles modular prompt fragments into a complete system prompt.

Fragments are Markdown files stored in subdirectories (system/, context/, research/).
Variable interpolation uses string.Template ($variable syntax) with safe_substitute
so undefined variables pass through unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from string import Template
from typing import Any


# ---------------------------------------------------------------------------
# Instruction intensity constants
# ---------------------------------------------------------------------------

class Intensity:
    """Instruction intensity hierarchy for system prompt language.

    Reserves ALL-CAPS phrases exclusively for hard safety/concurrency constraints
    in the subagent section.  All other fragments should use standard casing.
    """

    # Phrases that may appear in ALL CAPS (subagent safety only)
    RESERVED_CAPS_PHRASES: frozenset[str] = frozenset({
        "HARD LIMIT",
        "VIOLATION",
        "NEVER",
        "HARD ERROR",
        "HARD CONCURRENCY LIMIT",
        "MAXIMUM",
        "CRITICAL",
        "NOT OPTIONAL",
    })

    # Technical acronyms that are allowed in ALL CAPS anywhere
    ALLOWED_ACRONYMS: frozenset[str] = frozenset({
        "API", "URL", "HTML", "CSS", "JSON", "XML", "PDF", "PPT",
        "SQL", "JWT", "OAuth", "SSH", "HTTP", "HTTPS", "UUID",
        "LLM", "AI", "GPU", "CPU", "RAM", "SSD", "CLI", "SDK",
        "MCP", "SSE", "REST", "YAML", "TOML", "GCP", "AWS",
        "LaTeX", "ID", "UI", "UX", "CI", "CD",
    })


# ---------------------------------------------------------------------------
# Default path variables for sandbox environment
# ---------------------------------------------------------------------------

DEFAULT_VARIABLES: dict[str, str] = {
    "uploads_dir": "/mnt/user-data/uploads",
    "workspace_dir": "/mnt/user-data/workspace",
    "outputs_dir": "/mnt/user-data/outputs",
    "skills_base_path": "/mnt/skills",
}


# ---------------------------------------------------------------------------
# PromptComposer
# ---------------------------------------------------------------------------

# Directory containing this module (prompts/)
_PROMPTS_DIR = Path(__file__).resolve().parent


class PromptComposer:
    """Loads, caches, renders, and assembles prompt fragment files.

    Usage::

        composer = PromptComposer()
        prompt = composer.compose(
            memory_context="...",
            subagent_section="...",
            subagent_thinking="...",
            subagent_reminder="...",
            tool_policies="...",
            skills_section="...",
            current_date="2026-02-28, Saturday",
        )
    """

    def __init__(self, prompts_dir: str | Path | None = None) -> None:
        self._dir = Path(prompts_dir) if prompts_dir else _PROMPTS_DIR
        self._cache: dict[str, str] = {}

    # -- Fragment I/O -------------------------------------------------------

    def load_fragment(self, relative_path: str) -> str:
        """Load a fragment file and cache it.

        Args:
            relative_path: Path relative to the prompts directory
                           (e.g. ``"system/identity.md"``).

        Returns:
            Raw file content as a string.

        Raises:
            FileNotFoundError: If the fragment file does not exist.
        """
        if relative_path in self._cache:
            return self._cache[relative_path]

        full_path = self._dir / relative_path
        if not full_path.is_file():
            raise FileNotFoundError(f"Prompt fragment not found: {full_path}")

        content = full_path.read_text(encoding="utf-8")
        self._cache[relative_path] = content
        return content

    def render_fragment(self, relative_path: str, variables: dict[str, Any] | None = None) -> str:
        """Load a fragment and substitute ``$variable`` placeholders.

        Uses :meth:`string.Template.safe_substitute` so that undefined
        variables are left as-is (e.g. LaTeX ``$\\theta`` passes through).

        Args:
            relative_path: Path relative to the prompts directory.
            variables: Mapping of variable names to values.

        Returns:
            Rendered fragment string.
        """
        raw = self.load_fragment(relative_path)
        if not variables:
            return raw
        return Template(raw).safe_substitute(variables)

    def list_fragments(self) -> list[str]:
        """Return a sorted list of all ``.md`` fragment paths (relative)."""
        results: list[str] = []
        for root, _dirs, files in os.walk(self._dir):
            for fname in files:
                if fname.endswith(".md"):
                    rel = os.path.relpath(os.path.join(root, fname), self._dir)
                    results.append(rel)
        results.sort()
        return results

    def validate_fragments(self) -> list[str]:
        """Check all fragment files for issues.

        Returns:
            List of warning messages (empty if everything is fine).
        """
        warnings: list[str] = []
        for frag in self.list_fragments():
            content = self.load_fragment(frag)
            if not content.strip():
                warnings.append(f"Empty fragment: {frag}")
        return warnings

    def clear_cache(self) -> None:
        """Clear the in-memory fragment cache."""
        self._cache.clear()

    # -- Composition --------------------------------------------------------

    def compose(
        self,
        *,
        memory_context: str = "",
        subagent_section: str = "",
        subagent_thinking: str = "",
        subagent_reminder: str = "",
        tool_policies: str = "",
        skills_section: str = "",
        current_date: str = "",
        extra_variables: dict[str, Any] | None = None,
    ) -> str:
        """Assemble the full system prompt from fragments.

        Section ordering:
        identity -> memory -> thinking_style -> clarification ->
        tool_policies -> skills -> subagent -> working_directory ->
        response_style -> citations -> research_planning ->
        critical_reminders -> current_date

        Args:
            memory_context: Pre-formatted ``<memory>`` block or empty string.
            subagent_section: Pre-formatted ``<subagent_system>`` block or empty.
            subagent_thinking: Thinking bullet for subagent decomposition.
            subagent_reminder: Critical-reminders bullet for subagent mode.
            tool_policies: Pre-formatted ``<tool_usage_policies>`` block or empty.
            skills_section: Pre-formatted ``<skill_system>`` block or empty.
            current_date: Formatted date string for ``<current_date>`` tag.
            extra_variables: Additional template variables merged with defaults.

        Returns:
            Complete system prompt string.
        """
        # Merge variables
        variables = dict(DEFAULT_VARIABLES)
        if extra_variables:
            variables.update(extra_variables)

        # Dynamic variables injected into fragments
        variables["subagent_thinking"] = subagent_thinking
        variables["subagent_reminder"] = subagent_reminder

        sections: list[str] = []

        # 1. Identity
        sections.append(self.render_fragment("system/identity.md", variables))

        # 2. Memory (pass-through, may be empty)
        if memory_context.strip():
            sections.append(memory_context)

        # 3. Thinking style
        sections.append(self.render_fragment("system/thinking_style.md", variables))

        # 4. Clarification rules
        sections.append(self.render_fragment("system/clarification_rules.md", variables))

        # 5. Tool policies (pass-through)
        if tool_policies.strip():
            sections.append(tool_policies)

        # 6. Skills (pass-through)
        if skills_section.strip():
            sections.append(skills_section)

        # 7. Subagent (pass-through)
        if subagent_section.strip():
            sections.append(subagent_section)

        # 8. Working directory
        sections.append(self.render_fragment("context/working_directory.md", variables))

        # 9. Response style
        sections.append(self.render_fragment("system/response_style.md", variables))

        # 10. Citations
        sections.append(self.render_fragment("research/citation_rules.md", variables))

        # 11. Research planning
        sections.append(self.render_fragment("research/planning.md", variables))

        # 12. Critical reminders
        sections.append(self.render_fragment("system/critical_reminders.md", variables))

        # 13. Current date
        if current_date:
            sections.append(f"<current_date>{current_date}</current_date>")

        return "\n\n".join(s for s in sections if s.strip())
