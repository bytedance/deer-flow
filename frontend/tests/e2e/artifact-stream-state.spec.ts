import { expect, test, type Route } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000003788";
const RUN_ID = "00000000-0000-0000-0000-000000003789";
const ARTIFACT_PATH = "/artifact-fixtures/report.md";
const THREAD_MESSAGES = [
  {
    type: "human",
    id: "msg-human-artifact",
    content: [{ type: "text", text: "Create a markdown report" }],
  },
  {
    type: "ai",
    id: "msg-ai-artifact",
    content: "Created a markdown report.",
  },
];

function streamWithoutArtifacts(route: Route) {
  const events = [
    {
      event: "metadata",
      data: { run_id: RUN_ID, thread_id: THREAD_ID },
    },
    {
      event: "values",
      data: {
        messages: [
          {
            type: "human",
            id: "msg-human-artifact-follow-up",
            content: [{ type: "text", text: "Continue" }],
          },
          {
            type: "ai",
            id: "msg-ai-artifact-follow-up",
            content: "Updated response while the artifact list is omitted.",
          },
        ],
      },
    },
  ];

  return route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: events
      .map((event) => {
        return `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
      })
      .join(""),
  });
}

test("keeps artifact trigger after stream values omit artifacts", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Artifact stream state",
        artifacts: [ARTIFACT_PATH],
        messages: THREAD_MESSAGES,
      },
    ],
  });

  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    return streamWithoutArtifacts(route);
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);

  const artifactTrigger = page.getByRole("button", { name: /artifacts/i });
  await expect(artifactTrigger).toBeVisible({ timeout: 15_000 });

  const textarea = page.getByPlaceholder(/how can i assist you/i);
  await textarea.fill("Continue");
  await textarea.press("Enter");

  await expect(
    page.getByText("Updated response while the artifact list is omitted."),
  ).toBeVisible({ timeout: 10_000 });
  await expect(artifactTrigger).toBeVisible();

  await artifactTrigger.click();

  const artifactsPanel = page.locator("#artifacts");
  await expect(artifactsPanel.getByText("report.md")).toBeVisible();
  await artifactsPanel.getByText("report.md").click();

  await expect(artifactsPanel.getByRole("combobox")).toContainText("report.md");
});
