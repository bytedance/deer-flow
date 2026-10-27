import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.routers import enterprise_mail_outbox as outbox_router
from deerflow.integrations.enterprise.mail_outbox import MailOutboxService, MailOutboxStore
from deerflow.integrations.enterprise.service import EnterpriseService
from deerflow.integrations.enterprise.store import EnterpriseStore


@pytest.mark.anyio
async def test_enterprise_send_keeps_sqlite_and_crypto_off_event_loop(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = await asyncio.to_thread(store.create_target, "alice", "Operations", "wecom_webhook", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=example")
    provider = SimpleNamespace(send=AsyncMock())
    receipt = await EnterpriseService(store, providers={"wecom_webhook": provider}).send("alice", target["id"], "Reminder", "one")
    assert receipt["status"] == "sent"
    assert len(await asyncio.to_thread(store.deliveries, "alice")) == 1


@pytest.mark.anyio
async def test_mail_network_storage_and_crypto_stay_off_event_loop(tmp_path):
    import threading
    import time

    from deerflow.integrations.enterprise.mail import MailService

    main_thread = threading.get_ident()

    class Client:
        def check(self, credentials):
            assert threading.get_ident() != main_thread
            time.sleep(0.01)

        def read(self, credentials, **kwargs):
            self.check(credentials)
            return {"messages": []}

    store = EnterpriseStore(tmp_path)
    service = MailService(store, client=Client())
    account = await service.connect("alice", "Office", {"email": "alice@example.com", "password": "secret", "host": "imap.qiye.aliyun.com"})
    assert await service.read("alice", account["id"]) == {"messages": []}


@pytest.mark.anyio
async def test_mail_submission_keeps_smtp_storage_and_crypto_off_event_loop(tmp_path, monkeypatch):
    import json
    import threading
    import time

    main_thread = threading.get_ident()

    class Sender:
        def send(self, credentials, envelope, message_id):
            assert threading.get_ident() != main_thread
            time.sleep(0.01)
            return {"status": "sent", "error": None, "accepted": envelope["to"], "refused": []}

    store = MailOutboxStore(tmp_path)
    account = await asyncio.to_thread(store.create_mail_account, "alice", "Office", {"email": "alice@example.com", "password": "secret", "host": "imap.qiye.aliyun.com"})
    service = MailOutboxService(store, sender=Sender())
    monkeypatch.setattr(outbox_router, "_access", AsyncMock(return_value=("alice", service)))

    class Request:
        def __init__(self, payload):
            self.payload = payload

        async def stream(self):
            yield json.dumps(self.payload).encode()

    draft = await outbox_router.create_draft(Request({"account_id": account["id"], "to": ["bob@example.com"], "subject": "Hello", "body": "Review"}))
    result = await outbox_router.send_draft(Request({"confirmed": True}), draft["id"])
    assert result["status"] == "sent"
    assert (await outbox_router.list_drafts(Request(None)))["drafts"][0]["id"] == draft["id"]
