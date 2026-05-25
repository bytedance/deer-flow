## Context

ISSUE-01 已定版主流程和对象模型基线。当前 DeerFlow 中 thread、run、upload、artifact 的生命周期状态定义分散在 4 处：

| 位置 | 对象 | 形式 | 实际使用 |
|------|------|------|----------|
| `shared/status.py` | Thread/Run/Upload/Artifact | StrEnum | **未使用**（仅 `shared/__init__.py` 导出） |
| `runtime/runs/schemas.py` | Run | StrEnum + canonical_run_status() | **运行时使用** |
| `report_templates/records.py` | ReportRun | `Literal["pending", "running", "success", "failed", "canceled"]` | report_templates 模块内使用 |
| `report_templates/runtime/state.py` | RuntimeState | `Literal["pending", "running", "success", "failed", "canceled"]` | 运行状态机使用 |

关键差异：
- `shared/status.py` 和 `runtime/runs/schemas.py` 都定义了 RunStatus，后者多了 `error`/`timeout`/`interrupted` 弃用值和 `canonical_run_status()` 函数
- report_templates 的 RunStatus 拼写 "canceled"（美式），与 runtime 的 "cancelled"（英式）不一致
- `RunFailureCategory` 和 `FailedLayer` 只在 worker.py rollback 路径填充，services.py 中的外部依赖失败路径未填充
- 前端 `report-templates/types.ts` 独立定义 `ReportRunStatus`，与中心 `status.ts` 重复

## Goals / Non-Goals

**Goals:**
- 合并 RunStatus 为单一权威来源（`shared/status.py`），`runtime/runs/schemas.py` 从中导入
- 统一 "canceled" → "cancelled" 拼写
- report_templates 使用 shared RunStatus 替代 ad-hoc Literal
- 在所有 Run 失败路径中填充 failure_category 和 failed_layer
- Gateway API 响应中包含失败分类字段
- 前端 ReportRunStatus 引用中心 status.ts
- 回归测试覆盖状态映射、拼写一致性和失败语义

**Non-Goals:**
- 不修改 report run 的状态机转换逻辑（只改拼写和类型来源）
- 不修改 closure ticket 状态（已有独立状态机）
- 不修改知识库文档的 index_status（独立域）
- 不引入新的状态值（保持现有状态集不变）

## Decisions

### D1: `shared/status.py` 为唯一权威来源

**选择**: 将 `canonical_run_status()` 和弃用兼容逻辑从 `runtime/runs/schemas.py` 移至 `shared/status.py`，`runtime/runs/schemas.py` 改为从 shared 导入。

**理由**: shared 已经是文档基线（ISSUE-01），且前端已对齐。runtime 重复定义只会导致漂移。

**备选方案**: 删除 shared/status.py，只保留 runtime 版本 → 不可行，因为 shared 承载了 ThreadStatus、UploadStatus、ArtifactStatus 和前端对应的 status.ts。

### D2: "cancelled" 为规范拼写

**选择**: 统一使用 "cancelled"（双 l，英式拼写），与现有 runtime/schemas.py 和前端 status.ts 一致。

**理由**: runtime 和前端已经使用 "cancelled"，改动最小。report_templates 的 "canceled" 需要修正。

**迁移**: report_templates 中 `status.json` 文件可能存有 "canceled" 值，需要在读取时兼容处理。

### D3: failure_category + failed_layer 在 Gateway 层填充

**选择**: 在 `app/gateway/services.py` 的 `_create_run()` 调用链路中，当捕获外部服务异常时填充 `failure_category="external_dependency_unavailable"` + `failed_layer="external"`。

**理由**: Gateway 层能感知外部依赖（模型 API、Sandbox Provider、MCP Server），runtime 层只管 Agent 执行逻辑。

### D4: 前端 ReportRunStatus 改为引用 status.ts

**选择**: `report-templates/types.ts` 删除 `ReportRunStatus`，改为 `import { RunStatus } from "@/core/models/status"`。保留 `TemplateStatus`（draft/published/archived）独立定义，因为这是 report template 独有的状态语义。

**理由**: 减少类型重复，确保前后端状态值一致。

## Risks / Trade-offs

- **[数据兼容] 存量的 "canceled" 状态记录** → `canonical_run_status()` 和 report run 状态读取时统一映射
- **[拼写习惯] 美式英语用户可能继续写出 "canceled"** → 回归测试 + CI lint 规则防护
- **[导入变更] report_templates 改为导入 shared 枚举** → 所有 report_templates 文件的 import 路径需更新，影响面约 8-10 个文件
