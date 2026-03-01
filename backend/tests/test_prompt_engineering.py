"""Comprehensive tests for modular system prompt engineering.

Covers fragment existence, content validation, PromptComposer behaviour,
instruction intensity audit, backward compatibility, and full pipeline assembly.
"""

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "agents" / "lead_agent" / "prompts"

REQUIRED_FRAGMENTS = [
    "system/identity.md",
    "system/thinking_style.md",
    "system/clarification_rules.md",
    "system/response_style.md",
    "system/critical_reminders.md",
    "context/working_directory.md",
    "research/citation_rules.md",
    "research/planning.md",
]


def _load_fragment(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


# =========================================================================
# 1. Fragment Existence
# =========================================================================


class TestPromptFragmentsExist:
    """All required .md fragment files must exist and have content."""

    @pytest.mark.parametrize("fragment", REQUIRED_FRAGMENTS)
    def test_fragment_exists_and_nonempty(self, fragment: str):
        path = PROMPTS_DIR / fragment
        assert path.is_file(), f"Missing fragment: {fragment}"
        content = path.read_text(encoding="utf-8")
        assert content.strip(), f"Empty fragment: {fragment}"


# =========================================================================
# 2. Fragment Content
# =========================================================================


class TestFragmentContent:
    """Validate that each fragment contains expected structural elements."""

    def test_identity_has_role_tag(self):
        content = _load_fragment("system/identity.md")
        assert "<role>" in content
        assert "DeerFlow" in content

    def test_thinking_style_has_tag_and_variable(self):
        content = _load_fragment("system/thinking_style.md")
        assert "<thinking_style>" in content
        assert "$subagent_thinking" in content

    def test_clarification_has_examples(self):
        content = _load_fragment("system/clarification_rules.md")
        example_count = content.count("<example")
        assert example_count >= 3, f"Expected >=3 <example> tags, found {example_count}"

    def test_clarification_has_positive_example(self):
        """At least one example should show 'no clarification needed'."""
        content = _load_fragment("system/clarification_rules.md")
        assert "no clarification needed" in content.lower() or "proceed directly" in content.lower()

    def test_clarification_shows_reasoning(self):
        content = _load_fragment("system/clarification_rules.md")
        assert "Agent thinking:" in content or "thinking:" in content

    def test_citation_rules_has_format(self):
        content = _load_fragment("research/citation_rules.md")
        assert "[citation:" in content

    def test_citation_rules_has_quality_standards(self):
        content = _load_fragment("research/citation_rules.md")
        assert "quality" in content.lower() or "Quality" in content

    def test_research_planning_has_tag(self):
        content = _load_fragment("research/planning.md")
        assert "<research_planning>" in content

    def test_research_planning_has_numbered_steps(self):
        content = _load_fragment("research/planning.md")
        assert "1." in content and "2." in content and "3." in content

    def test_research_planning_mentions_reflect_and_synthesize(self):
        content = _load_fragment("research/planning.md")
        assert "Reflect" in content
        assert "Synthesize" in content

    def test_working_directory_has_paths(self):
        content = _load_fragment("context/working_directory.md")
        for path_var in ["$uploads_dir", "$workspace_dir", "$outputs_dir"]:
            assert path_var in content, f"Missing variable {path_var} in working_directory.md"

    def test_response_style_has_latex(self):
        content = _load_fragment("system/response_style.md")
        assert "LaTeX" in content or "latex" in content or "$$" in content

    def test_response_style_has_tag(self):
        content = _load_fragment("system/response_style.md")
        assert "<response_style>" in content

    def test_critical_reminders_has_variable(self):
        content = _load_fragment("system/critical_reminders.md")
        assert "$subagent_reminder" in content


# =========================================================================
# 3. PromptComposer Unit Tests
# =========================================================================


class TestPromptComposer:
    """Test the PromptComposer class methods."""

    def _make_composer(self):
        from src.agents.lead_agent.prompts.composer import PromptComposer
        return PromptComposer()

    def test_compose_returns_nonempty(self):
        composer = self._make_composer()
        result = composer.compose(current_date="2026-02-28, Saturday")
        assert isinstance(result, str)
        assert len(result) > 100

    def test_compose_includes_identity(self):
        composer = self._make_composer()
        result = composer.compose(current_date="2026-02-28, Saturday")
        assert "<role>" in result
        assert "DeerFlow" in result

    def test_compose_includes_date(self):
        composer = self._make_composer()
        result = composer.compose(current_date="2026-02-28, Saturday")
        assert "<current_date>2026-02-28, Saturday</current_date>" in result

    def test_compose_omits_empty_sections(self):
        """Empty pass-through sections should not produce extra blank lines."""
        composer = self._make_composer()
        result = composer.compose(current_date="2026-01-01, Wednesday")
        # No quadruple newlines (would indicate empty sections)
        assert "\n\n\n\n" not in result

    def test_compose_includes_memory_when_provided(self):
        composer = self._make_composer()
        result = composer.compose(memory_context="<memory>\ntest facts\n</memory>", current_date="2026-01-01, Wednesday")
        assert "<memory>" in result
        assert "test facts" in result

    def test_compose_excludes_memory_when_empty(self):
        composer = self._make_composer()
        result = composer.compose(memory_context="", current_date="2026-01-01, Wednesday")
        assert "<memory>" not in result

    def test_compose_passes_through_tool_policies(self):
        composer = self._make_composer()
        policies = "<tool_usage_policies>test policies</tool_usage_policies>"
        result = composer.compose(tool_policies=policies, current_date="2026-01-01, Wednesday")
        assert "test policies" in result

    def test_compose_passes_through_subagent_section(self):
        composer = self._make_composer()
        subagent = "<subagent_system>subagent content</subagent_system>"
        result = composer.compose(subagent_section=subagent, current_date="2026-01-01, Wednesday")
        assert "<subagent_system>" in result
        assert "subagent content" in result

    def test_render_fragment_substitutes_variables(self):
        composer = self._make_composer()
        result = composer.render_fragment("context/working_directory.md", {"uploads_dir": "/custom/uploads", "workspace_dir": "/custom/workspace", "outputs_dir": "/custom/outputs"})
        assert "/custom/uploads" in result
        assert "$uploads_dir" not in result

    def test_render_fragment_safe_substitute_leaves_undefined(self):
        composer = self._make_composer()
        result = composer.render_fragment("system/thinking_style.md", {})
        # $subagent_thinking should remain because it's not in variables
        assert "$subagent_thinking" in result

    def test_load_fragment_caches(self):
        composer = self._make_composer()
        first = composer.load_fragment("system/identity.md")
        second = composer.load_fragment("system/identity.md")
        assert first is second  # Same object from cache

    def test_load_fragment_raises_on_missing(self):
        composer = self._make_composer()
        with pytest.raises(FileNotFoundError):
            composer.load_fragment("nonexistent/fragment.md")

    def test_list_fragments_returns_all(self):
        composer = self._make_composer()
        fragments = composer.list_fragments()
        assert len(fragments) >= 8
        assert all(f.endswith(".md") for f in fragments)

    def test_clear_cache_empties(self):
        composer = self._make_composer()
        composer.load_fragment("system/identity.md")
        assert len(composer._cache) > 0
        composer.clear_cache()
        assert len(composer._cache) == 0

    def test_section_ordering(self):
        """Verify relative ordering of key sections in the composed prompt."""
        composer = self._make_composer()
        result = composer.compose(
            memory_context="<memory>facts</memory>",
            tool_policies="<tool_usage_policies>policies</tool_usage_policies>",
            subagent_section="<subagent_system>sub</subagent_system>",
            current_date="2026-01-01, Wednesday",
        )

        ordered_markers = [
            "<role>",             # identity
            "<memory>",           # memory
            "<thinking_style>",   # thinking
            "<clarification",     # clarification
            "<tool_usage_policies>",  # tool policies
            "<subagent_system>",  # subagent
            "<working_directory", # working directory
            "<response_style>",   # response style
            "<citations>",        # citations
            "<research_planning>",  # research planning
            "<critical_reminders>",  # reminders
            "<current_date>",     # date
        ]

        positions = []
        for marker in ordered_markers:
            pos = result.find(marker)
            assert pos != -1, f"Marker not found in output: {marker}"
            positions.append(pos)

        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Section order violation: {ordered_markers[i]} (pos {positions[i]}) "
                f"should come before {ordered_markers[i + 1]} (pos {positions[i + 1]})"
            )


# =========================================================================
# 4. Instruction Intensity Audit
# =========================================================================


class TestInstructionIntensityAudit:
    """Verify intensity hierarchy: ALL CAPS reserved for safety-critical subagent constraints."""

    # Fragments that are NOT the subagent section (which keeps CAPS for safety)
    NON_SAFETY_FRAGMENTS = [
        "system/identity.md",
        "system/thinking_style.md",
        "system/clarification_rules.md",
        "system/response_style.md",
        "system/critical_reminders.md",
        "context/working_directory.md",
        "research/citation_rules.md",
        "research/planning.md",
    ]

    def _get_allowed_caps(self) -> set[str]:
        from src.agents.lead_agent.prompts.composer import Intensity
        return Intensity.ALLOWED_ACRONYMS | Intensity.RESERVED_CAPS_PHRASES

    def test_no_all_caps_in_non_safety_fragments(self):
        """Non-safety fragments should not use ALL CAPS words (except technical acronyms)."""
        allowed = self._get_allowed_caps()
        # Pattern: standalone words of 2+ uppercase letters
        caps_pattern = re.compile(r"\b([A-Z]{2,})\b")

        violations = []
        for frag in self.NON_SAFETY_FRAGMENTS:
            content = _load_fragment(frag)
            for match in caps_pattern.finditer(content):
                word = match.group(1)
                if word not in allowed:
                    violations.append(f"{frag}: '{word}'")

        assert not violations, f"ALL CAPS words in non-safety fragments: {violations}"

    def test_critical_reminders_no_always_caps(self):
        """critical_reminders should use 'Always' not 'ALWAYS'."""
        content = _load_fragment("system/critical_reminders.md")
        assert "ALWAYS" not in content, "Use 'Always' instead of 'ALWAYS' in critical_reminders"

    def test_validate_fragments_no_empty(self):
        from src.agents.lead_agent.prompts.composer import PromptComposer
        composer = PromptComposer()
        warnings = composer.validate_fragments()
        assert len(warnings) == 0, f"Fragment validation warnings: {warnings}"


# =========================================================================
# 5. Backward Compatibility (Integration)
# =========================================================================


class TestApplyPromptTemplateBackwardCompat:
    """Verify apply_prompt_template() still works with the same API."""

    def _call_apply(self, **kwargs):
        with patch("src.agents.lead_agent.prompt._get_memory_context", return_value=""), \
             patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value=""):
            from src.agents.lead_agent.prompt import apply_prompt_template
            return apply_prompt_template(**kwargs)

    def test_returns_string(self):
        result = self._call_apply()
        assert isinstance(result, str)

    def test_contains_role(self):
        result = self._call_apply()
        assert "<role>" in result

    def test_contains_date(self):
        result = self._call_apply()
        assert "<current_date>" in result

    def test_contains_thinking_style(self):
        result = self._call_apply()
        assert "<thinking_style>" in result

    def test_contains_clarification(self):
        result = self._call_apply()
        assert "<clarification_system>" in result

    def test_contains_working_directory(self):
        result = self._call_apply()
        assert "<working_directory" in result

    def test_contains_response_style(self):
        result = self._call_apply()
        assert "<response_style>" in result

    def test_contains_citations(self):
        result = self._call_apply()
        assert "<citations>" in result

    def test_contains_research_planning(self):
        result = self._call_apply()
        assert "<research_planning>" in result

    def test_contains_critical_reminders(self):
        result = self._call_apply()
        assert "<critical_reminders>" in result

    def test_subagent_disabled_omits_subagent_system(self):
        result = self._call_apply(subagent_enabled=False)
        assert "<subagent_system>" not in result

    def test_subagent_enabled_includes_subagent_system(self):
        result = self._call_apply(subagent_enabled=True, max_concurrent_subagents=5)
        assert "<subagent_system>" in result
        assert "MAXIMUM 5" in result

    def test_tool_policies_injection(self):
        result = self._call_apply(tool_policies="<tool_usage_policies>custom</tool_usage_policies>")
        assert "custom" in result

    def test_api_signature_unchanged(self):
        from src.agents.lead_agent.prompt import apply_prompt_template
        sig = inspect.signature(apply_prompt_template)
        params = list(sig.parameters.keys())
        assert "subagent_enabled" in params
        assert "max_concurrent_subagents" in params
        assert "thinking_enabled" in params
        assert "tool_policies" in params


# =========================================================================
# 6. Full Pipeline (Integration)
# =========================================================================


class TestFullPromptAssemblyPipeline:
    """End-to-end assembly tests."""

    def _full_prompt(self, **kwargs):
        defaults = {
            "subagent_enabled": True,
            "max_concurrent_subagents": 3,
            "thinking_enabled": True,
            "tool_policies": "<tool_usage_policies>test</tool_usage_policies>",
        }
        defaults.update(kwargs)
        with patch("src.agents.lead_agent.prompt._get_memory_context", return_value="<memory>\ntest\n</memory>"), \
             patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value="<skill_system>\ntest skills\n</skill_system>"):
            from src.agents.lead_agent.prompt import apply_prompt_template
            return apply_prompt_template(**defaults)

    def test_full_assembly_all_sections(self):
        result = self._full_prompt()
        expected_tags = [
            "<role>",
            "<memory>",
            "<thinking_style>",
            "<clarification_system>",
            "<tool_usage_policies>",
            "<skill_system>",
            "<subagent_system>",
            "<working_directory",
            "<response_style>",
            "<citations>",
            "<research_planning>",
            "<critical_reminders>",
            "<current_date>",
        ]
        for tag in expected_tags:
            assert tag in result, f"Missing section in full assembly: {tag}"

    def test_minimal_assembly(self):
        """Minimal config: no subagent, no memory, no skills, no policies."""
        with patch("src.agents.lead_agent.prompt._get_memory_context", return_value=""), \
             patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value=""):
            from src.agents.lead_agent.prompt import apply_prompt_template
            result = apply_prompt_template(subagent_enabled=False, tool_policies="")
        assert "<role>" in result
        assert "<thinking_style>" in result
        assert "<subagent_system>" not in result
        assert "<memory>" not in result

    def test_no_unresolved_variables(self):
        """Final output should have no unresolved $variable patterns.

        Exception: LaTeX expressions like $\\theta$ and code examples like
        `$expression$` inside backtick-delimited code blocks are fine.
        """
        result = self._full_prompt()
        # Remove code blocks (``` ... ```) and inline code (` ... `) before checking
        cleaned = re.sub(r"```.*?```", "", result, flags=re.DOTALL)
        cleaned = re.sub(r"`[^`]+`", "", cleaned)
        # Find $word patterns that are NOT LaTeX (not preceded by backslash or another $)
        unresolved = re.findall(r"(?<!\$)(?<!\\)\$([a-z_][a-z0-9_]*)", cleaned)
        assert not unresolved, f"Unresolved variables in final output: {unresolved}"
