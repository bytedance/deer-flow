import { expect, test } from "@playwright/test";

test("search titles and old message bodies, navigate both directions and return to live history", async ({
  page,
  request,
}, testInfo) => {
  const threadId = `search-${Date.now()}`;
  const title = "新能源行业调研 · 2026 秋季";
  const needle = "储能成本测算";
  const created = await request.post("/api/threads", {
    data: { thread_id: threadId, metadata: { title } },
  });
  expect(created.status(), await created.text()).toBe(200);
  const renamed = await request.post(`/api/threads/${threadId}/state`, {
    data: { values: { title } },
  });
  expect(renamed.ok(), await renamed.text()).toBeTruthy();
  const messages = Array.from({ length: 140 }, (_, i) => ({
    id: `search-message-${i}`,
    role: i % 2 ? "ai" : "human",
    content:
      i === 5
        ? `## ${needle}\n\n报告比较了不同储能路线的单位成本与回收周期。\n\n\`\`\`python\ndef payback_years(capex, annual_savings):\n    return capex / annual_savings\n\`\`\`\n\n建议采用分阶段投资方案，并持续跟踪电价变化。`
        : `${i % 2 ? "分析结果" : "后续问题"} ${i}：比较不同技术路线与市场数据。`,
  }));
  const seeded = await request.post("/api/test-only/seed-runs", {
    data: {
      thread_id: threadId,
      runs: [
        {
          run_id: `${threadId}-run`,
          created_at: "2026-10-25T08:00:00Z",
          messages,
        },
      ],
    },
  });
  expect(seeded.ok(), await seeded.text()).toBeTruthy();
  await page.goto("/workspace/chats/new");
  await page
    .getByRole("button", { name: /^Search/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  const input = dialog.getByPlaceholder("Search titles and messages…");
  await input.fill("新能源");
  await expect(
    dialog.getByRole("option").filter({ hasText: title }).first(),
  ).toBeVisible();
  await input.fill(needle);
  const result = dialog.getByRole("option").filter({ hasText: needle }).first();
  await expect(result).toBeVisible({ timeout: 30_000 });
  await expect(result.locator("mark")).toHaveText(needle);
  await page.screenshot({ path: testInfo.outputPath("search-panel.png") });
  await result.click();
  await expect(page).toHaveURL(/message=search-message-5&message_seq=6/);
  const window = page.getByTestId("search-message-window");
  const target = window.locator('[data-search-target="true"]');
  await expect(target).toContainText(needle);
  await expect(target).toBeInViewport();
  await expect(window.locator("article")).toHaveCount(26);
  await page.screenshot({ path: testInfo.outputPath("message-jump.png") });
  await window.getByRole("button", { name: "Later messages" }).click();
  await expect(target).toHaveAttribute("data-message-id", "search-message-25");
  await window.getByRole("button", { name: "Earlier messages" }).click();
  await expect(target).toHaveAttribute("data-message-id", "search-message-5");
  await page.reload();
  await expect(window.locator('[data-search-target="true"]')).toContainText(
    needle,
  );
  await window
    .getByRole("button", { name: "Return to latest messages" })
    .click();
  await expect(page).not.toHaveURL(/message=/);
  await expect(window).toBeHidden();
  await expect(
    page.getByText("分析结果 139：比较不同技术路线与市场数据。", {
      exact: true,
    }),
  ).toBeVisible();
});
