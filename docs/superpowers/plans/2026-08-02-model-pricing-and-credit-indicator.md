# 模型定价与积分指示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让后台定价策略与对话可选模型一致，并将聊天右上角 Token 指示替换为用户可用积分。

**Architecture:** 前端复用 `useModels()` 的 `/api/models` 查询结果作为后台模型选择来源。后端继续以一个模型仅一条 active 策略为结算依据，保存新版本时原策略失效；钱包接口驱动聊天页积分显示。

**Tech Stack:** Next.js/React、TanStack Query、FastAPI、SQLAlchemy、pytest。

## Global Constraints

- 模型名称必须来自已配置模型列表。
- 同一模型对所有用户保持同一当前生效策略。
- 旧策略仅供审计，历史用量以已保存的价格快照为准。
- 不提交、不推送、不部署代码。

---

### Task 1: 后端模型策略约束与回归测试

**Files:**
- Modify: `backend/app/gateway/routers/admin_billing.py`
- Modify: `backend/tests/test_wallet_service.py`

**Interfaces:**
- Consumes: `get_app_config().models` 与 `ModelPricePolicyRequest.model_name`。
- Produces: 仅接受已配置模型名称的 `POST /api/admin/model-pricing`。

- [ ] **Step 1: Write the failing test**

```python
async def test_model_policy_rejects_unconfigured_model():
    response = await create_policy(model_name="not-configured")
    assert response.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wallet_service.py -q`

Expected: FAIL because arbitrary model names are currently accepted.

- [ ] **Step 3: Write minimal implementation**

```python
configured = {model.name for model in get_app_config().models}
if body.model_name not in configured:
    raise HTTPException(status_code=422, detail="Model is not configured")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_wallet_service.py -q`

Expected: PASS.

### Task 2: 后台模型选择与历史策略呈现

**Files:**
- Modify: `frontend/src/app/workspace/admin/page.tsx`
- Test: `frontend/src/app/workspace/admin/page.test.tsx`

**Interfaces:**
- Consumes: `useModels(): { models: Model[] }`、`GET /api/admin/model-pricing`。
- Produces: 受控模型下拉框；当前和历史策略列表。

- [ ] **Step 1: Write the failing test**

```tsx
it("renders only configured models in the pricing selector", () => {
  render(<AdminPage />);
  expect(screen.getByRole("option", { name: "DeepSeek Chat" })).toBeInTheDocument();
  expect(screen.queryByText("model_name")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test src/app/workspace/admin/page.test.tsx`

Expected: FAIL because the form exposes a text `model_name` input.

- [ ] **Step 3: Write minimal implementation**

```tsx
const { models } = useModels();
<select value={policy.model_name} onChange={onModelChange}>
  {models.map((model) => <option key={model.name} value={model.name}>{model.display_name}</option>)}
</select>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm check`

Expected: PASS.

### Task 3: 聊天顶部积分指示

**Files:**
- Modify: `frontend/src/components/workspace/token-usage-indicator.tsx`
- Create: `frontend/src/components/workspace/credit-balance-indicator.tsx`
- Test: `frontend/src/components/workspace/credit-balance-indicator.test.tsx`

**Interfaces:**
- Consumes: `getWallet(): Promise<{ available_credits: number }>`。
- Produces: `CreditBalanceIndicator`，在钱包不可用时渲染空内容。

- [ ] **Step 1: Write the failing test**

```tsx
it("shows the available credit balance", async () => {
  render(<CreditBalanceIndicator />);
  expect(await screen.findByText("1,000 积分")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test src/components/workspace/credit-balance-indicator.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Write minimal implementation**

```tsx
const { data: wallet } = useQuery({ queryKey: ["billing", "wallet"], queryFn: getWallet });
return wallet ? <span>{wallet.available_credits.toLocaleString()} 积分</span> : null;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm check`

Expected: PASS.
