"""Provider boundary. Credentials never cross into model-visible messages."""

import logging
import re
from typing import Protocol

import httpx


class EnterpriseError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MessageProvider(Protocol):
    async def send(self, secret: str, content: str) -> None: ...


class _RedactWebhook(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if "qyapi.weixin.qq.com" in message:
            record.msg = re.sub(r"(key=)[^\s\"'&]+", r"\1[REDACTED]", message)
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactWebhook())


def validate_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 2048:
        raise EnterpriseError("invalid_content")
    return content


class WeComWebhook:
    def __init__(self, *, transport=None):
        self.transport = transport

    @staticmethod
    def validate_secret(value: str) -> str:
        if not re.fullmatch(r"https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{1,256}", value):
            raise EnterpriseError("invalid_webhook")
        return value

    async def send(self, secret: str, content: str) -> None:
        self.validate_secret(secret)
        validate_content(content)
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport, trust_env=False) as client:
                async with client.stream("POST", secret, json={"msgtype": "text", "text": {"content": content}}) as response:
                    if response.status_code != 200:
                        raise EnterpriseError("unknown" if response.status_code >= 500 else "rejected")
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 65536:
                            raise EnterpriseError("unknown")
                    import json

                    data = json.loads(body)
                    if not isinstance(data, dict) or type(data.get("errcode")) is not int:
                        raise EnterpriseError("unknown")
                    if data["errcode"] != 0:
                        raise EnterpriseError("rejected")
        except (httpx.HTTPError, ValueError):
            # The provider may have accepted a request whose response was lost.
            raise EnterpriseError("unknown") from None


PROVIDERS: dict[str, MessageProvider] = {"wecom_webhook": WeComWebhook()}
