import asyncio
import hashlib
import json
from typing import Literal

from langchain.tools import tool

from deerflow.authz.principal import build_principal_from_context
from deerflow.runtime.user_context import get_current_user, resolve_runtime_user_id
from deerflow.tools.types import Runtime

from .access import authorize, make_store
from .providers import EnterpriseError
from .runtime import schedule_message
from .service import EnterpriseService


@tool(parse_docstring=True)
async def enterprise_messaging(
    runtime: Runtime,
    action: Literal["list", "send", "schedule"],
    target_id: str = "",
    content: str = "",
    schedule_type: Literal["once", "cron"] = "once",
    run_at: str = "",
    cron: str = "",
    timezone: str = "Asia/Shanghai",
) -> str:
    """List the user's enterprise groups, send a message, or schedule a fixed message.

    Use only when the user explicitly requests sending or scheduling. List targets
    first and match the exact group name; ask if ambiguous or absent. Never guess
    IDs or request credentials in chat: bind groups on /workspace/enterprise.
    Clarify missing message/time before scheduling. Never auto-retry delivery
    failures or unknown/sending status. A sent receipt confirms provider acceptance,
    not that members have read it. Scheduled jobs appear under Scheduled tasks.
    Message text is limited to 2048 UTF-8 bytes. Use enterprise_mail for email reading.

    Args:
        action: list available destinations, send now, or schedule a fixed message.
        target_id: Exact destination ID returned by list.
        content: Exact message authorized by the user. No additional instructions.
        schedule_type: once for one time, cron for recurring messages.
        run_at: For once, an ISO timestamp with UTC offset, e.g. 2026-10-20T09:00:00+08:00.
        cron: For cron, a five-field expression, e.g. 0 9 * * 1-5 for weekday 9am.
        timezone: IANA timezone; default Asia/Shanghai.
    """
    try:
        context = dict(runtime.context or {})
        context["user_id"] = resolve_runtime_user_id(runtime)
        current = get_current_user()
        if current is not None:
            if str(current.id) != context["user_id"]:
                raise EnterpriseError("access_denied")
            context["user_role"] = getattr(current, "system_role", None) or context.get("user_role", "user")
        principal = build_principal_from_context(context, default_role="user")
        config = await authorize(principal)
        store = make_store(config)
        owner = principal.user_id
        if action == "list":
            return json.dumps({"targets": await asyncio.to_thread(store.list_targets, owner)}, ensure_ascii=False)
        run_id = context.get("run_id")
        if not run_id:
            raise EnterpriseError("run_required")
        # A duplicate tool call within the same run cannot send twice, even if
        # the model generates a new tool_call_id. A new user turn is a new run.
        payload = [action, target_id, content, schedule_type, run_at, cron, timezone] if action == "schedule" else [action, target_id, content]
        key = f"run:{run_id}:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
        if action == "send":
            result = await EnterpriseService(store).send(owner, target_id, content, key)
        else:
            if context.get("non_interactive"):
                raise EnterpriseError("nested_schedule_disabled")
            result = await schedule_message(
                principal=principal, target_id=target_id, content=content, request_key=key, schedule_type=schedule_type, schedule_spec={"run_at": run_at} if schedule_type == "once" else {"cron": cron}, timezone=timezone
            )
            result = {"task_id": result["id"], "status": result["status"], "next_run_at": result["next_run_at"], "timezone": result["timezone"]}
        return json.dumps(result, ensure_ascii=False)
    except EnterpriseError as exc:
        return json.dumps({"error": exc.code, "sent": False})
