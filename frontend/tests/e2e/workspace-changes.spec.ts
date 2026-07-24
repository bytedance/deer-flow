import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000000321";
const RUN_ID = "run-workspace-changes";

test.describe("Workspace changes", () => {
  test("shows changed files badge and opens the diff panel", async ({
    page,
  }) => {
    const includeDiffValues: string[] = [];
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Workspace changes",
          updated_at: "2026-07-04T10:00:00Z",
          messages: [
            {
              type: "human",
              id: "msg-human-workspace-changes",
              content: [{ type: "text", text: "Create a report" }],
              run_id: RUN_ID,
            },
            {
              type: "ai",
              id: "msg-ai-workspace-changes",
              content: "I updated the workspace report.",
              run_id: RUN_ID,
            },
          ],
        },
      ],
    });
    await page.route(
      `**/api/threads/${THREAD_ID}/runs/${RUN_ID}/workspace-changes?*`,
      async (route) => {
        const url = new URL(route.request().url());
        const includeFiles = url.searchParams.get("include_files") !== "false";
        includeDiffValues.push(url.searchParams.get("include_diff") ?? "");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            available: true,
            version: 1,
            summary: {
              created: 1,
              modified: 1,
              deleted: 0,
              symlink_created: 0,
              additions: 8,
              deletions: 2,
              truncated: false,
            },
            files: includeFiles
              ? [
                  {
                    path: "/mnt/user-data/outputs/report.md",
                    root: "outputs",
                    status: "modified",
                    binary: false,
                    sensitive: false,
                    size_before: 12,
                    size_after: 20,
                    sha256_before: "before",
                    sha256_after: "after",
                    diff: "--- a/mnt/user-data/outputs/report.md\n+++ b/mnt/user-data/outputs/report.md\n@@ -1,2 +1,2 @@\n-Draft\n+Ready",
                    diff_truncated: false,
                    diff_unavailable_reason: null,
                    additions: 1,
                    deletions: 1,
                  },
                  {
                    path: "/mnt/user-data/workspace/notes.txt",
                    root: "workspace",
                    status: "created",
                    binary: false,
                    sensitive: false,
                    size_before: null,
                    size_after: 8,
                    sha256_before: null,
                    sha256_after: "created",
                    diff: "--- a/mnt/user-data/workspace/notes.txt\n+++ b/mnt/user-data/workspace/notes.txt\n@@ -0,0 +1 @@\n+Notes",
                    diff_truncated: false,
                    diff_unavailable_reason: null,
                    additions: 1,
                    deletions: 0,
                  },
                ]
              : [],
            limits: {},
          }),
        });
      },
    );

    await page.goto(`/workspace/chats/${THREAD_ID}`);

    await expect(page.getByText("Edited 2 files")).toBeVisible({
      timeout: 15_000,
    });
    // The human prompt carries the same run_id, but the badge must only render
    // under the assistant turn — never under the user's message.
    await expect(page.getByText("Edited 2 files")).toHaveCount(1);
    await expect(page.getByText("outputs/report.md")).toBeVisible();
    await expect(page.getByText("notes.txt")).toBeVisible();
    expect(includeDiffValues).toContain("false");

    await page.getByRole("button", { name: "View changes" }).click();
    await expect(
      page.getByRole("heading", { name: /workspace changes/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: /\/mnt\/user-data\/outputs\/report\.md/i,
      }),
    ).toBeVisible();
    expect(includeDiffValues).toContain("true");
    await expect(page.getByText("+Ready")).toBeVisible();
    await expect(page.getByText("-Draft")).toBeVisible();
  });
});
