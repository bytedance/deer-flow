"""Short-lived browser QR login sessions; bot credentials never leave the server."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel

logger = logging.getLogger(__name__)
_ACTIVE = {"pending", "scanned", "verification_required"}


def _wechat_api_url(value: Any) -> str:
    """Only accept provider-selected HTTPS origins within Tencent WeChat.

    Operator-supplied base_url remains configurable; untrusted login responses
    must never redirect a polling identifier or bot token to arbitrary hosts.
    """
    if not isinstance(value, str) or not re.fullmatch(r"https://(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+weixin\.qq\.com/?", value):
        raise ValueError("Invalid WeChat API origin")
    return value.rstrip("/")


class QRLoginError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.status_code = status_code


@dataclass
class _Session:
    owner: str
    config: dict[str, Any]
    id: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    expires_at: float = field(default_factory=lambda: time.monotonic() + 180)
    status: str = "pending"
    qrcode: str = ""
    content: str = ""
    provider: dict[str, Any] | None = None
    error: str | None = None
    verify_code: str | None = None
    poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def response(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "qrcode_content": self.content, "expires_in": max(0, int(self.expires_at - time.monotonic())), "provider": self.provider, "error": self.error}


class WechatQRLogin:
    """One process-local session, owned by the admin that started it.

    Network polling runs outside the mutation lock so cancellation can fence a
    late confirmation. Credential application shares the lock with manual setup
    and disconnect. No background task, open client or token is retained.
    """

    def __init__(self):
        self.session: _Session | None = None
        self._lock = asyncio.Lock()

    async def request(self, config: dict[str, Any], qrcode: str | None = None, *, verify_code: str | None = None) -> dict[str, Any]:
        channel = WechatChannel(MessageBus(), config)
        try:
            if qrcode is None:
                return await channel.request_login_qrcode()
            return await channel.request_login_status(qrcode, timeout=35, verify_code=verify_code)
        finally:
            await channel.stop()

    def _get(self, owner: str, session_id: str) -> _Session:
        session = self.session
        if session is None or session.id != session_id or session.owner != owner:
            raise QRLoginError("WeChat QR login session not found. Start again.", 404)
        if session.status in _ACTIVE and time.monotonic() >= session.expires_at:
            session.status = "expired"
            session.verify_code = None
        return session

    @asynccontextmanager
    async def mutation(self):
        async with self._lock:
            self.session = None
            yield

    async def start(self, owner: str, config: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            current = self.session
            if current and current.owner != owner and current.expires_at > time.monotonic() and current.status in _ACTIVE:
                raise QRLoginError("Another administrator is connecting WeChat. Try again later.", 409)
            session = _Session(owner, dict(config))
            self.session = session
        try:
            data = await self.request(session.config)
        except (httpx.HTTPError, ValueError):
            session.status = "failed"
            raise QRLoginError("Unable to request a WeChat QR code. Try again.", 502) from None
        async with self._lock:
            self._get(owner, session.id)
            qrcode, content = data.get("qrcode"), data.get("qrcode_img_content")
            if not isinstance(qrcode, str) or not qrcode.strip() or not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 2048:
                session.status = "failed"
                raise QRLoginError("WeChat returned an invalid QR code. Try again.", 502)
            session.qrcode, session.content = qrcode.strip(), content.strip()
            return session.response()

    async def cancel(self, owner: str, session_id: str) -> None:
        async with self._lock:
            self._get(owner, session_id)
            self.session = None

    async def poll(self, owner: str, session_id: str, apply: Callable[[dict[str, str]], Awaitable[dict[str, Any]]], *, verify_code: str | None = None) -> dict[str, Any]:
        session = self._get(owner, session_id)
        async with session.poll_lock:
            session = self._get(owner, session_id)
            if session.status not in _ACTIVE:
                return session.response()
            if verify_code is not None:
                if session.status != "verification_required" or not re.fullmatch(r"[0-9]{1,16}", verify_code):
                    raise QRLoginError("Enter the digits shown in WeChat.")
                session.verify_code = verify_code
            submitted_code = session.verify_code
            try:
                if submitted_code:
                    data = await self.request(session.config, session.qrcode, verify_code=submitted_code)
                else:
                    data = await self.request(session.config, session.qrcode)
            except httpx.TimeoutException:
                session = self._get(owner, session_id)
                if submitted_code and session.status in _ACTIVE:
                    session.error = "network"
                return session.response()
            except httpx.HTTPError as exc:
                session = self._get(owner, session_id)
                if session.status not in _ACTIVE:
                    return session.response()
                retryable = isinstance(exc, httpx.TransportError) or (isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500))
                session.error = "network" if retryable else "invalid_response"
                if not retryable:
                    session.status = "failed"
                    session.verify_code = None
                logger.warning("WeChat QR poll transport error: %s; retryable=%s", type(exc).__name__, retryable)
                return session.response()
            except ValueError:
                session = self._get(owner, session_id)
                session.status, session.error = "failed", "invalid_response"
                session.verify_code = None
                return session.response()
            async with self._lock:
                session = self._get(owner, session_id)
                if session.status not in _ACTIVE:
                    return session.response()
                status = str(data.get("status", "")).strip().lower()
                session.error = None
                # Waits and IDC redirects do not acknowledge the submitted code.
                # Keep sending it until WeChat accepts, rejects or ends the login.
                if status not in {"wait", "pending", "scaned_but_redirect"}:
                    session.verify_code = None
                if status == "confirmed":
                    token = data.get("bot_token")
                    session.status = "failed"
                    if not isinstance(token, str) or not token.strip():
                        session.error = "invalid_response"
                    else:
                        credentials = {"bot_token": token.strip()}
                        ilink_bot_id = str(data.get("ilink_bot_id") or "").strip()
                        if ilink_bot_id:
                            credentials["ilink_bot_id"] = ilink_bot_id
                        base_url = data.get("baseurl")
                        if base_url is not None:
                            try:
                                credentials["base_url"] = _wechat_api_url(base_url)
                            except ValueError:
                                session.error = "invalid_response"
                                return session.response()
                        elif session.config.get("base_url"):
                            credentials["base_url"] = session.config["base_url"]
                        # A partial restart must never be automatically repeated.
                        try:
                            session.provider = await apply(credentials)
                        except Exception as exc:
                            logger.warning("WeChat QR credential application failed: %s", type(exc).__name__)
                            raise QRLoginError("Unable to save or start WeChat. Start again.", 502) from None
                        session.status = "confirmed"
                        logger.info("WeChat QR credentials saved and channel started")
                elif status == "scaned_but_redirect":
                    try:
                        session.config["base_url"] = _wechat_api_url(f"https://{data.get('redirect_host', '')}")
                        session.status = "scanned"
                    except ValueError:
                        session.status, session.error = "failed", "invalid_response"
                        session.verify_code = None
                elif status == "need_verifycode":
                    session.status = "verification_required"
                    if submitted_code:
                        session.error = "verification_rejected"
                elif status in {"binded_redirect", "verify_code_blocked"}:
                    session.status = "failed"
                    session.error = "already_bound" if status == "binded_redirect" else "verification_blocked"
                elif status in {"expired", "canceled", "cancelled", "invalid", "failed"}:
                    session.status = "expired" if status == "expired" else "failed"
                elif status in {"scanned", "scaned"}:
                    session.status = "scanned"
                elif status in {"wait", "pending"}:
                    if submitted_code:
                        # Keep browser polling instead of asking for the code again.
                        session.status = "scanned"
                else:
                    session.status, session.error = "failed", "invalid_response"
                # Log normalized states only: never URLs, codes, tokens or upstream bodies.
                logger.debug("WeChat QR login: status=%s error=%s", session.status, session.error)
                return session.response()
