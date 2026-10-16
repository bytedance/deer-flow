import { createHash } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const threadA = "00000000-0000-0000-0000-000000006696";
const threadB = "00000000-0000-0000-0000-000000006697";
const filepath = "/mnt/user-data/outputs/navigation-report.txt";
const original = "Original saved report";
const draft = "My draft survives chat navigation";

async function navigateToChat(page: Page, threadId: string) {
  const link = page.locator(`a[href="/workspace/chats/${threadId}"]`).first();
  if (!(await link.isVisible())) {
    await page.getByRole("button", { name: "Toggle Sidebar" }).first().click();
  }
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/workspace/chats/${threadId}$`));
}

test("retains drafts through chat navigation and keeps Save and Discard final", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadA,
        title: "Draft navigation A",
        artifacts: [filepath],
        messages: [
          { type: "human", id: "draft-human", content: "Write a report" },
          {
            type: "ai",
            id: "draft-ai",
            content: "Here is the report",
            tool_calls: [
              {
                id: "draft-present",
                name: "present_files",
                args: { filepaths: [filepath] },
              },
            ],
          },
        ],
      },
      { thread_id: threadB, title: "Draft navigation B", messages: [] },
    ],
  });
  let saved = original;
  let putCount = 0;
  const sha256 = () => createHash("sha256").update(saved).digest("hex");
  await page.route(
    `**/api/threads/${threadA}/artifacts${filepath}`,
    (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as {
          content: string;
          expected_sha256: string;
        };
        expect(body.expected_sha256).toBe(sha256());
        saved = body.content;
        putCount++;
        return route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            path: filepath,
            sha256: sha256(),
            size: Buffer.byteLength(saved),
          }),
        });
      }
      return route.fulfill({
        contentType: "text/plain; charset=utf-8",
        headers: { ETag: `"${sha256()}"` },
        body: saved,
      });
    },
  );

  await page.goto(`/workspace/chats/${threadA}`);
  await page
    .getByText("navigation-report.txt", { exact: true })
    .first()
    .click();
  const panel = page.locator("#artifacts");
  await expect(panel.locator(".cm-content")).toHaveText(original);
  await panel.getByRole("button", { name: "Edit", exact: true }).click();
  await panel.locator('.cm-content[contenteditable="true"]').fill(draft);
  await expect(panel.getByText("Unsaved", { exact: true })).toHaveCount(1);
  await page.screenshot({
    path: "output/playwright/artifact-draft-before-navigation.png",
  });

  await navigateToChat(page, threadB);
  await navigateToChat(page, threadA);
  await expect(panel.locator(".cm-content")).toHaveText(draft);
  await expect(panel.getByText("Unsaved", { exact: true })).toHaveCount(1);
  await panel.getByRole("button", { name: "Edit", exact: true }).click();
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Save", exact: true }),
  ).toBeDisabled();
  expect(putCount).toBe(1);
  expect(saved).toBe(draft);

  await navigateToChat(page, threadB);
  await navigateToChat(page, threadA);
  await expect(panel.locator(".cm-content")).toHaveText(draft);
  await expect(panel.getByText("Unsaved", { exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: "Edit", exact: true }).click();
  await panel
    .locator('.cm-content[contenteditable="true"]')
    .fill("Discard this edit");
  page.once("dialog", (dialog) => dialog.accept());
  await panel
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await navigateToChat(page, threadB);
  await navigateToChat(page, threadA);
  await expect(panel.locator(".cm-content")).toHaveText(draft);
  await expect(panel.getByText("Unsaved", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: "output/playwright/artifact-draft-after-save-return.png",
  });
});
