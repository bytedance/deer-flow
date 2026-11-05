import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// A relative link in an assistant message (`[Report](final-report.md)`) must
// open the thread artifact it names. Left as a relative href, the browser
// resolves it to /workspace/chats/final-report.md and the chat page then loads
// the file name as a thread id.
const THREAD_ID = "00000000-0000-0000-0000-000000007315";
const REPORT_NAME = "final-report.md";
const REPORT_PATH = `/mnt/user-data/outputs/${REPORT_NAME}`;
const REPORT_API = `/api/threads/${THREAD_ID}/artifacts${REPORT_PATH}`;

test("relative report link in a message opens the thread artifact", async ({
  page,
  context,
}, testInfo) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Relative artifact link",
        artifacts: [REPORT_PATH],
        messages: [
          {
            type: "human",
            id: "msg-human-rel-link",
            content: [{ type: "text", text: "Write the full report." }],
          },
          {
            type: "ai",
            id: "msg-ai-rel-link",
            content: `The report is ready: [Final report](${REPORT_NAME}). See also [missing appendix](appendix.md).`,
          },
        ],
      },
    ],
  });

  const artifactRequests: string[] = [];
  const chatNavigations: string[] = [];
  await context.route(
    (url) => url.pathname === REPORT_API,
    (route) => {
      artifactRequests.push(route.request().url());
      return route.fulfill({
        contentType: "text/markdown; charset=utf-8",
        body: "# Final report\n\nREPORT_BODY_MARKER",
      });
    },
  );
  context.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith(`/chats/${REPORT_NAME}`)) {
      chatNavigations.push(request.url());
    }
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);

  const reportLink = page.getByRole("link", { name: "Final report" });
  await expect(reportLink).toBeVisible({ timeout: 30_000 });
  await expect(reportLink).toHaveAttribute("href", REPORT_API);
  await expect(reportLink).toHaveAttribute("target", "_blank");

  // A relative link that names no artifact renders as text, not an anchor.
  await expect(page.getByText("missing appendix")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "missing appendix" }),
  ).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("chat-message.png") });

  const popupPromise = context.waitForEvent("page");
  await reportLink.click();
  const popup = await popupPromise;
  await expect(popup.locator("body")).toContainText("REPORT_BODY_MARKER");
  expect(new URL(popup.url()).pathname).toBe(REPORT_API);

  expect(artifactRequests.length).toBeGreaterThan(0);
  expect(chatNavigations).toEqual([]);
  await expect(page).toHaveURL(new RegExp(`/workspace/chats/${THREAD_ID}$`));
});

// The present_files message text is rendered outside MessageListItem.
test("links in the present_files message text resolve to artifacts", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Relative artifact link (present_files)",
        artifacts: [REPORT_PATH],
        messages: [
          {
            type: "human",
            id: "msg-human-rel-link-present",
            content: [{ type: "text", text: "Write the full report." }],
          },
          {
            type: "ai",
            id: "msg-ai-rel-link-present",
            content: `Done: [relative link](${REPORT_NAME}), [absolute link](${REPORT_PATH}).`,
            tool_calls: [
              {
                id: "present-rel-link",
                name: "present_files",
                args: { filepaths: [REPORT_PATH] },
              },
            ],
          },
        ],
      },
    ],
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);
  for (const name of ["relative link", "absolute link"]) {
    const link = page.getByRole("link", { name });
    await expect(link).toBeVisible({ timeout: 30_000 });
    await expect(link).toHaveAttribute("href", REPORT_API);
    await expect(link).toHaveAttribute("target", "_blank");
  }
});

// A reopened thread rebuilds its values from the Gateway's POST /history head,
// which carries messages but not `artifacts`. Links and the artifact panel
// must still find the files from the present_files call in the messages.
test("reopened thread without state artifacts still resolves links and lists files", async ({
  page,
}, testInfo) => {
  const files = [
    REPORT_PATH,
    "/mnt/user-data/outputs/change-notes.md",
    "/mnt/user-data/outputs/calculations.zip",
  ];
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Reopened thread",
        // No `artifacts`: mirrors the real /history head.
        messages: [
          {
            type: "human",
            id: "msg-human-reopened",
            content: [{ type: "text", text: "Deliver the files." }],
          },
          {
            type: "ai",
            id: "msg-ai-present-reopened",
            content: "",
            tool_calls: [
              {
                id: "present-reopened",
                name: "present_files",
                args: { filepaths: files },
              },
            ],
          },
          {
            type: "tool",
            id: "msg-tool-reopened",
            name: "present_files",
            tool_call_id: "present-reopened",
            content: "Successfully presented files",
          },
          {
            type: "ai",
            id: "msg-ai-reopened",
            content: [
              "All three deliverables are ready.",
              "### Downloads",
              `- [Final report](./${REPORT_NAME})`,
              "- [Change notes](./change-notes.md)",
              "- [Calculation package](./calculations.zip)",
            ].join("\n\n"),
          },
        ],
      },
    ],
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);
  for (const [name, path] of [
    ["Final report", files[0]],
    ["Change notes", files[1]],
    ["Calculation package", files[2]],
  ] as const) {
    const link = page.getByRole("link", { name, exact: true });
    await expect(link).toBeVisible({ timeout: 30_000 });
    await expect(link).toHaveAttribute(
      "href",
      `/api/threads/${THREAD_ID}/artifacts${path}`,
    );
  }
  await page.screenshot({ path: testInfo.outputPath("reopened-message.png") });

  // The artifact panel (and its header button) is fed the same way.
  await page.getByTestId("artifact-trigger").click();
  const panel = page.locator("#artifacts");
  for (const file of ["change-notes.md", "calculations.zip"]) {
    await expect(panel.getByText(file, { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: testInfo.outputPath("reopened-panel.png") });
});
