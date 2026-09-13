import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const threadId = "00000000-0000-0000-0000-000000003140";
const csvPath = "/mnt/user-data/outputs/monthly-revenue.csv";
const tsvPath = "/mnt/user-data/outputs/regional-summary.tsv";
const headers = ["Order ID", "Region", "Revenue (CNY)", "Growth", "Notes"];
const records = Array.from({ length: 65 }, (_, index) => [
  String(index + 1).padStart(5, "0"),
  ["华东 · Shanghai", "华南 · Shenzhen", "华北 · Beijing"][index % 3]!,
  String(128600 + index * 1350),
  `${8 + (index % 9)}.2%`,
  index === 0 ? "Includes online orders, excludes refunds" : "Reviewed",
]);
const csv = [headers, ...records]
  .map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(","))
  .join("\r\n");

async function setup(page: Page, body = csv, truncated = false) {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "Monthly revenue review",
        artifacts: [csvPath, tsvPath],
        messages: [
          {
            type: "human",
            id: "request",
            content:
              "Analyze monthly revenue by region and export the detailed results as CSV.",
          },
          {
            type: "ai",
            id: "answer",
            content:
              "The regional revenue analysis is ready. The detailed export preserves order IDs and includes revenue, growth, and review notes. Open the CSV to inspect the results before the next analysis.",
            tool_calls: [
              {
                id: "present",
                name: "present_files",
                args: { filepaths: [csvPath, tsvPath] },
              },
            ],
          },
        ],
      },
    ],
  });
  for (const suffix of [
    "token-usage",
    "mcp-tasks**",
    "runs/*/artifacts/archive",
  ])
    await page.route(`**/api/threads/${threadId}/${suffix}`, (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: "{}",
      }),
    );
  await page
    .context()
    .route(`**/api/threads/${threadId}/artifacts/**`, (route) => {
      const isTsv = route.request().url().endsWith(".tsv");
      const content = isTsv
        ? "Region\tRevenue\n华东\t128600\n华南\t132500"
        : body;
      return route.fulfill({
        status: truncated ? 206 : 200,
        contentType: "text/plain",
        headers: {
          ETag: `"${"a".repeat(64)}"`,
          ...(truncated
            ? {
                "Content-Range": `bytes 0-${Buffer.byteLength(content) - 1}/2000000`,
              }
            : {}),
        },
        body: content,
      });
    });
  await page.goto(`/workspace/chats/${threadId}`);
  await page.getByText("monthly-revenue.csv").first().click();
  return page.locator("#artifacts");
}

test("previews real Worker results, paginates, toggles source, and opens a wide viewer", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 980 });
  const panel = await setup(page);
  await expect(panel.getByRole("table")).toBeVisible({ timeout: 20000 });
  await expect(
    panel.getByRole("cell", { name: "00001", exact: true }),
  ).toBeVisible();
  await expect(panel.getByText("65 rows", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Next page" }).click();
  await expect(panel.getByText("51–65", { exact: true })).toBeVisible();
  await panel.getByRole("checkbox", { name: "First row as header" }).uncheck();
  await panel.getByRole("radio", { name: "View source" }).click();
  await expect(panel.locator(".cm-editor")).toBeVisible();
  await panel.getByRole("radio", { name: "Table preview" }).click();
  await expect(
    panel.getByRole("checkbox", { name: "First row as header" }),
  ).not.toBeChecked();
  await panel.getByRole("checkbox", { name: "First row as header" }).check();
  const viewerPromise = page.context().waitForEvent("page");
  await panel.getByRole("button", { name: "Open in new window" }).click();
  const viewer = await viewerPromise;
  await expect(viewer.getByRole("table")).toBeVisible();
  await expect(
    viewer.getByRole("cell", {
      name: "Includes online orders, excludes refunds",
    }),
  ).toBeVisible();
  if (process.env.DEERFLOW_SCREENSHOT_DIR) {
    await mkdir(process.env.DEERFLOW_SCREENSHOT_DIR, { recursive: true });
    await page.bringToFront();
    await expect(panel.getByRole("table")).toBeVisible();
    await page.screenshot({
      path: path.join(
        process.env.DEERFLOW_SCREENSHOT_DIR,
        "csv-preview-chat.png",
      ),
    });
    await viewer.screenshot({
      path: path.join(
        process.env.DEERFLOW_SCREENSHOT_DIR,
        "csv-preview-window.png",
      ),
    });
  }
  await viewer.setViewportSize({ width: 390, height: 844 });
  await expect(viewer.getByRole("table")).toBeVisible();
  expect(
    await viewer.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  if (process.env.DEERFLOW_SCREENSHOT_DIR) {
    await viewer.screenshot({
      path: path.join(
        process.env.DEERFLOW_SCREENSHOT_DIR,
        "csv-preview-mobile.png",
      ),
    });
  }
  await viewer.close();
  await panel.getByRole("combobox").click();
  await page.getByRole("option", { name: "regional-summary.tsv" }).click();
  await expect(
    panel.getByRole("cell", { name: "华东", exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("cell", { name: "00001", exact: true }),
  ).toHaveCount(0);
});

test("discards a truncated final record and does not fetch the full file in table mode", async ({
  page,
}) => {
  const panel = await setup(
    page,
    'ID,Note\n00123,complete\n002,"unfinished\nfield',
    true,
  );
  await expect(panel.getByRole("table")).toBeVisible({ timeout: 20000 });
  await expect(
    panel.getByText("Preview of first 1 rows", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByText("00123", { exact: true })).toBeVisible();
  await expect(panel.getByText("002", { exact: true })).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Load full file" }),
  ).toHaveCount(0);
});

test("rejects malformed quotes and keeps source available", async ({
  page,
}) => {
  const panel = await setup(page, 'ID,Note\n00123,"bad"quote');
  await expect(
    panel.getByText(/Unable to preview this table reliably/),
  ).toBeVisible({ timeout: 20000 });
  await panel.getByRole("radio", { name: "View source" }).click();
  await expect(panel.locator(".cm-editor")).toBeVisible();
});

test("previews an unsaved draft and preserves it after a save conflict", async ({
  page,
}) => {
  const panel = await setup(page);
  await expect(panel.getByRole("table")).toBeVisible();
  await panel.getByRole("button", { name: "Edit", exact: true }).click();
  const editor = panel.locator('.cm-content[contenteditable="true"]');
  await editor.fill("ID,Note\n00999,draft value");
  await panel.getByRole("radio", { name: "Table preview" }).click();
  await expect(
    panel.getByRole("cell", { name: "00999", exact: true }),
  ).toBeVisible();
  await page.route(`**/api/threads/${threadId}/artifacts/**`, (route) => {
    if (route.request().method() === "PUT")
      return route.fulfill({
        status: 412,
        contentType: "application/json",
        body: JSON.stringify({ detail: "The file changed on the server" }),
      });
    return route.fallback();
  });
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    panel.getByText("Changed remotely", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("cell", { name: "draft value", exact: true }),
  ).toBeVisible();
});

test("retains header preference after loading the full source", async ({
  page,
}) => {
  const panel = await setup(page, "ID,Note\n00123,complete\n002,partial", true);
  await expect(panel.getByRole("table")).toBeVisible();
  await panel.getByRole("checkbox", { name: "First row as header" }).uncheck();
  await panel.getByRole("radio", { name: "View source" }).click();
  await page.route(`**/api/threads/${threadId}/artifacts/**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/plain",
      body: "ID,Note\n00123,complete\n002,complete",
    }),
  );
  await panel.getByRole("button", { name: "Load full file" }).click();
  await expect(panel.locator(".cm-editor")).toBeVisible();
  await panel.getByRole("radio", { name: "Table preview" }).click();
  await expect(
    panel.getByRole("checkbox", { name: "First row as header" }),
  ).not.toBeChecked();
  await expect(
    panel.getByRole("cell", { name: "002", exact: true }),
  ).toBeVisible();
});
