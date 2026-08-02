# Multi-tenant Billing Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add platform-managed, token-metered credits so each authenticated user can run DeerFlow only while their wallet has sufficient balance.

**Architecture:** Keep the existing authenticated `user_id` as the first-version `tenant_id`. Add immutable wallet/ledger/usage/order persistence alongside the existing SQLAlchemy models; reserve credits before `start_run`, settle from the run's already-persisted token aggregation on terminal status, and expose user and administrator APIs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL/SQLite, Next.js, TypeScript, React, Vitest/pytest.

## Global Constraints

- User-supplied tenant or user identifiers must never determine data ownership; use the authenticated request user only.
- Store money and credits as integer minor units; calculate provider costs with `Decimal`, never binary floats.
- Every balance mutation must create a ledger row in the same database transaction.
- An insufficient balance returns a stable `INSUFFICIENT_CREDITS` response before a run, sandbox, or model invocation exists.
- Model API keys remain server-only environment variables; no key is returned by billing or model APIs.
- Existing single-user/local development flows must retain a zero-cost compatibility mode until billing is explicitly enabled.

---

### Task 1: Add billing persistence and migration

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/billing/model.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0004_billing.py`
- Modify: `backend/packages/harness/deerflow/persistence/bootstrap.py`
- Test: `backend/tests/test_billing_models.py`

**Interfaces:**
- Produces `WalletRow`, `CreditLedgerRow`, `PaymentOrderRow`, `ModelPricePolicyRow`, and `UsageRecordRow`.
- Every row has `user_id`; `wallets.user_id` is unique.

- [ ] **Step 1: Write failing model tests**

```python
async def test_wallet_is_unique_per_user(async_session):
    async_session.add_all([WalletRow(user_id="u1"), WalletRow(user_id="u1")])
    with pytest.raises(IntegrityError):
        await async_session.commit()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_billing_models.py -q`

- [ ] **Step 3: Implement models and idempotent Alembic migration**

Use integer `available_credits`, `reserved_credits`, and signed `credit_delta`; include `reference_type`, `reference_id`, `reason`, `created_at`, and unique `(reference_type, reference_id, entry_type)` ledger identity.

- [ ] **Step 4: Re-run the model test**

Run: `cd backend && uv run pytest tests/test_billing_models.py -q`

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/persistence backend/tests/test_billing_models.py
git commit -m "feat: add billing persistence models"
```

### Task 2: Implement transactional wallet service

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/billing/service.py`
- Create: `backend/tests/test_wallet_service.py`

**Interfaces:**
- `reserve_credits(user_id: str, run_id: str, credits: int) -> WalletSnapshot`
- `settle_run(user_id: str, run_id: str, charged_credits: int) -> WalletSnapshot`
- `adjust_credits(user_id: str, credits: int, actor_user_id: str, reason: str) -> WalletSnapshot`

- [ ] **Step 1: Write failing balance and concurrency tests**

```python
async def test_reserve_rejects_insufficient_balance(service):
    await service.credit("u1", 10, "seed")
    with pytest.raises(InsufficientCredits) as exc:
        await service.reserve_credits("u1", "run-1", 11)
    assert exc.value.available_credits == 10
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_wallet_service.py -q`

- [ ] **Step 3: Implement locking and immutable ledger writes**

Use one transaction, `SELECT ... FOR UPDATE` on PostgreSQL, and SQLite-compatible serialized updates. Reservation moves credits from available to reserved; settlement writes exactly one charge and one release/refund, making retries idempotent by run id.

- [ ] **Step 4: Run service tests**

Run: `cd backend && uv run pytest tests/test_wallet_service.py -q`

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/persistence/billing backend/tests/test_wallet_service.py
git commit -m "feat: add transactional credit wallet service"
```

### Task 3: Meter tokens and protect run creation

**Files:**
- Modify: `backend/app/gateway/routers/thread_runs.py`
- Modify: `backend/packages/harness/deerflow/runtime/runs/worker.py`
- Create: `backend/app/gateway/billing.py`
- Test: `backend/tests/test_billing_run_guard.py`

**Interfaces:**
- `BillingRunGuard.reserve_for_run(request, run_request, thread_id) -> Reservation`
- `BillingRunGuard.settle_terminal_run(run_record) -> None`
- HTTP failure: status `402`, detail `{ "code": "INSUFFICIENT_CREDITS", "available_credits": int, "required_credits": int }`.

- [ ] **Step 1: Write a failing run-boundary test**

```python
async def test_insufficient_credits_does_not_start_run(client, seeded_user):
    response = await client.post("/api/threads/t1/runs", json={"input": {"messages": []}})
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "INSUFFICIENT_CREDITS"
    assert run_manager.start_calls == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_billing_run_guard.py -q`

- [ ] **Step 3: Reserve before `start_run`, settle on all terminal paths**

Derive actual charges from the existing `RunRow.token_usage_by_model`; create one usage record per model per run, snapshot the price policy, and settle success, error, timeout, cancellation, and orphan-recovery paths.

- [ ] **Step 4: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_billing_run_guard.py tests/test_run_manager.py -q`

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway backend/packages/harness/deerflow/runtime/runs backend/tests/test_billing_run_guard.py
git commit -m "feat: guard and settle token-metered runs"
```

### Task 4: Add account, simulated-payment, and admin APIs

**Files:**
- Create: `backend/app/gateway/routers/billing.py`
- Create: `backend/app/gateway/routers/admin_billing.py`
- Modify: `backend/app/gateway/app.py`
- Test: `backend/tests/test_billing_router.py`
- Test: `backend/tests/test_admin_billing_router.py`

**Interfaces:**
- User endpoints: `GET /api/billing/wallet`, `GET /api/billing/ledger`, `POST /api/payments/orders`.
- Administrator endpoints: `GET /api/admin/users`, `POST /api/admin/users/{user_id}/credits`, `POST /api/admin/users/{user_id}/freeze`, `GET /api/admin/billing/usage`.

- [ ] **Step 1: Write failing authorization and idempotency tests**

```python
async def test_mock_payment_is_idempotent(client):
    payload = {"package_id": "starter", "provider": "wechat", "idempotency_key": "k1"}
    assert (await client.post("/api/payments/orders", json=payload)).status_code == 201
    assert (await client.post("/api/payments/orders", json=payload)).status_code == 200
    assert await wallet_balance("current-user") == 1000
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `cd backend && uv run pytest tests/test_billing_router.py tests/test_admin_billing_router.py -q`

- [ ] **Step 3: Implement user-scoped and admin-only routers**

Use `get_current_user_from_request` for user endpoints and `require_admin_user` for admin endpoints. Mock payment transitions `pending` to `paid` and credits the wallet atomically.

- [ ] **Step 4: Run router tests**

Run: `cd backend && uv run pytest tests/test_billing_router.py tests/test_admin_billing_router.py -q`

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers backend/app/gateway/app.py backend/tests/test_billing_router.py backend/tests/test_admin_billing_router.py
git commit -m "feat: expose billing and admin APIs"
```

### Task 5: Build wallet UI and insufficient-credit dialog

**Files:**
- Create: `frontend/src/core/billing/api.ts`
- Create: `frontend/src/components/workspace/billing/wallet-card.tsx`
- Create: `frontend/src/components/workspace/billing/insufficient-credits-dialog.tsx`
- Modify: `frontend/src/components/workspace/settings/account-settings-page.tsx`
- Modify: `frontend/src/components/workspace/chats/use-thread-chat.ts`
- Test: `frontend/src/components/workspace/billing/insufficient-credits-dialog.test.tsx`

**Interfaces:**
- `BillingApi.getWallet(): Promise<Wallet>` and `BillingApi.createMockOrder(packageId, provider, idempotencyKey): Promise<Order>`.
- `InsufficientCreditsDialog` receives `availableCredits`, `requiredCredits`, and a `onRecharge` callback.

- [ ] **Step 1: Write a failing dialog test**

```tsx
it("opens a recharge action for INSUFFICIENT_CREDITS", async () => {
  render(<InsufficientCreditsDialog open availableCredits={8} requiredCredits={10} />);
  expect(screen.getByText("积分不足")).toBeVisible();
  expect(screen.getByRole("button", { name: "立即充值" })).toBeEnabled();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- insufficient-credits-dialog.test.tsx`

- [ ] **Step 3: Implement wallet display, mock recharge, and 402 handling**

Parse the stable backend error, display current and required credits, and do not retry the run automatically after recharge.

- [ ] **Step 4: Run frontend checks**

Run: `cd frontend && pnpm test -- insufficient-credits-dialog.test.tsx && pnpm lint`

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: add wallet and insufficient-credit experience"
```

### Task 6: Add administrator billing screens and release verification

**Files:**
- Create: `frontend/src/app/workspace/admin/page.tsx`
- Create: `frontend/src/components/workspace/admin/users-table.tsx`
- Create: `frontend/src/components/workspace/admin/billing-dashboard.tsx`
- Test: `frontend/tests/e2e/billing-credit-guard.spec.ts`

- [ ] **Step 1: Write a failing user-isolation browser test**

```ts
test("a user cannot read another user's ledger", async ({ request }) => {
  const response = await request.get("/api/billing/ledger?user_id=another-user");
  expect(response.status()).toBe(200);
  expect((await response.json()).items).toEqual([]);
});
```

- [ ] **Step 2: Run the E2E test to verify failure**

Run: `cd frontend && pnpm playwright test tests/e2e/billing-credit-guard.spec.ts`

- [ ] **Step 3: Implement admin page and verify all role-gated views**

Render users, balances, freeze controls, manual adjustments, and usage rows only for `system_role === "admin"`; redirect non-administrators away from `/workspace/admin`.

- [ ] **Step 4: Run release verification**

Run: `cd backend && make test && cd ../frontend && pnpm lint && pnpm test`

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/tests/e2e
git commit -m "feat: add billing administration workspace"
```
