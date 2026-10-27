import json
import smtplib
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from deerflow.integrations.enterprise.mail_outbox import MailOutboxService, MailOutboxStore
from deerflow.integrations.enterprise.mail_sender import AliMailSender, normalize_message
from deerflow.integrations.enterprise.providers import EnterpriseError


def credentials():
    return {"email": "alice@example.com", "password": "private-password", "host": "imap.qiye.aliyun.com"}


def message(**changes):
    return {"to": ["bob@example.com"], "cc": [], "subject": "会议安排", "body": "请查收日程。", **changes}


@pytest.fixture
def outbox(tmp_path):
    store = MailOutboxStore(tmp_path)
    account = store.create_mail_account("alice", "Office", credentials())
    sender = MagicMock()
    sender.send.return_value = {"status": "sent", "error": None, "accepted": ["bob@example.com"], "refused": []}
    return MailOutboxService(store, sender=sender), store, account["id"], sender


def test_draft_is_encrypted_private_and_cannot_send_twice(outbox):
    service, store, account_id, sender = outbox
    draft = service.draft("alice", account_id, message(body="private-draft-content"))
    sender.send.assert_not_called()
    assert draft["status"] == "draft"
    assert draft["sender"] == "alice@example.com"
    assert b"private-draft-content" not in (store.root / "users.db").read_bytes()
    assert store.drafts("bob") == []
    with pytest.raises(EnterpriseError, match="draft_not_found"):
        service.send("bob", draft["id"])
    result = service.send("alice", draft["id"])
    assert result["status"] == "sent"
    assert service.send("alice", draft["id"])["status"] == "sent"
    assert sender.send.call_count == 1
    assert "private-password" not in json.dumps(result)


def test_simultaneous_confirmation_sends_once(outbox):
    service, _, account, sender = outbox
    draft = service.draft("alice", account, message())
    entered, finish = threading.Event(), threading.Event()

    def send(*_):
        entered.set()
        assert finish.wait(2)
        return {"status": "sent", "error": None, "accepted": ["bob@example.com"], "refused": []}

    sender.send.side_effect = send
    with ThreadPoolExecutor(2) as workers:
        first = workers.submit(service.send, "alice", draft["id"])
        assert entered.wait(2)
        assert service.send("alice", draft["id"])["status"] == "sending"
        finish.set()
        assert first.result()["status"] == "sent"
    assert sender.send.call_count == 1


def test_disconnect_and_discard_prevent_sending(outbox):
    service, store, account, sender = outbox
    draft = service.draft("alice", account, message())
    assert store.discard("alice", draft["id"])["status"] == "discarded"
    assert service.send("alice", draft["id"])["status"] == "discarded"
    other = service.draft("alice", account, message())
    store.delete_target("alice", account)
    with pytest.raises(EnterpriseError, match="target_not_found"):
        service.send("alice", other["id"])
    sender.send.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"to": []},
        {"to": ["a@example.com\r\nBcc: victim@example.com"]},
        {"to": ["Bob <bob@example.com>"]},
        {"subject": "a\r\nBcc: x"},
        {"body": ""},
        {"body": "a" * 20001},
        {"from": "spoof@example.com"},
        {"to": [f"a{i}@example.com" for i in range(21)]},
    ],
)
def test_invalid_envelope_cannot_reach_smtp(changes):
    with pytest.raises(EnterpriseError, match="invalid_mail_message"):
        normalize_message("alice@example.com", message(**changes))


def test_smtp_uses_pinned_tls_sender_and_chinese_mime(monkeypatch):
    connection = MagicMock()
    connection.send_message.return_value = {}
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(smtplib, "SMTP_SSL", factory)
    envelope = normalize_message("alice@example.com", message(cc=["carol@example.com"]))
    result = AliMailSender().send(credentials(), envelope, "<test@example.com>")
    assert result["status"] == "sent"
    assert factory.call_args.args == ("smtp.qiye.aliyun.com", 465)
    assert factory.call_args.kwargs["context"].check_hostname
    connection.login.assert_called_once_with("alice@example.com", "private-password")
    sent = connection.send_message.call_args
    assert str(sent.args[0]["Subject"]) == "会议安排"
    assert str(sent.args[0]["From"]) == "alice@example.com"
    assert sent.kwargs["to_addrs"] == ["bob@example.com", "carol@example.com"]
    assert sent.kwargs["from_addr"] == "alice@example.com"


@pytest.mark.anyio
async def test_model_can_only_prepare_owned_drafts_not_send(outbox, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.integrations.enterprise import mail_compose_tool as module

    _, store, account_id, _ = outbox
    authorize = AsyncMock(return_value=SimpleNamespace())
    smtp = MagicMock(side_effect=AssertionError("AI must not send"))
    monkeypatch.setattr(module, "authorize", authorize)
    monkeypatch.setattr(module, "make_store", lambda _: store)
    monkeypatch.setattr(module, "get_current_user", lambda: SimpleNamespace(id="alice", system_role="user"))
    monkeypatch.setattr(AliMailSender, "send", smtp)
    runtime = SimpleNamespace(context={"user_id": "alice"})
    call = module.enterprise_mail_compose.coroutine
    result = json.loads(await call(runtime, "draft", account_id, **message()))
    assert result["status"] == "draft"
    assert result["preview_url"].endswith(result["id"])
    assert result["requires_user_confirmation"] is True
    assert "private-password" not in json.dumps(result)
    assert authorize.call_args.kwargs["tool_name"] == "enterprise_mail_compose"
    assert "send" not in module.enterprise_mail_compose.args["action"]["enum"]
    assert json.loads(await call(SimpleNamespace(context={"user_id": "bob"}), "list")) == {"error": "access_denied"}
    smtp.assert_not_called()


@pytest.mark.parametrize(
    "failure,status,error",
    [
        (smtplib.SMTPAuthenticationError(535, b"private-password"), "failed", "mail_auth_failed"),
        (smtplib.SMTPRecipientsRefused({"bob@example.com": (550, b"private details")}), "failed", "mail_recipient_rejected"),
        (smtplib.SMTPServerDisconnected("private details"), "unknown", "mail_send_unknown"),
    ],
)
def test_smtp_errors_are_redacted_and_uncertain_delivery_never_retried(monkeypatch, failure, status, error):
    connection = MagicMock()
    if isinstance(failure, smtplib.SMTPAuthenticationError):
        connection.login.side_effect = failure
    else:
        connection.send_message.side_effect = failure
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *_, **__: connection)
    result = AliMailSender().send(credentials(), normalize_message("alice@example.com", message()), "<test@example.com>")
    assert result["status"] == status
    assert result["error"] == error
    assert "private" not in json.dumps(result)
    assert connection.send_message.call_count <= 1


def test_partial_acceptance_is_explicit_and_quit_failure_does_not_change_success(monkeypatch):
    connection = MagicMock()
    connection.send_message.return_value = {"bob@example.com": (550, b"private details")}
    connection.quit.side_effect = OSError("disconnect")
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *_, **__: connection)
    result = AliMailSender().send(credentials(), normalize_message("alice@example.com", message(cc=["carol@example.com"])), "<test@example.com>")
    assert result == {"status": "partial", "error": "mail_partial", "accepted": ["carol@example.com"], "refused": ["bob@example.com"]}


@pytest.mark.asyncio
async def test_read_grant_does_not_grant_compose_and_revocation_is_immediate(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deerflow.authz.principal import build_principal_from_context
    from deerflow.authz.user_policy import PROVIDER_PATH
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.integrations.enterprise import access
    from deerflow.security.store import UserSecurityStore

    config = SimpleNamespace(
        get_tool_config=lambda name: SimpleNamespace(use=f"deerflow.integrations.enterprise.mail_compose_tool:{name}"),
        scheduler=SimpleNamespace(multi_instance=False),
        authorization=AuthorizationConfig(enabled=True, provider={"use": PROVIDER_PATH, "config": {"store_path": str(tmp_path)}}),
    )
    monkeypatch.setattr(access, "get_app_config", lambda: config)
    store = UserSecurityStore(tmp_path)
    principal = build_principal_from_context({"user_id": "alice", "user_role": "user"}, default_role="user")
    store.set_grant("alice", "tool", "enterprise_mail", True, actor="admin")
    with pytest.raises(EnterpriseError, match="access_denied"):
        await access.authorize(principal, tool_name="enterprise_mail_compose")
    store.set_grant("alice", "tool", "enterprise_mail_compose", True, actor="admin")
    await access.authorize(principal, tool_name="enterprise_mail_compose")
    store.set_override("alice", "tool", "enterprise_mail_compose", "deny", actor="admin")
    with pytest.raises(EnterpriseError, match="access_denied"):
        await access.authorize(principal, tool_name="enterprise_mail_compose")
