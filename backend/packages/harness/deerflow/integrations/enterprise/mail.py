"""Read-only AliMail IMAP access. Call all client methods in worker threads."""

import asyncio
import imaplib
import json
import re
import ssl
import threading
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

from .providers import EnterpriseError

HOSTS = {"imap.qiye.aliyun.com", "imaphk.qiye.aliyun.com", "imap.mxhichina.com"}
MAX_MESSAGE_BYTES = 256 * 1024
MAX_TEXT = 6000
_CONNECTIONS = threading.BoundedSemaphore(2)


def validate_account(value):
    if not isinstance(value, dict) or set(value) != {"email", "password", "host"}:
        raise EnterpriseError("invalid_mail_account")
    if not isinstance(value["host"], str) or value["host"] not in HOSTS:
        raise EnterpriseError("invalid_mail_host")
    if not isinstance(value["email"], str) or len(value["email"]) > 254 or not re.fullmatch(r"[^\s@\x00-\x1f]+@[^\s@\x00-\x1f]+\.[^\s@\x00-\x1f]+", value["email"]):
        raise EnterpriseError("invalid_mail_account")
    if not isinstance(value["password"], str) or not value["password"] or len(value["password"]) > 512 or any(ord(c) < 32 for c in value["password"]):
        raise EnterpriseError("invalid_mail_account")
    return value


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def parse_message(raw, uid, *, unread, size):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachments = []
    plain, html = [], []
    for part in message.walk():
        if part.get_filename() or part.get_content_disposition() == "attachment":
            attachments.append(str(part.get_filename() or "attachment")[:200])
    body_part = message.get_body(preferencelist=("plain", "html"))
    for part in [body_part] if body_part is not None else []:
        payload = part.get_payload(decode=True) or b""
        try:
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            parser = _PlainHTML()
            parser.feed(text)
            html.append("".join(parser.parts))
        else:
            plain.append(text)
    body = "\n".join(plain or html).strip()
    subject = str(message.get("Subject", ""))[:500]
    # Transparent keyword preview; semantic summaries are made by the chat agent.
    terms = (subject + "\n" + body[:2000]).casefold()
    category = "other"
    for name, words in (
        ("finance", ("invoice", "payment", "发票", "付款", "对账", "账单", "报销")),
        ("meeting", ("meeting", "calendar", "会议", "日程", "邀请")),
        ("work", ("合同", "订单", "报价", "项目", "交付", "contract", "order", "proposal")),
        ("notification", ("notification", "newsletter", "验证码", "通知", "订阅", "verification")),
    ):
        if any(word in terms for word in words):
            category = name
            break
    return {
        "uid": uid,
        "subject": subject,
        "sender": str(message.get("From", ""))[:500],
        "date": str(message.get("Date", ""))[:100],
        "unread": unread,
        "text": body[:MAX_TEXT],
        "truncated": size > MAX_MESSAGE_BYTES or len(body) > MAX_TEXT,
        "attachments": attachments[:30],
        "category": category,
    }


class AliMailClient:
    @contextmanager
    def _connection(self, credentials):
        validate_account(credentials)
        if not _CONNECTIONS.acquire(blocking=False):
            raise EnterpriseError("mail_busy")
        connection = None
        try:
            connection = imaplib.IMAP4_SSL(credentials["host"], 993, ssl_context=ssl.create_default_context(), timeout=15)
            connection.debug = 0
            try:
                status, _ = connection.login(credentials["email"], credentials["password"])
                if status != "OK":
                    raise EnterpriseError("mail_auth_failed")
            except imaplib.IMAP4.error:
                raise EnterpriseError("mail_auth_failed") from None
            yield connection
        except EnterpriseError:
            raise
        except (OSError, imaplib.IMAP4.error, ValueError, UnicodeError):
            raise EnterpriseError("mail_unavailable") from None
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.logout()
            _CONNECTIONS.release()

    @staticmethod
    def _inbox(connection):
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise EnterpriseError("mail_unavailable")

    def check(self, credentials):
        with self._connection(credentials) as connection:
            self._inbox(connection)

    def read(self, credentials, *, limit=20, days=7, unread_only=False, before_uid=None, uidvalidity=None):
        if type(limit) is not int or not 1 <= limit <= 50 or type(days) is not int or not 1 <= days <= 90 or type(unread_only) is not bool:
            raise EnterpriseError("invalid_mail_query")
        if before_uid is not None and (type(before_uid) is not int or not 1 <= before_uid <= 4294967295):
            raise EnterpriseError("invalid_mail_query")
        deadline = time.monotonic() + 60
        with self._connection(credentials) as connection:
            self._inbox(connection)
            _, validity = connection.response("UIDVALIDITY")
            current_validity = validity[0].decode("ascii") if validity and validity[0] else ""
            if not current_validity.isdigit() or uidvalidity and uidvalidity != current_validity:
                raise EnterpriseError("mail_changed")
            since = datetime.now(UTC) - timedelta(days=days)
            months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
            criteria = ["UNSEEN" if unread_only else "ALL", "SINCE", f"{since.day:02}-{months[since.month - 1]}-{since.year}"]
            if before_uid is not None:
                criteria.extend(["UID", f"1:{max(1, before_uid - 1)}"])
            status, data = connection.uid("SEARCH", None, *criteria)
            if status != "OK":
                raise EnterpriseError("mail_unavailable")
            uids = sorted({int(uid) for row in data if isinstance(row, bytes) for uid in row.split() if uid.isdigit()}, reverse=True)
            if before_uid is not None:
                uids = [uid for uid in uids if uid < before_uid]
            selected = uids[:limit]
            messages = []
            for uid in selected:
                if time.monotonic() > deadline:
                    raise EnterpriseError("mail_timeout")
                status, metadata = connection.uid("FETCH", str(uid), "(UID RFC822.SIZE FLAGS)")
                if status != "OK":
                    raise EnterpriseError("mail_unavailable")
                meta = b" ".join(item for item in metadata if isinstance(item, bytes))
                size_match = re.search(rb"RFC822.SIZE (\d+)", meta)
                if size_match is None:
                    continue  # A message may have disappeared in another client.
                size = int(size_match[1])
                status, parts = connection.uid("FETCH", str(uid), f"(BODY.PEEK[]<0.{MAX_MESSAGE_BYTES}>)")
                if status != "OK":
                    raise EnterpriseError("mail_unavailable")
                raw = b"".join(item[1] for item in parts if isinstance(item, tuple) and isinstance(item[1], bytes))[:MAX_MESSAGE_BYTES]
                if raw:
                    messages.append(parse_message(raw, uid, unread=b"\\Seen" not in meta, size=size))
            return {
                "messages": messages,
                "folder": "INBOX",
                "days": days,
                "unread_only": unread_only,
                "uidvalidity": current_validity,
                "has_more": len(uids) > limit,
                "next_before_uid": selected[-1] if len(uids) > limit else None,
                "classification": "keyword_preview",
                "read_only": True,
            }


class MailService:
    def __init__(self, store, *, client=None):
        self.store = store
        self.client = client or AliMailClient()

    async def connect(self, owner, name, credentials):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise EnterpriseError("invalid_name")
        validate_account(credentials)
        await asyncio.to_thread(self.client.check, credentials)
        return await asyncio.to_thread(self.store.create_mail_account, owner, name, credentials)

    async def read(self, owner, account_id, **query):
        target = await asyncio.to_thread(self.store.target, owner, account_id)
        if target["provider"] != "alimail":
            raise EnterpriseError("target_not_found")
        secret = await asyncio.to_thread(self.store.secret, owner, account_id)
        try:
            credentials = json.loads(secret)
        except (ValueError, TypeError):
            raise EnterpriseError("credential_unavailable") from None
        return await asyncio.to_thread(self.client.read, credentials, **query)
