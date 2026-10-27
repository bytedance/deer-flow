import imaplib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.integrations.enterprise import access
from deerflow.integrations.enterprise.mail import AliMailClient, MailService, validate_account
from deerflow.integrations.enterprise.providers import EnterpriseError
from deerflow.integrations.enterprise.store import EnterpriseStore


class FakeIMAP:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.capabilities = (b"IMAP4rev1",)

    def login(self, email, password):
        self.calls.append(("login", email, password))
        return "OK", []

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"2"]

    def response(self, name):
        return name, [b"1234"]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b"4 9"]
        if "RFC822.SIZE" in args[1]:
            return "OK", [b"2 (UID 9 RFC822.SIZE 300 FLAGS ())"]
        raw = b"Subject: Invoice due\r\nFrom: vendor@example.com\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Please pay invoice</p><script>steal()</script><img src='https://track.invalid/x'>"
        return "OK", [(b"2 (UID 9 BODY[] {200}", raw), b")"]

    def logout(self):
        self.calls.append(("logout",))


def account():
    return {"email": "alice@example.com", "password": "client-password", "host": "imap.qiye.aliyun.com"}


def test_imap_reads_do_not_mark_seen_or_fetch_remote_html(monkeypatch):
    connection = FakeIMAP()

    def factory(*args, **kwargs):
        assert args == ("imap.qiye.aliyun.com", 993)
        assert kwargs["ssl_context"].check_hostname
        return connection

    monkeypatch.setattr(imaplib, "IMAP4_SSL", factory)
    result = AliMailClient().read(account(), limit=1, days=7, unread_only=True)
    assert result["has_more"] is True
    assert result["next_before_uid"] == 9
    assert result["uidvalidity"] == "1234"
    assert len(result["messages"]) == 1
    mail = result["messages"][0]
    assert mail["category"] == "finance"
    assert "Please pay invoice" in mail["text"]
    assert "steal" not in mail["text"] and "track.invalid" not in mail["text"]
    assert ("select", "INBOX", True) in connection.calls
    assert any("BODY.PEEK[]" in str(call) for call in connection.calls)
    assert "UNSEEN" in str(connection.calls)
    assert not any(call[0] in {"STORE", "MOVE", "EXPUNGE", "COPY"} for call in connection.calls)
    assert connection.calls[-1] == ("logout",)


@pytest.mark.parametrize("changes", [{"host": "localhost"}, {"host": "imap.qiye.aliyun.com.evil.test"}, {"email": "a\r\n@example.com"}, {"password": ""}])
def test_only_official_tls_endpoints_and_valid_credentials(changes):
    with pytest.raises(EnterpriseError):
        validate_account({**account(), **changes})


def test_mail_credentials_encrypted_and_separate_from_webhooks(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_mail_account("alice", "Office", account())
    assert "client-password" not in json.dumps(target)
    assert b"client-password" not in (tmp_path / "users.db").read_bytes()
    assert store.list_targets("alice") == []
    assert store.list_targets("alice", provider="alimail") == [target]
    with pytest.raises(EnterpriseError, match="target_not_found"):
        store.secret("bob", target["id"])


@pytest.mark.anyio
async def test_mail_grant_is_independent_and_rechecked(tmp_path, monkeypatch):
    from deerflow.authz.principal import build_principal_from_context
    from deerflow.authz.user_policy import PROVIDER_PATH
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.security.store import UserSecurityStore

    config = SimpleNamespace(
        get_tool_config=lambda name: SimpleNamespace(use=f"deerflow.integrations.enterprise.{'mail_tool:enterprise_mail' if name == 'enterprise_mail' else 'tools:enterprise_messaging'}"),
        scheduler=SimpleNamespace(multi_instance=False),
        authorization=AuthorizationConfig(enabled=True, provider={"use": PROVIDER_PATH, "config": {"store_path": str(tmp_path)}}),
    )
    monkeypatch.setattr(access, "get_app_config", lambda: config)
    store = UserSecurityStore(tmp_path)
    principal = build_principal_from_context({"user_id": "alice", "user_role": "user"}, default_role="user")
    store.set_grant("alice", "tool", "enterprise_messaging", True, actor="admin")
    with pytest.raises(EnterpriseError, match="access_denied"):
        await access.authorize(principal, tool_name="enterprise_mail")
    store.set_grant("alice", "tool", "enterprise_mail", True, actor="admin")
    await access.authorize(principal, tool_name="enterprise_mail")
    store.set_override("alice", "tool", "enterprise_mail", "deny", actor="admin")
    with pytest.raises(EnterpriseError, match="access_denied"):
        await access.authorize(principal, tool_name="enterprise_mail")


@pytest.mark.anyio
async def test_connect_checks_login_before_saving_and_errors_redacted(tmp_path):
    class Rejected:
        def check(self, credentials):
            raise EnterpriseError("mail_auth_failed")

    store = EnterpriseStore(tmp_path)
    service = MailService(store, client=Rejected())
    with pytest.raises(EnterpriseError, match="mail_auth_failed"):
        await service.connect("alice", "Office", account())
    assert store.list_targets("alice", provider="alimail") == []


@pytest.mark.anyio
async def test_owner_checked_before_network_access(tmp_path):
    store = EnterpriseStore(tmp_path)
    target = store.create_mail_account("alice", "Office", account())
    client = SimpleNamespace(read=AsyncMock())
    with pytest.raises(EnterpriseError, match="target_not_found"):
        await MailService(store, client=client).read("bob", target["id"])
    client.read.assert_not_called()


def test_pagination_fences_mailbox_generation_and_bounds_queries(monkeypatch):
    connection = FakeIMAP()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *args, **kwargs: connection)
    with pytest.raises(EnterpriseError, match="mail_changed"):
        AliMailClient().read(account(), uidvalidity="old")
    assert not any(call[0] == "SEARCH" for call in connection.calls)
    result = AliMailClient().read(account(), before_uid=9, uidvalidity="1234")
    assert [item["uid"] for item in result["messages"]] == [4]
    assert result["has_more"] is False
    for query in ({"limit": 51}, {"days": 0}, {"before_uid": -1}):
        with pytest.raises(EnterpriseError, match="invalid_mail_query"):
            AliMailClient().read(account(), **query)


def test_provider_exception_never_exposes_password(monkeypatch):
    class FailedIMAP(FakeIMAP):
        def login(self, *args):
            raise imaplib.IMAP4.error("client-password internal details")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FailedIMAP)
    with pytest.raises(EnterpriseError, match="^mail_auth_failed$"):
        AliMailClient().check(account())


def test_mime_decoding_ignores_attachments_and_bounds_text():
    from email.message import EmailMessage

    from deerflow.integrations.enterprise.mail import parse_message

    message = EmailMessage()
    message["Subject"] = "会议邀请"
    message.set_content("正文" * 5000)
    message.add_attachment("SECRET ATTACHED CONTENT", filename="附录.txt")
    result = parse_message(message.as_bytes(), 1, unread=True, size=40000)
    assert result["subject"] == "会议邀请"
    assert result["category"] == "meeting"
    assert result["attachments"] == ["附录.txt"]
    assert "SECRET" not in result["text"]
    assert len(result["text"]) == 6000 and result["truncated"]
