import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const STOPPED_TASK_DESCRIPTION = "Research stopped reload regression";
const STOPPED_TASK_PROMPT =
  "Investigate why the stopped subtask card should not remain running after reload.";

const stoppedSubtaskMessages = [
  {
    type: "human",
    id: "msg-human-stopped-subtask",
    content: [
      {
        type: "text",
        text: "Start a subtask and then stop before the task tool returns.",
      },
    ],
  },
  {
    type: "ai",
    id: "msg-ai-stopped-subtask",
    content: "",
    additional_kwargs: {},
    response_metadata: {},
    tool_calls: [
      {
        id: "call-stopped-subtask",
        name: "task",
        args: {
          subagent_type: "general-purpose",
          description: STOPPED_TASK_DESCRIPTION,
          prompt: STOPPED_TASK_PROMPT,
        },
        type: "tool_call",
      },
    ],
    invalid_tool_calls: [],
  },
];

test.describe("Subtask card", () => {
  test("shows failed after a stopped task thread is reloaded", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Stopped subtask",
          updated_at: "2026-06-18T12:00:00Z",
          messages: stoppedSubtaskMessages,
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.reload();

    await expect(page.getByText(STOPPED_TASK_DESCRIPTION)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Subtask failed")).toBeVisible();
    await expect(page.getByText("Running subtask")).toHaveCount(0);
  });
});
