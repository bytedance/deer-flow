"""Teable table and field structure management tool."""

import json

from langchain_core.tools import tool

from .teable_client import check_configured, teable_delete, teable_patch, teable_post


@tool
def teable_manage_table(
    action: str,
    base_id: str = "",
    table_id: str = "",
    name: str = "",
    fields_json: str = "",
    field_id: str = "",
) -> str:
    """Teable 테이블/필드 구조를 관리합니다.

    Args:
        action: 작업 종류. 'create_table', 'delete_table', 'create_field', 'update_field', 'delete_field' 중 하나
        base_id: create_table, delete_table에 필요. Base ID
        table_id: delete_table, create/update/delete_field에 필요. Table ID
        name: 새 테이블 또는 필드 이름
        fields_json: 테이블 생성 시 필드 배열 JSON 또는 필드 생성/수정 시 단일 필드 JSON.
                     테이블: '[{"name":"이름","type":"singleLineText"},{"name":"등급","type":"singleSelect","options":{"choices":[{"name":"VIP"},{"name":"일반"}]}}]'
                     필드: '{"name":"등급","type":"singleSelect","options":{"choices":[{"name":"VIP"},{"name":"일반"}]}}'
        field_id: update_field, delete_field에 필요. Field ID
    """
    err = check_configured()
    if err:
        return err

    if action == "create_table":
        if not base_id:
            return "create_table에는 base_id가 필요합니다."
        if not name:
            return "create_table에는 name이 필요합니다."
        body = {"name": name}
        if fields_json:
            try:
                body["fields"] = json.loads(fields_json)
            except json.JSONDecodeError as e:
                return f"fields_json 파싱 오류: {e}"
        result = teable_post(f"/base/{base_id}/table", body)
        if isinstance(result, str):
            return f"테이블 생성 실패: {result}"
        tid = result.get("id", "?")
        tname = result.get("name", name)
        return f"=== 테이블 생성 완료 ===\n이름: {tname}\nID: {tid}"

    elif action == "delete_table":
        if not base_id or not table_id:
            return "delete_table에는 base_id와 table_id가 필요합니다."
        result = teable_delete(f"/base/{base_id}/table/arbitrary/{table_id}")
        if isinstance(result, str):
            return f"테이블 삭제 실패: {result}"
        return f"=== 테이블 {table_id} 삭제 완료 ==="

    elif action == "create_field":
        if not table_id:
            return "create_field에는 table_id가 필요합니다."
        if not fields_json:
            return "create_field에는 fields_json이 필요합니다."
        try:
            body = json.loads(fields_json)
        except json.JSONDecodeError as e:
            return f"fields_json 파싱 오류: {e}"
        if name and "name" not in body:
            body["name"] = name
        result = teable_post(f"/table/{table_id}/field", body)
        if isinstance(result, str):
            return f"필드 생성 실패: {result}"
        fid = result.get("id", "?")
        fname = result.get("name", "?")
        ftype = result.get("type", "?")
        return f"=== 필드 생성 완료 ===\n이름: {fname}\n타입: {ftype}\nID: {fid}"

    elif action == "update_field":
        if not table_id or not field_id:
            return "update_field에는 table_id와 field_id가 필요합니다."
        body = {}
        if fields_json:
            try:
                body = json.loads(fields_json)
            except json.JSONDecodeError as e:
                return f"fields_json 파싱 오류: {e}"
        if name and "name" not in body:
            body["name"] = name
        if not body:
            return "수정할 내용이 없습니다."
        result = teable_patch(f"/table/{table_id}/field/{field_id}", body)
        if isinstance(result, str):
            return f"필드 수정 실패: {result}"
        fname = result.get("name", "?")
        return f"=== 필드 {fname} (ID: {field_id}) 수정 완료 ==="

    elif action == "delete_field":
        if not table_id or not field_id:
            return "delete_field에는 table_id와 field_id가 필요합니다."
        result = teable_delete(f"/table/{table_id}/field/{field_id}")
        if isinstance(result, str):
            return f"필드 삭제 실패: {result}"
        return f"=== 필드 {field_id} 삭제 완료 ==="

    else:
        return f"알 수 없는 action: {action}. 사용 가능: create_table, delete_table, create_field, update_field, delete_field"
