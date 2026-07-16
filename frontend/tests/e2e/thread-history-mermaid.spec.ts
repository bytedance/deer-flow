import { expect, test } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

const mermaidContent = `Here is a relationship diagram.

\`\`\`mermaid
flowchart TD
    A[Lin<br/>protagonist]
    F[Gu<br/>daughter]
    A -- "sealed memory" -.-> F
\`\`\`
`;

test("historical run messages preview labelled dotted Mermaid arrows", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Mermaid history",
        updated_at: "2026-05-24T04:47:01.123949+00:00",
      },
    ],
  });

  await page.route(/\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          run_id: MOCK_RUN_ID,
          thread_id: MOCK_THREAD_ID,
          status: "success",
          created_at: "2026-05-24T04:46:42.565307+00:00",
          updated_at: "2026-05-24T04:47:01.123949+00:00",
        },
      ]),
    }),
  );

  await page.route(`**/api/threads/${MOCK_THREAD_ID}/messages/page`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: [
          {
            thread_id: MOCK_THREAD_ID,
            run_id: MOCK_RUN_ID,
            event_type: "llm.ai.response",
            category: "message",
            content: {
              content: mermaidContent,
              additional_kwargs: {},
              response_metadata: {},
              type: "ai",
              name: null,
              id: "lc_run--issue-3193",
              tool_calls: [],
              invalid_tool_calls: [],
            },
            seq: 720,
            created_at: "2026-05-24T04:47:01.123949+00:00",
            metadata: {
              caller: "lead_agent",
              content_is_json: true,
              content_is_dict: true,
            },
          },
        ],
        has_more: false,
        next_before_seq: null,
      }),
    }),
  );

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

  await expect(page.getByLabel("Mermaid chart")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("Mermaid Error:")).toHaveCount(0);
});
