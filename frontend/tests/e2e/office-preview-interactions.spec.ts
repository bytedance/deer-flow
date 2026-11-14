import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";
import { mockOfficePreview, officeFixtures } from "./utils/office-preview";

const threadId = "00000000-0000-0000-0000-000000009812";
const names = ["navigation.xlsx", "navigation.docx", "project-review.pptx"];
const qa = path.resolve("test-results/office-preview");

async function setup(page: Page) {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  const files = names.map((name) => `/mnt/user-data/outputs/${name}`);
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "File interaction review",
        artifacts: files,
        messages: [
          { type: "human", id: "ask", content: "Review these files" },
          {
            type: "ai",
            id: "ready",
            content: "Files are ready.",
            tool_calls: [
              {
                id: "present",
                name: "present_files",
                args: { filepaths: files },
              },
            ],
          },
        ],
      },
    ],
  });
  await mockOfficePreview(page);
  await page.route(`**/api/threads/${threadId}/artifacts/**`, async (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop()!;
    await route.fulfill({
      body: await readFile(path.join(officeFixtures, name)),
      contentType: "application/octet-stream",
    });
  });
  await page.goto(`/workspace/chats/${threadId}`);
  await expect(page.getByText("Files are ready.")).toBeVisible();
  await mkdir(qa, { recursive: true });
}
async function open(page: Page, name: string) {
  await page
    .getByRole("button", {
      name: `${name} ${name.endsWith("xlsx") ? "Excel" : name.endsWith("docx") ? "Word" : "PowerPoint"}`,
      exact: true,
    })
    .click();
  return page.locator("#artifacts");
}
async function switchFile(page: Page, name: string) {
  await page.locator("#artifacts [role=combobox]").click();
  await page.getByRole("option", { name, exact: true }).click();
}
const find = (panel: Locator) =>
  panel.getByRole("searchbox", { name: "Find in file", exact: true });

test("Excel finds across visible sheets, excludes hidden and truncated cells and restores each file's reading state", async ({
  page,
}) => {
  await setup(page);
  const panel = await open(page, names[0]!);
  await expect(panel.getByRole("table", { name: "Navigation" })).toBeVisible();
  await find(panel).fill("  Search target  ");
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("1 / 2");
  await expect(panel.locator('td[data-address="E8"] mark')).toHaveText(
    "Search target",
  );
  await expect(panel.locator(".search-scope")).toContainText("500 rows");
  await panel.getByRole("button", { name: "Next match", exact: true }).click();
  await expect(
    panel.getByRole("tab", { name: "Other sheet", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(panel.locator('td[data-address="A2"] mark')).toHaveAttribute(
    "data-current",
    "true",
  );
  await panel
    .getByRole("button", { name: "Previous match", exact: true })
    .click();
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("1 / 2");
  await find(panel).fill("[literal].*");
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("0 matches");
  await find(panel).fill("Search target");
  await panel.getByRole("button", { name: "Next match", exact: true }).click();
  await panel.getByRole("button", { name: "Zoom in", exact: true }).click();
  const zoom = await panel.locator(".bar .muted").last().textContent();
  await page.screenshot({
    path: path.join(qa, "excel-cross-sheet-search-light.png"),
    animations: "disabled",
  });
  await switchFile(page, names[1]!);
  await expect(panel.locator("section.docx")).toHaveCount(3);
  await switchFile(page, names[0]!);
  await expect(
    panel.getByRole("tab", { name: "Other sheet", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(panel.locator(".bar .muted").last()).toHaveText(zoom!);
  await expect(panel.locator('td[data-address="A2"]')).toHaveAttribute(
    "data-selected",
    "true",
  );
});

test("Word searches styled runs, navigates real headings, collapses its outline and restores scroll and zoom", async ({
  page,
}) => {
  await setup(page);
  const panel = await open(page, names[1]!);
  await expect(panel.locator("section.docx")).toHaveCount(3);
  const outline = panel.getByRole("navigation", { name: "Document outline" });
  await expect(outline.getByRole("button")).toHaveCount(3);
  await find(panel).fill("Search target");
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("1 / 3");
  await expect(panel.locator("mark[data-office-match]")).toHaveCount(6);
  await find(panel).press("Shift+Enter");
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("3 / 3");
  await page.mouse.move(30, 30);
  await page.screenshot({
    path: path.join(qa, "word-search-light.png"),
    animations: "disabled",
  });
  await find(panel).press("Escape");
  await outline
    .getByRole("button", { name: "Final review page", exact: true })
    .click();
  await expect(panel.locator(".tabs")).toContainText("3 / 3");
  await panel.getByRole("button", { name: "Zoom in", exact: true }).click();
  const zoom = await panel.locator(".bar .muted").last().textContent();
  const scroll = await panel
    .locator(".canvas")
    .evaluate((node) => node.scrollTop);
  await page.screenshot({
    path: path.join(qa, "word-outline-light.png"),
    animations: "disabled",
  });
  await panel
    .getByRole("button", { name: "Toggle document outline", exact: true })
    .click();
  await expect(outline).toBeHidden();
  await switchFile(page, names[0]!);
  await expect(panel.getByRole("table", { name: "Navigation" })).toBeVisible();
  await switchFile(page, names[1]!);
  await expect(panel.locator("section.docx")).toHaveCount(3);
  await expect(panel.locator(".bar .muted").last()).toHaveText(zoom!);
  await expect(panel.locator(".tabs")).toContainText("3 / 3");
  await expect(outline).toBeHidden();
  await expect
    .poll(() => panel.locator(".canvas").evaluate((node) => node.scrollTop))
    .toBeCloseTo(scroll, -1);
});

test("PPT search changes slide, keeps thumbnails sandboxed and restores page, zoom and navigation visibility", async ({
  page,
}) => {
  await setup(page);
  const panel = await open(page, names[2]!);
  await expect(panel.locator("iframe.slide")).toBeVisible();
  const thumbnails = panel.getByRole("navigation", {
    name: "Slide thumbnails",
  });
  await expect(thumbnails.getByRole("button")).toHaveCount(2);
  await expect(thumbnails.locator("iframe").first()).toHaveAttribute(
    "sandbox",
    "",
  );
  await panel.getByRole("button", { name: "Slide 2", exact: true }).click();
  const slideText = panel.frameLocator("iframe.slide").locator("body");
  // Compare actual glyph positions, including text after the highlighted word.
  // Converter text boxes use flex: inserting marks must not create extra items.
  const glyphPositions = () =>
    slideText.evaluate((body) => {
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      const positions: { text: string; x: number; y: number }[] = [];
      let node;
      while ((node = walker.nextNode())) {
        if (node.parentElement?.closest("style,script")) continue;
        for (let index = 0; index < node.textContent!.length; index++) {
          const text = node.textContent![index]!;
          if (!text.trim()) continue;
          const range = document.createRange();
          range.setStart(node, index);
          range.setEnd(node, index + 1);
          const { x, y } = range.getBoundingClientRect();
          positions.push({ text, x, y });
        }
      }
      return positions;
    });
  await expect(slideText).toContainText(/milestone/i);
  const unhighlighted = await glyphPositions();
  await find(panel).fill("milestone");
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("1 / 1");
  await expect(panel.locator(".tabs")).toContainText("2 / 2");
  await expect(
    panel.frameLocator("iframe.slide").locator("mark[data-current=true]"),
  ).toContainText(/milestone/i);
  const highlighted = await glyphPositions();
  expect(highlighted.map(({ text }) => text)).toEqual(
    unhighlighted.map(({ text }) => text),
  );
  for (let index = 0; index < unhighlighted.length; index++) {
    expect(highlighted[index]!.x).toBeCloseTo(unhighlighted[index]!.x, 0);
    expect(highlighted[index]!.y).toBeCloseTo(unhighlighted[index]!.y, 0);
  }
  await panel.getByRole("button", { name: "Zoom in", exact: true }).click();
  const zoom = await panel.locator(".bar .muted").last().textContent();
  await page.screenshot({
    path: path.join(qa, "ppt-search-thumbnails-light.png"),
    animations: "disabled",
  });
  await panel
    .getByRole("button", { name: "Toggle slide thumbnails", exact: true })
    .click();
  await expect(thumbnails).toBeHidden();
  await switchFile(page, names[0]!);
  await expect(panel.getByRole("table", { name: "Navigation" })).toBeVisible();
  await switchFile(page, names[2]!);
  await expect(panel.locator(".tabs")).toContainText("2 / 2");
  await expect(panel.locator(".bar .muted").last()).toHaveText(zoom!);
  await expect(thumbnails).toBeHidden();
});
