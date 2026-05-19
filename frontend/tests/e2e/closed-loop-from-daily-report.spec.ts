import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const REPORT_TICKET_ID = "tkt-rep001rep001rep0";

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

function reportTicket(): ClosureTicket {
  const now = new Date().toISOString();
  return {
    id: REPORT_TICKET_ID,
    tenant_id: "default",
    title: "日报登记的整改项：油位偏低",
    description: "由日报 Agent 自动登记",
    status: "pending",
    priority: "normal",
    severity: "medium",
    device_id: "lub-2",
    device_name: "2#润滑油站",
    created_by: "agent:ai-report--daily",
    assignee_id: null,
    verifier_id: null,
    source_type: "daily_report",
    source_run_id: "daily-run-77",
    source_thread_id: "thr-daily-77",
    metadata: { observed_at: now },
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
  const ticket = reportTicket();

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

  await page.route(/\/api\/closure\/tickets(\?[^/]*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [ticket],
        meta: { total: 1, page: 1, page_size: 50 },
      }),
    }),
  );

  await page.route(`**/api/closure/tickets/${REPORT_TICKET_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ticket),
    }),
  );

  await page.route(
    `**/api/closure/tickets/${REPORT_TICKET_ID}/events`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          events: [
            {
              id: "evt-1",
              ticket_id: REPORT_TICKET_ID,
              action: "create",
              from_status: null,
              to_status: "pending",
              actor_id: "agent:ai-report--daily",
              payload: {},
              occurred_at: ticket.created_at,
            },
          ],
        }),
      }),
  );
}

test.describe("Closed-loop daily-report integration", () => {
  test("daily report ticket appears in workspace closed-loop list with source link", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockClosureAPI(page);

    await page.goto("/workspace/closed-loop?source=daily_report");

    await expect(page.getByRole("heading", { name: "闭环管理" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByText("日报登记的整改项：油位偏低"),
    ).toBeVisible();

    // Drawer shows source link
    await page.getByText("日报登记的整改项：油位偏低").first().click();
    await expect(
      page.getByRole("dialog", { name: "闭环单详情" }),
    ).toBeVisible();

    const link = page
      .getByRole("dialog", { name: "闭环单详情" })
      .getByRole("link");
    await expect(link).toHaveAttribute(
      "href",
      "/workspace/report-runs/daily-run-77",
    );
  });
});
