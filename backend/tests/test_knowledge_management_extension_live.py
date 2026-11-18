"""Explicit opt-in writes to a dedicated, operator-granted test base.

No automatic retries or cleanup: preserve document IDs to reconcile outcomes.
The API and upstream must be real; session/CSRF credentials come from the caller.
"""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


async def test_live_management_ingestion_to_scoped_evidence(monkeypatch):
    if os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1" or os.getenv("KNOWLEDGE_MANAGEMENT_ALLOW_WRITES") != "1":
        pytest.skip("management writes require two explicit opt-ins")
    required = ["KNOWLEDGE_GATEWAY_URL", "KNOWLEDGE_SESSION_COOKIE", "KNOWLEDGE_CSRF_TOKEN", "KNOWLEDGE_CONNECTION_ID", "WEKNORA_BASE_URL", "WEKNORA_TENANT_ID", "WEKNORA_KNOWLEDGE_BASE_ID", "WEKNORA_API_KEY"]
    if any(not os.getenv(key) for key in required):
        pytest.fail("Set all documented management live-test environment variables")
    from urllib.parse import quote

    gateway = os.environ["KNOWLEDGE_GATEWAY_URL"].rstrip("/")
    base = os.environ["WEKNORA_KNOWLEDGE_BASE_ID"]
    path = f"/api/extensions/knowledge-management/connections/{quote(os.environ['KNOWLEDGE_CONNECTION_ID'], safe='')}/bases/{quote(base, safe='')}"
    marker = "MANAGEMENT-LIVE-" + uuid4().hex
    cookies = {"access_token": os.environ["KNOWLEDGE_SESSION_COOKIE"], "csrf_token": os.environ["KNOWLEDGE_CSRF_TOKEN"]}
    headers = {"Origin": gateway, "X-CSRF-Token": os.environ["KNOWLEDGE_CSRF_TOKEN"]}
    async with httpx.AsyncClient(base_url=gateway, cookies=cookies, headers=headers, timeout=90) as client:
        result = await client.get(path + "/capabilities")
        assert result.status_code == 200
        assert {"manual", "status"} <= set(result.json()["operations"])
        response = await client.post(
            path + "/documents", json={"kind": "manual", "title": marker, "content": f"Synthetic acceptance fixture. Approval marker {marker}. Travel allowance is 735 CNY.", "processing": {"summary_enabled": False}}
        )
        assert response.status_code == 202, "Write failed or uncertain: reconcile upstream before running again"
        document = response.json()
        # A native ID is safe diagnostic evidence and necessary for reconciliation.
        print(f"Created synthetic live document: {document['document_id']}")
        for _ in range(60):
            response = await client.get(path + "/documents/" + quote(document["document_id"], safe=""))
            assert response.status_code == 200
            state = response.json()
            if state["state"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(2)
        else:
            pytest.fail("Processing timed out; retain the printed document ID for reconciliation")
        assert state["state"] == "completed" and state["searchable"], "Upstream processing did not complete"

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages

    provider = WeKnoraProvider({"spaces": [{"base_url": os.environ["WEKNORA_BASE_URL"], "tenant_id": os.environ["WEKNORA_TENANT_ID"], "api_key_env": "WEKNORA_API_KEY", "user_ids": ["live-probe"], "knowledge_base_ids": [base]}]})
    scope = {"version": 1, "mode": "selected", "dataset_ids": [document["dataset_id"]], "document_filters": [{"dataset_id": document["dataset_id"], "document_ids": [document["document_id"]]}]}
    result = await provider.search_scoped(marker, context=KnowledgeRequestContext("live-probe", "lead_agent", scope))
    content, artifact = format_result(result)
    sources = sources_from_messages([json.loads(json.dumps({"type": "tool", "content": content, "artifact": artifact}))])
    assert sources and any(marker in source.excerpt for source in sources)
