# Deep-Link 直达流程修复总结

**日期**: 2026-06-08  
**修复范围**: 前端参数传递、LLM 指令遵循、SOUL.md 规则精简

## 修复内容

### 1. 前端 Hydration 竞态修复

**文件**: `frontend/src/components/workspace/chats/use-deep-link-chat.ts`

**问题**: `useMemo` 依赖项不完整，导致 `searchParams` 变化后参数未更新

**修复**: 移除 `firedRef`，让 `useMemo` 正确响应 `searchParams` 变化

### 2. SystemMessage 注入

**文件**: `backend/packages/harness/deerflow/agents/middlewares/passthrough_params_middleware.py`

**修复**: 注入 SystemMessage 强制 LLM 遵循 deep-link 直达规则

### 3. SOUL.md 规则精简

**文件**：

- `agents/builtin/ai-report--daily/SOUL.md`
- `agents/builtin/ai-report--weekly/SOUL.md`
- `agents/builtin/ai-report--monthly/SOUL.md`

**精简前** (30+ 行)：

- 泛化规则 + 具体步骤规则 + 执行序列 + 注意事项
- 存在语义重复（同一规则说了 3 遍）

**精简后** (15 行)：

```markdown
**deep-link 直达约束（必须遵守）**

当 deep-link 参数齐全时，**禁止**调用 `report_template_render_step`（会触发 `before_step` 脚本调用 Organize API），**禁止**渲染任何 GenUI 表单。状态机允许从 `pending` 状态直接提交，必须按以下序列执行：

```text
1. report_template_prepare_run(...)
2. report_template_submit_step(..., step_id="equipment", payload={"equipment_ids": [...], "equipment_labels": [...]})
3. report_template_submit_step(..., step_id="kpis", payload={"kpi_keys": [...]})
...
```

**严禁行为**：

- ❌ `report_template_render_step(..., step_id="equipment")`
- ❌ `report_template_render_step(..., step_id="kpis")`
- ❌ 调用 `list_equipment.py` 触发 `kpis.before_step`
- ❌ 发起 Organize API 查询获取 `available_kpis`

**必须行为**：

- 缺省的可选参数对应的步骤**整步跳过**
```

## 测试结果

```bash
# Deep-link SOUL 规则测试
pytest tests/test_ai_report_deeplink_soul.py -v
✅ 9 passed

# PassthroughParamsMiddleware 测试
pytest tests/test_passthrough_params_middleware.py -v
✅ 14 passed

# DSL 引擎测试
pytest tests/test_report_template_runtime.py -v
✅ 23 passed
```

## 关键修复点

1. **前端**: 移除 `firedRef`，让 `useMemo` 响应 `searchParams`
2. **后端**: 注入 SystemMessage 强制 LLM 遵循规则
3. **SOUL.md**: 精简规则，消除重复，明确禁止行为

## 技术细节

- DSL 引擎 `submit_step` 支持从 `pending` 状态直接提交（无需先调用 `render_step`）
- `render_step` 会触发 `before_step` 脚本（调用 Organize API 获取 `available_kpis`）
- deep-link 直达流程必须跳过 `render_step`，直接调用 `submit_step`

## 影响范围

- ✅ 日报 deep-link 直达流程
- ✅ 周报 deep-link 直达流程
- ✅ 月报 deep-link 直达流程

---

**修复完成时间**: 2026-06-08
