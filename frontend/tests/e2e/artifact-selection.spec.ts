import { createHash } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  visibleRunInputMessages,
  runStreamThreadId,
} from "./utils/mock-api";

const filepath = "/mnt/user-data/outputs/selection-report.md";
const original =
  "# Quarterly report\n\nKeep the introduction.\n\nRevenue rose by 20 percent.\n\nKeep the conclusion.\n";
const revision = createHash("sha256").update(original).digest("hex");
const selected = "Revenue rose by 20 percent.";

async function setup(page: Page, source = original) {
  const api = mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Quarterly report",
        artifacts: [filepath],
        messages: [
          {
            type: "human",
            id: "question",
            content: "Write a quarterly report",
          },
          {
            type: "ai",
            id: "report",
            content: "The report is ready.",
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
  const writes: unknown[] = [];
  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/artifacts/mnt/user-data/outputs/selection-report.md`,
    async (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as { content: string };
        writes.push(body);
        source = body.content;
        return route.fulfill({
          json: {
            path: filepath,
            sha256: createHash("sha256").update(source).digest("hex"),
            size: source.length,
          },
        });
      }
      return route.fulfill({
        contentType: "text/markdown",
        headers: { ETag: `"${revision}"` },
        body: source,
      });
    },
  );
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await page.getByText("selection-report.md", { exact: true }).first().click();
  await expect(page.getByTestId("artifact-markdown-preview")).toContainText(
    "Quarterly report",
  );
  return { writes, api };
}

async function select(page: Page, text: string, occurrence = 0) {
  await page.getByTestId("artifact-markdown-preview").evaluate(
    (root, { text, occurrence }) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node: Node | null;
      let count = 0;
      while ((node = walker.nextNode())) {
        const start = (node.textContent ?? "").indexOf(text);
        if (start < 0 || count++ !== occurrence) continue;
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, start + text.length);
        window.getSelection()?.removeAllRanges();
        window.getSelection()?.addRange(range);
        node.parentElement!.dispatchEvent(
          new MouseEvent("mouseup", { bubbles: true }),
        );
        return;
      }
      throw new Error("Selection text not found");
    },
    { text, occurrence },
  );
  await expect(page.getByTestId("artifact-selection-toolbar")).toBeVisible();
}

test("artifact quotes retain the selected source line in the conversation", async ({
  page,
}, testInfo) => {
  const { writes } = await setup(page);
  await select(page, selected);
  await page.screenshot({
    path: testInfo.outputPath("artifact-selection-entry.png"),
    fullPage: true,
  });
  await page
    .getByTestId("artifact-selection-toolbar")
    .getByRole("button", { name: "Add to conversation" })
    .click();
  const composer = page.getByPlaceholder(/How can I assist you/i);
  const form = composer.locator("xpath=ancestor::form");
  await expect(form).toContainText("selected text fragment");
  let submitted: unknown;
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    submitted = route.request().postDataJSON();
    return handleRunStream(route);
  });
  await composer.fill("Explain this figure");
  await form.getByRole("button", { name: "Submit", exact: true }).click();
  await expect
    .poll(() => JSON.stringify(submitted))
    .toContain(`${filepath}:L5-L5`);
  expect(JSON.stringify(submitted)).toContain(selected);
  expect(writes).toHaveLength(0);
});

test("rewriting changes only the selection after review, then uses revision-checked Save", async ({
  page,
}, testInfo) => {
  const { writes, api } = await setup(page);
  let submitted: unknown;
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    submitted = route.request().postDataJSON();
    const answer = {
      type: "ai",
      id: "rewrite-answer",
      content: "Revenue increased by one fifth.",
    };
    const id = runStreamThreadId(route);
    const inputs = visibleRunInputMessages(route);
    api.upsertThread({
      ...api.getThread(id),
      thread_id: id,
      messages: [...inputs, answer],
    });
    return handleRunStream(route, {}, inputs, { responseMessage: answer });
  });
  await select(page, selected);
  await page
    .getByTestId("artifact-selection-toolbar")
    .getByRole("button", { name: "Rewrite selection" })
    .click();
  const review = page.getByTestId("artifact-rewrite-review");
  await expect(review).toContainText(`${filepath}:L5-L5`);
  await expect(
    review.getByRole("button", { name: "Review replacement" }),
  ).toBeDisabled();
  const composer = page.getByPlaceholder(/deeper follow-up/i);
  await composer.fill("Make the wording simpler");
  await composer
    .locator("xpath=ancestor::form")
    .getByRole("button", { name: "Submit", exact: true })
    .click();
  await expect(
    review.getByRole("button", { name: "Review replacement" }),
  ).toBeEnabled();
  expect(JSON.stringify(submitted)).toContain("artifact_selection_edit");
  expect(JSON.stringify(submitted)).toContain(selected);
  expect(writes).toHaveLength(0);
  await review.getByRole("button", { name: "Review replacement" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Selected passage")).toHaveValue(selected);
  await expect(dialog.getByLabel("Replacement", { exact: true })).toHaveValue(
    "Revenue increased by one fifth.",
  );
  await expect(dialog).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: testInfo.outputPath("artifact-rewrite-review.png"),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "Apply to draft" }).click();
  await expect(page.locator("#artifacts .cm-content")).toContainText(
    "Revenue increased by one fifth.",
  );
  expect(writes).toHaveLength(0);
  await page
    .locator("#artifacts")
    .getByRole("button", { name: "Save", exact: true })
    .click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({
    content: original.replace(selected, "Revenue increased by one fifth."),
    expected_sha256: revision,
  });
});

test("repeated paragraphs use source offsets of the selected occurrence", async ({
  page,
}) => {
  await setup(page, original + "\n" + selected + "\n");
  await select(page, selected, 1);
  await page
    .getByTestId("artifact-selection-toolbar")
    .getByRole("button", { name: "Rewrite selection" })
    .click();
  await expect(page.getByTestId("artifact-rewrite-review")).toContainText(
    `${filepath}:L9-L9`,
  );
});

test("source editor selections carry exact offsets and line ranges", async ({
  page,
}) => {
  await setup(page);
  await page.locator("#artifacts").getByLabel("View source").click();
  const editor = page.locator("#artifacts .cm-content");
  await editor.click();
  await editor.press("x");
  await expect(editor).not.toContainText("x");
  await editor.press("ControlOrMeta+a");
  await page
    .getByTestId("artifact-selection-toolbar")
    .getByRole("button", { name: "Rewrite selection" })
    .click();
  await expect(page.getByTestId("artifact-rewrite-review")).toContainText(
    `${filepath}:L1-L7`,
  );
});

test("formatted text can be quoted without guessing a replacement span", async ({
  page,
}) => {
  await setup(
    page,
    original.replace(selected, "Revenue rose by **20 percent**."),
  );
  await page
    .getByTestId("artifact-markdown-preview")
    .locator("p")
    .filter({ hasText: selected })
    .evaluate((paragraph) => {
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
      paragraph.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    });
  const toolbar = page.getByTestId("artifact-selection-toolbar");
  await expect(
    toolbar.getByRole("button", { name: "Rewrite selection" }),
  ).toBeDisabled();
  await toolbar.getByRole("button", { name: "Ask in side chat" }).click();
  await expect(page.getByPlaceholder(/deeper follow-up/i)).toBeVisible();
  await expect(page.getByTestId("sidecar-reference-attachment")).toContainText(
    "1 selected text fragment",
  );
});
