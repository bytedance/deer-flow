import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

// Browser presentation regression with simulated recovered API state. The real
// SIGKILL/write/restart path is covered by test_batch_gateway_crash_recovery.py.
for (const zh of [false, true]) {
  test(`unknown batch outcome blocks retry and follow-up (${zh ? "zh narrow" : "en desktop"})`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: zh ? 390 : 1440, height: 1000 });
    await page.context().addCookies([
      {
        name: "locale",
        value: zh ? "zh-CN" : "en-US",
        url: testInfo.project.use.baseURL!,
      },
    ]);
    await page.addInitScript(() => localStorage.setItem("theme", "light"));
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Native batch recovery",
          messages: [
            {
              type: "human",
              id: "request",
              content: "Write the record, then prepare its summary.",
            },
            {
              type: "ai",
              id: "submitted",
              content: "The background batch has been submitted.",
            },
          ],
        },
      ],
    });
    await page.route("**/api/features", (route) =>
      route.fulfill({
        json: {
          agents_api: { enabled: true },
          browser_control: { enabled: false },
          subagent_batches: {
            repository_available: true,
            worker_running: true,
            max_running: 8,
          },
        },
      }),
    );
    const prefix = `/api/threads/${MOCK_THREAD_ID}/subagent-batches`;
    const write = {
      id: "item-write",
      batch_id: "recovery",
      item_key: "write-record",
      position: 0,
      status: "outcome_unknown",
      attempt: 1,
      attempt_id: "attempt-before-crash",
      dispatch_started_at: "2026-11-08T07:00:00Z",
      result_preview: null,
      error: "Execution lease expired after dispatch; outcome unknown.",
    };
    const items = [
      write,
      {
        id: "item-summary",
        batch_id: "recovery",
        item_key: "dependent-summary",
        position: 1,
        status: "pending",
        attempt: 0,
        result_preview: null,
      },
    ];
    let itemReads = 0;
    const mutations: string[] = [];
    await page.route(`**${prefix}**`, (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (request.method() !== "GET") {
        mutations.push(pathname);
        return route.fulfill({ status: 409 });
      }
      if (pathname.endsWith("/items/0"))
        return route.fulfill({
          json: {
            ...write,
            report: null,
            report_truncated: false,
            evidence: null,
            acceptance_criteria: null,
            acceptance_verdict: null,
          },
        });
      if (pathname.endsWith("/items")) {
        itemReads++;
        return route.fulfill({ json: items });
      }
      return route.fulfill({
        json: [
          {
            id: "recovery",
            thread_id: MOCK_THREAD_ID,
            title: "Record write and summary",
            subagent_type: "general-purpose",
            status: "running",
            recovery_policy: "conservative",
            total_items: 2,
            max_live_items: 2,
            max_running_items: 1,
            max_attempts: 3,
            counts: {
              pending: 1,
              queued: 0,
              leased: 0,
              running: 0,
              succeeded: 0,
              failed: 0,
              cancelled: 0,
              outcome_unknown: 1,
            },
            continuation_status: "pending",
            continuation_run_id: null,
          },
        ],
      });
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByTestId("subagent-batches-trigger").click();
    const card = page.getByTestId("subagent-batch-recovery");
    const followup = zh
      ? "存在结果未知的条目，后续工作将继续等待。"
      : "Follow-up is waiting for unknown outcomes to be resolved.";
    const unknown = zh ? "结果未知" : "Outcome unknown";
    const hint = zh
      ? "操作可能已生效，但结果尚未保存。系统不会自动重试，依赖该条目的任务将继续等待。"
      : "The operation may have taken effect before its result was saved. It will not be retried automatically; dependent items remain blocked.";
    await expect(card.getByText(followup, { exact: true })).toBeVisible();
    await expect(
      card.getByText(zh ? "0/2 已结束" : "0 of 2 terminal"),
    ).toBeVisible();
    await card
      .getByRole("button", { name: zh ? "查看条目" : "View items" })
      .click();
    await expect(card.getByText(unknown, { exact: true })).toBeVisible();
    await expect(card.getByText(hint, { exact: true })).toBeVisible();
    await expect(
      card.getByText("dependent-summary", { exact: true }),
    ).toBeVisible();
    await expect(card.getByText("pending", { exact: true })).toBeVisible();
    await expect(
      card.getByRole("button", { name: zh ? "重试" : "Retry", exact: true }),
    ).toHaveCount(0);
    // Wait for a real refresh so the unknown state isn't only an initial frame.
    await expect.poll(() => itemReads).toBeGreaterThan(1);
    await page.screenshot({
      path: testInfo.outputPath("unknown-batch-panel.png"),
      fullPage: true,
      animations: "disabled",
    });

    await card
      .getByRole("button", { name: zh ? "查看结果" : "Review result" })
      .first()
      .click();
    const detail = page.getByRole("dialog", {
      name: zh ? "批处理结果" : "Batch result",
    });
    await expect(detail.getByText(unknown, { exact: true })).toBeVisible();
    await expect(detail.getByText(hint, { exact: true })).toBeVisible();
    await expect(
      detail.getByText(
        zh ? "该条目还没有保存报告。" : "No report has been stored yet.",
        { exact: true },
      ),
    ).toBeVisible();
    expect(mutations).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath("unknown-batch-detail.png"),
      fullPage: true,
      animations: "disabled",
    });
  });
}
