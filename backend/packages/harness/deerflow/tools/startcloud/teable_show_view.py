"""Teable view creation and embed artifact tool.

Creates a Teable shared view and registers it as an embed artifact
in the DeerFlow artifact panel. The iframe receives real-time updates
via Teable's WebSocket when data changes through API calls.
"""

import json
import re
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState

from .teable_client import check_configured, get_public_url, teable_post

# Date-like string pattern: YYYY-MM-DD or ISO datetime
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Operators that Teable's DatetimeCellValueFilterAdapter expects
# with object-style values ({mode, exactDate, timeZone})
_DATE_OPERATORS = {"isAfter", "isBefore", "isOnOrAfter", "isOnOrBefore", "is", "isNot"}

# Map numeric operators to proper date operators
_OPERATOR_REMAP = {
    "isGreater": "isAfter",
    "isGreaterEqual": "isOnOrAfter",
    "isLess": "isBefore",
    "isLessEqual": "isOnOrBefore",
}


def _normalize_date_filter(filter_obj):
    """Recursively normalize date filter values for Teable's share view renderer.

    Teable's view creation API accepts plain string date values like "2026-04-12",
    but the share view renderer (DatetimeCellValueFilterAdapter.getFilterDateTimeRange)
    requires an object: {mode: "exactDate", exactDate: "...", timeZone: "..."}.

    This function also remaps numeric operators (isGreater -> isAfter) for date fields.
    """
    if not isinstance(filter_obj, dict):
        return filter_obj

    # Process filterSet arrays
    if "filterSet" in filter_obj:
        filter_obj["filterSet"] = [_normalize_date_filter(item) for item in filter_obj["filterSet"]]
        return filter_obj

    # Process individual filter items with operator + value
    operator = filter_obj.get("operator", "")
    value = filter_obj.get("value")

    # Remap numeric operators to date operators
    if operator in _OPERATOR_REMAP:
        filter_obj["operator"] = _OPERATOR_REMAP[operator]
        operator = filter_obj["operator"]

    # Convert string date values to object format for date operators
    if isinstance(value, str) and _DATE_RE.match(value) and operator in _DATE_OPERATORS:
        filter_obj["value"] = {
            "mode": "exactDate",
            "exactDate": value,
            "timeZone": "Asia/Seoul",
        }

    return filter_obj


@tool("teable_show_view", parse_docstring=True)
def teable_show_view(
    runtime: ToolRuntime[ContextT, ThreadState],
    table_id: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    view_type: str = "grid",
    view_name: str = "",
    filter_json: str = "",
    sort_json: str = "",
) -> Command:
    """Teable 테이블의 뷰를 생성하고 오른쪽 패널에 실시간으로 표시합니다.
    데이터가 변경되면 자동으로 화면이 업데이트됩니다.

    Args:
        table_id: 테이블 ID
        view_type: 뷰 타입 - grid, kanban, calendar, form, gallery (기본: grid)
        view_name: 뷰 이름 (비워두면 자동 생성)
        filter_json: 필터 JSON (teable_query_records와 동일 형식)
        sort_json: 정렬 JSON. 예: '[{"fieldId":"fldXXX","order":"asc"}]'
    """
    err = check_configured()
    if err:
        return Command(
            update={"messages": [ToolMessage(err, tool_call_id=tool_call_id)]},
        )

    # 1. Create view
    view_body = {
        "name": view_name or f"AI View ({view_type})",
        "type": view_type,
    }
    if filter_json:
        try:
            filter_obj = json.loads(filter_json)
            # Normalize date filter values for share view compatibility
            filter_obj = _normalize_date_filter(filter_obj)
            view_body["filter"] = filter_obj
        except json.JSONDecodeError as e:
            return Command(
                update={"messages": [ToolMessage(f"filter_json 파싱 오류: {e}", tool_call_id=tool_call_id)]},
            )
    if sort_json:
        try:
            view_body["sort"] = {"sortObjs": json.loads(sort_json), "manualSort": False}
        except json.JSONDecodeError as e:
            return Command(
                update={"messages": [ToolMessage(f"sort_json 파싱 오류: {e}", tool_call_id=tool_call_id)]},
            )

    view_result = teable_post(f"/table/{table_id}/view", view_body)
    if isinstance(view_result, str):
        return Command(
            update={"messages": [ToolMessage(f"뷰 생성 실패: {view_result}", tool_call_id=tool_call_id)]},
        )

    view_id = view_result.get("id")
    if not view_id:
        return Command(
            update={"messages": [ToolMessage("뷰 생성 결과에서 ID를 찾을 수 없습니다.", tool_call_id=tool_call_id)]},
        )

    # 2. Enable sharing
    share_result = teable_post(f"/table/{table_id}/view/{view_id}/enable-share", {})
    if isinstance(share_result, str):
        return Command(
            update={"messages": [ToolMessage(f"공유 활성화 실패: {share_result}", tool_call_id=tool_call_id)]},
        )

    share_id = share_result.get("shareId") or view_result.get("shareId")
    if not share_id:
        return Command(
            update={"messages": [ToolMessage("공유 ID를 찾을 수 없습니다.", tool_call_id=tool_call_id)]},
        )

    # 3. Build embed URL using the public Teable URL
    public_url = get_public_url().rstrip("/")
    embed_url = f"{public_url}/share/{share_id}/view?embed=true&hideToolBar=true"

    # 4. Register as embed artifact
    return Command(
        update={
            "artifacts": [f"embed:{embed_url}"],
            "messages": [
                ToolMessage(
                    f"Teable 뷰가 오른쪽 패널에 표시됩니다.\n뷰: {view_body['name']}\n타입: {view_type}\nURL: {embed_url}\n데이터를 수정하면 자동으로 반영됩니다.",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )
