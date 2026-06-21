"""Industrial asset context tools for equipment/component lookup."""

from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from langchain.tools import ToolRuntime, tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from langgraph.config import get_config
from langgraph.typing import ContextT
from pydantic import BaseModel, Field

from deerflow.agents.thread_state import ThreadState
from deerflow.rpc.machine_service import MachineServiceClient
from deerflow.rpc.organize_service import OrganizeServiceClient
from deerflow.rpc.point_service import PointServiceClient
from deerflow.rpc.rpc_client import RpcClient

DEFAULT_EHM_ORIGIN = "http://10.0.2.233"
DEFAULT_EHM_SERVER_PREFIX = "/ehm-server"
DEFAULT_TIMEOUT_SECONDS = 30.0


def _run_async(coro):
    """Run an async RPC flow from a synchronous LangChain tool."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def _first_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value:
        first = value[0]
        return first if isinstance(first, dict) else None
    return value if isinstance(value, dict) else None


def _stringify_id(value: Any) -> str:
    return "" if value is None else str(value)


def _compact_record(record: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not record:
        return None
    compact = {key: record.get(key) for key in keys if record.get(key) is not None}
    return compact or record


def _compact_records(
    records: list[dict[str, Any]],
    keys: tuple[str, ...],
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    normalized_max_items = max(0, min(max_items, 200))
    visible_records = records[:normalized_max_items] if normalized_max_items else []
    return [
        _compact_record(record, keys) or record
        for record in visible_records
    ], len(records) > len(visible_records)


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _resolve_ehm_server_base_url() -> str:
    explicit = os.environ.get("EHM_SERVER_BASE_URL", "").strip()
    if explicit:
        return _strip_trailing_slash(explicit)
    origin = _strip_trailing_slash(os.environ.get("EHM_BASE_ORIGIN", DEFAULT_EHM_ORIGIN).strip())
    prefix = os.environ.get("EHM_SERVER_API_PREFIX", DEFAULT_EHM_SERVER_PREFIX).strip() or DEFAULT_EHM_SERVER_PREFIX
    return f"{origin}/{prefix.strip('/')}"


def _resolve_timeout_seconds() -> float:
    raw = os.environ.get("EHM_SERVER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1.0, min(float(raw), 300.0))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _read_context_token(context: Any) -> str | None:
    if isinstance(context, dict):
        token = context.get("access_token") or context.get("ins_base_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
    return None


def _runtime_access_token(
    runtime: ToolRuntime[ContextT, ThreadState] | None,
    config: RunnableConfig | None = None,
) -> str | None:
    if runtime is not None and isinstance(runtime.context, dict):
        token = _read_context_token(runtime.context)
        if token:
            return token

    configurable = (config or {}).get("configurable") if isinstance(config, dict) else None
    if isinstance(configurable, dict):
        pregel_runtime = configurable.get("__pregel_runtime")
        token = _read_context_token(getattr(pregel_runtime, "context", None))
        if token:
            return token

    token = _read_context_token((config or {}).get("context") if isinstance(config, dict) else None)
    if token:
        return token

    try:
        graph_config = get_config()
    except Exception:
        graph_config = {}
    token = _read_context_token(graph_config.get("context") if isinstance(graph_config, dict) else None)
    if token:
        return token
    configurable = graph_config.get("configurable") if isinstance(graph_config, dict) else None
    if isinstance(configurable, dict):
        pregel_runtime = configurable.get("__pregel_runtime")
        token = _read_context_token(getattr(pregel_runtime, "context", None))
        if token:
            return token
    return None


def _build_ehm_headers(access_token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


async def get_ehm_equipment_by_id(
    equipment_id: str,
    *,
    access_token: str | None = None,
) -> dict[str, Any] | None:
    """Fetch an EHM equipment record by EHM platform equipmentId."""
    equipment_id_str = str(equipment_id).strip()
    if not equipment_id_str:
        return None
    base_url = _resolve_ehm_server_base_url()
    url = f"{base_url}/api/v1/equipments/{quote(equipment_id_str, safe='')}"
    timeout = httpx.Timeout(_resolve_timeout_seconds())
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=_build_ehm_headers(access_token))
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        data = payload.get("data")
        return data if isinstance(data, dict) else payload
    return None


def _points_for_component(grouped_points: Any, component_id: str) -> list[dict[str, Any]]:
    if isinstance(grouped_points, list):
        return [p for p in grouped_points if isinstance(p, dict)]
    if not isinstance(grouped_points, dict):
        return []
    candidates = (
        grouped_points.get(component_id),
        grouped_points.get(int(component_id)) if component_id.isdigit() else None,
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return [p for p in candidate if isinstance(p, dict)]
    return []


async def resolve_component_context_data(
    component_id: int | str | None = None,
    *,
    equipment_id: int | str | None = None,
    access_token: str | None = None,
    include_points: bool = True,
    include_children: bool = True,
    hidden_if_valid: bool = False,
    max_points: int = 50,
) -> dict[str, Any]:
    """Resolve component, owning machine, readable path, and optional points."""
    equipment_id_str = str(equipment_id).strip() if equipment_id is not None else ""
    ehm_equipment: dict[str, Any] | None = None
    component_id_str = str(component_id).strip() if component_id is not None else ""

    if not component_id_str and equipment_id_str:
        try:
            ehm_equipment = await get_ehm_equipment_by_id(equipment_id_str, access_token=access_token)
        except httpx.HTTPStatusError as exc:
            return {
                "status": "ehm_equipment_error",
                "equipment_id": equipment_id_str,
                "message": f"EHM 设备接口返回异常状态: {exc.response.status_code}",
            }
        except Exception as exc:
            return {
                "status": "ehm_equipment_error",
                "equipment_id": equipment_id_str,
                "message": f"EHM 设备接口调用失败: {exc}",
            }
        source_data_id = (ehm_equipment or {}).get("sourceDataId")
        component_id_str = str(source_data_id or "").strip()
        if not component_id_str:
            return {
                "status": "source_data_id_missing",
                "equipment_id": equipment_id_str,
                "ehm_equipment": ehm_equipment,
                "message": f"EHM 设备 {equipment_id_str} 未返回 sourceDataId，无法映射到 InS componentId",
            }

    if not component_id_str:
        return {
            "status": "invalid_input",
            "component_id": component_id_str,
            "equipment_id": equipment_id_str,
            "message": "component_id 和 equipment_id 不能同时为空",
        }

    rpc_client = RpcClient()
    try:
        machine_client = MachineServiceClient(rpc_client)
        component = _first_item(await machine_client.get_component_info_by_ids([component_id_str]))
        if not component:
            return {
                "status": "not_found",
                "equipment_id": equipment_id_str,
                "component_id": component_id_str,
                "message": f"未查询到 componentId={component_id_str} 对应的部件/子设备信息",
            }

        machine_id = _stringify_id(component.get("machineId") or component.get("machine_id"))
        machine: dict[str, Any] | None = None
        if machine_id:
            try:
                machine = _first_item(await machine_client.get_machine_info_by_ids([int(machine_id)]))
            except (TypeError, ValueError):
                machine = None

        organize_client = OrganizeServiceClient(rpc_client)
        component_path_data = await organize_client.get_component_path(component_id_str)
        component_path = component_path_data.get("path") if isinstance(component_path_data, dict) else None

        points: list[dict[str, Any]] = []
        if include_points:
            point_client = PointServiceClient(rpc_client)
            if include_children:
                grouped_points = await point_client.get_point_info_under_component_ids(
                    [component_id_str],
                    hidden_if_valid=hidden_if_valid,
                )
            else:
                grouped_points = await point_client.get_point_info_by_component_ids([component_id_str])
            points = _points_for_component(grouped_points, component_id_str)

        point_count = len(points)
        normalized_max_points = max(0, min(max_points, 200))
        visible_points = points[:normalized_max_points] if normalized_max_points else []

        component_name = component.get("name") or component.get("componentName") or component_id_str
        machine_name = (machine or {}).get("name") or (machine or {}).get("machineName") or machine_id
        summary_parts = [f"部件/子设备 {component_name}"]
        if machine_id:
            summary_parts.append(f"归属设备ID {machine_id}")
        if machine_name:
            summary_parts.append(f"设备名称 {machine_name}")
        if component_path:
            summary_parts.append(f"路径 {component_path}")
        if include_points:
            summary_parts.append(f"查询到测点 {point_count} 个")

        return {
            "status": "ok",
            "equipment_id": equipment_id_str,
            "ehm_equipment": _compact_record(
                ehm_equipment,
                ("equipmentId", "name", "code", "source", "sourceDataId", "craftBit", "type", "subType"),
            ),
            "component_id": component_id_str,
            "component": _compact_record(
                component,
                (
                    "id",
                    "name",
                    "machineId",
                    "parentId",
                    "type",
                    "craftBit",
                    "classification",
                    "configInfo",
                ),
            ),
            "machine_id": machine_id,
            "machine": _compact_record(
                machine,
                ("id", "name", "code", "machineCode", "machineName", "typeId", "orgId", "factoryId"),
            ),
            "component_path": component_path,
            "points_scope": "component_and_descendants" if include_children else "direct_component",
            "point_count": point_count,
            "points_truncated": point_count > len(visible_points),
            "points": visible_points,
            "summary": "，".join(summary_parts),
        }
    finally:
        await rpc_client.close()


async def resolve_machine_context_data(
    machine_id: int | str | None = None,
    *,
    equipment_id: int | str | None = None,
    component_id: int | str | None = None,
    access_token: str | None = None,
    include_components: bool = True,
    include_points: bool = True,
    hidden_if_valid: bool = False,
    max_components: int = 50,
    max_points: int = 50,
) -> dict[str, Any]:
    """Resolve machine information, component list, and optional points."""
    machine_id_str = str(machine_id).strip() if machine_id is not None else ""
    input_machine_id = machine_id_str
    equipment_id_str = str(equipment_id).strip() if equipment_id is not None else ""
    component_id_str = str(component_id).strip() if component_id is not None else ""
    resolved_from = "machine_id" if machine_id_str else ""
    mapping_context: dict[str, Any] | None = None

    if equipment_id_str:
        mapping_context = await resolve_component_context_data(
            "",
            equipment_id=equipment_id_str,
            access_token=access_token,
            include_points=False,
            include_children=False,
            hidden_if_valid=hidden_if_valid,
        )
        if mapping_context.get("status") != "ok":
            return {
                **mapping_context,
                "machine_id": machine_id_str,
                "resolved_from": "equipment_id",
                "message": mapping_context.get("message") or "无法通过 EHM 设备ID映射到 InS 设备",
            }
        machine_id_str = _stringify_id(mapping_context.get("machine_id"))
        component_id_str = _stringify_id(mapping_context.get("component_id") or component_id_str)
        resolved_from = "equipment_id"
    elif component_id_str and not machine_id_str:
        mapping_context = await resolve_component_context_data(
            component_id_str,
            access_token=access_token,
            include_points=False,
            include_children=False,
            hidden_if_valid=hidden_if_valid,
        )
        if mapping_context.get("status") != "ok":
            return {
                **mapping_context,
                "machine_id": machine_id_str,
                "resolved_from": "component_id",
                "message": mapping_context.get("message") or "无法通过 componentId 映射到 InS 设备",
            }
        machine_id_str = _stringify_id(mapping_context.get("machine_id"))
        equipment_id_str = _stringify_id(mapping_context.get("equipment_id") or equipment_id_str)
        resolved_from = "component_id"

    if not machine_id_str:
        return {
            "status": "invalid_input",
            "machine_id": machine_id_str,
            "equipment_id": equipment_id_str,
            "component_id": component_id_str,
            "message": "machine_id、equipment_id、component_id 不能同时为空",
        }

    try:
        machine_id_int = int(machine_id_str)
    except (TypeError, ValueError):
        return {
            "status": "invalid_input",
            "machine_id": machine_id_str,
            "message": "machine_id 必须是 InS 设备数字 ID",
        }

    rpc_client = RpcClient()
    try:
        machine_client = MachineServiceClient(rpc_client)
        mapped_machine = (mapping_context or {}).get("machine")
        machine = mapped_machine if isinstance(mapped_machine, dict) else None
        if not machine:
            machine = _first_item(await machine_client.get_machine_info_by_ids([machine_id_int]))

        if not machine and resolved_from == "machine_id" and input_machine_id:
            fallback_context = await resolve_component_context_data(
                "",
                equipment_id=input_machine_id,
                access_token=access_token,
                include_points=False,
                include_children=False,
                hidden_if_valid=hidden_if_valid,
            )
            if fallback_context.get("status") == "ok" and fallback_context.get("machine_id"):
                mapping_context = fallback_context
                equipment_id_str = input_machine_id
                component_id_str = _stringify_id(fallback_context.get("component_id") or component_id_str)
                machine_id_str = _stringify_id(fallback_context.get("machine_id"))
                resolved_from = "machine_id_fallback_equipment_id"
                try:
                    machine_id_int = int(machine_id_str)
                except (TypeError, ValueError):
                    return {
                        "status": "invalid_input",
                        "input_machine_id": input_machine_id,
                        "equipment_id": equipment_id_str,
                        "component_id": component_id_str,
                        "machine_id": machine_id_str,
                        "resolved_from": resolved_from,
                        "message": "EHM 设备映射出的 machine_id 不是数字 ID",
                    }
                mapped_machine = fallback_context.get("machine")
                machine = mapped_machine if isinstance(mapped_machine, dict) else None
                if not machine:
                    machine = _first_item(await machine_client.get_machine_info_by_ids([machine_id_int]))

        if not machine:
            return {
                "status": "not_found",
                "input_machine_id": input_machine_id,
                "equipment_id": equipment_id_str,
                "component_id": component_id_str,
                "machine_id": machine_id_str,
                "resolved_from": resolved_from,
                "message": f"未查询到 machineId={machine_id_str} 对应的设备信息",
            }

        components: list[dict[str, Any]] = []
        if include_components:
            raw_components = await machine_client.get_component_info_by_machine_id(
                machine_id_int,
                hidden_if_valid=hidden_if_valid,
            )
            components = [item for item in raw_components if isinstance(item, dict)]

        points: list[dict[str, Any]] = []
        if include_points:
            point_client = PointServiceClient(rpc_client)
            raw_points = await point_client.get_point_list_by_machine_ids([machine_id_int])
            points = [item for item in raw_points if isinstance(item, dict)]

        visible_components, components_truncated = _compact_records(
            components,
            ("id", "name", "machineId", "parentId", "type", "craftBit", "classification", "configInfo"),
            max_components,
        )
        visible_points, points_truncated = _compact_records(
            points,
            (
                "id",
                "name",
                "machineId",
                "parentId",
                "craftBit",
                "type",
                "moniType",
                "machineName",
                "componentName",
                "sampleName",
                "samplingPointName",
                "syncSourceId",
            ),
            max_points,
        )

        machine_name = machine.get("name") or machine.get("machineName") or machine_id_str
        summary_parts = [f"设备 {machine_name}", f"设备ID {machine_id_str}"]
        if include_components:
            summary_parts.append(f"查询到部件/子设备 {len(components)} 个")
        if include_points:
            summary_parts.append(f"查询到测点 {len(points)} 个")

        return {
            "status": "ok",
            "input_machine_id": input_machine_id,
            "equipment_id": equipment_id_str,
            "component_id": component_id_str,
            "component_path": (mapping_context or {}).get("component_path"),
            "resolved_from": resolved_from,
            "machine_id": machine_id_str,
            "machine": _compact_record(
                machine,
                (
                    "id",
                    "name",
                    "code",
                    "machineCode",
                    "machineName",
                    "typeId",
                    "deviceName",
                    "orgId",
                    "factoryId",
                    "producer",
                ),
            ),
            "component_count": len(components),
            "components_truncated": components_truncated,
            "components": visible_components,
            "point_count": len(points),
            "points_truncated": points_truncated,
            "points": visible_points,
            "summary": "，".join(summary_parts),
        }
    finally:
        await rpc_client.close()


class ResolveComponentContextInput(BaseModel):
    component_id: str = Field(default="", description="InS componentId / 子设备ID。若已知 EHM equipment_id，可留空。")
    equipment_id: str = Field(default="", description="EHM 平台设备ID。工具会先查 sourceDataId，再映射到 InS componentId。")
    include_points: bool = Field(default=True, description="是否包含测点列表。")
    include_children: bool = Field(default=True, description="是否包含下级部件测点。")
    hidden_if_valid: bool = Field(default=False, description="是否启用隐藏过滤。")
    max_points: int = Field(default=50, description="最多返回测点数量，上限 200。")


class ResolveMachineContextInput(BaseModel):
    machine_id: str = Field(default="", description="InS machineId / 设备ID。若只知道 EHM equipment_id，可留空。")
    equipment_id: str = Field(default="", description="EHM 平台设备ID。工具会先查 sourceDataId，再映射到 InS machineId。")
    component_id: str = Field(default="", description="InS componentId / sourceDataId / 子设备ID。工具会先映射到归属 machineId。")
    include_components: bool = Field(default=True, description="是否包含部件/子设备列表。")
    include_points: bool = Field(default=True, description="是否包含设备测点列表。")
    hidden_if_valid: bool = Field(default=False, description="查询部件/子设备时是否启用隐藏过滤。")
    max_components: int = Field(default=50, description="最多返回部件/子设备数量，上限 200。")
    max_points: int = Field(default=50, description="最多返回测点数量，上限 200。")


@tool("resolve_component_context", args_schema=ResolveComponentContextInput)
def resolve_component_context(
    component_id: str = "",
    equipment_id: str = "",
    include_points: bool = True,
    include_children: bool = True,
    hidden_if_valid: bool = False,
    max_points: int = 50,
    runtime: ToolRuntime[ContextT, ThreadState] | None = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Resolve equipment context from a component/sub-device ID.

    Use this when the user provides a componentId/sub-device ID, or when the
    selected defect has an equipment/component ID and you need to know the
    owning device, component path, or related measurement points.

    Args:
        component_id: InS component/sub-device ID.
        equipment_id: EHM equipment ID. When provided without component_id,
            this tool fetches EHM equipment.sourceDataId and uses it as
            component_id.
        include_points: Whether to include measurement points.
        include_children: If true, include points under descendant components.
        hidden_if_valid: Pass through hidden filtering to ins-bus-rpc point APIs.
        max_points: Maximum point records to return, capped at 200.

    Returns:
        JSON string with status, component, machine, component_path, points,
        and a Chinese summary.
    """
    payload = _run_async(
        resolve_component_context_data(
            component_id,
            equipment_id=equipment_id,
            access_token=_runtime_access_token(runtime, config),
            include_points=include_points,
            include_children=include_children,
            hidden_if_valid=hidden_if_valid,
            max_points=max_points,
        )
    )
    return json.dumps(payload, ensure_ascii=False)


@tool("resolve_machine_context", args_schema=ResolveMachineContextInput)
def resolve_machine_context(
    machine_id: str = "",
    equipment_id: str = "",
    component_id: str = "",
    include_components: bool = True,
    include_points: bool = True,
    hidden_if_valid: bool = False,
    max_components: int = 50,
    max_points: int = 50,
    runtime: ToolRuntime[ContextT, ThreadState] | None = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Resolve equipment context from an InS machineId, EHM equipmentId, or componentId.

    Use this when the user asks for owning device basics, component/sub-device
    list, or measurement point metadata. If the selected defect only has an EHM
    equipmentId, pass it as equipment_id; if a model accidentally passes that
    value as machine_id, the tool attempts one EHM equipment fallback. The
    result does not fetch trend, waveform, or diagnosis data.

    Args:
        machine_id: InS machineId / device ID.
        equipment_id: EHM equipment ID from a defect.
        component_id: InS componentId/sourceDataId/sub-device ID.
        include_components: Whether to include component/sub-device records.
        include_points: Whether to include measurement point records.
        hidden_if_valid: Pass through hidden filtering to component lookup.
        max_components: Maximum component records to return, capped at 200.
        max_points: Maximum point records to return, capped at 200.

    Returns:
        JSON string with status, machine, components, points, and a Chinese
        summary.
    """
    payload = _run_async(
        resolve_machine_context_data(
            machine_id,
            equipment_id=equipment_id,
            component_id=component_id,
            access_token=_runtime_access_token(runtime, config),
            include_components=include_components,
            include_points=include_points,
            hidden_if_valid=hidden_if_valid,
            max_components=max_components,
            max_points=max_points,
        )
    )
    return json.dumps(payload, ensure_ascii=False)
