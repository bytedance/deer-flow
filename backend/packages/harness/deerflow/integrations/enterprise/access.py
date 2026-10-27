import asyncio

from deerflow.authz.provider import AuthzDecision, AuthzRequest
from deerflow.authz.runtime import construct_authorization_provider, resolve_authorization_provider_spec
from deerflow.config import get_app_config

from .providers import EnterpriseError
from .store import EnterpriseStore

TOOL_USE = "deerflow.integrations.enterprise.tools:enterprise_messaging"


async def authorize(principal, *, schedule=False, tool_name="enterprise_messaging"):
    if not principal.user_id or principal.user_id == "default" or principal.role not in {"admin", "user"}:
        raise EnterpriseError("access_denied")
    config = await asyncio.to_thread(get_app_config)
    expected = {
        "enterprise_messaging": TOOL_USE,
        "enterprise_mail": "deerflow.integrations.enterprise.mail_tool:enterprise_mail",
        "enterprise_mail_compose": "deerflow.integrations.enterprise.mail_compose_tool:enterprise_mail_compose",
    }.get(tool_name)
    tool = config.get_tool_config(tool_name)
    if expected is None or tool is None or tool.use != expected:
        raise EnterpriseError("not_configured")
    if config.scheduler.multi_instance:
        raise EnterpriseError("single_node_required")
    if config.authorization.enabled:
        requests = [AuthzRequest(principal=principal, resource="tool", action="call", target=tool_name)]
        if schedule:
            requests.extend(AuthzRequest(principal=principal, resource="route", action=target.split(":")[1], target=target) for target in ("threads:write", "runs:create"))
        try:
            spec = await asyncio.to_thread(resolve_authorization_provider_spec, config.authorization)
            provider = construct_authorization_provider(spec, config.authorization)
            for request in requests:
                decision = await provider.aauthorize(request)
                if not isinstance(decision, AuthzDecision) or not decision.allow:
                    raise EnterpriseError("access_denied")
        except asyncio.CancelledError:
            raise
        except Exception:
            raise EnterpriseError("access_denied") from None
    return config


def make_store(config):
    auth = config.authorization
    path = auth.provider.config.get("store_path") if auth.provider else None
    return EnterpriseStore(path)
