"""Shared interaction policy for lead-agent tools and prompt guidance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

ASK_CLARIFICATION_TOOL_NAME = "ask_clarification"


class RunInteractionMode(StrEnum):
    """Interaction modes that can be selected by a trusted run entry point."""

    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"
    WEBHOOK = "webhook"
    SCHEDULED = "scheduled"


_INTERACTIVE_CLARIFICATION_SYSTEM = """<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
1. **FIRST**: Analyze the request in your thinking - identify what's unclear, missing, or ambiguous
2. **SECOND**: If clarification is needed, call `ask_clarification` tool IMMEDIATELY - do NOT start working
3. **THIRD**: Only after all clarifications are resolved, proceed with planning and execution

**CRITICAL RULE: Clarification ALWAYS comes BEFORE action. Never start working and clarify mid-execution.**

**MANDATORY Clarification Scenarios - You MUST call ask_clarification BEFORE starting work when:**

1. **Missing Information** (`missing_info`): Required details not provided
   - Example: User says "create a web scraper" but doesn't specify the target website
   - Example: "Deploy the app" without specifying environment
   - **REQUIRED ACTION**: Call ask_clarification to get the missing information

2. **Ambiguous Requirements** (`ambiguous_requirement`): Multiple valid interpretations exist
   - Example: "Optimize the code" could mean performance, readability, or memory usage
   - Example: "Make it better" is unclear what aspect to improve
   - **REQUIRED ACTION**: Call ask_clarification to clarify the exact requirement

3. **Approach Choices** (`approach_choice`): Several valid approaches exist
   - Example: "Add authentication" could use JWT, OAuth, session-based, or API keys
   - Example: "Store data" could use database, files, cache, etc.
   - **REQUIRED ACTION**: Call ask_clarification to let user choose the approach

4. **Risky Operations** (`risk_confirmation`): Destructive actions need confirmation
   - Example: Deleting files, modifying production configs, database operations
   - Example: Overwriting existing code or data
   - **REQUIRED ACTION**: Call ask_clarification to get explicit confirmation

5. **Suggestions** (`suggestion`): You have a recommendation but want approval
   - Example: "I recommend refactoring this code. Should I proceed?"
   - **REQUIRED ACTION**: Call ask_clarification to get approval

**STRICT ENFORCEMENT:**
- ❌ DO NOT start working and then ask for clarification mid-execution - clarify FIRST
- ❌ DO NOT skip clarification for "efficiency" - accuracy matters more than speed
- ❌ DO NOT make assumptions when information is missing - ALWAYS ask
- ❌ DO NOT proceed with guesses - STOP and call ask_clarification first
- ✅ Analyze the request in thinking → Identify unclear aspects → Ask BEFORE any action
- ✅ If you identify the need for clarification in your thinking, you MUST call the tool IMMEDIATELY
- ✅ After calling ask_clarification, execution will be interrupted automatically
- ✅ Wait for user response - do NOT continue with assumptions

**How to Use:**
```python
ask_clarification(
    question="Your specific question here?",
    clarification_type="missing_info",  # or other type
    context="Why you need this information",  # optional but recommended
    options=["option1", "option2"]  # optional, for choices
)
```

**Example:**
User: "Deploy the application"
You (thinking): Missing environment info - I MUST ask for clarification
You (action): ask_clarification(
    question="Which environment should I deploy to?",
    clarification_type="approach_choice",
    context="I need to know the target environment for proper configuration",
    options=["development", "staging", "production"]
)
[Execution stops - wait for user response]

User: "staging"
You: "Deploying to staging..." [proceed]
</clarification_system>"""

_AUTONOMOUS_CLARIFICATION_SYSTEM = """<clarification_system>
**WORKFLOW PRIORITY: ASSESS -> CHOOSE THE LOWEST-RISK PATH -> ACT**

There is no human available to answer a synchronous question during this run.
Do not wait for clarification or approval. Resolve ambiguity from the request,
{context_sources}.

- For low-risk and reversible work, make the smallest reasonable assumption and continue.
- State every material assumption in the final result.
- For high-risk or irreversible work without sufficient authorization, do not guess:
  stop with a concise structured `BLOCKED` result that names the missing decision.
- Prefer inspection and read-only checks before changing state.
</clarification_system>"""

_AUTONOMOUS_CONTEXT_SOURCES = "the available run context and existing configuration"
_WEBHOOK_CONTEXT_SOURCES = "the issue, pull request, repository, event context, and existing configuration"


@dataclass(frozen=True, slots=True)
class RunInteractionPolicy:
    """The single source for interaction-sensitive tools and prompt guidance."""

    mode: RunInteractionMode

    @property
    def allows_clarification(self) -> bool:
        return self.mode is RunInteractionMode.INTERACTIVE

    @property
    def disabled_tool_names(self) -> frozenset[str]:
        if self.allows_clarification:
            return frozenset()
        return frozenset({ASK_CLARIFICATION_TOOL_NAME})

    @property
    def thinking_guidance(self) -> str:
        if self.allows_clarification:
            return "- **PRIORITY CHECK: If anything is unclear, missing, or has multiple interpretations, you MUST ask for clarification FIRST - do NOT proceed with work**"
        return "- **INTERACTION CHECK: This run has no synchronous human. Resolve ambiguity with the run context, choose the lowest-risk reversible path, and record material assumptions.**"

    @property
    def clarification_system(self) -> str:
        if self.allows_clarification:
            return _INTERACTIVE_CLARIFICATION_SYSTEM
        context_sources = _WEBHOOK_CONTEXT_SOURCES if self.mode is RunInteractionMode.WEBHOOK else _AUTONOMOUS_CONTEXT_SOURCES
        return _AUTONOMOUS_CLARIFICATION_SYSTEM.format(context_sources=context_sources)

    @property
    def clarification_reminder(self) -> str:
        if self.allows_clarification:
            return "- **Clarification First**: ALWAYS clarify unclear/missing/ambiguous requirements BEFORE starting work - never assume or guess"
        return "- **Autonomous Interaction**: Do not wait for a human response; make minimal reversible assumptions, list them, or return a structured `BLOCKED` result for high-risk ambiguity"

    @classmethod
    def interactive(cls) -> RunInteractionPolicy:
        return cls(RunInteractionMode.INTERACTIVE)


def resolve_run_interaction_policy(config: Mapping[str, Any] | None) -> RunInteractionPolicy:
    """Resolve one policy from legacy runtime flags and channel context.

    ``non_interactive`` is the scheduler's trusted legacy flag. GitHub and
    other webhook channels currently use ``disable_clarification`` and/or
    ``channel_name``; both remain supported while callers migrate to an
    explicit mode.
    """

    merged: dict[str, Any] = {}
    if config:
        configurable = config.get("configurable")
        context = config.get("context")
        if isinstance(configurable, Mapping):
            merged.update(configurable)
        if isinstance(context, Mapping):
            merged.update(context)

    raw_mode = merged.get("interaction_mode")
    if raw_mode is not None:
        try:
            return RunInteractionPolicy(RunInteractionMode(str(raw_mode)))
        except ValueError as exc:
            valid_modes = ", ".join(mode.value for mode in RunInteractionMode)
            raise ValueError(f"Invalid interaction_mode {raw_mode!r}; expected one of: {valid_modes}") from exc

    if merged.get("non_interactive"):
        return RunInteractionPolicy(RunInteractionMode.SCHEDULED)
    if merged.get("channel_name") == "github":
        return RunInteractionPolicy(RunInteractionMode.WEBHOOK)
    if merged.get("disable_clarification"):
        return RunInteractionPolicy(RunInteractionMode.AUTONOMOUS)
    return RunInteractionPolicy.interactive()
