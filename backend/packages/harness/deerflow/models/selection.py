"""Resolve direct user model choices without calling a classifier or modifying state.

Only the caller's visible catalog supplies candidates. This deliberately handles
direct controls, not model mentions in documents, quotations or conditional text.
"""

from __future__ import annotations

import re
from typing import Any, Literal

ModelScope = Literal["task", "turn", "conversation"]

_PATTERNS = (
    ("conversation", r"^(?:请)?(?:以后|今后|接下来)(?:这个对话|这段对话|这里)?(?:都|一直|默认)?(?:用|使用|改用|换成)\s*(.+?)(?:模型)?(?:[，。：:]|$)"),
    ("conversation", r"^(?:please\s+)?from now on\s+use\s+(.+?)(?:[,:]|$)"),
    ("task", r"^(?:请|麻烦)?你?(?:找|让|叫)\s*(.+?)\s*(?:去|来)?(?:处理|做|解决|分析|计算|回答|帮我)"),
    ("task", r"^(?:这个|这部分|这件事|这个任务).{0,16}?(?:交给|让)\s*(.+?)\s*(?:去|来)?(?:处理|做|解决|分析|计算|回答)"),
    ("task", r"^(?:please\s+)?(?:ask|delegate to)\s+(.+?)\s+to\s+"),
    ("turn", r"^(?:请)?(?:这次|本次|这一轮)(?:请)?(?:用|使用|改用|换成)\s*(.+?)(?:\s*(?:模型)?(?P<action>帮我|来|去|处理|计算|回答|分析|生成|写|做|[，：:])|$)"),
    ("turn", r"^(?:please\s+)?use\s+(.+?)\s+for this\s+(?:turn|task)\b"),
    (None, r"^(?:请)?(?:用|使用|改用|换成)\s*(.+?)(?:\s*(?:模型)?(?P<action>帮我|来|去|处理|计算|回答|分析|生成|写|做|[，：:])|$)"),
    (None, r"^(?:please\s+)?use\s+(.+?)\s+to\s+"),
)


def _tokens(value: str) -> list[str]:
    # Keep decimal versions intact: 4.1 must not accidentally match 4.10.
    return [part for part in re.findall(r"[a-z]+|\d+(?:\.\d+)*|[\u4e00-\u9fff]+", value.casefold()) if part != "v"]


def _spellings(model: Any) -> list[str]:
    return [value for value in (model.name, model.display_name, model.model, *getattr(model, "aliases", ())) if isinstance(value, str) and value.strip()]


def _matches(query: str, model: Any) -> bool:
    wanted = _tokens(query)
    if not wanted:
        return False
    for spelling in _spellings(model):
        available = _tokens(spelling)
        # CamelCase names such as DeepSeek also admit their initials (ds).
        for word in re.findall(r"[A-Za-z]+", spelling):
            capitals = "".join(re.findall(r"[A-Z]", word))
            if len(capitals) > 1:
                available.append(capitals.casefold())
        if all(any(token == part if token[0].isdigit() else part.startswith(token) for part in available) for token in wanted):
            return True
    return False


def resolve_model_control(text: str, models: list[Any], *, model_name: str | None = None, scope: ModelScope | None = None) -> dict[str, Any]:
    """Return a read-only decision; explicit selections are checked afresh.

    The host must enforce model:use before execution. Visibility is not permission
    to use a model. Text must be the user's direct input, never attachment text.
    """
    result: dict[str, Any] = {"status": "none", "scope": None, "query": "", "model_name": None, "candidates": [], "task_offset": 0}
    if len(text) > 4000 or "\n" in text.split("：", 1)[0].split(":", 1)[0] or text.lstrip().startswith(("`", '"', "“", "'")):
        return result
    for found_scope, pattern in _PATTERNS:
        match = re.match(pattern, text.strip(), re.IGNORECASE)
        if match:
            query = match.group(1).strip()
            break
    else:
        return result
    if model_name is not None:
        candidates = [model for model in models if model.name == model_name]
        if not candidates:
            candidates = [model for model in models if _matches(model_name, model)]
    else:
        candidates = [model for model in models if _matches(query, model)]
    # "Use Python to ..." is an ordinary task. Unknown versioned or explicitly
    # named models, however, must not fall through to a misleading model reply.
    if not candidates and model_name is None and not re.search(r"\bv\d|模型|\bmodel\b", query, re.IGNORECASE):
        return result
    offset = len(text) - len(text.lstrip()) + match.end()
    if match.groupdict().get("action") in {"处理", "计算", "回答", "分析", "生成", "写", "做"}:
        offset = len(text) - len(text.lstrip()) + match.start("action")
    while offset < len(text) and (text[offset].isspace() or text[offset] in "，。：:,"):
        offset += 1
    result.update(scope=scope or found_scope, query=query, candidates=[{"name": m.name, "label": m.display_name or m.name} for m in candidates], task_offset=offset)
    if not candidates:
        result["status"] = "unavailable"
    elif len(candidates) != 1 or result["scope"] is None:
        result["status"] = "ambiguous"
    else:
        result.update(status="resolved", model_name=candidates[0].name)
    return result


def authorize_selected_model(model_name: str, *, context: Any, app_config: Any) -> None:
    """Check an explicit choice without the lead agent's default substitution.

    Run off-loop: provider resolution and authorization can perform blocking I/O.
    Explicit denials reject; provider failures retain the deployment's policy.
    """
    if app_config.get_model_config(model_name) is None:
        raise ValueError("The selected model is not configured.")
    authz = getattr(app_config, "authorization", None)
    if authz is None or authz.enabled is not True:
        return
    from deerflow.authz.principal import build_principal_from_context
    from deerflow.authz.provider import AuthzDecision, AuthzRequest
    from deerflow.authz.runtime import resolve_authorization_provider

    try:
        provider = resolve_authorization_provider(authz)
        if provider is None:
            raise RuntimeError("Authorization provider unavailable")
        principal = build_principal_from_context(context, default_role=authz.default_role)
        decision = provider.authorize(AuthzRequest(principal=principal, resource="model", action="use", target=model_name))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("Invalid authorization result")
    except Exception:
        if authz.fail_closed:
            raise ValueError("Model authorization is unavailable.") from None
        return
    if not decision.allow:
        raise ValueError("The selected model is not available for your role.")


def bind_selected_task_model(tools: list[Any], model_name: str) -> list[Any]:
    """Expose this run's resolved choice in the task parameter, not a prompt.

    Clone both schema and tool: parallel runs must never rewrite the singleton.
    No unfiltered model catalog or provider configuration is exposed.
    """
    from pydantic import Field, create_model

    selected = []
    for tool in tools:
        schema = getattr(tool, "args_schema", None)
        if tool.name != "task" or not isinstance(schema, type) or "model_name" not in schema.model_fields:
            selected.append(tool)
            continue
        selected_schema = create_model(
            "SelectedTaskModel",
            __base__=schema,
            model_name=(Literal[model_name] | None, Field(default=model_name, description="The user's selected model for this child task; the parent model is unchanged.")),
        )
        selected.append(tool.model_copy(update={"args_schema": selected_schema}))
    return selected
