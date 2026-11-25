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

  test("collapses long file lists independently of the diff panel", async ({
    page,
  }) => {
    const runs = [3, 4, 40].map((count) => ({
      count,
      runId: `${RUN_ID}-${count}`,
    }));
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Workspace changes",
          messages: runs.flatMap(({ count, runId }) => [
            {
              type: "human",
              id: `request-${count}`,
              content: `Update ${count} files`,
              run_id: runId,
            },
            {
              type: "ai",
              id: `answer-${count}`,
              content: `Updated the ${count} requested files.`,
              run_id: runId,
            },
          ]),
        },
      ],
    });
    const fileName = (count: number, index: number) =>
      `report-${count}-${String(index).padStart(2, "0")}.md`;
    for (const { count, runId } of runs) {
      await page.route(
        `**/api/threads/${THREAD_ID}/runs/${runId}/workspace-changes?*`,
        async (route) => {
          const { searchParams } = new URL(route.request().url());
          await route.fulfill({
            json: {
              available: true,
              version: 1,
              summary: {
                created: count,
                modified: 0,
                deleted: 0,
                symlink_created: 0,
                additions: count,
                deletions: 0,
                truncated: false,
              },
              files: Array.from({ length: count }, (_, i) => ({
                path: `/mnt/user-data/workspace/${fileName(count, i + 1)}`,
                root: "workspace",
                status: "created",
                binary: false,
                sensitive: false,
                additions: 1,
                deletions: 0,
                diff:
                  searchParams.get("include_diff") === "true"
                    ? `@@ -0,0 +1 @@\n+Report ${i + 1}`
                    : "",
                diff_truncated: false,
                diff_unavailable_reason: null,
              })),
              limits: {},
            },
          });
        },
      );
    }
    await page.goto(`/workspace/chats/${THREAD_ID}`);

    const longTitle = page.getByText("Edited 40 files", { exact: true });
    await expect(longTitle).toBeVisible();
    const toggle = (count: number) =>
      page.getByRole("button", { name: `Edited ${count} files`, exact: true });
    const lastFile = (count: number) =>
      page.getByText(fileName(count, count), { exact: true });

    await expect(lastFile(3)).toBeVisible();
    await expect(toggle(3)).toHaveCount(0);
    await expect(lastFile(40)).toBeHidden();
    await expect(toggle(4)).toHaveAttribute("aria-expanded", "false");
    await expect(toggle(40)).toHaveAttribute("aria-expanded", "false");
    await toggle(40).press("Enter");
    await expect(toggle(40)).toHaveAttribute("aria-expanded", "true");
    await expect(lastFile(40)).toBeVisible();
    await expect(toggle(4)).toHaveAttribute("aria-expanded", "false");
    await toggle(40).press("Space");
    await expect(lastFile(40)).toBeHidden();
    await toggle(4).click();
    await expect(lastFile(4)).toBeVisible();
    await expect(toggle(40)).toHaveAttribute("aria-expanded", "false");

    const longTurn = page
      .locator("[data-assistant-turn]")
      .filter({ has: longTitle });
    await longTurn.getByRole("button", { name: "View changes" }).click();
    const panel = page.getByRole("dialog", { name: "Workspace changes" });
    await expect(panel.getByText("+Report 1", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(toggle(40)).toHaveAttribute("aria-expanded", "false");
    await expect(toggle(4)).toHaveAttribute("aria-expanded", "true");

    await page.reload();
    await expect(toggle(4)).toHaveAttribute("aria-expanded", "false");
    await expect(toggle(40)).toHaveAttribute("aria-expanded", "false");
  });

  test("renders one badge for a run that ends in two assistant bubbles", async ({
    page,
  }) => {
    // Answer text the model emitted mid-run that never gained a tool call
    // settles into its own terminal assistant bubble, so this run owns two.
    // The card is resolved from (threadId, runId) alone, so rendering it per
    // message painted the identical summary twice (#4555).
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Workspace changes",
          updated_at: "2026-07-04T10:00:00Z",
          messages: [
            {
              type: "human",
              id: "msg-human-multi-bubble",
              content: [{ type: "text", text: "Create a report" }],
              run_id: RUN_ID,
            },
            {
              type: "ai",
              id: "msg-ai-multi-bubble-first",
              content: "Let me check the workspace first.",
              run_id: RUN_ID,
            },
            {
              type: "ai",
              id: "msg-ai-multi-bubble-final",
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
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            available: true,
            version: 1,
            summary: {
              created: 0,
              modified: 1,
              deleted: 0,
              symlink_created: 0,
              additions: 8,
              deletions: 2,
              truncated: false,
            },
            files: [
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
                diff: null,
                diff_truncated: false,
                diff_unavailable_reason: null,
                additions: 8,
                deletions: 2,
              },
            ],
            limits: {},
          }),
        });
      },
    );

    await page.goto(`/workspace/chats/${THREAD_ID}`);

    await expect(page.getByText("Edited 1 file")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Edited 1 file")).toHaveCount(1);

    // The surviving card belongs to the run's last bubble, matching how run
    // duration anchors its own run-scoped display.
    const assistantTurns = page.locator("[data-assistant-turn]");
    await expect(assistantTurns).toHaveCount(2);
    await expect(assistantTurns.nth(0).getByText("Edited 1 file")).toHaveCount(
      0,
    );
    await expect(assistantTurns.nth(1).getByText("Edited 1 file")).toHaveCount(
      1,
    );
  });
});
