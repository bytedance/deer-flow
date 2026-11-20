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
const FOLLOW_UP_MESSAGES = [
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
        messages: FOLLOW_UP_MESSAGES,
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

  // A real gateway persists the run's messages, so the SDK's end-of-run state
  // refetch returns them. This spec's stream route bypasses the shared mock's
  // thread upsert, which would otherwise leave post-run state looking like the
  // run never happened — an impossible backend state that only a same-tick
  // render could paper over. Serve the persisted turn once the run has started;
  // stream values still omit artifacts, which is the invariant under test.
  let runStarted = false;
  await page.route("**/api/langgraph/threads/*/history", (route) => {
    if (!runStarted) {
      return route.fallback();
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          values: {
            title: "Artifact stream state",
            goal: null,
            messages: [...THREAD_MESSAGES, ...FOLLOW_UP_MESSAGES],
            artifacts: [ARTIFACT_PATH],
          },
          next: [],
          metadata: {},
          created_at: "2025-01-01T00:00:00Z",
          parent_config: null,
        },
      ]),
    });
  });
  await page.route(/\/api\/threads\/([^/]+)\/messages\/page/, (route) => {
    if (!runStarted) {
      return route.fallback();
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [...THREAD_MESSAGES, ...FOLLOW_UP_MESSAGES].map(
          (message, index) => ({
            run_id: RUN_ID,
            seq: index + 1,
            content: message,
            metadata: { caller: "lead_agent" },
            created_at: `2025-01-01T00:00:${String(index).padStart(2, "0")}Z`,
          }),
        ),
        has_more: false,
        next_before_seq: null,
      }),
    });
  });
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    runStarted = true;
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
