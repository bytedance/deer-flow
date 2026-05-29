"""Shared synchronous Xiaoshouyi (销售易) API client for skill scripts.

Uses requests library (not async httpx) for standalone script execution.
Credentials from environment variables.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests


class XsyClient:
    """Synchronous Xiaoshouyi API client."""

    def __init__(self) -> None:
        self._auth_url = os.environ.get(
            "XSY_AUTH_URL",
            "https://login.xiaoshouyi.com/auc/oauth2/token",
        )
        self._api_host = os.environ.get("XSY_API_HOST", "api.xiaoshouyi.com")
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._session = requests.Session()

    def authenticate(self) -> str:
        """Acquire or refresh access token."""
        now = time.time()
        if self._access_token and now < (self._expires_at - 300):
            return self._access_token

        client_id = os.environ.get("XSY_CLIENT_ID")
        client_secret = os.environ.get("XSY_CLIENT_SECRET")
        username = os.environ.get("XSY_USERNAME")
        password = os.environ.get("XSY_PASSWORD")

        if not all([client_id, client_secret, username, password]):
            raise RuntimeError("Missing Xiaoshouyi credentials")

        payload = {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
        }

        resp = self._session.post(self._auth_url, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data.get("access_token")
        if not self._access_token:
            raise RuntimeError("Auth response missing access_token")

        expires_in = data.get("expires_in", 86399)
        self._expires_at = time.time() + expires_in

        instance_uri = data.get("instance_uri")
        if instance_uri:
            self._api_host = instance_uri

        return self._access_token

    def query(self, sql: str) -> dict[str, Any]:
        """Execute a single SQL query."""
        token = self.authenticate()
        url = f"https://{self._api_host}/rest/data/v2/query"
        headers = {"Authorization": f"Bearer {token}"}
        resp = self._session.get(url, params={"q": sql}, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"Query error: {data.get('msg')}")
        return data.get("result", {})

    def query_all_pages(self, sql_base: str, max_records: int = 500) -> list[dict[str, Any]]:
        """Fetch all pages using cursor pagination."""
        all_records: list[dict[str, Any]] = []
        last_id: str | None = None

        while len(all_records) < max_records:
            if last_id:
                sql = f"{sql_base} and id > '{last_id}' order by id limit 100"
            else:
                sql = f"{sql_base} order by id limit 100"

            result = self.query(sql)
            records = result.get("records", [])
            if not records:
                break

            all_records.extend(records)

            if len(records) < 100:
                break

            last_id = str(records[-1].get("id", ""))
            if not last_id:
                break

        return all_records[:max_records]

    def query_outbound(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        spec_model: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query outbound details."""
        from datetime import datetime

        conditions = []
        if spec_model:
            conditions.append(f"customItem5__c like '{spec_model}%'")
        if start_date:
            ts = int(datetime.fromisoformat(start_date).timestamp() * 1000)
            conditions.append(f"createdAt >= {ts}")
        if end_date:
            ts = int(datetime.fromisoformat(end_date).timestamp() * 1000)
            conditions.append(f"createdAt <= {ts}")

        where = " and ".join(conditions) if conditions else ""
        sql = f"select id, customItem3__c, customItem5__c, createdAt from customEntity93__c"
        if where:
            sql += f" where {where}"

        return self.query_all_pages(sql, max_records=limit)

    def query_service_events(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        unit_name: str | None = None,
        event_name: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query service events."""
        from datetime import datetime

        conditions = []
        if unit_name:
            conditions.append(f"customItem4__c like '{unit_name}%'")
        if event_name:
            conditions.append(f"customItem6__c like '{event_name}%'")
        if start_date:
            ts = int(datetime.fromisoformat(start_date).timestamp() * 1000)
            conditions.append(f"customItem8__c.id >= {ts}")
        if end_date:
            ts = int(datetime.fromisoformat(end_date).timestamp() * 1000)
            conditions.append(f"customItem8__c.id <= {ts}")

        where = " and ".join(conditions) if conditions else ""
        sql = f"select id, customItem4__c, customItem6__c, customItem8__c from customEntity35__c"
        if where:
            sql += f" where {where}"

        return self.query_all_pages(sql, max_records=limit)
