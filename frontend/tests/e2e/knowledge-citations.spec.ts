import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

const sourceId = "0123456789abcdef0123456789abcdef-1";
const messages = [
  { id: "human-1", type: "human", content: "What is the maximum pressure?" },
  {
    id: "ai-search",
    type: "ai",
    content: "",
    tool_calls: [
      {
        id: "search-1",
        name: "knowledge_search",
        args: { query: "maximum pressure" },
      },
    ],
  },
  {
    id: "tool-1",
    type: "tool",
    name: "knowledge_search",
    tool_call_id: "search-1",
    content: `[citation:1](#knowledge-${sourceId}) Engineering / Safety manual.pdf\nMaximum pressure: 42 kPa.`,
    artifact: {
      knowledge_sources: {
        version: 1,
        sources: [
          {
            id: sourceId,
            provider: "ragflow",
            dataset_name: "Engineering",
            document_name: "Safety manual.pdf",
            dataset_id: "dataset-a",
            document_id: "doc-a",
            chunk_id: "chunk-a",
            text: "Maximum pressure: 42 kPa.\nInspect the seal before operation.",
            pages: [3],
            truncated: false,
          },
        ],
      },
    },
  },
  {
    id: "answer-1",
    type: "ai",
    content: `The maximum pressure is **42 kPa**. [citation:1](#knowledge-${sourceId})\n\n## Sources\n- [Safety manual.pdf](#knowledge-${sourceId})`,
  },
];

test("knowledge references open source evidence before and after history reload", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Knowledge source verification",
        messages,
      },
    ],
  });
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  const source = page.getByRole("button", {
    name: "View source: Safety manual.pdf",
  });
  await expect(source.first()).toBeVisible();
  await source.first().click();
  await expect(page.getByRole("dialog")).toContainText(
    "Maximum pressure: 42 kPa.",
  );
  await expect(page.getByRole("dialog")).toContainText("Pages 3");
  await expect(page.getByRole("dialog")).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: testInfo.outputPath("knowledge-citation-desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  // Sources-section links have an ordinary title, without the citation prefix.
  const titledSource = source.filter({ hasText: "Safety manual.pdf" }).first();
  await titledSource.click();
  await expect(page.getByRole("dialog")).toContainText(
    "Maximum pressure: 42 kPa.",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page.reload();
  await expect(source.first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await titledSource.click();
  await expect(page.getByRole("dialog")).toContainText(
    "Inspect the seal before operation.",
  );
  await expect(page.getByRole("dialog")).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: testInfo.outputPath("knowledge-citation-mobile.png"),
    fullPage: true,
  });
});
