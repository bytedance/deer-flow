import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000000237";

const BREAKDOWN = {
  total_tokens: 1000,
  percentage: 25,
  remaining_tokens: 3000,
  system_prompt_tokens: 100,
  builtin_tools_tokens: 200,
  mcp_tools_tokens: 50,
  skill_body_tokens: 25,
  memory_tokens: 30,
  task_state_tokens: 40,
  other_injection_tokens: 5,
  conversation_tokens: 500,
  tool_result_tokens: 50,
  model_name: "model-1",
  context_window: 4000,
  captured_at: "2026-11-13T00:00:00Z",
};

const VIEWPORTS = [
  { name: "phone", width: 390, height: 664 },
  { name: "small phone", width: 320, height: 480 },
];

for (const viewport of VIEWPORTS) {
  test(`context composition stays reachable on a ${viewport.name}`, async ({
    page,
  }) => {
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    mockLangGraphAPI(page, {
      agents: [{ name: "test-agent", description: "Context usage test agent" }],
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Context usage",
          agent_name: "test-agent",
        },
      ],
    });

    await page.route("**/api/models", (route) =>
      route.fulfill({
        json: {
          models: [
            {
              name: "model-1",
              model: "model-1",
              display_name: "Model 1",
              context_window: 4000,
            },
          ],
          token_usage: { enabled: true },
        },
      }),
    );
    await page.route(`**/api/threads/${THREAD_ID}/token-usage`, (route) =>
      route.fulfill({
        json: {
          thread_id: THREAD_ID,
          total_tokens: 1000,
          total_input_tokens: 800,
          total_output_tokens: 200,
          total_runs: 1,
          by_model: {},
          by_caller: { lead_agent: 1000, subagent: 0, middleware: 0 },
          context_usage: { breakdown: BREAKDOWN },
        },
      }),
    );

    await page.goto(`/workspace/agents/test-agent/chats/${THREAD_ID}`);

    const ring = page.getByTestId("context-usage-ring");
    await expect(ring).toBeVisible({ timeout: 15_000 });
    const ringBox = await ring.boundingBox();
    expect(ringBox).not.toBeNull();
    expect(ringBox!.x).toBeGreaterThanOrEqual(0);
    expect(ringBox!.x + ringBox!.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(ringBox!.y + ringBox!.height).toBeLessThanOrEqual(
      viewport.height + 1,
    );
    await ring.click();

    const popover = page.getByTestId("context-usage-popover");
    await expect(popover).toBeVisible();
    for (const label of [
      "System prompt",
      "Tools",
      "Skills",
      "Memory & context",
      "Conversation",
    ]) {
      await expect(popover.getByText(label, { exact: true })).toBeVisible();
    }

    const box = await popover.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1);
  });
}
