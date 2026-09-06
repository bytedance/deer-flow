import { expect, test } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

const MOCK_AGENTS = [
  {
    name: "test-agent",
    description: "A test agent for E2E tests",
    system_prompt: "You are a test agent.",
  },
  {
    name: "second-agent",
    description: "Another test agent for E2E tests",
    system_prompt: "You are another test agent.",
  },
];

test.describe("Agent chat", () => {
  test("agent gallery page loads and shows agents", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents");

    // The agent card should appear with the agent name
    await expect(page.getByText("test-agent")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("agent chat page loads with input box and AI disclaimer", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents/test-agent/chats/new");

    // The prompt input textarea should be visible
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByText("DeerFlow is AI and can make mistakes", { exact: true }),
    ).toBeVisible();
  });

  test("mobile agent welcome keeps the sidebar trigger clickable", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 664 });
    mockLangGraphAPI(page, {
      agents: [
        {
          ...MOCK_AGENTS[0]!,
          description: "这是一个用于验证移动端欢迎页布局的测试智能体。".repeat(
            16,
          ),
        },
      ],
    });

    await page.goto("/workspace/agents/test-agent/chats/new");
    await page.evaluate(() => {
      document.cookie = "locale=zh-CN; path=/; SameSite=Lax";
    });
    await page.reload();

    const sidebarTrigger = page
      .locator("[data-sidebar='trigger']:visible")
      .first();
    await expect(sidebarTrigger).toBeVisible({ timeout: 15_000 });
    const triggerBox = await sidebarTrigger.boundingBox();
    expect(triggerBox).not.toBeNull();
    const triggerReceivesPointerEvents = await page.evaluate(
      ({ x, y }) => {
        const trigger = document.elementFromPoint(x, y);
        return trigger?.closest("[data-sidebar='trigger']") !== null;
      },
      {
        x: triggerBox!.x + triggerBox!.width / 2,
        y: triggerBox!.y + triggerBox!.height / 2,
      },
    );
    expect(triggerReceivesPointerEvents).toBe(true);
    await page.mouse.click(
      triggerBox!.x + triggerBox!.width / 2,
      triggerBox!.y + triggerBox!.height / 2,
    );

    await expect(
      page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
    ).toBeVisible();
  });

  test("keeps new-chat drafts isolated between agents", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents/test-agent/chats/new");
    const firstAgentInput = page.getByPlaceholder(/how can i assist you/i);
    await expect(firstAgentInput).toBeVisible({ timeout: 15_000 });
    await firstAgentInput.fill("Draft for the first agent");

    await page.goto("/workspace/agents/second-agent/chats/new");
    const secondAgentInput = page.getByPlaceholder(/how can i assist you/i);
    await expect(secondAgentInput).toHaveValue("");
    await secondAgentInput.fill("Draft for the second agent");

    await page.goto("/workspace/agents/test-agent/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      "Draft for the first agent",
    );
  });

  test("agent chat page shows agent badge", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents/test-agent/chats/new");

    // The agent badge should display in the header (scoped to header to avoid
    // matching the welcome area which also shows the agent name)
    await expect(
      page.locator("header span", { hasText: "test-agent" }),
    ).toBeVisible({ timeout: 15_000 });
  });

  for (const {
    name,
    toolGroups,
    browserControlEnabled,
    expectedVisible,
    mock,
  } of [
    {
      name: "shows Browser Live for an explicit browser tool group",
      toolGroups: ["browser"],
      browserControlEnabled: true,
      expectedVisible: true,
    },
    {
      name: "shows Browser Live when tool groups are unrestricted",
      toolGroups: null,
      browserControlEnabled: true,
      expectedVisible: true,
    },
    {
      name: "hides Browser Live without the browser tool group",
      toolGroups: ["web"],
      browserControlEnabled: true,
      expectedVisible: false,
    },
    {
      name: "hides Browser Live when browser control is unavailable",
      toolGroups: ["browser"],
      browserControlEnabled: false,
      expectedVisible: false,
    },
    {
      name: "hides Browser Live in mock custom-agent chats",
      toolGroups: ["browser"],
      browserControlEnabled: true,
      expectedVisible: false,
      mock: true,
    },
  ]) {
    test(name, async ({ page }) => {
      const agent = {
        name: "browser-agent",
        description: "A custom agent for Browser Live tests",
        tool_groups: toolGroups,
      };
      mockLangGraphAPI(page, {
        agents: [agent],
        features: { browserControlEnabled },
        threads: [
          {
            thread_id: MOCK_THREAD_ID,
            title: "Browser agent conversation",
            agent_name: agent.name,
            messages: [
              {
                type: "ai",
                id: "msg-ai-browser-agent",
                content: "Ready to browse",
              },
            ],
          },
        ],
      });

      const featuresLoaded = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/features" &&
          response.status() === 200,
      );
      await page.goto(
        `/workspace/agents/${agent.name}/chats/${MOCK_THREAD_ID}${mock ? "?mock=true" : ""}`,
      );
      await featuresLoaded;
      if (mock) {
        await expect(
          page.locator("header span", { hasText: agent.name }),
        ).toBeVisible({ timeout: 15_000 });
      } else {
        await expect(page.getByText("Ready to browse")).toBeVisible({
          timeout: 15_000,
        });
      }

      const browserTrigger = page.getByTestId("browser-trigger");
      if (expectedVisible) {
        await expect(browserTrigger).toBeVisible();
        await browserTrigger.click();
        await expect(
          page.getByPlaceholder("Enter a URL and press Enter"),
        ).toBeVisible();
      } else {
        await expect(browserTrigger).toHaveCount(0);
      }
    });
  }

  test("hides Browser Live before a custom-agent thread is created", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: [
        {
          name: "browser-agent",
          description: "A custom agent for Browser Live tests",
          tool_groups: ["browser"],
        },
      ],
      features: { browserControlEnabled: true },
    });

    await page.goto("/workspace/agents/browser-agent/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("browser-trigger")).toHaveCount(0);
  });

  test("agent chat can regenerate its latest response", async ({ page }) => {
    const humanMessage = {
      type: "human",
      id: "msg-human-agent",
      content: [{ type: "text", text: "Original agent question" }],
    };
    const aiMessage = {
      type: "ai",
      id: "msg-ai-agent",
      content: "Custom agent response",
    };
    mockLangGraphAPI(page, {
      agents: MOCK_AGENTS,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Agent conversation",
          agent_name: "test-agent",
          messages: [humanMessage, aiMessage],
        },
      ],
    });

    let prepareMessageId: string | undefined;
    let streamBody: Record<string, unknown> | undefined;
    await page.route(
      `**/api/threads/${MOCK_THREAD_ID}/runs/regenerate/prepare`,
      (route) => {
        prepareMessageId = (
          route.request().postDataJSON() as { message_id?: string }
        ).message_id;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            input: { messages: [humanMessage] },
            checkpoint: {
              checkpoint_id: "checkpoint-before-human",
              checkpoint_ns: "",
              checkpoint_map: null,
            },
            metadata: {
              regenerate_from_message_id: aiMessage.id,
              regenerate_from_run_id: `run-${MOCK_THREAD_ID}`,
              regenerate_checkpoint_id: "checkpoint-before-human",
            },
            target_run_id: `run-${MOCK_THREAD_ID}`,
          }),
        });
      },
    );
    await page.route(
      `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/stream`,
      (route) => {
        streamBody = route.request().postDataJSON() as Record<string, unknown>;
        return handleRunStream(route);
      },
    );

    await page.goto(`/workspace/agents/test-agent/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(aiMessage.content)).toBeVisible({
      timeout: 15_000,
    });

    await page.evaluate((selectedText) => {
      const element = Array.from(document.querySelectorAll("p")).find(
        (candidate) => candidate.textContent?.includes(selectedText),
      );
      const textNode = element?.firstChild;
      if (!element || !textNode) {
        throw new Error("Unable to find the custom agent response");
      }
      const range = document.createRange();
      range.selectNodeContents(textNode);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    }, aiMessage.content);
    await expect(
      page.getByRole("button", { name: "Ask in side chat" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");

    const assistantTurn = page.locator("[data-assistant-turn]").last();
    await assistantTurn.hover();
    await page.getByRole("button", { name: "Regenerate" }).click();

    await expect.poll(() => prepareMessageId).toBe(aiMessage.id);
    await expect.poll(() => streamBody).toBeDefined();
    expect(streamBody).toMatchObject({
      checkpoint: {
        checkpoint_id: "checkpoint-before-human",
        checkpoint_ns: "",
        checkpoint_map: null,
      },
      metadata: {
        regenerate_from_message_id: aiMessage.id,
        regenerate_from_run_id: `run-${MOCK_THREAD_ID}`,
        regenerate_checkpoint_id: "checkpoint-before-human",
      },
      context: {
        agent_name: "test-agent",
        thread_id: MOCK_THREAD_ID,
      },
    });
  });

  test("agent chat can edit and rerun its latest user message", async ({
    page,
  }) => {
    const humanMessage = {
      type: "human",
      id: "msg-human-agent",
      content: [{ type: "text", text: "Original agent question" }],
    };
    const replacementHumanMessage = {
      type: "human",
      id: "msg-human-agent-edited",
      content: [{ type: "text", text: "Edited agent question" }],
    };
    const aiMessage = {
      type: "ai",
      id: "msg-ai-agent",
      content: "Custom agent response",
    };
    mockLangGraphAPI(page, {
      agents: MOCK_AGENTS,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Agent conversation",
          agent_name: "test-agent",
          messages: [humanMessage, aiMessage],
        },
      ],
    });
    let historyRows = [
      { run_id: `run-${MOCK_THREAD_ID}`, content: humanMessage },
      { run_id: `run-${MOCK_THREAD_ID}`, content: aiMessage },
    ];
    await page.route(
      `**/api/threads/${MOCK_THREAD_ID}/messages/page`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: historyRows.map((row, index) => ({
              run_id: row.run_id,
              seq: index + 1,
              content: row.content,
              metadata: { caller: "lead_agent" },
              created_at: `2025-01-01T00:00:${String(index).padStart(2, "0")}Z`,
            })),
            has_more: false,
            next_before_seq: null,
          }),
        }),
    );

    let prepareBody:
      | { human_message_id?: string; replacement_text?: string }
      | undefined;
    let streamBody: Record<string, unknown> | undefined;
    await page.route(
      `**/api/threads/${MOCK_THREAD_ID}/runs/edit-regenerate/prepare`,
      (route) => {
        prepareBody = route.request().postDataJSON() as {
          human_message_id?: string;
          replacement_text?: string;
        };
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            input: { messages: [replacementHumanMessage] },
            checkpoint: {
              checkpoint_id: "checkpoint-before-human",
              checkpoint_ns: "",
              checkpoint_map: null,
            },
            metadata: {
              replay_kind: "edit",
              regenerate_from_message_id: aiMessage.id,
              regenerate_from_run_id: `run-${MOCK_THREAD_ID}`,
              regenerate_checkpoint_id: "checkpoint-before-human",
              edit_from_message_id: humanMessage.id,
              edit_message_id: replacementHumanMessage.id,
              edit_version_group_id: humanMessage.id,
            },
            target_run_id: `run-${MOCK_THREAD_ID}`,
            replacement_human_message_id: replacementHumanMessage.id,
            source_message_ids: [humanMessage.id, aiMessage.id],
          }),
        });
      },
    );
    await page.route(
      `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/stream`,
      (route) => {
        streamBody = route.request().postDataJSON() as Record<string, unknown>;
        historyRows = [
          { run_id: MOCK_RUN_ID, content: replacementHumanMessage },
          {
            run_id: MOCK_RUN_ID,
            content: {
              type: "ai",
              id: "msg-ai-1",
              content: "Hello from DeerFlow!",
            },
          },
        ];
        return handleRunStream(route);
      },
    );

    await page.goto(`/workspace/agents/test-agent/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("Original agent question")).toBeVisible({
      timeout: 15_000,
    });

    const humanTurn = page.getByText("Original agent question");
    await humanTurn.hover();
    await page.getByRole("button", { name: "Edit and rerun" }).click();

    const editor = page.locator("textarea").first();
    await expect(editor).toHaveValue("Original agent question");
    await editor.fill("Edited agent question");
    await page.getByRole("button", { name: "Update and rerun" }).click();

    await expect
      .poll(() => prepareBody)
      .toEqual({
        human_message_id: humanMessage.id,
        replacement_text: "Edited agent question",
      });
    await expect.poll(() => streamBody).toBeDefined();
    expect(streamBody).toMatchObject({
      input: { messages: [replacementHumanMessage] },
      checkpoint: {
        checkpoint_id: "checkpoint-before-human",
        checkpoint_ns: "",
        checkpoint_map: null,
      },
      metadata: {
        replay_kind: "edit",
        regenerate_from_message_id: aiMessage.id,
        regenerate_from_run_id: `run-${MOCK_THREAD_ID}`,
        regenerate_checkpoint_id: "checkpoint-before-human",
        edit_from_message_id: humanMessage.id,
        edit_message_id: replacementHumanMessage.id,
        edit_version_group_id: humanMessage.id,
      },
      context: {
        agent_name: "test-agent",
        thread_id: MOCK_THREAD_ID,
      },
    });
    await expect(page.getByText("Edited agent question")).toBeVisible();
    await expect(page.getByText("Original agent question")).not.toBeVisible();
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible();
  });
});
