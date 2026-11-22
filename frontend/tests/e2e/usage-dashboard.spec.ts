import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ timezoneId: "Asia/Shanghai" });

function summary(days: number) {
  const tokens = days === 7 ? 3000 : 10000;
  return {
    total_tokens: tokens,
    total_runs: 3,
    total_cost: 0.012,
    currency: "USD",
    days: Array.from({ length: days }, (_, index) => {
      const weight = [0.2, 0.3, 0.5][index - (days - 3)] ?? 0;
      const totalTokens = tokens * weight;
      const outputTokens = index === days - 1 ? 100 : 0;
      return {
        date: new Date(Date.UTC(2026, 9, 25 - days + index))
          .toISOString()
          .slice(0, 10),
        total_tokens: totalTokens,
        input_tokens: totalTokens - outputTokens,
        output_tokens: outputTokens,
        runs: weight > 0 ? 1 : 0,
        cost: 0.012 * weight,
      };
    }),
    by_model: {
      "deepseek-flash": {
        tokens,
        runs: 3,
        cost: 0.012,
        input_tokens: tokens - 100,
        cache_read_tokens: 500,
      },
    },
  };
}

test("switches the usage period, sends browser offset and exposes daily details", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  mockLangGraphAPI(page, { threads: [] });
  const offsets: string[] = [];
  await page.route("**/api/console/usage?*", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    offsets.push(query.get("tz_offset_minutes") ?? "");
    await route.fulfill({ json: summary(Number(query.get("days"))) });
  });
  await page.route("**/api/console/runs?*", (route) =>
    route.fulfill({ json: { runs: [], has_more: false } }),
  );
  await page.goto("/workspace/chats/new");
  await page
    .getByRole("link", { name: "Token usage", exact: true })
    .first()
    .click();
  await expect(page.getByTestId("usage-total-tokens")).toHaveText("3,000");
  await expect(page.getByTestId("usage-total-cost")).toHaveCount(0);
  await page.getByRole("button", { name: "Last 30 days" }).click();
  await expect(page.getByTestId("usage-total-tokens")).toHaveText("10,000");
  await page.getByText("View daily details", { exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Daily token usage", exact: true }),
  ).toBeVisible();
  expect(offsets.length).toBeGreaterThan(1);
  expect(offsets.every((value) => value === "480")).toBe(true);
  await expect(
    page.getByRole("link", { name: "Token usage", exact: true }).first(),
  ).toBeVisible();
  await page.getByText("View daily details", { exact: true }).click();
  await page
    .getByRole("heading", { name: "Token usage", exact: true })
    .scrollIntoViewIfNeeded();
  await testInfo.attach("usage-desktop", {
    body: await page.screenshot({
      path: testInfo.outputPath("usage-desktop.png"),
      fullPage: true,
    }),
    contentType: "image/png",
  });
});

test("recovers from reporting unavailability and shows token counts", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let available = false;
  await page.route("**/api/console/usage?*", (route) => {
    return !available
      ? route.fulfill({ status: 503, json: { detail: "database unavailable" } })
      : route.fulfill({ json: summary(7) });
  });
  await page.route("**/api/console/runs?*", (route) =>
    route.fulfill({ json: { runs: [], has_more: false } }),
  );
  await page.goto("/workspace/usage");
  await expect(
    page.getByRole("alert").filter({ hasText: "SQLite or PostgreSQL" }),
  ).toBeVisible();
  await expect(page.getByTestId("usage-total-cost")).toHaveCount(0);
  available = true;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByTestId("usage-total-tokens")).toHaveText("3,000");
});

test("pages run history and resets its offset when filtering failures", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/console/usage?*", (route) =>
    route.fulfill({ json: summary(7) }),
  );
  const requests: Array<{ offset: string; status: string | null }> = [];
  await page.route("**/api/console/runs?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const offset = query.get("offset") ?? "0";
    const status = query.get("status");
    requests.push({ offset, status });
    return route.fulfill({
      json: {
        has_more: offset === "0",
        runs: [
          {
            run_id: `run-${offset}-${status ?? "all"}`,
            thread_id: "thread/a #?",
            thread_title: offset === "0" ? "Latest report" : "Older report",
            assistant_id: null,
            status: status ?? "success",
            model_name: "deepseek-flash",
            created_at: "2026-10-25T08:00:00Z",
            updated_at: null,
            duration_seconds: 6.2,
            total_tokens: 100,
            message_count: 2,
            cost: 0.012,
            error: status === "error" ? "An upstream request failed" : null,
          },
        ],
      },
    });
  });
  await page.goto("/workspace/usage");
  await expect(
    page.getByRole("link", { name: "Latest report" }),
  ).toHaveAttribute("href", "/workspace/chats/thread%2Fa%20%23%3F");
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByRole("link", { name: "Older report" })).toBeVisible();
  await page
    .getByRole("combobox", { name: "Run status" })
    .selectOption("error");
  await expect(page.getByText("Page 1", { exact: true })).toBeVisible();
  await expect(page.getByText("Failed", { exact: true }).last()).toBeVisible();
  await page.getByText("Error details", { exact: true }).click();
  await expect(page.getByText("An upstream request failed")).toBeVisible();
  expect(requests).toContainEqual({ offset: "20", status: null });
  expect(requests).toContainEqual({ offset: "0", status: "error" });
});

test("renders Chinese on mobile without widening the document", async ({
  page,
  context,
  baseURL,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await context.addCookies([
    { name: "locale", value: "zh-CN", url: baseURL ?? "http://localhost:3000" },
  ]);
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/console/usage?*", (route) =>
    route.fulfill({ json: summary(7) }),
  );
  await page.route("**/api/console/runs?*", (route) =>
    route.fulfill({ json: { runs: [], has_more: false } }),
  );
  await page.goto("/workspace/usage");
  await expect(
    page.getByRole("heading", { name: "Token 用量", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("usage-total-cost")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "近 30 天", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await testInfo.attach("usage-mobile-zh", {
    body: await page.screenshot({
      path: testInfo.outputPath("usage-mobile-zh.png"),
      fullPage: true,
    }),
    contentType: "image/png",
  });
});
