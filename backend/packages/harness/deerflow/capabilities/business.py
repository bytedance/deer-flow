"""Bundled business tools served through the existing stdio MCP lifecycle.

These clients implement the documented provider APIs independently. Credentials
stay in MCP process environment, never in tool arguments or discovery results.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from typing import Annotated, Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

MODULE = "deerflow.capabilities.business"
CREDENTIALS = {
    "dingtalk": {"access_token": "DEERFLOW_DINGTALK_ACCESS_TOKEN", "sign_secret": "DEERFLOW_DINGTALK_SIGN_SECRET"},
    "wecom": {"webhook_key": "DEERFLOW_WECOM_WEBHOOK_KEY"},
    "hubspot": {"access_token": "DEERFLOW_HUBSPOT_ACCESS_TOKEN"},
}


def connection_config(provider: str, configuration: dict[str, Any]) -> dict[str, Any]:
    fields = CREDENTIALS.get(provider)
    if fields is None or set(configuration) != set(fields):
        raise ValueError("Supply the required credentials only")
    env = {}
    for field, variable in fields.items():
        value = configuration[field]
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,4096}", value):
            raise ValueError(f"Invalid credential: {field}")
        env[variable] = value
    return {"type": "stdio", "command": sys.executable, "args": ["-I", "-m", MODULE, provider], "env": env, "enabled": True}


def is_bundled_connection(command: str | None, args: list[str], env: dict[str, str]) -> bool:
    """Narrow exception to the executable allowlist, including edits/toggles.

    Never trust catalog metadata to grant execution. The interpreter, module,
    provider, flags and allowed environment keys must all match our own launcher.
    """
    return command == sys.executable and len(args) == 4 and args[:3] == ["-I", "-m", MODULE] and args[3] in CREDENTIALS and set(env) == set(CREDENTIALS[args[3]].values())


class BusinessClient:
    def __init__(self, provider: str, credentials: dict[str, str], http: httpx.AsyncClient | None = None):
        connection_config(provider, credentials)
        self.provider = provider
        self.credentials = credentials
        self.http = http

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        async def perform(client: httpx.AsyncClient) -> dict[str, Any]:
            try:
                async with client.stream(method, url, follow_redirects=False, timeout=20, **kwargs) as response:
                    if not 200 <= response.status_code < 300:
                        raise ValueError(f"{self.provider}: HTTP {response.status_code}; check credentials, permissions and provider limits")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 2_000_000:
                            raise ValueError("Provider response exceeds the size limit")
                    try:
                        data = json.loads(chunks)
                    except (ValueError, UnicodeError):
                        raise ValueError("Provider returned an invalid JSON response") from None
                    if not isinstance(data, dict):
                        raise ValueError("Provider returned an invalid response")
                    return data
            except httpx.RequestError:
                # Request exceptions contain token-bearing webhook URLs.
                raise ValueError(f"{self.provider}: network request failed; delivery may be unknown, check before retrying") from None

        if self.http is not None:
            return await perform(self.http)
        async with httpx.AsyncClient() as client:
            return await perform(client)

    async def send_message(self, content: str, message_type: Literal["text", "markdown"] = "text", title: str = "Notification") -> dict[str, Any]:
        if self.provider not in ("dingtalk", "wecom"):
            raise ValueError("This provider has no group notification tool")
        limit = 2048 if message_type == "text" or self.provider == "dingtalk" else 4096
        if message_type not in ("text", "markdown") or not content.strip() or len(content.encode("utf-8")) > limit:
            raise ValueError(f"Message must contain 1–{limit} UTF-8 bytes")
        if not title.strip() or len(title) > 100:
            raise ValueError("Title must contain 1–100 characters")
        if self.provider == "dingtalk":
            timestamp = str(int(time.time() * 1000))
            secret = self.credentials["sign_secret"]
            signature = hmac.new(secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256).digest()
            params = {"access_token": self.credentials["access_token"], "timestamp": timestamp, "sign": base64.b64encode(signature).decode()}
            url = "https://oapi.dingtalk.com/robot/send"
            body = {"text": content, "title": title} if message_type == "markdown" else {"content": content}
        else:
            params = {"key": self.credentials["webhook_key"]}
            url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
            body = {"content": content}
        data = await self._request("POST", url, params=params, json={"msgtype": message_type, message_type: body})
        code = data.get("errcode")
        if type(code) is not int or code != 0:
            safe_code = str(code) if type(code) is int else "unknown"
            raise ValueError(f"{self.provider}: provider rejected the message (code {safe_code}); check robot settings and limits")
        return {"sent": True}

    async def get_companies(self, limit: int = 10, after: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 100 or (after is not None and len(after) > 512):
            raise ValueError("Invalid page size or cursor")
        params = {"limit": str(limit), "properties": "name,domain,industry,phone,city,country", "archived": "false"}
        if after:
            params["after"] = after
        data = await self._hubspot("GET", "/crm/v3/objects/companies", params=params)
        if not isinstance(data.get("results"), list):
            raise ValueError("HubSpot returned an invalid company list")
        return {"companies": data["results"], "next_after": data.get("paging", {}).get("next", {}).get("after")}

    async def create_contact(self, email: str, firstname: str = "", lastname: str = "", phone: str = "", company: str = "", jobtitle: str = "") -> dict[str, Any]:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
            raise ValueError("Supply a valid contact email")
        fields = {"email": email, "firstname": firstname, "lastname": lastname, "phone": phone, "company": company, "jobtitle": jobtitle}
        if any(len(value) > 1000 for value in fields.values()):
            raise ValueError("Contact fields must not exceed 1000 characters")
        data = await self._hubspot("POST", "/crm/v3/objects/contacts", json={"properties": {key: value for key, value in fields.items() if value}})
        if not data.get("id"):
            raise ValueError("HubSpot did not return a created contact ID")
        return {"id": data["id"], "properties": data.get("properties", {})}

    async def _hubspot(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if self.provider != "hubspot":
            raise ValueError("This provider has no CRM tools")
        return await self._request(method, "https://api.hubapi.com" + path, headers={"Authorization": f"Bearer {self.credentials['access_token']}"}, **kwargs)


def build_server(provider: str) -> FastMCP:
    if provider not in CREDENTIALS:
        raise ValueError("Unknown business provider")
    server = FastMCP(f"deerflow-{provider}", log_level="WARNING")

    def client() -> BusinessClient:
        return BusinessClient(provider, {field: os.environ.get(variable, "") for field, variable in CREDENTIALS[provider].items()})

    if provider == "hubspot":

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
        async def get_companies(limit: Annotated[int, Field(ge=1, le=100)] = 10, after: str | None = None) -> dict[str, Any]:
            """Read a page of HubSpot companies; pass next_after to retrieve the next page."""
            return await client().get_companies(limit, after)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
        async def create_contact(email: str, firstname: str = "", lastname: str = "", phone: str = "", company: str = "", jobtitle: str = "") -> dict[str, Any]:
            """Create a real HubSpot contact when requested. Do not retry an uncertain write without checking for duplicates."""
            return await client().create_contact(email, firstname, lastname, phone, company, jobtitle)

    else:

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
        async def send_message(content: str, message_type: Literal["text", "markdown"] = "text", title: str = "Notification") -> dict[str, Any]:
            """Send a real notification to the configured group robot when requested. Does not read chats. Do not automatically retry uncertain delivery."""
            return await client().send_message(content, message_type, title)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="DeerFlow bundled business MCP tools")
    parser.add_argument("provider", choices=CREDENTIALS)
    build_server(parser.parse_args().provider).run()


if __name__ == "__main__":
    main()
