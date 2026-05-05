"""update_agent tool — let a custom agent persist updates to its own SOUL.md / config.

Bound to the lead agent only when ``runtime.context['agent_name']`` is set
(i.e. inside an existing custom agent's chat). The default agent does not see
this tool, and the bootstrap flow continues to use ``setup_agent`` for the
initial creation handshake.

The tool writes back to ``{base_dir}/users/{user_id}/agents/{agent_name}/{config.yaml,SOUL.md}``
so an agent created by one user is never visible to (or mutable by) another.
Writes are staged into temp files first; both files are renamed into place only
after both temp files are successfully written, so a partial failure cannot leave
config.yaml updated while SOUL.md still holds stale content.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from deerflow.config.agents_config import load_agent_config, validate_agent_name
from deerflow.config.app_config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


def _stage_temp(path: Path, text: str) -> Path:
    """Write ``text`` into a sibling temp file and return its path.

    The caller is responsible for ``Path.replace``-ing the temp into the target
    once every staged file is ready, or for unlinking it on failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        fd.write(text)
        fd.flush()
        fd.close()
        return Path(fd.name)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise


def _cleanup_temps(temps: list[Path]) -> None:
    """Best-effort removal of staged temp files."""
    for tmp in temps:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to clean up temp file %s", tmp, exc_info=True)


@tool
def update_agent(
    runtime: ToolRuntime,
    soul: str | None = None,
    description: str | None = None,
    skills: list[str] | None = None,
    tool_groups: list[str] | None = None,
    model: str | None = None,
) -> Command:
    """Persist updates to the current custom agent's SOUL.md and config.yaml.

    Use this when the user asks to refine the agent's identity, description,
    skill whitelist, tool-group whitelist, or default model. Only the fields
    you explicitly pass are updated; omitted fields keep their existing values.

    Pass ``soul`` as the FULL replacement SOUL.md content — there is no patch
    semantics, so always start from the current SOUL and apply your edits.

    Pass ``skills=[]`` to disable all skills for this agent. Omit ``skills``
    entirely to keep the existing whitelist.

    Args:
        soul: Optional full replacement SOUL.md content.
        description: Optional new one-line description.
        skills: Optional skill whitelist. ``[]`` = no skills, omit = unchanged.
        tool_groups: Optional tool-group whitelist. ``[]`` = empty, omit = unchanged.
        model: Optional model override (must match a configured model name).

    Returns:
        Command with a ToolMessage describing the result. Changes take effect
        on the next user turn (when the lead agent is rebuilt with the fresh
        SOUL.md and config.yaml).
    """
    tool_call_id = runtime.tool_call_id
    agent_name_raw: str | None = runtime.context.get("agent_name") if runtime.context else None

    def _err(message: str) -> Command:
        return Command(update={"messages": [ToolMessage(content=f"Error: {message}", tool_call_id=tool_call_id)]})

    if soul is None and description is None and skills is None and tool_groups is None and model is None:
        return _err("No fields provided. Pass at least one of: soul, description, skills, tool_groups, model.")

    try:
        agent_name = validate_agent_name(agent_name_raw)
    except ValueError as e:
        return _err(str(e))

    if not agent_name:
        return _err("update_agent is only available inside a custom agent's chat. There is no agent_name in the current runtime context, so there is nothing to update. If you are inside the bootstrap flow, use setup_agent instead.")

    # Resolve the active user so that updates only affect this user's agent.
    # ``get_effective_user_id`` returns DEFAULT_USER_ID when no auth context
    # is set (matching how memory and thread storage behave).
    user_id = get_effective_user_id()

    # Reject an unknown ``model`` *before* touching the filesystem. Otherwise
    # ``_resolve_model_name`` silently falls back to the default at runtime
    # and the user sees confusing repeated warnings on every later turn.
    if model is not None and get_app_config().get_model_config(model) is None:
        return _err(f"Unknown model '{model}'. Pass a model name that exists in config.yaml's models section.")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, agent_name)
    if not agent_dir.exists() and paths.agent_dir(agent_name).exists():
        return _err(f"Agent '{agent_name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before updating.")

    try:
        existing_cfg = load_agent_config(agent_name, user_id=user_id)
    except FileNotFoundError:
        return _err(f"Agent '{agent_name}' does not exist for the current user. Use setup_agent to create a new agent first.")
    except ValueError as e:
        return _err(f"Agent '{agent_name}' has an unreadable config: {e}")

    if existing_cfg is None:
        return _err(f"Agent '{agent_name}' could not be loaded.")

    updated_fields: list[str] = []

    # Force the on-disk ``name`` to match the directory we are writing into,
    # even if ``existing_cfg.name`` had drifted (e.g. from manual yaml edits).
    config_data: dict[str, Any] = {"name": agent_name}
    new_description = description if description is not None else existing_cfg.description
    config_data["description"] = new_description
    if description is not None and description != existing_cfg.description:
        updated_fields.append("description")

    new_model = model if model is not None else existing_cfg.model
    if new_model is not None:
        config_data["model"] = new_model
    if model is not None and model != existing_cfg.model:
        updated_fields.append("model")

    new_tool_groups = tool_groups if tool_groups is not None else existing_cfg.tool_groups
    if new_tool_groups is not None:
        config_data["tool_groups"] = new_tool_groups
    if tool_groups is not None and tool_groups != existing_cfg.tool_groups:
        updated_fields.append("tool_groups")

    new_skills = skills if skills is not None else existing_cfg.skills
    if new_skills is not None:
        config_data["skills"] = new_skills
    if skills is not None and skills != existing_cfg.skills:
        updated_fields.append("skills")

    config_changed = bool({"description", "model", "tool_groups", "skills"} & set(updated_fields))

    # Stage every file we intend to rewrite into a temp sibling. Only after
    # *all* temp files exist do we rename them into place — so a failure on
    # SOUL.md cannot leave config.yaml already replaced.
    pending: list[tuple[Path, Path]] = []
    staged_temps: list[Path] = []

    try:
        agent_dir.mkdir(parents=True, exist_ok=True)

        if config_changed:
            yaml_text = yaml.dump(config_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            config_target = agent_dir / "config.yaml"
            config_tmp = _stage_temp(config_target, yaml_text)
            staged_temps.append(config_tmp)
            pending.append((config_tmp, config_target))

        if soul is not None:
            soul_target = agent_dir / "SOUL.md"
            soul_tmp = _stage_temp(soul_target, soul)
            staged_temps.append(soul_tmp)
            pending.append((soul_tmp, soul_target))
            updated_fields.append("soul")

        # Commit phase. ``Path.replace`` is atomic per file on POSIX/NTFS and
        # the staging step above means any earlier failure has already been
        # reported. The remaining failure mode is a crash *between* two
        # ``replace`` calls, which is reported via the partial-write error
        # branch below so the caller knows which files are now on disk.
        committed: list[Path] = []
        try:
            for tmp, target in pending:
                tmp.replace(target)
                committed.append(target)
        except Exception as e:
            _cleanup_temps([t for t, _ in pending if t not in committed])
            if committed:
                logger.error(
                    "[update_agent] Partial write for agent '%s' (user=%s): committed=%s, failed during rename: %s",
                    agent_name,
                    user_id,
                    [p.name for p in committed],
                    e,
                    exc_info=True,
                )
                return _err(f"Partial update for agent '{agent_name}': {[p.name for p in committed]} were updated, but the rest failed ({e}). Re-run update_agent to retry the remaining fields.")
            raise

    except Exception as e:
        _cleanup_temps(staged_temps)
        logger.error("[update_agent] Failed to update agent '%s' (user=%s): %s", agent_name, user_id, e, exc_info=True)
        return _err(f"Failed to update agent '{agent_name}': {e}")

    if not updated_fields:
        return Command(update={"messages": [ToolMessage(content=f"No changes applied to agent '{agent_name}'. The provided values matched the existing config.", tool_call_id=tool_call_id)]})

    logger.info("[update_agent] Updated agent '%s' (user=%s) fields: %s", agent_name, user_id, updated_fields)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(f"Agent '{agent_name}' updated successfully. Changed: {', '.join(updated_fields)}. The new configuration takes effect on the next user turn."),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )
