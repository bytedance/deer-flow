import asyncio
from types import SimpleNamespace

from deerflow_extension_api import ExtensionPrincipal

from deerflow_extension_skill_evolution.actions import ManagedEvolutionActions
from deerflow_extension_skill_evolution.mutations import ManagedEvolution
from deerflow_extension_skill_evolution.service import CapabilityHandle


def _ctx(user_id="user-1", admin=False):
    return SimpleNamespace(principal=ExtensionPrincipal(user_id=user_id, is_admin=admin), settings={})


def _wired():
    mutations, evidence = CapabilityHandle(), CapabilityHandle()
    return mutations, evidence, ManagedEvolution(mutations, evidence)


def test_actions_report_unauthenticated_without_a_principal() -> None:
    actions = ManagedEvolutionActions(ManagedEvolution(*_wired()[:2]))
    for handler, payload in (
        (actions.managed_propose, {"skill_name": "my-skill", "content": "# new"}),
        (actions.managed_stage, {"skill_name": "my-skill", "content": "# new"}),
        (actions.managed_check, {"proposal_id": "prop-1"}),
    ):
        assert asyncio.run(handler(payload, _ctx(user_id=""))) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}


def test_actions_validate_payloads_fail_closed() -> None:
    actions = ManagedEvolutionActions(ManagedEvolution(*_wired()[:2]))
    ctx = _ctx()
    for payload in (
        {},
        {"skill_name": "my-skill"},  # missing content
        {"skill_name": "my-skill", "content": 7},
        {"skill_name": "my-skill", "content": "# new", "source": "t-0/r-0"},
        {"skill_name": "my-skill", "content": "# new", "source": {"thread_id": "", "run_id": "r-0"}},
        {"skill_name": "my-skill", "content": "# new", "source": {"thread_id": "t-0", "run_id": "r-0", "extra": 1}},
    ):
        assert asyncio.run(actions.managed_propose(payload, ctx)) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(actions.managed_publish({}, ctx)) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(actions.managed_rollback({"operation_id": None}, ctx)) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(actions.managed_stage({}, ctx)) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(actions.managed_check({"proposal_id": ""}, ctx)) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}


def test_actions_forward_to_the_pipeline_with_the_principal_identity() -> None:
    mutations, evidence, evolution = _wired()
    captured = {}

    class _Adapter:
        async def read(self, *, user_id, source, skill_name):
            captured["read"] = (user_id, source, skill_name)
            return {"ok": True, "skill": {"name": skill_name}}

        async def stage(self, *, user_id, source, skill_name, content):
            captured["stage"] = (user_id, source, skill_name, content)
            return {"ok": True}

        async def check(self, *, user_id, proposal_id):
            captured["check"] = (user_id, proposal_id)
            return {"ok": True}

        async def propose(self, *, user_id, source, skill_name, content):
            captured["propose"] = (user_id, source, skill_name, content)
            return {"ok": True}

        async def publish(self, *, user_id, proposal_id):
            captured["publish"] = (user_id, proposal_id)
            return {"ok": True}

        async def discard(self, *, user_id, proposal_id):
            captured["discard"] = (user_id, proposal_id)
            return {"ok": True}

        async def rollback(self, *, user_id, operation_id):
            captured["rollback"] = (user_id, operation_id)
            return {"ok": True}

    actions = ManagedEvolutionActions(_Adapter())
    source = {"thread_id": "t-0", "run_id": "r-0"}
    asyncio.run(actions.managed_read({"skill_name": "my-skill", "source": source}, _ctx()))
    asyncio.run(actions.managed_stage({"skill_name": "my-skill", "content": "# new"}, _ctx()))
    asyncio.run(actions.managed_check({"proposal_id": "prop-1"}, _ctx()))
    asyncio.run(actions.managed_propose({"skill_name": "my-skill", "content": "# new"}, _ctx()))
    asyncio.run(actions.managed_publish({"proposal_id": "prop-1"}, _ctx()))
    asyncio.run(actions.managed_discard({"proposal_id": "prop-1"}, _ctx()))
    asyncio.run(actions.managed_rollback({"operation_id": "op-1"}, _ctx()))
    assert captured["read"] == ("user-1", source, "my-skill")
    assert captured["stage"] == ("user-1", None, "my-skill", "# new")
    assert captured["check"] == ("user-1", "prop-1")
    assert captured["propose"] == ("user-1", None, "my-skill", "# new")
    assert captured["publish"] == ("user-1", "prop-1")
    assert captured["discard"] == ("user-1", "prop-1")
    assert captured["rollback"] == ("user-1", "op-1")


def test_actions_ignore_payload_supplied_owner_fields() -> None:
    mutations, evidence, evolution = _wired()
    captured = {}

    class _Adapter:
        async def propose(self, *, user_id, source, skill_name, content):
            captured["user_id"] = user_id
            return {"ok": True}

    actions = ManagedEvolutionActions(_Adapter())
    payload = {"skill_name": "my-skill", "content": "# new", "user_id": "attacker", "owner_id": "attacker"}
    asyncio.run(actions.managed_propose(payload, _ctx(user_id="user-1")))
    assert captured["user_id"] == "user-1"
