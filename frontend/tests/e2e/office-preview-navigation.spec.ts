import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";
import { mockOfficePreview, officeFixtures } from "./utils/office-preview";

const threadId = "00000000-0000-0000-0000-000000009811";

async function openFile(page: Page, name: string) {
  const filepath = `/mnt/user-data/outputs/${name}`;
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "Navigation review",
        artifacts: [filepath],
        messages: [
          { type: "human", id: "request", content: "Review this file" },
          {
            type: "ai",
            id: "result",
            content: "Ready to review.",
            tool_calls: [
              {
                id: "present",
                name: "present_files",
                args: { filepaths: [filepath] },
              },
            ],
          },
        ],
      },
    ],
  });
  await mockOfficePreview(page);
  await page.route(`**/api/threads/${threadId}/artifacts/**`, async (route) =>
    route.fulfill({
      body: await readFile(path.join(officeFixtures, name)),
      contentType: "application/octet-stream",
    }),
  );
  await page.goto(`/workspace/chats/${threadId}`);
  await page
    .getByRole("button", {
      name: `${name} ${name.endsWith("xlsx") ? "Excel" : "Word"}`,
      exact: true,
    })
    .click();
  return page.locator("#artifacts");
}

test("spreadsheet keyboard navigation skips hidden cells and merged ranges, remembers selection and copies values", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const panel = await openFile(page, "navigation.xlsx");
  await expect(panel.getByRole("table", { name: "Navigation" })).toBeVisible();
  await expect(panel.locator('td[tabindex="0"]')).toHaveCount(1);
  await panel.locator('td[data-address="A1"]').focus();
  await page.keyboard.press("ArrowRight");
  await expect(panel.locator('td[data-address="C1"]')).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(panel.locator('td[data-address="C3"]')).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(panel.locator('td[data-address="E3"]')).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(panel.locator('td[data-address="C3"]')).toBeFocused();
  await panel
    .getByRole("textbox", { name: "Go to cell", exact: true })
    .fill("D3");
  await panel
    .getByRole("button", { name: "Go to cell address", exact: true })
    .click();
  await expect(panel.locator('td[data-address="C3"]')).toBeFocused();
  await panel.locator('td[data-address="C4"]').focus();
  await page.keyboard.press("ArrowDown");
  const merged = panel.locator('td[data-address="A5"]');
  await expect(merged).toBeFocused();
  await expect(merged).toHaveAttribute("rowspan", "2");
  await expect(merged).toHaveAttribute("colspan", "2");
  await page.keyboard.press("ArrowRight");
  await expect(panel.locator('td[data-address="D5"]')).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(merged).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(panel.locator('td[data-address="A8"]')).toBeFocused();
  await panel.locator('td[data-address="C3"]').focus();
  await panel
    .getByRole("button", { name: "Copy cell value", exact: true })
    .click();
  await expect(
    panel.getByRole("status", { name: "Cell action status" }),
  ).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "Merged cell",
  );
  const tab = panel.getByRole("tab", { name: "Navigation", exact: true });
  await tab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    panel.getByRole("tab", { name: "Other sheet", exact: true }),
  ).toBeFocused();
  await expect(panel.locator(".formula")).toContainText("Other value");
  await page.keyboard.press("Home");
  await expect(panel.locator(".formula")).toContainText("C3");
  await expect(panel.locator(".formula")).toContainText("Merged cell");
  await expect(panel.locator('td[tabindex="0"]')).toHaveCount(1);
});

test("Word page controls follow manual scrolling and fit width follows viewport changes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const panel = await openFile(page, "navigation.docx");
  await expect(panel.locator("section.docx")).toHaveCount(3);
  const previous = panel.getByRole("button", {
    name: "Previous page",
    exact: true,
  });
  const next = panel.getByRole("button", { name: "Next page", exact: true });
  await expect(previous).toBeDisabled();
  await next.click();
  await expect(panel.locator(".tabs")).toContainText("2 / 3");
  await panel.locator(".canvas").evaluate((canvas) => {
    canvas.scrollTop = canvas.scrollHeight;
  });
  await expect(panel.locator(".tabs")).toContainText("3 / 3");
  await expect(next).toBeDisabled();
  await previous.click();
  await expect(panel.locator(".tabs")).toContainText("2 / 3");
  const oldZoom = await panel.locator(".bar .muted").last().textContent();
  await page.setViewportSize({ width: 900, height: 960 });
  await expect(panel.locator(".bar .muted").last()).not.toHaveText(oldZoom!);
  await expect(
    panel.getByRole("button", { name: "Fit width", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await panel.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Fit width", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
});

test("Word preview and outline work without secure-context crypto", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, "crypto", {
      value: {},
      configurable: true,
    });
  });
  const panel = await openFile(page, "navigation.docx");
  await expect(panel.locator("section.docx")).toHaveCount(3);
  await expect(
    panel
      .getByRole("navigation", { name: "Document outline" })
      .getByRole("button"),
  ).toHaveCount(3);
});

test("Excel pending search supports Enter and Escape", async ({ page }) => {
  const panel = await openFile(page, "chart-only.xlsx");
  const find = panel.getByRole("searchbox", { name: "Find in file" });
  const matches = panel.getByRole("status", { name: "Search matches" });
  await expect(panel.getByRole("table", { name: "Summary" })).toBeVisible();
  await find.fill("Design");
  await find.press("Enter");
  await expect(matches).toHaveText("1 / 2");
  await find.fill("Documentation");
  await find.press("Escape");
  await expect(matches).toHaveText("Find text");
  await expect(panel.locator("mark[data-office-match]")).toHaveCount(0);
});

test("chart-only Excel drawings do not prevent cell previews or cross-sheet search", async ({
  page,
}) => {
  const panel = await openFile(page, "chart-only.xlsx");
  await expect(panel.getByRole("table", { name: "Summary" })).toBeVisible();
  await expect(panel.locator('td[data-address="B2"]')).toHaveText("8");
  await panel.getByRole("searchbox", { name: "Find in file" }).fill("Design");
  const matches = panel.getByRole("status", { name: "Search matches" });
  await expect(matches).toHaveText("1 / 2");
  await panel.getByRole("button", { name: "Next match", exact: true }).click();
  await expect(matches).toHaveText("2 / 2");
  await expect(
    panel.getByRole("tab", { name: "Design", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(panel.locator('td[data-address="A1"]')).toHaveText(
    "Design review",
  );
  await expect(panel.locator('td[data-address="A2"]')).toHaveText(
    "Documentation",
  );
  const downloadPromise = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download chart-only.xlsx", exact: true })
    .click();
  const download = await downloadPromise;
  expect(await readFile(await download.path())).toEqual(
    await readFile(path.join(officeFixtures, "chart-only.xlsx")),
  );
});
