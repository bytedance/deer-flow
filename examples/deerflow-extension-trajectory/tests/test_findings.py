"""Saved tool failures and retry evidence survive SQLite reopen."""

import io
import zipfile

from fastapi.testclient import TestClient
from trajectory_plugin_gateway import (
    TOOL_FINDINGS_THREAD,
    create_app,
)


def test_error_and_retry_evidence_reopens_without_running_tools_again(tmp_path):
    headers = {"x-test-user": "alice"}
    route = f"/api/ext-trajectory/threads/{TOOL_FINDINGS_THREAD}/export"
    with TestClient(create_app(tmp_path, timing_evidence=True)) as client:
        response = client.get(route + "?format=json", headers=headers)
        assert response.status_code == 200
        initial = response.json()
    with TestClient(create_app(tmp_path, seed=False)) as client:
        response = client.get(route + "?format=json", headers=headers)
        assert response.status_code == 200
        saved = response.json()
        assert saved["rows"] == initial["rows"]
        failures = [
            r["analysis"]["tool_failure"]
            for r in saved["rows"]
            if r["analysis"].get("tool_failure")
        ]
        assert len([f for f in failures if f["confidence"] == "observed"]) == 2
        assert [f["basis"] for f in failures if f["confidence"] == "inferred"] == [
            "status_text_conflict"
        ]
        retries = [
            (c["name"], c["analysis"]["retry"])
            for r in saved["rows"]
            for c in r.get("tool_calls", [])
            if c["analysis"].get("retry")
        ]
        row_ids = {r["id"]: r["row_id"] for r in saved["rows"]}
        assert [
            (
                name,
                retry["confidence"],
                retry["previous_call_row_id"],
                retry["previous_result_row_id"],
            )
            for name, retry in retries
        ] == [
            ("read_file", "observed", row_ids["first-read"], row_ids["first-error"]),
            ("bash", "inferred", row_ids["second-read"], row_ids["second-error"]),
            ("glob", "inferred", row_ids["second-read"], row_ids["second-error"]),
        ]
        shell = next(r for r in saved["rows"] if r.get("tool_name") == "bash")
        assert "EXIT_CODE=1" in shell["text"]
        assert shell["process"] == []
        assert shell["tool_status"] == "success"
        assert shell["analysis"]["tool_failure"] is None
        empty = next(r for r in saved["rows"] if r.get("tool_name") == "glob")
        assert empty["analysis"]["tool_failure"] is None
        response = client.get(route + "?format=markdown", headers=headers)
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            text = archive.read("trajectory.md").decode()
        assert "重试线索：失败后重复相同调用" in text
        assert "可能重试" in text and "工具失败线索" in text
