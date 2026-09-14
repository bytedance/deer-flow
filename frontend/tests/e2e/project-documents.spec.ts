import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const THREAD_ID = "00000000-0000-0000-0000-000000000701";

function seedProject(): Parameters<typeof mockLangGraphAPI>[1] {
  return {
    projects: [{ id: PROJECT_ID, name: "Alpha" }],
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Project chat",
        updated_at: "2026-09-10T10:00:00Z",
        metadata: { deerflow_project_id: PROJECT_ID },
      },
    ],
  };
}

async function openDocumentsTab(page: Page) {
  await page.goto(`/workspace/projects/${PROJECT_ID}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("tab", { name: "Documents", exact: true }).click();
  await expect(page.getByTestId("project-documents-shelf")).toBeVisible();
}

test("project document lifecycle: upload → shelf → attach → trash → restore → purge", async ({
  page,
}) => {
  mockLangGraphAPI(page, seedProject());

  // Upload joins the shelf.
  await openDocumentsTab(page);
  await page.getByTestId("project-documents-upload-input").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("hello shelf"),
  });
  await expect(page.getByText("notes.txt", { exact: true })).toBeVisible();

  // Attach hands the thread's composer a completed attachment.
  await page
    .getByRole("button", { name: "Attach to chat", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Project chat", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/workspace/chats/${THREAD_ID}`));
  await expect(page.getByTestId("project-attachment-chip")).toContainText(
    "notes.txt",
  );

  // Move to trash behind its retention-window confirmation.
  await openDocumentsTab(page);
  await page
    .getByRole("button", { name: "Move to trash", exact: true })
    .click();
  await expect(
    page.getByText(/will move to the trash and stay recoverable for 30 days/),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Move to trash", exact: true })
    .click();
  await expect(page.getByText("No documents yet")).toBeVisible();

  // Trash view: origin project + retention, then restore into the origin.
  await page.goto("/workspace/trash", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("notes.txt", { exact: true })).toBeVisible();
  await expect(page.getByText(/from Alpha/)).toBeVisible();
  await expect(page.getByText(/days left/)).toBeVisible();
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.getByText("Trash is empty.")).toBeVisible();

  // Restored row is back on the shelf; trash it again, then purge for good.
  await openDocumentsTab(page);
  await expect(page.getByText("notes.txt", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Move to trash", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Move to trash", exact: true })
    .click();
  await page.goto("/workspace/trash", { waitUntil: "domcontentloaded" });
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByText(/will be permanently deleted. This cannot be undone./),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.getByText("Trash is empty.")).toBeVisible();
});

test("the shelf paginates past the first page and the trash confirmation names the configured retention", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    ...seedProject(),
    projectsConfig: { trash_retention_days: 7 },
    projectDocuments: Array.from({ length: 120 }, (_, index) => ({
      id: `doc-${index}`,
      project_id: PROJECT_ID,
      name: `doc-${String(index).padStart(3, "0")}.txt`,
      size_bytes: 128,
    })),
  });

  await openDocumentsTab(page);
  // First page: 100 of 120 loaded, with a Load more affordance.
  await expect(page.getByText("Showing 100 of 120")).toBeVisible();
  await expect(page.getByText("doc-099.txt", { exact: true })).toBeVisible();
  await expect(page.getByText("doc-119.txt", { exact: true })).toHaveCount(0);
  await page.getByTestId("project-documents-load-more").click();
  await expect(page.getByText("Showing 120 of 120")).toBeVisible();
  await expect(page.getByText("doc-119.txt", { exact: true })).toBeVisible();
  await expect(page.getByTestId("project-documents-load-more")).toHaveCount(0);

  // The confirmation names the server-configured 7-day window, not the
  // 30-day default.
  await page
    .getByRole("button", { name: "Move to trash", exact: true })
    .first()
    .click();
  await expect(page.getByText(/stay recoverable for 7 days/)).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
});

test("the trash view paginates and counts down the configured retention window", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    ...seedProject(),
    projectsConfig: { trash_retention_days: 7 },
    trashDocuments: Array.from({ length: 120 }, (_, index) => ({
      id: `trash-${index}`,
      project_id: PROJECT_ID,
      name: `trash-${String(index).padStart(3, "0")}.txt`,
      size_bytes: 64,
      // Trashed 10 days ago: past the configured 7-day window.
      trashed_at: new Date(Date.now() - 10 * 86_400_000).toISOString(),
      trash_origin: { project_id: PROJECT_ID, project_name: "Alpha" },
    })),
  });

  await page.goto("/workspace/trash", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Showing 100 of 120")).toBeVisible();
  await page.getByTestId("trash-load-more").click();
  await expect(page.getByText("Showing 120 of 120")).toBeVisible();
  await expect(page.getByTestId("trash-load-more")).toHaveCount(0);
  await expect(page.getByText(/Less than a day left/).first()).toBeVisible();
});

test("a project member thread renders no injected <project> text in the message list", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    projects: [
      {
        id: PROJECT_ID,
        name: "Alpha",
        instructions: "Always answer in haiku.",
      },
    ],
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Project chat",
        updated_at: "2026-09-10T10:00:00Z",
        metadata: { deerflow_project_id: PROJECT_ID },
        messages: [
          {
            type: "human",
            id: "msg-human-1",
            content: [{ type: "text", text: "status?" }],
          },
          { type: "ai", id: "msg-ai-1", content: "all green" },
        ],
      },
    ],
  });
  await page.goto(`/workspace/chats/${THREAD_ID}`, {
    waitUntil: "domcontentloaded",
  });
  const list = page.getByTestId("main-message-list");
  await expect(list.getByText("all green", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  // Project context is injected request-side only: no <project> block, and no
  // instructions text, ever reaches the rendered conversation.
  await expect(list.getByText(/<project>/)).toHaveCount(0);
  await expect(list.getByText(/Always answer in haiku/)).toHaveCount(0);
});
