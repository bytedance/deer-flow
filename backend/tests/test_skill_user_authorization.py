from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.skills.types import Skill, SkillCategory


def skill(name, category=SkillCategory.PUBLIC):
    return Skill(name, "private metadata", None, Path(name), Path(name) / "SKILL.md", Path(name), category, enabled=True)


@pytest.fixture
def policy(tmp_path):
    return SimpleNamespace(authorization=SimpleNamespace(enabled=True, provider=SimpleNamespace(use="deerflow.authz.user_policy:UserAuthorizationProvider", config={"store_path": str(tmp_path)})))


def test_default_public_does_not_exempt_custom_shadow(policy):
    from deerflow.security.skill_access import filter_authorized_skills, skill_resource_target

    token = set_current_user(SimpleNamespace(id="alice", role="user"))
    try:
        public, custom = skill("data-analysis"), skill("data-analysis", SkillCategory.CUSTOM)
        assert skill_resource_target(custom) == "custom:alice:data-analysis"
        assert filter_authorized_skills([public, custom, skill("new-public")], app_config=policy) == [public]
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_runtime_identity_grant_and_revocation(policy):
    from deerflow.security.skill_access import filter_authorized_skills
    from deerflow.security.store import UserSecurityStore

    custom = skill("extra", SkillCategory.CUSTOM)
    runtime = SimpleNamespace(context={"user_id": "alice", "user_role": "user"})
    store = UserSecurityStore(policy.authorization.provider.config["store_path"])
    assert filter_authorized_skills([custom], app_config=policy, runtime=runtime) == []
    store.set_grant("alice", "skill", "custom:alice:extra", True, actor="admin")
    assert filter_authorized_skills([custom], app_config=policy, runtime=runtime) == [custom]
    store.set_grant("alice", "skill", "custom:alice:extra", False, actor="admin")
    assert filter_authorized_skills([custom], app_config=policy, runtime=runtime) == []
    assert filter_authorized_skills([skill("data-analysis")], app_config=policy, user_id="alice") == []
    assert filter_authorized_skills([custom], app_config=policy, runtime=runtime, user_id="bob") == []


def test_server_user_role_and_scheduled_owner_runtime(policy):
    from deerflow.security.skill_access import filter_authorized_skills

    private = skill("extra")
    token = set_current_user(SimpleNamespace(id="alice", system_role="admin"))
    try:
        assert filter_authorized_skills([private], app_config=policy) == [private]
    finally:
        reset_current_user(token)

    token = set_current_user(SimpleNamespace(id="alice"))
    try:
        assert filter_authorized_skills([private], app_config=policy, runtime={"user_id": "alice", "user_role": "admin"}) == [private]
        assert filter_authorized_skills([private], app_config=policy, runtime={"user_id": "bob", "user_role": "admin"}) == []
        assert filter_authorized_skills([private], app_config=policy) == []
    finally:
        reset_current_user(token)


def test_cache_and_deferred_metadata_recheck_grants(policy, monkeypatch):
    from deerflow.agents.lead_agent import prompt
    from deerflow.security.store import UserSecurityStore
    from deerflow.skills.catalog import SkillCatalog
    from deerflow.skills.describe import build_describe_skill_tool

    item = skill("enterprise-extra")
    token = set_current_user(SimpleNamespace(id="alice", system_role="user"))
    try:
        monkeypatch.setattr("deerflow.config.get_app_config", lambda: policy)
        monkeypatch.setattr(prompt, "get_or_new_user_skill_storage", lambda *args, **kwargs: SimpleNamespace(load_skills=lambda **kwargs: [item]))
        tool = build_describe_skill_tool(SkillCatalog((item,)))
        store = UserSecurityStore(policy.authorization.provider.config["store_path"])
        store.set_grant("alice", "skill", "public:enterprise-extra", True, actor="admin")
        assert prompt.get_enabled_skills_for_config(policy, "alice") == [item]
        assert "private metadata" in tool.func("enterprise-extra", "call-1").update["messages"][0].content
        store.set_grant("alice", "skill", "public:enterprise-extra", False, actor="admin")
        assert prompt.get_enabled_skills_for_config(policy, "alice") == []
        assert "private metadata" not in tool.func("enterprise-extra", "call-2").update["messages"][0].content
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_api_hides_ungranted_metadata_including_disabled(policy, monkeypatch):
    from dataclasses import replace

    from fastapi import HTTPException

    from app.gateway.routers import skills as router

    token = set_current_user(SimpleNamespace(id="alice", system_role="user"))
    items = [skill("data-analysis"), skill("private-extra"), replace(skill("disabled-extra"), enabled=False)]
    monkeypatch.setattr(router, "_get_user_skill_storage", lambda config: SimpleNamespace(load_skills=lambda **kwargs: items))
    try:
        assert [item.name for item in (await router.list_skills(policy)).skills] == ["data-analysis"]
        with pytest.raises(HTTPException) as error:
            await router.get_skill("private-extra", policy)
        assert error.value.status_code == 404
    finally:
        reset_current_user(token)


def test_active_skill_tool_decision_revokes_before_next_tool_call(policy, monkeypatch):
    from test_skill_tool_policy_middleware import ModelRequestStub, NamedTool, ToolRequestStub, _middleware

    from deerflow.security.store import UserSecurityStore

    item = skill("private-extra")
    token = set_current_user(SimpleNamespace(id="alice", system_role="user"))
    try:
        monkeypatch.setattr("deerflow.config.get_app_config", lambda: policy)
        store = UserSecurityStore(policy.authorization.provider.config["store_path"])
        store.set_grant("alice", "skill", "public:private-extra", True, actor="admin")
        middleware = _middleware([item])
        state = {"skill_context": [{"path": item.get_container_file_path()}]}
        context = {}
        middleware.wrap_model_call(ModelRequestStub([NamedTool("web_search")], state=state, context=context), lambda request: request)
        store.set_grant("alice", "skill", "public:private-extra", False, actor="admin")
        result = middleware.wrap_tool_call(ToolRequestStub("web_search", state=state, context=context), lambda request: "executed")
        assert result != "executed"
    finally:
        reset_current_user(token)
