import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec

import httpx
import pytest

from deerflow.integrations.enterprise.providers import EnterpriseError, WeComWebhook
from deerflow.integrations.enterprise.service import EnterpriseService
from deerflow.integrations.enterprise.store import EnterpriseStore

URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=example-key"


@pytest.mark.parametrize(
    "url",
    [
        "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x",
        "https://evil.test/?key=x",
        "https://qyapi.weixin.qq.com@evil.test/?key=x",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x&other=y",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x#fragment",
    ],
)
def test_webhook_url_rejects_other_destinations(url):
    with pytest.raises(EnterpriseError):
        WeComWebhook.validate_secret(url)


def test_targets_are_owner_scoped_and_secret_is_encrypted(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_target("alice", "运营群", "wecom_webhook", URL)
    assert "example-key" not in str(store.list_targets("alice"))
    assert store.list_targets("bob") == []
    with pytest.raises(EnterpriseError):
        store.target("bob", target["id"])
    assert b"example-key" not in (tmp_path / "users.db").read_bytes()
    assert store.secret("alice", target["id"]) == URL
    store.delete_target("alice", target["id"])
    with pytest.raises(EnterpriseError):
        store.secret("alice", target["id"])


@pytest.mark.anyio
async def test_send_is_deduplicated_and_provider_failure_never_claims_success(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_target("alice", "运营群", "wecom_webhook", URL)
    provider = SimpleNamespace(send=AsyncMock(return_value=None))
    service = EnterpriseService(store, providers={"wecom_webhook": provider})
    first, second = await asyncio.gather(*[service.send("alice", target["id"], "日报", "request-1") for _ in range(2)])
    assert provider.send.await_count == 1
    assert {first["status"], second["status"]} <= {"sent", "sending"}
    with pytest.raises(EnterpriseError):
        await service.send("alice", target["id"], "different", "request-1")
    provider.send.side_effect = EnterpriseError("rejected")
    assert (await service.send("alice", target["id"], "日报", "request-2"))["status"] == "failed"
    assert (await service.send("alice", target["id"], "日报", "request-2"))["status"] == "failed"
    assert provider.send.await_count == 2


@pytest.mark.anyio
async def test_schedule_uses_existing_owner_scoped_repository_and_validates_time(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_target("alice", "运营群", "wecom_webhook", URL)
    saved = {}

    async def create(**fields):
        task = {**fields, "id": fields["task_id"], "status": "enabled"}
        saved[task["id"]] = task
        return task

    async def get(task_id, *, user_id):
        assert user_id == "alice"
        return saved.get(task_id)

    repo = SimpleNamespace(create=AsyncMock(side_effect=create), get=AsyncMock(side_effect=get))
    config = SimpleNamespace(enabled=True, multi_instance=False, min_once_delay_seconds=10)
    service = EnterpriseService(store, task_repo=repo, scheduler_config=config)
    run_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    args = dict(schedule_type="once", schedule_spec={"run_at": run_at}, timezone="Asia/Shanghai")
    first = await service.schedule("alice", target["id"], "日报提醒", "once", **args)
    second = await service.schedule("alice", target["id"], "日报提醒", "once", **args)
    assert first["id"] == second["id"]
    assert repo.create.await_count == 1
    assert first["user_id"] == "alice"
    assert first["context_mode"] == "fresh_thread_per_run"
    assert "example-key" not in first["prompt"]
    assert "enterprise_messaging" in first["prompt"]
    with pytest.raises(EnterpriseError, match="invalid_schedule"):
        await service.schedule("alice", target["id"], "日报", "past", schedule_type="once", schedule_spec={"run_at": "2000-01-01T00:00:00Z"}, timezone="Asia/Shanghai")
    with pytest.raises(EnterpriseError, match="invalid_schedule"):
        await service.schedule("alice", target["id"], "日报", "bad-cron", schedule_type="cron", schedule_spec={"cron": "every day"}, timezone="Asia/Shanghai")
    config.enabled = False
    with pytest.raises(EnterpriseError, match="scheduler_unavailable"):
        await service.schedule("alice", target["id"], "日报", "off", **args)


@pytest.mark.anyio
async def test_content_limit_is_utf8_bytes_and_foreign_send_is_blocked(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_target("alice", "运营群", "wecom_webhook", URL)
    provider = SimpleNamespace(send=AsyncMock())
    service = EnterpriseService(store, providers={"wecom_webhook": provider})
    with pytest.raises(EnterpriseError, match="target_not_found"):
        await service.send("bob", target["id"], "hello", "id")
    with pytest.raises(EnterpriseError, match="invalid_content"):
        await service.send("alice", target["id"], "中" * 700, "id")
    provider.send.assert_not_awaited()


@pytest.mark.anyio
async def test_tool_schema_hides_identity_and_repeat_calls_share_receipt(tmp_path, monkeypatch):
    from deerflow.integrations.enterprise import tools

    schema = tools.enterprise_messaging.tool_call_schema.model_json_schema()["properties"]
    assert not {"runtime", "owner", "user_id", "request_key", "webhook"}.intersection(schema)
    store = EnterpriseStore(tmp_path)
    target = store.create_target("alice", "运营群", "wecom_webhook", URL)
    monkeypatch.setattr(tools, "authorize", AsyncMock(return_value=object()))
    monkeypatch.setattr(tools, "make_store", lambda _: store)
    monkeypatch.setattr(tools, "get_current_user", lambda: None)
    provider = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(tools, "EnterpriseService", lambda store: EnterpriseService(store, providers={"wecom_webhook": provider}))
    runtime = SimpleNamespace(context={"user_id": "alice", "run_id": "run1", "user_role": "user"}, config={})
    for _ in range(2):
        result = await tools.enterprise_messaging.coroutine(runtime=runtime, action="send", target_id=target["id"], content="hello")
        assert '"status": "sent"' in result
    assert provider.send.await_count == 1
    runtime.context["non_interactive"] = True
    result = await tools.enterprise_messaging.coroutine(runtime=runtime, action="schedule", target_id=target["id"], content="hello")
    assert "nested_schedule_disabled" in result
    runtime.context["non_interactive"] = False
    callback = AsyncMock(return_value={"id": "task1", "status": "enabled", "next_run_at": "2026-12-01T01:00:00Z", "timezone": "Asia/Shanghai"})
    monkeypatch.setattr(tools, "schedule_message", callback)
    result = await tools.enterprise_messaging.coroutine(runtime=runtime, action="schedule", target_id=target["id"], content="hello", schedule_type="cron", cron="0 9 * * 1-5")
    assert '"task_id": "task1"' in result
    assert callback.call_args.kwargs["principal"].user_id == "alice"
    assert callback.call_args.kwargs["schedule_spec"] == {"cron": "0 9 * * 1-5"}


@pytest.mark.anyio
async def test_wecom_checks_application_error_and_does_not_follow_redirects():
    provider = WeComWebhook(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"errcode": 93000, "errmsg": URL})))
    with pytest.raises(EnterpriseError) as error:
        await provider.send(URL, "hello")
    assert error.value.code == "rejected"
    assert "example-key" not in str(error.value)
    provider = WeComWebhook(transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location": "https://evil.test"})))
    with pytest.raises(EnterpriseError):
        await provider.send(URL, "hello")


@pytest.mark.anyio
async def test_unknown_delivery_is_not_retried(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_target("alice", "运营群", "wecom_webhook", URL)
    provider = SimpleNamespace(send=AsyncMock(side_effect=EnterpriseError("unknown")))
    service = EnterpriseService(store, providers={"wecom_webhook": provider})
    for _ in range(2):
        assert (await service.send("alice", target["id"], "hello", "same"))["status"] == "unknown"
    assert provider.send.await_count == 1


@pytest.mark.anyio
async def test_schedule_checks_run_permission_and_policy_errors_fail_closed(monkeypatch):
    from deerflow.authz.provider import AuthzDecision, Principal
    from deerflow.integrations.enterprise import access

    config = SimpleNamespace(
        get_tool_config=lambda _: SimpleNamespace(use=access.TOOL_USE),
        scheduler=SimpleNamespace(multi_instance=False),
        authorization=SimpleNamespace(enabled=True),
    )
    provider = SimpleNamespace(aauthorize=AsyncMock(side_effect=lambda request: AuthzDecision(allow=request.target != "runs:create")))
    monkeypatch.setattr(access, "get_app_config", lambda: config)
    monkeypatch.setattr(access, "resolve_authorization_provider_spec", lambda _: None)
    construct = create_autospec(access.construct_authorization_provider, return_value=provider)
    monkeypatch.setattr(access, "construct_authorization_provider", construct)
    principal = Principal(user_id="alice", role="user")
    assert await access.authorize(principal) is config
    construct.assert_called_once_with(None, config.authorization)
    with pytest.raises(EnterpriseError, match="access_denied"):
        await access.authorize(principal, schedule=True)
    provider.aauthorize.side_effect = RuntimeError("private error")
    with pytest.raises(EnterpriseError, match="access_denied"):
        await access.authorize(principal)


@pytest.mark.anyio
async def test_scheduler_bridge_runs_on_gateway_loop_and_uninstalls():
    from deerflow.integrations.enterprise.runtime import schedule_message, set_scheduler

    gateway_loop = asyncio.get_running_loop()

    async def schedule(**kwargs):
        assert asyncio.get_running_loop() is gateway_loop
        return kwargs

    set_scheduler(schedule)
    try:
        assert await asyncio.to_thread(lambda: asyncio.run(schedule_message(owner="alice"))) == {"owner": "alice"}
    finally:
        set_scheduler(None)
    with pytest.raises(EnterpriseError, match="scheduler_unavailable"):
        await schedule_message(owner="alice")
