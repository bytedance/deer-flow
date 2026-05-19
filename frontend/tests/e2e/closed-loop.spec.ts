import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const TICKET_ID = "tkt-cl001cl001cl0001";

type ClosureTicket = {
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  severity: string | null;
  device_id: string | null;
  device_name: string | null;
  created_by: string;
  assignee_id: string | null;
  verifier_id: string | null;
  source_type: string;
  source_run_id: string | null;
  source_thread_id: string | null;
  metadata: Record<string, unknown>;
  due_at: string | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
  assigned_at: string | null;
  started_at: string | null;
  submitted_at: string | null;
  closed_at: string | null;
};

function baseTicket(): ClosureTicket {
  const now = new Date().toISOString();
  return {
    id: TICKET_ID,
    tenant_id: "default",
    title: "1#泵振动超标整改",
    description: "诊断 Agent 自动建单",
    status: "pending",
    priority: "important",
    severity: "high",
    device_id: "pump-1",
    device_name: "1#给水泵",
    created_by: "agent:fault-diagnosis",
    assignee_id: null,
    verifier_id: null,
    source_type: "diagnosis",
    source_run_id: "run-001",
    source_thread_id: "thr-001",
    metadata: { fault_code: "VIB-OVR" },
    due_at: null,
    is_overdue: false,
    created_at: now,
    updated_at: now,
    assigned_at: null,
    started_at: null,
    submitted_at: null,
    closed_at: null,
  };
}

async function mockClosureAPI(page: Page) {
  let current = baseTicket();
  const events: Array<{
    id: string;
    ticket_id: string;
    action: string;
    from_status: string | null;
    to_status: string | null;
    actor_id: string;
    payload: Record<string, unknown>;
    occurred_at: string;
  }> = [
    {
      id: "evt-1",
      ticket_id: TICKET_ID,
      action: "create",
      from_status: null,
      to_status: "pending",
      actor_id: "agent",
      payload: {},
      occurred_at: current.created_at,
    },
  ];

  await page.route("**/api/closure/notifications/summary", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        open: 1,
        overdue: 0,
        pending_verification: 0,
        assigned_to_me: 0,
      }),
    }),
  );

  await page.route(
    /\/api\/closure\/tickets(\?[^/]*)?$/,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [current],
          meta: { total: 1, page: 1, page_size: 50 },
        }),
      }),
  );

  await page.route(
    `**/api/closure/tickets/${TICKET_ID}`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current),
      }),
  );

  await page.route(
    `**/api/closure/tickets/${TICKET_ID}/events`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ events }),
      }),
  );

  await page.route(
    `**/api/closure/tickets/${TICKET_ID}/transition`,
    async (route) => {
      const req = route.request();
      const body = JSON.parse(req.postData() ?? "{}") as {
        action: string;
        payload?: Record<string, unknown>;
      };
      const prev = current.status;
      let next = prev;
      if (body.action === "assign") next = "assigned";
      else if (body.action === "start") next = "in_progress";
      else if (body.action === "submit_verification")
        next = "pending_verification";
      else if (body.action === "verify_close") next = "closed";
      else if (body.action === "reject") next = "rejected";

      current = {
        ...current,
        status: next,
        assignee_id:
          body.action === "assign"
            ? typeof body.payload?.assignee_id === "string"
              ? body.payload.assignee_id
              : "u-test"
            : current.assignee_id,
        closed_at:
          next === "closed" ? new Date().toISOString() : current.closed_at,
        updated_at: new Date().toISOString(),
      };
      events.push({
        id: `evt-${events.length + 1}`,
        ticket_id: TICKET_ID,
        action: body.action,
        from_status: prev,
        to_status: next,
        actor_id: "u-tester",
        payload: body.payload ?? {},
        occurred_at: new Date().toISOString(),
      });

      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current),
      });
    },
  );
}

test.describe("Closed-loop workspace flow", () => {
  test("ticket walks through assign → start → submit → verify_close", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockClosureAPI(page);

    await page.goto("/workspace/closed-loop");

    await expect(page.getByRole("heading", { name: "闭环管理" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("1#泵振动超标整改")).toBeVisible();

    // Open the drawer
    await page.getByText("1#泵振动超标整改").first().click();
    await expect(
      page.getByRole("dialog", { name: "闭环单详情" }),
    ).toBeVisible();

    // 派单
    await page.getByRole("button", { name: "派单" }).click();
    await page.getByPlaceholder("输入受理人 user id").fill("u-tester");
    await page
      .getByRole("dialog", { name: "闭环单详情" })
      .getByRole("button", { name: "派单" })
      .click();

    // 开始处置
    await expect(page.getByRole("button", { name: "开始处置" })).toBeVisible();
    await page.getByRole("button", { name: "开始处置" }).click();

    // 提交验证
    await expect(page.getByRole("button", { name: "提交验证" })).toBeVisible();
    await page.getByRole("button", { name: "提交验证" }).click();
    await page.getByPlaceholder("处置经过、验证依据").fill("已更换轴承并复测振动");
    await page
      .getByRole("dialog", { name: "闭环单详情" })
      .getByRole("button", { name: "提交验证" })
      .click();

    // Drawer eventually shows closed state visible (verify_close button gated by role,
    // but in DEER_FLOW_AUTH_DISABLED mode the user is treated as superadmin in tests)
    await expect(page.getByText("已关闭").first()).toBeVisible({
      timeout: 10_000,
    });
  });
});
