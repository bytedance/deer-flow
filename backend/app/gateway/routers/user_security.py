"""Session-only personal credentials and administrator-managed user tool grants."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from app.gateway.deps import get_current_user_from_request, get_local_provider, require_admin_user
from app.gateway.routers.auth import require_session_source
from deerflow.authz.user_policy import get_user_security_store, user_security_enabled
from deerflow.config.app_config import get_app_config
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.headers import illegal_header_value_reason
from deerflow.security.defaults import is_default_resource


class PrivateInputRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI normally includes raw input in validation errors,
                # even with Pydantic hide_input_in_errors/SecretStr enabled.
                raise HTTPException(422, "Invalid user-security request") from None

        return safe_handler


router = APIRouter(prefix="/api/user-security", tags=["user-security"], dependencies=[Depends(require_session_source)], route_class=PrivateInputRoute)


class CredentialWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    credential: SecretStr


class GrantWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    resource: Literal["tool", "mcp_server", "sandbox", "skill"]
    target: str = Field(min_length=1, max_length=255)
    allowed: bool


class OverrideWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    resource: Literal["tool", "mcp_server", "sandbox", "skill"]
    target: str = Field(min_length=1, max_length=255)
    mode: Literal["inherit", "allow", "deny"]


class GroupWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


class MemberWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class GroupGrantWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: Literal["tool", "mcp_server", "sandbox", "skill"]
    target: str = Field(min_length=1, max_length=255)
    allowed: bool


def _skill_catalog(config, user_id=None):
    from deerflow.runtime.user_context import get_effective_user_id
    from deerflow.security.skill_access import skill_resource_target
    from deerflow.skills.storage import get_or_new_user_skill_storage

    user_id = user_id or get_effective_user_id()
    storage = get_or_new_user_skill_storage(user_id, app_config=config)
    result = []
    for skill in storage.load_skills(enabled_only=False):
        target = skill_resource_target(skill, user_id=user_id)
        if not is_default_resource("skill", target):
            result.append({"resource": "skill", "target": target, "label": skill.name})
    return result


def _catalog_for_user(user_id):
    # Admin may authorize private skill use by its owner without publishing it.
    resources = [item for item in _catalog() if item["resource"] != "skill"]
    return resources + _skill_catalog(get_app_config(), user_id=user_id)


def _catalog():
    from deerflow.mcp.cache import get_cached_mcp_tools
    from deerflow.mcp.personal_auth import validate_personal_server
    from deerflow.tools.builtins import setup_agent, update_agent
    from deerflow.tools.mcp_metadata import get_mcp_source
    from deerflow.tools.tools import get_available_tools

    config = get_app_config()
    vision_model = next((model.name for model in config.models if model.supports_vision), None)
    names = {tool.name for tool in get_available_tools(include_mcp=False, subagent_enabled=True, model_name=vision_model, app_config=config)}
    names.update({setup_agent.name, update_agent.name, "write_todos", "memory_search", "memory_add", "memory_update", "memory_delete"})
    result = [{"resource": "tool", "target": name} for name in sorted(names) if not is_default_resource("tool", name)]
    result.extend(_skill_catalog(config))
    for name, server in ExtensionsConfig.from_file().mcp_servers.items():
        try:
            validate_personal_server(server)
            supported = server.enabled
        except ValueError:
            supported = False
        result.append({"resource": "mcp_server", "target": name, "credential_supported": supported})
    # Discovery is administrator configured, performed off the event loop, and
    # guarded by build_server_params before any stdio subprocess could start.
    for tool in get_cached_mcp_tools():
        source = get_mcp_source(tool)
        if source and not is_default_resource("tool", tool.name):
            result.append({"resource": "tool", "target": tool.name, "server": source["server_name"]})
    return result


async def _enabled():
    if not await asyncio.to_thread(user_security_enabled):
        raise HTTPException(409, "Per-user tool security is not enabled")


async def _store():
    return await asyncio.to_thread(get_user_security_store)


@router.get("/me")
async def personal_status(user=Depends(get_current_user_from_request)):
    enabled = await asyncio.to_thread(user_security_enabled)
    if not enabled:
        return {"enabled": False, "admin": False, "resources": [], "credentials": []}
    store = await _store()
    grants = await asyncio.to_thread(store.grants, str(user.id))
    admin = user.system_role == "admin"
    resources = await asyncio.to_thread(_catalog)
    return {
        "enabled": True,
        "admin": admin,
        "resources": [{**item, "allowed": admin or (item["resource"], item["target"]) in grants} for item in resources],
        "credentials": await asyncio.to_thread(store.credential_status, str(user.id)),
    }


@router.put("/credentials/{server}")
async def save_credential(server: str, body: CredentialWrite, user=Depends(get_current_user_from_request)):
    await _enabled()
    store = await _store()
    resources = await asyncio.to_thread(_catalog)
    entry = next((item for item in resources if item["resource"] == "mcp_server" and item["target"] == server), None)
    if entry is None or not entry.get("credential_supported"):
        raise HTTPException(400, "This server does not support private credentials; ask the administrator to configure HTTP/SSE personal authentication")
    if user.system_role != "admin" and ("mcp_server", server) not in await asyncio.to_thread(store.grants, str(user.id)):
        raise HTTPException(403, "You are not authorized to use this server")
    value = body.credential.get_secret_value()
    if not value or len(value) > 16384 or illegal_header_value_reason(value):
        raise HTTPException(400, "Invalid credential header value")
    await asyncio.to_thread(store.set_credential, str(user.id), server, value)
    return {"configured": True}


@router.delete("/credentials/{server}")
async def remove_credential(server: str, user=Depends(get_current_user_from_request)):
    await _enabled()
    store = await _store()
    # Permit deletion after the server is disabled, removed or access revoked.
    await asyncio.to_thread(store.delete_credential, str(user.id), server)
    return {"configured": False}


async def _target_user(email):
    provider = get_local_provider()
    target = await provider.get_user_by_email(str(email))
    if target is None:
        raise HTTPException(404, "User not found")
    return target


@router.get("/grants")
async def read_grants(request: Request, email: EmailStr):
    await require_admin_user(request, detail="Administrator access required")
    await _enabled()
    target = await _target_user(email)
    store = await _store()
    details = await asyncio.to_thread(store.grant_details, str(target.id))
    resources = await asyncio.to_thread(_catalog_for_user, str(target.id))
    resources = [{**item, "allowed": target.system_role == "admin" or (item["resource"], item["target"]) in details["grants"]} for item in resources]
    return {"email": str(target.email), "admin": target.system_role == "admin", "groups": details["groups"], "resources": resources, **{key: _resource_rows(details[key]) for key in ("grants", "direct_grants", "denied")}}


@router.put("/grants")
async def write_grant(request: Request, body: GrantWrite, user=Depends(get_current_user_from_request)):
    await require_admin_user(request, detail="Administrator access required")
    await _enabled()
    target = await _target_user(body.email)
    if target.system_role == "admin":
        raise HTTPException(400, "Administrator access is controlled by the account role")
    resources = await asyncio.to_thread(_catalog_for_user, str(target.id))
    if body.allowed and not any(item["resource"] == body.resource and item["target"] == body.target for item in resources):
        raise HTTPException(400, "Unknown extension resource")
    store = await _store()
    try:
        await asyncio.to_thread(store.set_grant, str(target.id), body.resource, body.target, body.allowed, actor=str(user.id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"allowed": body.allowed}


def _resource_rows(rows):
    return [{"resource": resource, "target": target} for resource, target in rows]


async def _admin_store(request):
    await require_admin_user(request, detail="Administrator access required")
    await _enabled()
    return await _store()


async def _store_call(method, *args, **kwargs):
    try:
        return await asyncio.to_thread(method, *args, **kwargs)
    except KeyError:
        raise HTTPException(404, "Group not found") from None
    except ValueError as exc:
        raise HTTPException(409 if str(exc) == "Group name already exists" else 400, str(exc)) from None


async def _known_resource(resource, target, user_id=None):
    resources = await asyncio.to_thread(_catalog_for_user, user_id) if user_id else await asyncio.to_thread(_catalog)
    if not any(item["resource"] == resource and item["target"] == target for item in resources):
        raise HTTPException(400, "Unknown extension resource")


@router.put("/overrides")
async def write_override(request: Request, body: OverrideWrite, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    target = await _target_user(body.email)
    if target.system_role == "admin":
        raise HTTPException(400, "Administrator access is controlled by the account role")
    if body.mode != "inherit" and is_default_resource(body.resource, body.target):
        raise HTTPException(400, "Default capabilities do not require permissions")
    if body.mode == "allow":
        await _known_resource(body.resource, body.target, str(target.id))
    await _store_call(store.set_override, str(target.id), body.resource, body.target, body.mode, actor=str(user.id))
    return {"mode": body.mode}


@router.get("/groups")
async def list_groups(request: Request):
    store = await _admin_store(request)
    return {"groups": await _store_call(store.list_groups)}


@router.post("/groups")
async def create_group(request: Request, body: GroupWrite, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    return await _store_call(store.create_group, body.name, actor=str(user.id))


@router.get("/groups/{group_id}")
async def read_group(request: Request, group_id: str):
    store = await _admin_store(request)
    details = await _store_call(store.group_details, group_id)
    provider = get_local_provider()
    members = []
    for user_id in details["members"]:
        member = await provider.get_user(user_id)
        members.append({"id": user_id, "email": str(member.email) if member else None})
    return {**details, "members": members, "grants": _resource_rows(details["grants"])}


@router.patch("/groups/{group_id}")
async def rename_group(request: Request, group_id: str, body: GroupWrite, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    return await _store_call(store.rename_group, group_id, body.name, actor=str(user.id))


@router.delete("/groups/{group_id}")
async def delete_group(request: Request, group_id: str, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    await _store_call(store.delete_group, group_id, actor=str(user.id))
    return {"deleted": True}


@router.post("/groups/{group_id}/members")
async def add_member(request: Request, group_id: str, body: MemberWrite, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    target = await _target_user(body.email)
    await _store_call(store.set_member, group_id, str(target.id), True, actor=str(user.id))
    return {"member": True}


@router.delete("/groups/{group_id}/members/{user_id}")
async def remove_member(request: Request, group_id: str, user_id: str, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    # Stable ID removal also works for a deleted account's stale membership.
    await _store_call(store.set_member, group_id, user_id, False, actor=str(user.id))
    return {"member": False}


@router.put("/groups/{group_id}/grants")
async def write_group_grant(request: Request, group_id: str, body: GroupGrantWrite, user=Depends(get_current_user_from_request)):
    store = await _admin_store(request)
    if body.allowed:
        await _known_resource(body.resource, body.target)
    await _store_call(store.set_group_grant, group_id, body.resource, body.target, body.allowed, actor=str(user.id))
    return {"allowed": body.allowed}
