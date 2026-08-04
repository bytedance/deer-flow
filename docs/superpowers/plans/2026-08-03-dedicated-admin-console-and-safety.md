# 独立运营后台与内容安全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供独立多租户运营后台、完整技能说明查看，以及在模型流式输出中止违规内容并持久化安全占位消息的内容安全能力。

**Architecture:** 后台使用独立的 Next.js `AdminShell` 与子路由，所有数据通过管理员专属资源接口读取和操作。内容安全由运行器中、SSE 发布前的本地 `StreamingContentGuard` 执行；它对输入进行预拦截、对输出做短窗口检测，命中时取消运行、写风险事件并向客户端发送替换当前回复的事件。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy async ORM、Alembic、Next.js App Router、React、TypeScript、Rstest、pytest。

## Global Constraints

- 一个注册用户是一个租户；用户归属必须从认证会话取得，不得接受客户端传入的 `user_id`。
- 管理员后台不复用普通用户的工作区导航或聊天容器；普通用户不能访问后台。
- 内容安全默认检测用户输入和模型输出；管理员不具备任意查看聊天全文的能力。
- 输入在模型调用前被拦截时不扣积分；模型开始生成后被拦截时，按实际 Token 结算且不自动退款。
- 命中规则时不向用户暴露具体规则、关键词或置信度；替代文案使用固定中性提示。
- 所有管理写操作、审核上下文查看、风险处置都必须写审计记录。
- 不接入真实支付、外部审核服务或任何会产生费用的外部调用。
- 本次不提交、推送或部署代码；保留工作树已有的未提交改动。

---

### Task 1: 建立风险事件、处置与审计持久化边界

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/safety/model.py`
- Create: `backend/packages/harness/deerflow/persistence/safety/service.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0013_content_safety.py`
- Modify: `backend/packages/harness/deerflow/persistence/models/__init__.py`
- Create: `backend/tests/test_content_safety_service.py`

**Interfaces:**
- Produces `RiskEventRow` with `id`, `user_id`, `thread_id`, `run_id`, `direction`, `category`, `severity`, `rule_version`, `confidence_bps`, `redacted_excerpt`, `status`, `resolution`, `created_at`.
- Produces `AdminAuditLogRow` with `actor_user_id`, `action`, `target_type`, `target_id`, `reason`, `before_summary`, `after_summary`, `created_at`.
- Produces `ContentSafetyService.create_risk_event(...)`, `record_context_access(...)`, and `resolve_risk_event(...)`.

- [ ] **Step 1: Write failing service tests for tenant ownership, immutable detection data and context-access audit records.**

```python
async def test_context_access_records_reason_and_never_returns_another_users_event(service):
    event = await service.create_risk_event(user_id="tenant-a", thread_id="t1", run_id="r1", direction="output", category="unsafe", severity="high", rule_version="v1", confidence_bps=9800, redacted_excerpt="危险***")
    assert await service.get_event_for_admin(event.id) is not None
    await service.record_context_access(event.id, actor_user_id="reviewer-1", reason="处理高风险告警")
    assert await service.list_audit_actions(event.id) == ["safety.context_viewed"]
```

- [ ] **Step 2: Run the focused test to verify failure.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_content_safety_service.py -q`

Expected: FAIL because the safety persistence package does not exist.

- [ ] **Step 3: Add the models and an idempotent migration.**

```python
class RiskEventRow(Base):
    __tablename__ = "risk_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)

class AdminAuditLogRow(Base):
    __tablename__ = "admin_audit_logs"
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
```

- [ ] **Step 4: Implement the service using one transaction for each risk event or resolution plus its audit event.**

```python
async def resolve_risk_event(self, event_id: str, *, actor_user_id: str, resolution: str, reason: str) -> RiskEventRow:
    if not reason.strip():
        raise ValueError("A resolution reason is required")
    # lock event, update status/resolution, append an audit row, commit once
```

- [ ] **Step 5: Run focused tests and an Alembic upgrade on a temporary SQLite database.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_content_safety_service.py -q`

### Task 2: 添加输入预拦截与流式输出安全终止

**Files:**
- Create: `backend/packages/harness/deerflow/safety/streaming_guard.py`
- Modify: `backend/app/gateway/services.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/worker.py`
- Modify: `backend/app/gateway/routers/thread_runs.py`
- Create: `backend/tests/test_streaming_content_guard.py`
- Create: `backend/tests/test_safety_run_integration.py`

**Interfaces:**
- Produces `SafetyVerdict(blocked: bool, category: str | None, severity: str | None, redacted_excerpt: str | None)`.
- Produces `StreamingContentGuard.inspect_input(text: str) -> SafetyVerdict`, `push_output(delta: str) -> tuple[SafetyVerdict, list[str]]`, and `flush() -> list[str]`.
- Produces SSE event `content_blocked` with `{ "run_id": str, "message": str }`.
- Consumes `RunManager.cancel(run_id, action="interrupt")` and `ContentSafetyService.create_risk_event(...)`.

- [ ] **Step 1: Write failing pure-logic tests for split keyword matching, delayed safe output and fixed blocked message.**

```python
def test_guard_detects_phrase_split_across_stream_chunks():
    guard = StreamingContentGuard(rule_set=RuleSet.from_terms(["forbidden phrase"]), window_chars=80)
    assert guard.push_output("forbidden ")[0].blocked is False
    verdict, released = guard.push_output("phrase")
    assert verdict.blocked is True
    assert released == []
```

- [ ] **Step 2: Run the pure-logic test to verify failure.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_streaming_content_guard.py -q`

Expected: FAIL because `StreamingContentGuard` is absent.

- [ ] **Step 3: Implement a local, versioned rule set and a bounded output buffer.**

```python
BLOCKED_RESPONSE_TEXT = "抱歉，当前请求或回复内容可能违反平台内容安全规范，已停止生成。"

def push_output(self, delta: str) -> tuple[SafetyVerdict, list[str]]:
    self._pending += delta
    verdict = self._inspect(self._tail_context + self._pending)
    if verdict.blocked:
        return verdict, []
    return SafetyVerdict.allow(), self._release_complete_prefix()
```

- [ ] **Step 4: Write failing run integration tests for input blocking, output blocking, cancellation and billing behavior.**

```python
async def test_blocked_input_does_not_create_run_or_reservation(client):
    response = await client.post("/api/threads/t1/runs", json=unsafe_input_payload())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "CONTENT_BLOCKED"
    assert run_manager.create_calls == 0

async def test_blocked_stream_publishes_replacement_and_settles_actual_usage(worker):
    events = await collect_stream(worker, chunks=["safe", " forbidden", " phrase"])
    assert [event.name for event in events][-2:] == ["content_blocked", "end"]
    assert wallet.actual_charge("run-1") > 0
```

- [ ] **Step 5: Implement run-boundary checks and stream interception before every `messages` bridge publish.**

```python
if verdict.blocked:
    await safety_service.create_risk_event(..., direction="output", redacted_excerpt=verdict.redacted_excerpt)
    await bridge.publish(run_id, "content_blocked", {"run_id": run_id, "message": BLOCKED_RESPONSE_TEXT})
    await run_manager.cancel(run_id, action="interrupt")
    return
```

- [ ] **Step 6: Persist a safe assistant placeholder rather than the partial assistant text and ensure terminal settlement uses actual token usage.**

```python
await write_blocked_assistant_placeholder(
    checkpointer, thread_id=thread_id, run_id=run_id, content=BLOCKED_RESPONSE_TEXT
)
```

- [ ] **Step 7: Run guard and billing regression tests.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_streaming_content_guard.py tests/test_safety_run_integration.py tests/test_billing_run_owner.py tests/test_wallet_service.py -q`

### Task 3: 暴露安全审核、分页运营数据与禁止自我冻结的管理员 API

**Files:**
- Create: `backend/app/gateway/routers/admin_safety.py`
- Modify: `backend/app/gateway/routers/admin_billing.py`
- Modify: `backend/app/gateway/app.py`
- Modify: `backend/tests/test_admin_billing.py`
- Create: `backend/tests/test_admin_safety_router.py`

**Interfaces:**
- Produces `GET /api/admin/safety/events`, `GET /api/admin/safety/events/{event_id}`, `POST /api/admin/safety/events/{event_id}/context`, and `POST /api/admin/safety/events/{event_id}/resolve`.
- Produces paginated `GET /api/admin/users`, `GET /api/admin/usage`, `GET /api/admin/orders` using `{ "items": list, "next_cursor": str | null }`.
- Consumes `require_admin_user(request)` and authenticated actor identity.

- [ ] **Step 1: Write failing API tests for role protection, context reasons, pagination and self-freeze rejection.**

```python
def test_admin_cannot_freeze_self(client, admin_headers):
    response = client.post("/api/admin/users/admin-1/freeze?frozen=true", headers=admin_headers)
    assert response.status_code == 422

def test_safety_context_requires_reason(client, admin_headers, event):
    response = client.post(f"/api/admin/safety/events/{event.id}/context", json={"reason": ""}, headers=admin_headers)
    assert response.status_code == 422
```

- [ ] **Step 2: Run router tests to verify failure.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_admin_billing.py tests/test_admin_safety_router.py -q`

- [ ] **Step 3: Implement cursor parsing, stable sort order, filters and explicit response schemas.**

```python
@router.get("/safety/events", response_model=RiskEventPage)
async def list_risk_events(status: str | None = None, severity: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)) -> RiskEventPage:
    return await service.list_for_admin(status=status, severity=severity, cursor=cursor, limit=limit)
```

- [ ] **Step 4: Implement context redaction and capped neighboring-message retrieval; append an audit record for every success.**

```python
if len(reason.strip()) < 3:
    raise HTTPException(status_code=422, detail="请填写查看上下文的原因")
return ContextResponse(messages=redact_messages(messages[-6:]), truncated=len(messages) > 6)
```

- [ ] **Step 5: Reject freezes targeting the authenticated actor and append audit events to all existing credit, freeze, pricing and market write operations.**

```python
if str(request.state.user.id) == user_id and frozen:
    raise HTTPException(status_code=422, detail="不能冻结当前管理员账号")
```

- [ ] **Step 6: Run router tests and existing billing/market authorization regressions.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_admin_billing.py tests/test_admin_safety_router.py tests/test_skill_market_router.py -q`

### Task 4: 让技能详情按需读取完整 SKILL.md

**Files:**
- Modify: `backend/app/gateway/routers/skills.py`
- Modify: `frontend/src/core/skills/type.ts`
- Modify: `frontend/src/core/skills/api.ts`
- Modify: `frontend/src/components/workspace/settings/skill-settings-page.tsx`
- Create: `backend/tests/test_skill_details_router.py`
- Create: `frontend/tests/unit/core/skills/api.test.ts`
- Create: `frontend/tests/unit/components/workspace/settings/skill-settings-page.dom.test.tsx`

**Interfaces:**
- Produces `GET /api/skills/{skill_name}/details` returning `{ name, description, category, content }` only for a skill visible to the authenticated user.
- Produces `loadSkillDetails(skillName): Promise<SkillDetails>`.
- Uses `SkillDetailsDialog` or an inline controlled detail panel with escaped plain-text/Markdown display.

- [ ] **Step 1: Write failing backend tests proving public and user-owned skills can be read, while unknown/cross-tenant names return 404.**

```python
def test_visible_skill_details_returns_full_markdown(client, user_headers):
    response = client.get("/api/skills/academic-paper-review/details", headers=user_headers)
    assert response.status_code == 200
    assert "# Academic Paper Review Skill" in response.json()["content"]
```

- [ ] **Step 2: Run the route test to verify failure.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_skill_details_router.py -q`

- [ ] **Step 3: Add a visible-skill-only resolver and raw Markdown response; never use client paths or return arbitrary directory files.**

```python
skill = next((item for item in storage.load_skills(enabled_only=False) if item.name == skill_name), None)
if skill is None:
    raise HTTPException(status_code=404, detail="Skill not found")
content = storage.read_skill_markdown(skill)
```

- [ ] **Step 4: Write failing UI tests for a lazy detail request and untruncated visible content.**

```tsx
await user.click(screen.getByRole("button", { name: "展开完整说明" }));
expect(await screen.findByText("Academic Paper Review Skill")).toBeVisible();
expect(loadSkillDetails).toHaveBeenCalledWith("academic-paper-review");
```

- [ ] **Step 5: Implement the lazy detail panel with loading, error, retry and `whitespace-pre-wrap break-words` text rendering.**

```tsx
{expanded && <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words">{detail.content}</pre>}
```

- [ ] **Step 6: Run backend/UI tests and TypeScript checks.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_skill_details_router.py -q && cd ../frontend && pnpm exec rstest run tests/unit/core/skills/api.test.ts tests/unit/components/workspace/settings/skill-settings-page.dom.test.tsx && pnpm exec tsc --noEmit`

### Task 5: 构建独立 AdminShell、后台客户端与概览页面

**Files:**
- Create: `frontend/src/components/admin/admin-shell.tsx`
- Create: `frontend/src/components/admin/admin-sidebar.tsx`
- Create: `frontend/src/components/admin/admin-page-header.tsx`
- Create: `frontend/src/core/admin/api.ts`
- Create: `frontend/src/core/admin/types.ts`
- Modify: `frontend/src/app/workspace/admin/layout.tsx`
- Modify: `frontend/src/app/workspace/admin/page.tsx`
- Create: `frontend/tests/unit/components/admin/admin-shell.dom.test.tsx`
- Create: `frontend/tests/unit/core/admin/api.test.ts`

**Interfaces:**
- Produces `AdminShell({ children })`, `adminNavItems`, `adminApi.listUsers`, `adminApi.getOverview`, `adminApi.listUsage`, `adminApi.listOrders`, `adminApi.listRiskEvents`.
- Consumes server-side `getServerSideUser` redirect guard from the existing admin layout.

- [ ] **Step 1: Write failing DOM tests for the dedicated navigation and absence of user-workspace controls.**

```tsx
render(<AdminShell><div>概览内容</div></AdminShell>);
expect(screen.getByRole("link", { name: "内容安全" })).toBeVisible();
expect(screen.queryByText("新对话")).toBeNull();
```

- [ ] **Step 2: Run the DOM test to verify failure.**

Run: `cd frontend && pnpm exec rstest run tests/unit/components/admin/admin-shell.dom.test.tsx --project dom`

- [ ] **Step 3: Implement the admin layout shell and typed authenticated admin fetch client.**

```tsx
export function AdminShell({ children }: { children: ReactNode }) {
  return <div className="min-h-screen bg-muted/30"><AdminSidebar /><main>{children}</main></div>;
}
```

- [ ] **Step 4: Replace the monolithic existing admin page with a server-protected overview route using metric cards and failure/loading states.**

```tsx
<AdminPageHeader title="运营概览" description="查看平台运营、计费与内容安全状态" />
<OverviewMetrics data={overview} />
```

- [ ] **Step 5: Run DOM/API-client tests, lint and type checks.**

Run: `cd frontend && pnpm exec rstest run tests/unit/components/admin/admin-shell.dom.test.tsx tests/unit/core/admin/api.test.ts && pnpm exec eslint src/components/admin src/core/admin src/app/workspace/admin && pnpm exec tsc --noEmit`

### Task 6: 实现后台业务子页面与受控操作体验

**Files:**
- Create: `frontend/src/app/workspace/admin/tenants/page.tsx`
- Create: `frontend/src/app/workspace/admin/billing/page.tsx`
- Create: `frontend/src/app/workspace/admin/usage/page.tsx`
- Create: `frontend/src/app/workspace/admin/orders/page.tsx`
- Create: `frontend/src/app/workspace/admin/skills/page.tsx`
- Create: `frontend/src/app/workspace/admin/safety/page.tsx`
- Create: `frontend/src/app/workspace/admin/audit/page.tsx`
- Create: `frontend/src/components/admin/users-table.tsx`
- Create: `frontend/src/components/admin/safety-event-drawer.tsx`
- Create: `frontend/src/components/admin/confirm-admin-action-dialog.tsx`
- Create: `frontend/tests/unit/components/admin/safety-event-drawer.dom.test.tsx`
- Create: `frontend/tests/unit/components/admin/users-table.dom.test.tsx`

**Interfaces:**
- Consumes typed `adminApi` from Task 5 and the paginated API schemas from Task 3.
- Produces route pages that use filters, cursor pagination, confirmation dialogs and visible mutation results rather than browser `prompt`.

- [ ] **Step 1: Write failing UI tests for self-freeze state, mandatory adjustment reason and context-view reason.**

```tsx
expect(screen.getByRole("button", { name: "冻结" })).toBeDisabled();
await user.click(screen.getByRole("button", { name: "查看受控上下文" }));
expect(screen.getByLabelText("查看原因")).toBeRequired();
```

- [ ] **Step 2: Run focused DOM tests to verify failure.**

Run: `cd frontend && pnpm exec rstest run tests/unit/components/admin/users-table.dom.test.tsx tests/unit/components/admin/safety-event-drawer.dom.test.tsx --project dom`

- [ ] **Step 3: Implement tenant/user detail, balance adjustment and freeze/recovery dialogs; never offer a self-freeze action.**

```tsx
<ConfirmAdminActionDialog reasonLabel="调整原因" onConfirm={({ reason }) => adminApi.adjustCredits(user.id, credits, reason)} />
```

- [ ] **Step 4: Implement billing, usage, order, market, audit and safety route pages over the shared table/filter primitives.**

```tsx
<SafetyEventDrawer event={selectedEvent} onLoadContext={(reason) => adminApi.loadSafetyContext(selectedEvent.id, reason)} />
```

- [ ] **Step 5: Display the fixed user-facing safety replacement text and ensure the chat stream reducer replaces—not appends to—the active assistant message on `content_blocked`.**

```ts
if (event.event === "content_blocked") {
  replaceAssistantMessage(event.data.run_id, event.data.message);
}
```

- [ ] **Step 6: Run component tests, all affected frontend tests, lint and type checks.**

Run: `cd frontend && pnpm exec rstest run tests/unit/components/admin tests/unit/components/workspace/settings/skill-settings-page.dom.test.tsx && pnpm exec eslint src/app/workspace/admin src/components/admin src/components/workspace/settings && pnpm exec tsc --noEmit`

### Task 7: 全链路回归与迁移验证

**Files:**
- Modify: `docs/superpowers/specs/2026-08-03-dedicated-admin-console-design.md` only if verification reveals an explicit design correction.
- Test: `backend/tests/test_content_safety_service.py`
- Test: `backend/tests/test_streaming_content_guard.py`
- Test: `backend/tests/test_safety_run_integration.py`
- Test: `backend/tests/test_admin_safety_router.py`
- Test: `backend/tests/test_admin_billing.py`
- Test: `backend/tests/test_skill_details_router.py`

**Interfaces:**
- Verifies the stable public interfaces emitted by Tasks 1 through 6.

- [ ] **Step 1: Run complete affected backend suite.**

Run: `cd backend && UV_CACHE_DIR=/private/tmp/deerflow-safety-uv-cache uv run pytest tests/test_content_safety_service.py tests/test_streaming_content_guard.py tests/test_safety_run_integration.py tests/test_admin_safety_router.py tests/test_admin_billing.py tests/test_skill_details_router.py tests/test_skill_market_router.py tests/test_user_mcp_config.py tests/test_skills_router_authz.py tests/test_billing_run_owner.py tests/test_wallet_service.py -q`

Expected: PASS.

- [ ] **Step 2: Run migration upgrade from a fresh temporary SQLite database and verify the expected new tables.**

Run: `cd backend && DEER_FLOW_DATABASE_URL=sqlite+aiosqlite:////private/tmp/deerflow-safety-migration.db uv run alembic -c packages/harness/deerflow/persistence/migrations/alembic.ini upgrade head`

Expected: PASS with `risk_events` and `admin_audit_logs` created.

- [ ] **Step 3: Run the affected frontend suite and static checks.**

Run: `cd frontend && pnpm exec rstest run tests/unit/core/auth/role-routing.test.ts tests/unit/core/skills/api.test.ts tests/unit/components/workspace/settings tests/unit/components/admin && pnpm exec eslint src/app/workspace/admin src/components/admin src/components/workspace/settings src/core/admin src/core/skills && pnpm exec tsc --noEmit`

Expected: PASS.

- [ ] **Step 4: Manually verify one safe stream, one input-blocked request and one output-blocked stream in the local development browser.**

Expected: safe text streams normally; blocked input shows the fixed prompt without billing; blocked output is replaced by the fixed prompt and creates a risk event with charged usage.
