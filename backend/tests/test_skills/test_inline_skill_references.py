"""Explicit multi-skill activation uses the existing owner and policy boundaries."""

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
from deerflow.runtime.secret_context import (
    _SLASH_SECRET_SOURCE_KEY,
    _SLASH_SKILL_ACTIVATION_RUN_KEY,
    ACTIVE_SECRETS_CONTEXT_KEY,
    read_slash_skill_source_path,
    read_slash_skill_source_paths,
    write_slash_skill_source_path,
    write_slash_skill_source_paths,
)
from deerflow.skills.types import SecretRequirement, Skill, SkillCategory

OWNER = "test-chain-owner"


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    skills = []
    for index in range(16):
        name = f"skill-{index}"
        directory = tmp_path / name
        directory.mkdir()
        skill_file = directory / "SKILL.md"
        skill_file.write_text(f"# {name}\nDo <safe> work.", encoding="utf-8")
        skills.append(
            Skill(name=name, description=name, license="MIT", skill_dir=directory, skill_file=skill_file, relative_path=Path(name), category=SkillCategory.CUSTOM, enabled=True, required_secrets=(SecretRequirement(name=f"KEY_{index}"),))
        )
    storage = SimpleNamespace(load_skills=lambda **_: skills, get_container_root=lambda: "/mnt/skills", get_skills_root_path=lambda: tmp_path, validate_skill_file_path=lambda path: path.resolve())
    factory = Mock(return_value=storage)
    monkeypatch.setattr("deerflow.agents.middlewares.skill_activation_middleware.get_or_new_user_skill_storage", factory)
    middleware = SkillActivationMiddleware(user_id="owner-a", slash_source_owner_token=OWNER)
    return middleware, skills, factory


def request(text, metadata, context):
    message = HumanMessage(content=text, additional_kwargs=metadata)
    return ModelRequest(model=object(), messages=[message], state={"messages": [message]}, runtime=SimpleNamespace(context=context))


@pytest.mark.parametrize("count", [1, 2, 16])
@pytest.mark.parametrize("async_call", [False, True])
def test_inline_batch_activates_once_with_owner_scoped_secrets_and_usage(catalog, count, async_call):
    middleware, skills, factory = catalog
    names = [skill.name for skill in skills[:count]]
    journal = SimpleNamespace(record_middleware=Mock(), record_skill_usage=Mock())
    context = {"__run_journal": journal, "secrets": {f"KEY_{i}": f"value-{i}" for i in range(16)}}
    original = request("Compare <inputs>", {"skill_references": names}, context)
    seen = []

    def handler(value):
        seen.append(value)
        return AIMessage(content="done")

    async def ahandler(value):
        return handler(value)

    def invoke(model_request):
        return asyncio.run(middleware.awrap_model_call(model_request, ahandler)) if async_call else middleware.wrap_model_call(model_request, handler)

    response = invoke(original)
    reminder = seen[0].messages[0]
    assert isinstance(reminder, HumanMessage)
    assert reminder.additional_kwargs["hide_from_ui"] is True
    assert reminder.additional_kwargs["deerflow_producer_kind"]
    assert "Do &lt;safe&gt; work." in reminder.content
    assert reminder.content.count("Compare &lt;inputs&gt;") == 1
    assert original.state["messages"] == original.messages
    expected_paths = tuple(skill.get_container_file_path() for skill in skills[:count])
    assert read_slash_skill_source_paths(context, owner_token=OWNER) == expected_paths
    assert context[ACTIVE_SECRETS_CONTEXT_KEY] == {f"KEY_{i}": f"value-{i}" for i in range(count)}
    assert all(call.args == ("owner-a",) for call in factory.call_args_list)
    key = "skill_usage" if count == 1 else "skill_usages"
    usages = [response.additional_kwargs[key]] if count == 1 else response.additional_kwargs[key]
    assert [entry["name"] for entry in usages] == names
    assert journal.record_skill_usage.call_count == count
    assert context[_SLASH_SKILL_ACTIVATION_RUN_KEY]
    # The tool loop's next call sees the answered slash message in state.
    follow_up = original.override(messages=[*original.messages, response])
    invoke(follow_up)
    assert seen[1].messages == follow_up.messages
    assert journal.record_skill_usage.call_count == count
    assert context[ACTIVE_SECRETS_CONTEXT_KEY] == {f"KEY_{i}": f"value-{i}" for i in range(count)}


def test_duplicate_references_activate_and_record_each_skill_once(catalog):
    middleware, _, _ = catalog
    captured = Mock(return_value=AIMessage(content="done"))
    response = middleware.wrap_model_call(request("compare", {"skill_references": ["skill-0", "skill-1", "skill-0"]}, {}), captured)
    assert [entry["name"] for entry in response.additional_kwargs["skill_usages"]] == ["skill-0", "skill-1"]
    assert captured.call_args.args[0].messages[0].content.count('<skill name="skill-0"') == 1


@pytest.mark.parametrize("names", [False, 0, "", {}, "skill-0", ["skill-0", None], ["skill-0", "a--b"], ["skill-0", "missing"], ["skill-0"] * 17])
def test_invalid_inline_batch_never_reaches_model_or_publishes_partial_authority(catalog, names):
    middleware, _, _ = catalog
    context = {"secrets": {"KEY_0": "test-only"}}
    handler = Mock()
    response = middleware.wrap_model_call(request("task", {"skill_references": names}, context), handler)
    assert isinstance(response, AIMessage)
    handler.assert_not_called()
    assert _SLASH_SECRET_SOURCE_KEY not in context
    assert _SLASH_SKILL_ACTIVATION_RUN_KEY not in context
    assert ACTIVE_SECRETS_CONTEXT_KEY not in context
    assert "skill_usage" not in response.additional_kwargs
    assert "skill_usages" not in response.additional_kwargs


@pytest.mark.parametrize("denied", ["disabled", "agent-allowlist"])
def test_invalid_second_selection_rejects_the_entire_batch(catalog, denied):
    middleware, skills, _ = catalog
    if denied == "disabled":
        skills[1] = replace(skills[1], enabled=False)
    else:
        middleware._available_skills = {"skill-0"}
    handler = Mock()
    context = {}
    middleware.wrap_model_call(request("task", {"skill_references": ["skill-0", "skill-1"]}, context), handler)
    handler.assert_not_called()
    assert not context


@pytest.mark.parametrize("metadata", [{}, {"skill_references": None}, {"skill_references": []}])
@pytest.mark.parametrize("text", ["ordinary task", "/skill-0 legacy task"])
def test_empty_selection_preserves_ordinary_and_legacy_paths(catalog, metadata, text):
    middleware, _, _ = catalog
    handler = Mock(return_value=AIMessage(content="done"))
    result = middleware.wrap_model_call(request(text, metadata, {}), handler)
    handler.assert_called_once()
    assert ("skill_usage" in result.additional_kwargs) == text.startswith("/")


def test_idless_activation_identity_includes_selected_skills():
    key = SkillActivationMiddleware._activation_run_key
    first = HumanMessage(content="same text", additional_kwargs={"skill_references": ["skill-0"]})
    second = HumanMessage(content="same text", additional_kwargs={"skill_references": ["skill-1"]})
    assert key(first) != key(second)
    assert key(first) == key(first.model_copy())


def test_plural_source_round_trip_and_single_path_compatibility():
    context = {}
    paths = ("/mnt/skills/custom/one/SKILL.md", "/mnt/skills/custom/two/SKILL.md")
    write_slash_skill_source_paths(context, (*paths, paths[0]), owner_token=OWNER)
    assert read_slash_skill_source_paths(context, owner_token=OWNER) == paths
    assert read_slash_skill_source_path(context, owner_token=OWNER) == paths[0]
    assert read_slash_skill_source_paths(context, owner_token="foreign") == ()
    write_slash_skill_source_path(context, paths[1], owner_token=OWNER)
    assert read_slash_skill_source_paths(context, owner_token=OWNER) == (paths[1],)


@pytest.mark.parametrize("paths", [None, [], "first", {}, ["other"], ["first", ""], ["first", 1], ["first"] * 17])
def test_plural_source_malformed_list_fails_closed(paths):
    context = {_SLASH_SECRET_SOURCE_KEY: {"path": "first", "paths": paths, "owner_token": OWNER}}
    assert read_slash_skill_source_paths(context, owner_token=OWNER) == ()


@pytest.mark.parametrize("denied", [False, True])
@pytest.mark.parametrize("fail_closed", [False, True])
def test_async_inline_batch_authorizes_every_selection_on_the_event_loop(catalog, denied, fail_closed):
    from deerflow.authz.provider import AuthzDecision
    from deerflow.authz.skill_filter import ResolvedSkillAuthorization

    middleware, _, _ = catalog
    provider = SimpleNamespace(authorize=Mock(side_effect=RuntimeError("sync API must not run")))
    calls = []

    async def authorize(value):
        calls.append(value.target)
        return AuthzDecision(allow=not (denied and value.target == "skill-1"))

    provider.aauthorize = authorize
    middleware._skill_authorization = ResolvedSkillAuthorization(provider=provider, principal=None, fail_closed=fail_closed)
    context = {"secrets": {"KEY_0": "zero", "KEY_1": "one"}}
    original = request("compare", {"skill_references": ["skill-0", "skill-1"]}, context)
    seen = []

    async def handler(value):
        seen.append(value)
        return AIMessage(content="done")

    result = asyncio.run(middleware.awrap_model_call(original, handler))
    assert calls == ["skill-0", "skill-1"]
    provider.authorize.assert_not_called()
    if denied:
        assert not seen
        assert "not available" in result.content
        assert _SLASH_SECRET_SOURCE_KEY not in context
        assert ACTIVE_SECRETS_CONTEXT_KEY not in context
    else:
        assert len(seen) == 1
        assert context[ACTIVE_SECRETS_CONTEXT_KEY] == {"KEY_0": "zero", "KEY_1": "one"}
        assert [entry["name"] for entry in result.additional_kwargs["skill_usages"]] == ["skill-0", "skill-1"]


def test_each_inline_activation_excludes_its_stale_entry_secret_snapshot(catalog):
    from deerflow.authz.provider import AuthzDecision
    from deerflow.authz.skill_filter import ResolvedSkillAuthorization

    middleware, skills, factory = catalog
    old = skills[1]
    skills[1] = replace(old, required_secrets=(SecretRequirement(name="OLD_KEY"),))
    calls = []

    async def authorize(value):
        calls.append(value.target)
        # The prepass already captured OLD_KEY; activation and binding must use
        # the new declaration, including for the second explicit selection.
        skills[1] = old
        return AuthzDecision(allow=True)

    provider = SimpleNamespace(aauthorize=authorize, authorize=Mock(side_effect=RuntimeError("sync API must not run")))
    middleware._skill_authorization = ResolvedSkillAuthorization(provider=provider, principal=None, fail_closed=True)
    context = {"secrets": {"KEY_0": "zero", "KEY_1": "one", "OLD_KEY": "stale"}}
    original = request("compare", {"skill_references": ["skill-0", "skill-1"]}, context)
    original.state["skill_context"] = [{"name": old.name, "path": old.get_container_file_path()}]

    async def handler(value):
        return AIMessage(content="done")

    asyncio.run(middleware.awrap_model_call(original, handler))
    assert calls == ["skill-0", "skill-1"]
    provider.authorize.assert_not_called()
    assert context[ACTIVE_SECRETS_CONTEXT_KEY] == {"KEY_0": "zero", "KEY_1": "one"}
    assert factory.called
