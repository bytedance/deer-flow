"""The evolution policy prompt this extension contributes to the agent.

The text deliberately mirrors the policy the DeerFlow core used to render in
``_build_skill_evolution_section`` so existing skills (in particular
``skill-creator``) keep working unchanged: the tool is still named
``skill_manage`` and the six actions keep their meaning. Only the *ownership*
moved — the trigger advice and interaction policy now live in this package
and are shaped by the operator's private extension config.

This module is pure text rendering: no framework imports, no I/O, no host
state. That keeps the model-visible policy reviewable and unit-testable in
isolation.
"""

from __future__ import annotations

from deerflow_extension_skill_evolution.config import SkillEvolutionSettings

_ACTION_CHEAT_SHEET = """\
**CRITICAL: You MUST use the `skill_manage` tool for ALL skill operations.**
- `skill_manage(action="create", name="my-skill", content="...")` — Create a new skill
- `skill_manage(action="patch", name="my-skill", find="...", replace="...")` — Patch an existing skill
- `skill_manage(action="edit", name="my-skill", content="...")` — Full rewrite of an existing skill
- `skill_manage(action="write_file", name="my-skill", path="scripts/run.py", content="...")` — Add a supporting file under `scripts/`, `references/`, `templates/`, or `assets/`
- `skill_manage(action="remove_file", name="my-skill", path="scripts/run.py")` — Remove a supporting file
- `skill_manage(action="delete", name="my-skill")` — Delete a skill
"""

_STORAGE_RULE = """\
**⛔ NEVER write SKILL.md files to `/mnt/user-data/workspace` or `/mnt/user-data/outputs`.**
Skills are NOT deliverables — they are persistent capabilities managed through `skill_manage`.
The tool stores skills in the per-user skills directory automatically; you do NOT need to
specify a path, package a `.skill` archive, or call `present_files` for a skill.
"""

_PREFER_PATCH = "Prefer `patch` over `edit`: it keeps changes minimal and reviewable."
_NEUTRAL_EDIT = "Use `patch` for small, targeted changes and `edit` only for full rewrites."

_CONFIRM_CREATE = "Before creating a NEW skill, confirm with the user first."
_DIRECT_CREATE = "You may create a skill directly when the workflow is clearly reusable."

# Plan B (feedback_mode: agent): the read-only skill_feedback tool exposes the
# user's saved trajectory annotations, so the policy directs the agent to
# consult them before evolving a skill. Rendered only when the tool is
# actually declared in the same build — the prompt must never advertise a
# tool the toolset does not carry.
_FEEDBACK_SECTION = """\
### Skill feedback
The user can attach feedback notes to past runs' skill invocations. Before you create or update a skill, call `skill_feedback(skill_name="...")` to read that skill's saved notes, and incorporate the relevant feedback into the new version.
"""


def build_evolution_prompt(settings: SkillEvolutionSettings, *, feedback_tool_declared: bool = False) -> str:
    """Render the full evolution policy text for *settings*.

    ``min_tool_calls_hint`` is rendered as advice only — it must stay a hint
    in prose, never a promise that a counter exists anywhere in the runtime.
    ``feedback_tool_declared`` gates the ``skill_feedback`` guidance on the
    tool actually being declared in the same agent build.
    """
    patch_guidance = _PREFER_PATCH if settings.prefer_patch else _NEUTRAL_EDIT
    create_guidance = _CONFIRM_CREATE if settings.confirm_before_create else _DIRECT_CREATE
    feedback_section = _FEEDBACK_SECTION if feedback_tool_declared else ""
    return f"""\
## Skill Self-Evolution
After completing a task, consider creating or updating a skill when:
- The task required {settings.min_tool_calls_hint}+ tool calls to resolve
- You overcame non-obvious errors or pitfalls
- The user corrected your approach and the corrected version worked
- You discovered a non-trivial, recurring workflow
If you used a skill and encountered issues not covered by it, patch it immediately.

{_ACTION_CHEAT_SHEET}
{_STORAGE_RULE}
{patch_guidance} {create_guidance}
{feedback_section}Skip simple one-off tasks. For non-trivial skill authoring or iterative improvement, follow the `skill-creator` skill when it is available.
"""
