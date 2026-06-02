# 异常研判Agent — 完整实现方案

## 一、整体架构

```
abnormal-judgment (group)                    异常研判导航入口
├── abnormal-judgment--rotating              旋转机组异常研判  ← 本文档覆盖
├── abnormal-judgment--pump                  机泵异常研判
└── abnormal-judgment--reciprocating         往复机异常研判
```

### 后端：复用并扩展SmsAdapter

已有的SmsAdapter只覆盖了3个评估类能力，需要新增异常列表和详情两个能力：

```
已有能力（不动）：
  SmsAdapter
    ├── health.assessment        → SMS /assessment/health
    ├── health.anomaly_statistics → SMS /assessment/anomaly-stats
    └── health.risk_ranking      → SMS /assessment/risk-ranking

新增能力：
  SmsAdapter (扩展)
    ├── abnormal.list            → SMS /api/abnormal/list
    └── abnormal.detail          → SMS /api/abnormal/detail

完整调用链：
  Agent SOUL.md
    → abnormal_get_list / abnormal_get_detail (StructuredTool)
    → AssessmentTools.get_abnormal_list / get_abnormal_detail
    → AssessmentService.get_abnormal_list / get_abnormal_detail
    → CapabilityRouter.route("abnormal.list" / "abnormal.detail")
    → SmsAdapter._handle_abnormal_list / _handle_abnormal_detail
    → httpx → SMS 接口
    → transform → 规范模型
```

### 前端：新增A2UI组件

```
Agent: render_ui(component="abnormal-list-selector", ...)
    ↓
前端 GenUI registry → AbnormalListSelectorBlock
    ↓ 调用 Gateway API
GET /api/abnormal/list （Gateway代理 → SmsAdapter）
    ↓
用户点击选择 → onInteraction(callback_id, {selected: {abnormalId}})
    ↓
Agent收到 ui_interaction → 进入Phase 2研判
```

## 二、改动文件清单

| # | 文件 | 改动类型 | 说明 |
|---|------|----------|------|
| **后端 — SmsAdapter扩展** |
| 1 | `integrations/models/queries.py` | 修改 | 新增 `AbnormalListQuery`、`AbnormalDetailQuery` |
| 2 | `integrations/models/assessment.py` | 修改 | 新增 `AbnormalItem`、`AbnormalDetail`、`AbnormalEvent` 规范模型 |
| 3 | `integrations/adapters/sms/adapter.py` | 修改 | 新增 `_handle_abnormal_list`、`_handle_abnormal_detail` |
| 4 | `integrations/adapters/sms/transform.py` | 修改 | 新增 `transform_abnormal_list`、`transform_abnormal_detail` |
| 5 | `integrations/services/assessment_service.py` | 修改 | 新增 `get_abnormal_list`、`get_abnormal_detail` |
| 6 | `integrations/tools/assessment_tools.py` | 修改 | 新增工具方法 `get_abnormal_list`、`get_abnormal_detail` |
| 7 | `integrations/tools/tool_builder.py` | 修改 | 注册 `abnormal_get_list`、`abnormal_get_detail` StructuredTool |
| **后端 — Gateway代理端点** |
| 8 | `app/gateway/routers/abnormal.py` | 新增 | `GET /api/abnormal/list`、`GET /api/abnormal/detail` |
| **前端 — A2UI组件** |
| 9 | `components/genui/AbnormalListSelectorBlock.tsx` | 新增 | 异常列表选择器A2UI组件 |
| 10 | `core/genui/registry.ts` | 修改 | 注册 `"abnormal-list-selector"` |
| 11 | `core/i18n/locales/zh-CN.ts` | 修改 | 异常选择器相关文案 |
| 12 | `core/i18n/locales/en-US.ts` | 修改 | 异常选择器相关文案 |
| **Agent配置** |
| 13 | `agents/builtin/abnormal-judgment/config.yaml` | 新增 | 父级group Agent |
| 14 | `agents/builtin/abnormal-judgment--rotating/config.yaml` | 新增 | 旋转机组子Agent |
| 15 | `agents/builtin/abnormal-judgment--rotating/SOUL.md` | 新增 | 完整研判工作流 |

## 三、SmsAdapter 扩展

### 3.1 新增 Query 模型

在 `integrations/models/queries.py` 中追加：

```python
@dataclass(frozen=True)
class AbnormalListQuery:
    """Query for abnormal list."""
    tenant_id: str
    current_page: int = 1
    page_size: int = 10
    start_time: int | None = None    # 毫秒时间戳
    end_time: int | None = None      # 毫秒时间戳
    org_id: int = 0
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AbnormalDetailQuery:
    """Query for abnormal detail."""
    tenant_id: str
    abnormal_id: str
    extra_params: dict[str, Any] = field(default_factory=dict)
```

### 3.2 新增规范模型

在 `integrations/models/assessment.py` 中追加。**关键设计决策**：不做大而全的字段映射，只保留研判所需的核心字段，避免模型与SMS接口耦合过紧。

```python
@dataclass(frozen=True)
class AbnormalPoint:
    """异常关联的测点信息"""
    point_id: str
    point_name: str
    value_type: str
    point_type: int


@dataclass(frozen=True)
class AbnormalEvent:
    """单个异常事件"""
    time: int                     # 毫秒时间戳
    health: float | None
    type: str                     # sensor / t / w / k / d
    run_status: str
    event_level: int
    desc: str
    points: tuple[AbnormalPoint, ...]
    time_range_start: int          # jumpParams.startTime
    time_range_end: int            # jumpParams.endTime
    factory_id: str


@dataclass(frozen=True)
class AbnormalItem:
    """异常列表中的一条"""
    abnormal_id: str
    process_status: str
    mac_path: str
    mac_name: str
    component_name: str
    mac_id: str
    component_id: str
    serious_health: float
    latest_health: float
    first_event_time: int
    lastest_event_time: int
    serious_level: int
    latest_level: int
    event_count: int
    recorder: str
    run_status: str
    process_duration: int
    mac_type: int
    defect_transfer_status: int
    fault_transfer_status: int


@dataclass(frozen=True)
class AbnormalDetail:
    """异常详情"""
    abnormal_id: str
    process_status: str
    mac_path: str
    mac_name: str
    component_name: str
    events: tuple[AbnormalEvent, ...]
    logs: tuple[dict[str, Any], ...]
    ai_analyse: dict[str, Any] | None = None
    risk_assessment: dict[str, Any] | None = None
    # 以下字段从列表侧带入（详情接口不返回）
    mac_id: str = ""
    component_id: str = ""
```

### 3.3 新增 Transform 函数

在 `integrations/adapters/sms/transform.py` 中追加：

```python
def transform_abnormal_list(
    raw_data: dict[str, Any],
    system_key: str,
) -> tuple[AbnormalItem, ...]:
    """Transform SMS abnormal list response into AbnormalItem tuple."""
    provenance = _build_provenance(system_key, "abnormal.list")
    rows = raw_data.get("rows") or raw_data.get("data", {}).get("rows") or []
    items: list[AbnormalItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append(AbnormalItem(
            abnormal_id=str(row.get("id", "")),
            process_status=str(row.get("processStatus", "")),
            mac_path=str(row.get("macPath", "")),
            mac_name=str(row.get("macName", "")),
            component_name=str(row.get("componentName", "")),
            mac_id=str(row.get("macId", "")),
            component_id=str(row.get("componentId", "")),
            serious_health=float(row.get("seriousHealth", 0)),
            latest_health=float(row.get("latestHealth", 0)),
            first_event_time=int(row.get("firstEventTime", 0)),
            lastest_event_time=int(row.get("lastestEventTime", 0)),
            serious_level=int(row.get("seriousLevel", 0)),
            latest_level=int(row.get("latestLevel", 0)),
            event_count=int(row.get("eventCount", 0)),
            recorder=str(row.get("recorder", "")),
            run_status=str(row.get("runStatus", "")),
            process_duration=int(row.get("processDuration", 0)),
            mac_type=int(row.get("macType", 1)),
            defect_transfer_status=int(row.get("defectTransferStatus", 0)),
            fault_transfer_status=int(row.get("faultTransferStatus", 0)),
        ))
    return tuple(items)


def transform_abnormal_detail(
    raw_data: dict[str, Any],
    system_key: str,
    abnormal_id: str = "",
    mac_id: str = "",
    component_id: str = "",
) -> AbnormalDetail:
    """Transform SMS abnormal detail response into AbnormalDetail."""
    provenance = _build_provenance(system_key, "abnormal.detail")
    data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else {}

    events: list[AbnormalEvent] = []
    for evt in data.get("events") or []:
        points: list[AbnormalPoint] = []
        jp = evt.get("jumpParams", {}) or {}
        for pt in jp.get("points") or []:
            points.append(AbnormalPoint(
                point_id=str(pt.get("pointId", "")),
                point_name=str(pt.get("pointName", "")),
                value_type=str(pt.get("valueType", "")),
                point_type=int(pt.get("pointType", 0)),
            ))
        events.append(AbnormalEvent(
            time=int(evt.get("time", 0)),
            health=float(evt["health"]) if evt.get("health") is not None else None,
            type=str(evt.get("type", "")),
            run_status=str(evt.get("runStatus", "")),
            event_level=int(evt.get("eventLevel", 0)),
            desc=str(evt.get("desc", "")),
            points=tuple(points),
            time_range_start=int(jp.get("startTime", 0)),
            time_range_end=int(jp.get("endTime", 0)),
            factory_id=str(jp.get("factoryId", "")),
        ))

    return AbnormalDetail(
        abnormal_id=abnormal_id,
        process_status=str(data.get("processStatus", "")),
        mac_path=str(data.get("macPath", "")),
        mac_name=str(data.get("macName", "")),
        component_name=str(data.get("componentName", "")),
        events=tuple(events),
        logs=tuple(data.get("logs") or []),
        ai_analyse=data.get("aiAnalyse"),
        risk_assessment=data.get("riskAssessment"),
        mac_id=mac_id,
        component_id=component_id,
    )
```

### 3.4 扩展 SmsAdapter

在 `integrations/adapters/sms/adapter.py` 中：

**1) 注册新 capability handler：**

```python
# 在 call() 方法的 handlers dict 中追加：
handlers = {
    "health.assessment": self._handle_health_assessment,
    "health.anomaly_statistics": self._handle_anomaly_statistics,
    "health.risk_ranking": self._handle_risk_ranking,
    # 新增
    "abnormal.list": self._handle_abnormal_list,
    "abnormal.detail": self._handle_abnormal_detail,
}
```

**2) 新增 `_handle_abnormal_list`：**

```python
async def _handle_abnormal_list(self, query: Any, auth_context: AuthContext) -> Any:
    if self._http is None:
        raise IntegrationError(
            message="HTTP client not initialized",
            system_key=self._config.system_key,
        )

    params: dict[str, Any] = {
        "currentPage": getattr(query, "current_page", 1),
        "pageSize": getattr(query, "page_size", 10),
        "orgId": getattr(query, "org_id", 0),
    }
    if hasattr(query, "start_time") and query.start_time:
        params["startTime"] = query.start_time
    if hasattr(query, "end_time") and query.end_time:
        params["endTime"] = query.end_time
    if hasattr(query, "extra_params"):
        params.update(query.extra_params)

    response = await self._http.get(
        "/api/abnormal/list",
        params=params,
        headers=self._build_headers(auth_context),
    )
    response.raise_for_status()
    raw_data = response.json()
    data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data
    return transform_abnormal_list(data, self._config.system_key)
```

**3) 新增 `_handle_abnormal_detail`：**

```python
async def _handle_abnormal_detail(self, query: Any, auth_context: AuthContext) -> Any:
    if self._http is None:
        raise IntegrationError(
            message="HTTP client not initialized",
            system_key=self._config.system_key,
        )

    abnormal_id = getattr(query, "abnormal_id", "")
    if not abnormal_id:
        raise IntegrationError(
            message="abnormal_id is required",
            system_key=self._config.system_key,
            capability_key="abnormal.detail",
        )

    params: dict[str, Any] = {"abnormalId": abnormal_id}
    if hasattr(query, "extra_params"):
        params.update(query.extra_params)

    response = await self._http.get(
        "/api/abnormal/detail",
        params=params,
        headers=self._build_headers(auth_context),
    )
    response.raise_for_status()
    raw_data = response.json()
    data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data
    return transform_abnormal_detail(data, self._config.system_key, abnormal_id=abnormal_id)
```

### 3.5 扩展 AssessmentService

在 `integrations/services/assessment_service.py` 中追加：

```python
async def get_abnormal_list(
    self, query: AbnormalListQuery, auth_context: AuthContext,
) -> ServiceResult:
    logger.info("Getting abnormal list: page=%s", query.current_page)
    return await self._router.route(
        capability_key="abnormal.list",
        query=query,
        auth_context=auth_context,
    )

async def get_abnormal_detail(
    self, query: AbnormalDetailQuery, auth_context: AuthContext,
) -> ServiceResult:
    logger.info("Getting abnormal detail: id=%s", query.abnormal_id)
    return await self._router.route(
        capability_key="abnormal.detail",
        query=query,
        auth_context=auth_context,
    )
```

### 3.6 扩展 AssessmentTools

在 `integrations/tools/assessment_tools.py` 中追加两个工具方法。工具方法的返回是格式化文本（供Agent直接消费），入参精简为Agent可直接填写的自然参数：

```python
async def get_abnormal_list(
    self,
    tenant_id: str,
    user_id: str,
    current_page: int = 1,
    page_size: int = 10,
    start_time: int | None = None,
    end_time: int | None = None,
    org_id: int = 0,
    token: str | None = None,
) -> str:
    """获取异常列表。

    Args:
        tenant_id: 租户ID
        user_id: 用户ID
        current_page: 当前页码
        page_size: 每页条数
        start_time: 开始时间（毫秒时间戳，默认30天前）
        end_time: 结束时间（毫秒时间戳，默认当前）
        org_id: 组织ID（默认0）
        token: 用户访问令牌

    Returns:
        格式化的异常列表字符串（JSON）
    """
    try:
        import time
        if end_time is None:
            end_time = int(time.time() * 1000)
        if start_time is None:
            start_time = end_time - 30 * 24 * 3600 * 1000

        query = AbnormalListQuery(
            tenant_id=tenant_id,
            current_page=current_page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
            org_id=org_id,
        )
        auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
        result = await self._service.get_abnormal_list(query, auth_context)
        items = result.data

        if not items:
            return json.dumps({"total": 0, "items": []}, ensure_ascii=False)

        return json.dumps({
            "total": len(items),
            "items": [
                {
                    "abnormal_id": item.abnormal_id,
                    "mac_path": item.mac_path,
                    "mac_name": item.mac_name,
                    "component_name": item.component_name,
                    "latest_health": item.latest_health,
                    "latest_level": item.latest_level,
                    "event_count": item.event_count,
                    "first_event_time": item.first_event_time,
                    "process_status": item.process_status,
                    "run_status": item.run_status,
                    "mac_type": item.mac_type,
                }
                for item in items
            ]
        }, ensure_ascii=False)

    except IntegrationError as e:
        logger.error("Failed to get abnormal list: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def get_abnormal_detail(
    self,
    tenant_id: str,
    user_id: str,
    abnormal_id: str,
    mac_id: str = "",
    component_id: str = "",
    token: str | None = None,
) -> str:
    """获取异常详情。

    Args:
        tenant_id: 租户ID
        user_id: 用户ID
        abnormal_id: 异常ID
        mac_id: 设备ID（从列表数据中补充，详情接口不返回）
        component_id: 子设备ID（从列表数据中补充，详情接口不返回）
        token: 用户访问令牌

    Returns:
        格式化的异常详情字符串（JSON）
    """
    try:
        query = AbnormalDetailQuery(
            tenant_id=tenant_id,
            abnormal_id=abnormal_id,
        )
        auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
        result = await self._service.get_abnormal_detail(query, auth_context)
        detail = result.data
        # 补充列表侧字段
        detail = replace(detail, mac_id=mac_id, component_id=component_id)

        return json.dumps({
            "abnormal_id": detail.abnormal_id,
            "mac_path": detail.mac_path,
            "mac_name": detail.mac_name,
            "component_name": detail.component_name,
            "mac_id": detail.mac_id,
            "component_id": detail.component_id,
            "process_status": detail.process_status,
            "events": [
                {
                    "time": e.time,
                    "health": e.health,
                    "type": e.type,
                    "run_status": e.run_status,
                    "event_level": e.event_level,
                    "desc": e.desc,
                    "points": [
                        {"point_id": p.point_id, "point_name": p.point_name,
                         "value_type": p.value_type, "point_type": p.point_type}
                        for p in e.points
                    ],
                    "time_range_start": e.time_range_start,
                    "time_range_end": e.time_range_end,
                    "factory_id": e.factory_id,
                }
                for e in detail.events
            ],
            "logs": list(detail.logs),
            "ai_analyse": detail.ai_analyse,
            "risk_assessment": detail.risk_assessment,
        }, ensure_ascii=False)

    except IntegrationError as e:
        logger.error("Failed to get abnormal detail: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

### 3.7 扩展 Tool Builder

在 `integrations/tools/tool_builder.py` 中注册新的 StructuredTool：

```python
# 新增 Input Schema
class AbnormalListInput(BaseModel):
    current_page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=10, description="每页条数")
    start_time: int | None = Field(default=None, description="开始时间（毫秒时间戳）")
    end_time: int | None = Field(default=None, description="结束时间（毫秒时间戳）")

class AbnormalDetailInput(BaseModel):
    abnormal_id: str = Field(description="异常ID")
    mac_id: str = Field(default="", description="设备ID")
    component_id: str = Field(default="", description="子设备ID")

# 在 build_integration_tools() 中注册
if _should_include(data_tools, "abnormal_get_list", "assessment"):
    if assessment_tools:
        tools.append(StructuredTool(
            name="abnormal_get_list",
            description="获取SMS系统的设备异常列表，支持分页和时间范围过滤",
            args_schema=AbnormalListInput,
            coroutine=_make_coro(
                assessment_tools.get_abnormal_list, tenant_id, user_id,
                _identity_transform, token,
            ),
        ))

if _should_include(data_tools, "abnormal_get_detail", "assessment"):
    if assessment_tools:
        tools.append(StructuredTool(
            name="abnormal_get_detail",
            description="获取指定异常的详情，包含所有异常事件、关联测点和操作日志",
            args_schema=AbnormalDetailInput,
            coroutine=_make_coro(
                assessment_tools.get_abnormal_detail, tenant_id, user_id,
                _identity_transform, token,
            ),
        ))
```

## 四、Gateway API 代理端点

新增 `app/gateway/routers/abnormal.py`，供前端 A2UI 组件直接调用：

```python
"""Abnormal list/detail proxy endpoints.
前端 A2UI 组件通过此端点获取异常数据，内部代理到 SmsAdapter。
"""

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/abnormal", tags=["abnormal"])


async def _get_sms_adapter(request: Request):
    """从集成注册表获取SmsAdapter实例"""
    from deerflow.integrations.registry import get_integration_registry
    registry = get_integration_registry()
    # 查找 sms 类型的 adapter
    for adapter in registry.list_all():
        if adapter.system_type == "sms":
            return adapter
    return None


@router.get("/list")
async def abnormal_list(
    request: Request,
    current_page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    start_time: int | None = Query(None),
    end_time: int | None = Query(None),
    org_id: int = Query(0),
):
    """获取异常列表，代理到SmsAdapter"""
    adapter = await _get_sms_adapter(request)
    if adapter is None:
        raise HTTPException(status_code=503, detail="SMS adapter not available")

    from deerflow.integrations.models.queries import AbnormalListQuery
    from deerflow.integrations.adapters.base import AuthContext

    query = AbnormalListQuery(
        tenant_id="default",
        current_page=current_page,
        page_size=page_size,
        start_time=start_time,
        end_time=end_time,
        org_id=org_id,
    )
    auth = AuthContext(tenant_id="default", user_id="", token=None)
    try:
        items = await adapter.call("abnormal.list", query, auth)
        return {
            "items": [
                {
                    "abnormal_id": item.abnormal_id,
                    "mac_path": item.mac_path,
                    "mac_name": item.mac_name,
                    "component_name": item.component_name,
                    "latest_health": item.latest_health,
                    "latest_level": item.latest_level,
                    "event_count": item.event_count,
                    "first_event_time": item.first_event_time,
                    "lastest_event_time": item.lastest_event_time,
                    "process_status": item.process_status,
                    "run_status": item.run_status,
                    "mac_type": item.mac_type,
                    "mac_id": item.mac_id,
                    "component_id": item.component_id,
                }
                for item in items
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/detail")
async def abnormal_detail(
    request: Request,
    abnormal_id: str = Query(..., description="异常ID"),
):
    """获取异常详情，代理到SmsAdapter"""
    adapter = await _get_sms_adapter(request)
    if adapter is None:
        raise HTTPException(status_code=503, detail="SMS adapter not available")

    from deerflow.integrations.models.queries import AbnormalDetailQuery
    from deerflow.integrations.adapters.base import AuthContext

    query = AbnormalDetailQuery(tenant_id="default", abnormal_id=abnormal_id)
    auth = AuthContext(tenant_id="default", user_id="", token=None)
    try:
        detail = await adapter.call("abnormal.detail", query, auth)
        return {
            "abnormal_id": detail.abnormal_id,
            "mac_path": detail.mac_path,
            "mac_name": detail.mac_name,
            "component_name": detail.component_name,
            "process_status": detail.process_status,
            "events": [
                {
                    "time": e.time, "health": e.health, "type": e.type,
                    "run_status": e.run_status, "event_level": e.event_level,
                    "desc": e.desc, "factory_id": e.factory_id,
                    "time_range_start": e.time_range_start,
                    "time_range_end": e.time_range_end,
                    "points": [{"point_id": p.point_id, "point_name": p.point_name,
                                "value_type": p.value_type, "point_type": p.point_type}
                               for p in e.points],
                }
                for e in detail.events
            ],
            "logs": list(detail.logs),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
```

在 `app/gateway/app.py` 中注册路由：

```python
from app.gateway.routers.abnormal import router as abnormal_router
app.include_router(abnormal_router)
```

## 五、前端 A2UI 组件

### 5.1 AbnormalListSelectorBlock.tsx

参照 `SubDeviceSelectorBlock.tsx` 的模式：

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import type { InteractionState } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";

interface AbnormalItem {
  abnormal_id: string;
  mac_path: string;
  mac_name: string;
  component_name: string;
  latest_health: number;
  latest_level: number;
  event_count: number;
  first_event_time: number;
  process_status: string;
  run_status: string;
  mac_type: number;
}

interface AbnormalListSelectorBlockProps {
  block: {
    block_id?: string;
    props: {
      title?: string;
      start_time?: number;  // 默认30天前
      end_time?: number;    // 默认当前
      org_id?: number;      // 默认0
    };
    callback_id?: string;
    interactionState?: InteractionState;
    onInteraction?: (
      callbackId: string,
      payload: Record<string, unknown>,
      blockId?: string,
    ) => void;
  };
}

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

function formatTimestamp(ms: number): string {
  return new Date(ms).toLocaleString();
}

const LEVEL_STYLE: Record<number, string> = {
  60: "text-red-700 bg-red-100",
  40: "text-orange-700 bg-orange-100",
  20: "text-yellow-700 bg-yellow-100",
  0: "text-gray-500 bg-gray-100",
};

function getLevelStyle(level: number): string {
  if (level >= 60) return LEVEL_STYLE[60]!;
  if (level >= 40) return LEVEL_STYLE[40]!;
  if (level >= 20) return LEVEL_STYLE[20]!;
  return LEVEL_STYLE[0]!;
}

export default function AbnormalListSelectorBlock({
  block,
}: AbnormalListSelectorBlockProps) {
  const { t } = useI18n();
  const { block_id, props, callback_id, interactionState, onInteraction } = block;
  const { title, start_time, end_time, org_id = 0 } = props;

  const [items, setItems] = useState<AbnormalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const isDisabled =
    interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired" ||
    interactionState?.status === "readonly";

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("current_page", "1");
      params.set("page_size", "50");
      params.set("org_id", String(org_id));
      if (start_time) params.set("start_time", String(start_time));
      if (end_time) params.set("end_time", String(end_time));
      const baseUrl = getBaseUrl();
      const res = await fetch(`${baseUrl}/api/abnormal/list?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setItems(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch abnormal list");
    } finally {
      setLoading(false);
    }
  }, [start_time, end_time, org_id]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  const handleSelect = (item: AbnormalItem) => {
    if (isDisabled) return;
    setSelectedId(item.abnormal_id);
    if (callback_id && onInteraction) {
      onInteraction(
        callback_id,
        {
          selected: {
            abnormal_id: item.abnormal_id,
            mac_id: item.mac_id,
            component_id: item.component_id,
            mac_name: item.mac_name,
            component_name: item.component_name,
            mac_path: item.mac_path,
            mac_type: item.mac_type,
          },
        },
        block_id,
      );
    }
  };

  if (interactionState?.status === "submitted") return null;

  if (interactionState?.status === "expired") {
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4">
        <p className="text-sm text-yellow-800">该选择器已过期</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4" role="region">
      {title && <h3 className="mb-3 text-sm font-medium">{title}</h3>}

      {loading ? (
        <div className="flex h-60 items-center justify-center text-xs text-muted-foreground">
          正在加载异常列表…
        </div>
      ) : error ? (
        <div className="flex h-60 items-center justify-center text-xs text-red-600">
          加载失败: {error}
          <button type="button" className="ml-2 underline" onClick={fetchList}>
            重试
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-60 items-center justify-center text-xs text-muted-foreground">
          当前时间范围内无异常记录
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="py-2 px-2 text-left font-medium">设备</th>
                <th className="py-2 px-2 text-left font-medium">子设备</th>
                <th className="py-2 px-2 text-right font-medium">健康值</th>
                <th className="py-2 px-2 text-center font-medium">等级</th>
                <th className="py-2 px-2 text-center font-medium">事件数</th>
                <th className="py-2 px-2 text-left font-medium">首次异常</th>
                <th className="py-2 px-2 text-center font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.abnormal_id}
                  className={`cursor-pointer border-b transition-colors hover:bg-muted/50 ${
                    selectedId === item.abnormal_id ? "bg-primary/10" : ""
                  }`}
                  onClick={() => handleSelect(item)}
                >
                  <td className="py-2 px-2">
                    <div className="max-w-[200px] truncate font-medium" title={item.mac_name}>
                      {item.mac_name}
                    </div>
                    <div className="max-w-[200px] truncate text-muted-foreground" title={item.mac_path}>
                      {item.mac_path}
                    </div>
                  </td>
                  <td className="py-2 px-2 max-w-[120px] truncate">{item.component_name}</td>
                  <td className="py-2 px-2 text-right">
                    <span className={item.latest_health >= 80 ? "text-green-600" : item.latest_health >= 60 ? "text-yellow-600" : "text-red-600"}>
                      {item.latest_health}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className={`rounded px-1.5 py-0.5 text-xs ${getLevelStyle(item.latest_level)}`}>
                      {item.latest_level}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-center">{item.event_count}</td>
                  <td className="py-2 px-2 text-muted-foreground text-xs">
                    {formatTimestamp(item.first_event_time)}
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className={item.process_status === "todo" ? "text-red-600" : "text-green-600"}>
                      {item.process_status === "todo" ? "待处理" : item.process_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {interactionState?.status === "error" && (
        <p className="mt-2 text-xs text-red-600" role="alert">{interactionState.error}</p>
      )}
    </div>
  );
}
```

### 5.2 注册到 GenUI Registry

在 `core/genui/registry.ts` 的 `COMPONENT_REGISTRY` 中追加：

```typescript
"abnormal-list-selector": () => import("@/components/genui/AbnormalListSelectorBlock") as any,
```

## 六、Agent 配置文件

### 6.1 父级Group

```yaml
# agents/builtin/abnormal-judgment/config.yaml
name: abnormal-judgment
display_name: "异常研判"
description: "对设备异常事件进行智能研判，识别根因、评估风险、给出处置建议，支持关联故障诊断深度分析"
icon: "🔍"
type: group
order: 2
model: null
tool_groups:
  - bash
exclude_tools: []
skills: []
tags:
  - abnormal
  - judgment
  - diagnosis
```

### 6.2 旋转机组子Agent

```yaml
# agents/builtin/abnormal-judgment--rotating/config.yaml
name: abnormal-judgment--rotating
display_name: "旋转机组异常研判"
description: "汽轮机 / 离心 / 轴流 / 齿轮 / 螺杆压缩机 / 齿轮箱的异常事件研判"
icon: "⚙️"
parent: abnormal-judgment
order: 1
model: null
plan_mode: true
tool_groups:
  - bash
  - monitoring
  - assessment        # ← 关键：加载 assessment 工具组，获得 abnormal_get_list / abnormal_get_detail
exclude_tools: []
skills:
  - rotating-device-context
  - vibration-fault-diagnosis
mcp_servers: null
tags:
  - abnormal
  - judgment
  - rotating
  - turbine
  - compressor
starters:
  - label: "研判旋转机组异常"
    prompt: "查看最近的旋转机组异常事件并进行研判"
    auto_start: true
```

## 七、SOUL.md — 旋转机组异常研判工作流

### Phase 1：渲染异常列表选择器

```markdown
## 首次进入：渲染异常列表选择器并停止

当用户要求研判异常但当前消息不是 `ui_interaction` 时，调用 `render_ui` 创建异常列表选择器：

```json
{
  "component": "abnormal-list-selector",
  "action": "create",
  "interactive": true,
  "callback_id": "ab-list-select",
  "callback_timeout_ms": 600000,
  "props": {
    "title": "旋转机组异常研判 · 选择需要研判的异常",
    "org_id": 0
  }
}
```

调用后只回复一句"请选择需要研判的异常事件后提交。"并立即停止。**严禁在此轮渲染后续表单或调用任何工具**。
```

### Phase 2：接收选择 → 拉详情

```markdown
## 异常列表选择器回调：拉取详情并开始研判

当收到 `ui_interaction` 且 `callback_id` 为 `ab-list-select` 时：

1. 从 `payload.selected` 提取：
   - `abnormal_id`
   - `mac_id`、`component_id`
   - `mac_name`、`component_name`、`mac_path`
   - `mac_type`

2. 校验 `mac_type`：
   - `mac_type == 1` → 旋转机组，继续
   - `mac_type != 1` → markdown提示"该异常设备类型为{type}，不在旋转机组研判范围内"，终止

3. 调用 `abnormal_get_detail(abnormal_id, mac_id, component_id)` 获取详情

4. 解析返回JSON → 进入Phase 3
```

### Phase 3：分级数据拉取

根据事件类型和严重等级，从监测系统拉取对应深度数据。

```markdown
## 数据拉取策略

### 测点ID映射
SMS异常接口返回的 pointId（如"1706041457263000015"）可直接作为
measurement_point_id 传入 monitoring_get_trend / monitoring_get_waveform。
asset_id 使用 mac_id。pointType（如83）暗示 endpoint_series="8k"，
监测工具内部自动路由。

### 分级策略

Level 1 — 快速筛查（eventLevel ≤ 20，单点偶发，type=sensor）
  monitoring_get_trend(pointId, startTime, endTime)

Level 2 — 标准研判（eventLevel 21-40，type=t/w）
  monitoring_get_trend(所有关联pointId, startTime, endTime)
  + monitoring_get_waveform(主异常pointId, captured_at=异常时刻)
  + monitoring_get_alarm_history(macId, startTime-7d, endTime)

Level 3 — 深度诊断（eventLevel > 40，type=k/d，或多点同时触发）
  Level 2 全部数据
  + monitoring_get_trend(长窗口: startTime-30d, endTime)

### 并行拉取
同一异常的所有数据请求必须并行发出，不允许串行等待。用 bash
同时发起多个 monitoring_get_* 调用。

### 时间窗口

| 异常类型 | 趋势窗口 | 原因 |
|:---|:---|:---|
| sensor | 异常前后各30min | 判断跳变是否为瞬时 |
| t | 异常前后各2h | 看超限前兆和恢复 |
| w | 异常前后各1h | 看波动持续特征 |
| k | 异常前30d | 长周期退化拟合 |
| d | 异常前后各30min | 曲线对比 |
```

### Phase 4：逐事件研判

针对每种异常类型，根据拉回的监测数据执行差异化研判。

```markdown
## 逐事件研判

### sensor — 传感器异常
研判目标：判断是否传感器硬件故障。

1. 同位置多测点互校：同子设备其他测点是否同步跳变？
   - X/Y同时跳变 → 倾向真实物理变化
   - 仅单个测点 → 倾向传感器故障
2. 跳变形态：瞬时阶跃/数值冻结/归零或超量程
3. 与 runStatus 关联：无运行状态变化 → 传感器故障概率↑

### t — 阈值超限
研判目标：评估是否代表真实设备劣化。

1. 超限幅度与持续时间：
   - 轻微超限(<10%)且短时(<5min) → 可能是工况波动
   - 大幅超限(>30%)或持续(>30min) → 倾向真实劣化
2. 多点一致性：
   - 联端X/Y同步超限+非联端也超限 → 转子本身问题
   - 仅联端超限 → 联轴节/对中问题
   - 仅单个测点 → 测点局部问题
3. 频谱特征（从waveform提取）：
   - 1X主导 → 不平衡/热弯曲/临界响应
   - 2X主导 → 不对中
   - 0.3-0.8X → 油膜涡动/旋转失速
   - 高频分量 → 轴承/齿轮缺陷
4. 趋势走向：超限后恢复 vs 持续高位

### w — 波动异常
研判目标：区分正常工况波动和异常振荡。

1. 波动频率匹配（从频谱提取）
2. 波动幅度：<20%正常 vs >50%异常
3. 与工艺参数关联

### k — 趋势异常
研判目标：判断劣化趋势速度。

1. 30天趋势线性回归斜率
2. 剩余时间外推（到达报警阈值）
3. 同类设备2σ对比

### d — 升速曲线偏差
研判目标：判断启停机特性异常。

1. 偏差模式：临界区/低速/高速/整体
2. 与历史3-5次启停机对比

### 输出格式
每个事件输出结构化判定：
{
  "event_type": "t",
  "verdict": "real_fault",
  "sub_category": "unbalance",
  "confidence": 0.85,
  "reasoning": "...",
  "evidence": ["..."],
  "severity": "medium",
  "suspected_fault_type": "unbalance_1x"
}
```

### Phase 5：综合研判

```markdown
## 综合研判

### 多事件汇总
一个abnormalId可包含多个events。综合所有事件研判结果：

- 至少1个非sensor事件confidence ≥ 0.7 → real_fault
- 最高confidence在0.4-0.7之间 → suspected
- 所有事件都是sensor故障或confidence < 0.4 → false_alarm

### 严重程度映射
- eventLevel ≥ 60 → critical
- eventLevel 41-59 → high
- eventLevel 21-40 → medium
- eventLevel ≤ 20 → low

### 综合结论输出格式
{
  "abnormal_id": "...",
  "overall_verdict": "real_fault",
  "overall_confidence": 0.85,
  "severity": "medium",
  "suspected_fault_type": "unbalance_1x",
  "events_judgment": [...],
  "recommendations": {
    "operation": "...",
    "maintenance": "..."
  }
}
```

### Phase 6：渲染研判报告

```markdown
## 渲染研判报告

按以下顺序调用 render_ui：

1. card（设备概览）：title={macName}，value={latestHealth}，subtitle={macPath}
2. table（事件研判明细）：每行一个event的type/desc/level/verdict/confidence
3. markdown（综合结论+证据+建议）

判断结果写入 /mnt/user-data/outputs/abnormal_judgment_result.json
用于后续handoff携带和审计追溯。
```

### Phase 7：Handoff — 触发故障诊断Agent

```markdown
## 触发Handoff到故障诊断Agent

### 触发条件（全部满足才触发）
1. overall_verdict == "real_fault"
2. overall_confidence ≥ 0.7
3. suspected_fault_type 非空

不满足条件的异常（false_alarm / suspected）不触发Handoff，
正常结案即可。

### Handoff 输出

调用 render_ui 输出 agent_handoff 块：

```json
{
  "component": "agent_handoff",
  "action": "create",
  "sequence": 99,
  "props": {
    "target_agent": "fault-diagnosis--rotating",
    "target_display_name": "旋转机组故障诊断",
    "target_icon": "⚙️",
    "message": "该异常判定为真实故障（{suspected_fault_type}，置信度{confidence}%），建议调用旋转机组故障诊断进行深度根因分析。",
    "handoff_data": {
      "source_agent": "abnormal-judgment--rotating",
      "abnormal_id": "{abnormalId}",
      "equipment": {
        "mac_id": "{macId}",
        "component_id": "{componentId}",
        "factory_id": "{factoryId}",
        "mac_name": "{macName}",
        "mac_path": "{macPath}",
        "component_name": "{componentName}",
        "mac_type": 1
      },
      "events": [{完整events数组，包含type/level/desc/points/time}],
      "judgment": {
        "conclusion": "{综合结论文本}",
        "confidence": 0.85,
        "suspected_fault_type": "unbalance_1x",
        "severity": "medium",
        "evidence": ["证据1", "证据2"],
        "health_score": 84.0,
        "run_status": "normal"
      }
    }
  }
}
```

Handoff数据包涵了故障诊断Agent跳过初始化两个步骤（选设备、选时间）
所需的全部参数。故障诊断Agent收到后直接从拉设备树开始诊断。
```

---

## 八、跨Agent交互：故障诊断Agent的Handoff接收端

### 8.1 Handoff 入口逻辑

在 `fault-diagnosis--rotating/SOUL.md` **最前面**增加以下章节：

```markdown
# 旋转机组故障诊断

## Handoff模式：来自异常研判Agent的转交

当用户消息的 `additional_kwargs` 中存在 `handoff` 字段时，
说明这是一个从异常研判Agent转交过来的诊断请求。

### 检测

读取 `additional_kwargs.handoff`，检查 `equipment.mac_id` 和 `events` 字段。
两者都存在且非空 → 进入Handoff模式。

### 校验

用 Python 校验必填字段：
```bash
python -c "
import json, sys
# 从最近一条HumanMessage的additional_kwargs中读取handoff
# （此处由Agent从消息中提取后校验）
required = [
    ('equipment.mac_id', '设备ID'),
    ('equipment.component_id', '子设备ID'),
    ('equipment.component_name', '子设备名称'),
    ('events[0].time', '异常时间'),
    ('judgment.conclusion', '研判结论'),
]
# 缺失任一字段 → markdown报告并终止
"
```

### 跳过初始化，直接进入诊断

校验通过后：

1. **组装参数**（不渲染任何表单）：
   - machineId = handoff.equipment.mac_id
   - componentId = handoff.equipment.component_id
   - componentName = handoff.equipment.component_name
   - 从 handoff.events[0].time（毫秒时间戳）推导诊断时间：
     diagnosis_date = YYYY-MM-DD
     diagnosis_hour = H (0-23)
     start_iso = f"{diagnosis_date}T{H:02d}:00:00"
     end_iso = f"{diagnosis_date}T{H:02d}:59:59"

2. **简短告知用户**：
   > 收到异常研判Agent的转交，已自动填充：
   > - 设备：{componentName}
   > - 诊断时间：{diagnosis_date} {diagnosis_hour}:00
   > - 疑似故障方向：{suspected_fault_type}
   >
   > 正在开始深度诊断…

3. **直接跳转到 Step 3**（拉设备树）：
   ```bash
   python /opt/features-tool/tools/device_analysis.py "{machineId}" --output /mnt/user-data/outputs/device_tree_raw.json
   ```
   然后按 rotating-device-context skill 生成 device_context.json。

4. **执行规则诊断**（Step 5）：
   ```bash
   python /mnt/skills/custom/rotating-fault-diagnosis/scripts/run_rotating_rule_diagnosis.py \
     --device-id "{machineId}" \
     --sub-device-id "{componentId}" \
     --diagnosis-time "{start_iso}" \
     --output /mnt/user-data/outputs/rotating_rule_result.json
   ```

5. **后续步骤**（Step 6-8）：报告渲染 + 导出 + 建闭环单，
   与正常流程完全一致。

### 禁止事项

- ❌ 禁止渲染 sub-device-selector
- ❌ 禁止渲染诊断时间表单
- ❌ 禁止让用户重新选择设备或时间
- ❌ 禁止忽略 handoff 上下文中的 suspected_fault_type

### Handoff 模式下的报告标注

在最终诊断报告的顶部增加来源说明：

> **诊断来源**：异常研判Agent转交（异常ID: {abnormal_id}）
> **初始研判方向**：{suspected_fault_type}（置信度 {confidence}%）
> **转交原因**：{conclusion}

### 与原流程的对照

| 步骤 | 正常模式 | Handoff模式 |
|:---|:---|:---|
| Step 1 选设备 | render_ui(sub-device-selector) | **跳过**，使用handoff数据 |
| Step 2 选时间 | render_ui(form) | **跳过**，从events[0].time推导 |
| Step 3 拉设备树 | device_analysis.py | 直接执行（参数来自handoff） |
| Step 4 device_context | rotating-device-context skill | 同正常流程 |
| Step 5 规则诊断 | run_rotating_rule_diagnosis.py | 同正常流程，增加 --focus 策略 |
| Step 6-8 报告 | 渲染+导出+建单 | 同正常流程，增加来源标注 |
```

### 8.2 Handoff 数据契约

异常研判Agent输出的 `handoff_data` 与故障诊断Agent的对应关系：

```
handoff_data                      故障诊断Agent使用                   替代的初始化步骤
─────────────────────────────────────────────────────────────────────────────────────
equipment.mac_id              →   --device-id                        替代 sub-device-selector
equipment.component_id        →   --sub-device-id                    替代 sub-device-selector
equipment.component_name      →   报告标题 + 时间表单描述              替代 sub-device-selector
equipment.factory_id          →   InS数据查询上下文                    —
events[0].time                →   推导 diagnosis_date + hour         替代整个时间表单
events[].type                 →   告知各异常类型，辅助规则匹配          —
events[].points[]             →   诊断脚本内部拉趋势/波形时参考         —
judgment.suspected_fault_type →   --focus 策略，优先匹配该故障码规则    —
judgment.evidence[]           →   交叉校验，避免重复拉取已排除方向       —
judgment.conclusion           →   报告中的来源说明                      —
```

---

## 九、前端：AgentHandoffBlock 组件 + 页面跳转

### 9.1 AgentHandoffBlock.tsx

当异常研判Agent输出 `component="agent_handoff"` 的 GenUI block 时，
前端渲染为可点击的跳转按钮：

```tsx
// frontend/src/components/genui/AgentHandoffBlock.tsx
"use client";

import { useRouter } from "next/navigation";
import { ArrowRight, Wrench } from "lucide-react";

interface AgentHandoffBlockProps {
  block: {
    props: {
      target_agent: string;
      target_display_name: string;
      target_icon: string;
      message: string;
      handoff_data: Record<string, unknown>;
    };
  };
}

export default function AgentHandoffBlock({ block }: AgentHandoffBlockProps) {
  const router = useRouter();
  const { target_agent, target_display_name, target_icon, message, handoff_data } = block.props;

  const handleJump = () => {
    // ① 将 handoff 上下文暂存到 sessionStorage
    sessionStorage.setItem(
      `handoff:${target_agent}`,
      JSON.stringify(handoff_data)
    );
    // ② 跳转到目标Agent的新对话
    router.push(
      `/workspace/agents/${target_agent}/chats/new?handoff=1`
    );
  };

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span>{target_icon}</span>
        <span>{target_display_name}</span>
      </div>
      <p className="text-sm text-muted-foreground">{message}</p>
      <button
        type="button"
        className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        onClick={handleJump}
      >
        <Wrench className="h-4 w-4" />
        跳转到{target_display_name}
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}
```

### 9.2 注册到 GenUI Registry

在 `core/genui/registry.ts` 的 `COMPONENT_REGISTRY` 中追加：

```typescript
"agent_handoff": () => import("@/components/genui/AgentHandoffBlock") as any,
```

### 9.3 目标Agent页面接收Handoff

在 `app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` 中，
页面初始化时检测 `?handoff=1` URL参数：

```typescript
// 在 AgentChatPage 组件中增加：

const searchParams = useSearchParams();

useEffect(() => {
  const isHandoff = searchParams.get("handoff") === "1";
  if (!isHandoff || !isNewThread) return;

  // 从 sessionStorage 读取 handoff 上下文
  const key = `handoff:${agent_name}`;
  const raw = sessionStorage.getItem(key);
  if (!raw) return;

  sessionStorage.removeItem(key); // 用完即清理
  const handoff: AgentHandoff = JSON.parse(raw);

  // 构造第一条消息
  const firstMessage = buildHandoffMessage(handoff);

  // 自动发送，将 handoff 数据放在 additional_kwargs 中
  sendMessage(
    threadId,                           // 新创建的线程ID
    { text: firstMessage, files: [] },  // 消息内容
    undefined,                          // extraContext
    { additionalKwargs: { handoff } }   // handoff上下文随消息传递
  );
}, [isNewThread, threadId]);
```

### 9.4 构造第一条消息文本

```typescript
function buildHandoffMessage(handoff: AgentHandoff): string {
  const { equipment, events, judgment } = handoff;

  const eventLines = events.map((e: any) =>
    `- [${e.type}] ${e.desc}（等级:${e.event_level}）`
  ).join("\n");

  const evidenceLines = judgment.evidence.map((e: string) => `- ${e}`).join("\n");

  return `【异常研判转交】

请对以下设备进行深度故障诊断：

设备：${equipment.mac_path}/${equipment.mac_name}/${equipment.component_name}
当前健康值：${judgment.health_score}
运行状态：${judgment.run_status}

异常事件列表：
${eventLines}

研判结论：${judgment.conclusion}（置信度：${(judgment.confidence * 100).toFixed(0)}%）
疑似故障类型：${judgment.suspected_fault_type}

关键证据：
${evidenceLines}

请分析根因并给出维修建议。`;
}
```

### 9.5 Handoff 数据类型定义

```typescript
// frontend/src/core/genui/agent-handoff-types.ts

interface AgentHandoff {
  source_agent: string;
  abnormal_id: string;
  equipment: {
    mac_id: string;
    component_id: string;
    factory_id: string;
    mac_name: string;
    mac_path: string;
    component_name: string;
    mac_type: number;
  };
  events: Array<{
    time: number;
    type: string;
    event_level: number;
    desc: string;
    points: Array<{
      point_id: string;
      point_name: string;
      value_type: string;
      point_type: number;
    }>;
    time_range_start: number;
    time_range_end: number;
  }>;
  judgment: {
    conclusion: string;
    confidence: number;
    suspected_fault_type: string;
    severity: string;
    evidence: string[];
    health_score: number;
    run_status: string;
  };
}
```

---

## 十、完整交互时序

```
用户              异常研判Agent           前端                 故障诊断Agent
 |                     |                    |                       |
 | 点击starter         |                    |                       |
 |────────────────────→|                    |                       |
 |                     | Phase 1:           |                       |
 |                     | render_ui(         |                       |
 |                     |   abnormal-list    |                       |
 |                     |   -selector)       |                       |
 |                     |───────────────────→|                       |
 |  渲染异常列表        |                    |                       |
 |←────────────────────|                    |                       |
 |                     |                    |                       |
 | 点击某个异常         |                    |                       |
 |──────────────────────────────────────────→|                       |
 |                     |                    | onInteraction(        |
 |                     |                    |   callback_id,        |
 |                     |                    |   {selected:{...}})   |
 |                     |←───────────────────|                       |
 |                     |                    |                       |
 |                     | Phase 2-6:         |                       |
 |                     | 拉详情→拉监测数据    |                       |
 |                     | →逐事件研判→综合    |                       |
 |                     | →渲染报告           |                       |
 |                     |                    |                       |
 | 研判报告             |                    |                       |
 |←────────────────────|                    |                       |
 |                     |                    |                       |
 |                     | Phase 7:           |                       |
 |                     | render_ui(         |                       |
 |                     |   agent_handoff)   |                       |
 |                     |───────────────────→|                       |
 |  渲染跳转按钮        |                    |                       |
 |←────────────────────|                    |                       |
 |                     |                    |                       |
 | 点击"跳转到故障诊断"  |                    |                       |
 |──────────────────────────────────────────→|                       |
 |                     |                    | ① sessionStorage      |
 |                     |                    |    .set(handoff)      |
 |                     |                    | ② router.push(        |
 |                     |                    |    /agents/fault-     |
 |                     |                    |    diagnosis--rotating|
 |                     |                    |    /chats/new         |
 |                     |                    |    ?handoff=1)        |
 |                     |                    |                       |
 |                     |                    | ③ 检测?handoff=1     |
 |                     |                    | ④ sessionStorage      |
 |                     |                    |    .get(handoff)      |
 |                     |                    | ⑤ 构造首条消息+       |
 |                     |                    |    additional_kwargs   |
 |                     |                    | ⑥ sendMessage()      |
 |                     |                    |──────────────────────→|
 |                     |                    |                       |
 |                     |                    |        ⑦ 检测handoff  |
 |                     |                    |        ⑧ 跳过选设备    |
 |                     |                    |        ⑨ 跳过选时间    |
 |                     |                    |        ⑩ 直接拉设备树  |
 |                     |                    |        ⑪ 执行规则诊断  |
 |                     |                    |        ⑫ 渲染报告      |
 |                     |                    |                       |
 |  诊断报告            |                    |                       |
 |←────────────────────────────────────────────────────────────────|
```

---

## 十一、改动量总结

| 层 | 新增文件 | 修改文件 | 核心改动 |
|:---|:---|:---|:---|
| **SmsAdapter** | 0 | 4 | adapter、transform、service、tools 各加2个方法 |
| **Query/Model** | 0 | 2 | 新增4个dataclass |
| **Tool Builder** | 0 | 1 | 注册2个StructuredTool |
| **Gateway API** | 1 | 1 | 新增 abnormal.py 路由 + app.py注册 |
| **前端A2UI选择器** | 1 | 3 | AbnormalListSelectorBlock + registry注册 + i18n |
| **前端Handoff** | 2 | 2 | AgentHandoffBlock + types + registry + page.tsx |
| **Agent配置** | 3 | 0 | parent config + child config + SOUL.md |
| **故障诊断Agent** | 0 | 1 | fault-diagnosis--rotating/SOUL.md 增加Handoff模式 |

**核心设计原则**：
- SMS接入复用 `SmsAdapter` 已有的HTTP客户端、认证、错误处理、健康检查等基础设施
- Agent通过 `abnormal_get_list` / `abnormal_get_detail` 两个 StructuredTool 调用
- 前端A2UI组件通过 Gateway 代理端点调用，与Agent共享同一个 SmsAdapter 实例
- 跨Agent Handoff 通过 GenUI block → 前端 sessionStorage → URL → additional_kwargs 链路传递
- 故障诊断Agent在Handoff模式下完全跳过两个初始化选择步骤
