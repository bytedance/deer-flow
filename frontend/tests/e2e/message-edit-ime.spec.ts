import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

for (const agentName of [undefined, "test-agent"]) {
  test(`message editing keeps composing shortcuts in ${agentName ?? "default"} chat`, async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: agentName
        ? [
            {
              name: agentName,
              description: "Test agent",
              system_prompt: "Test",
            },
          ]
        : [],
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Editing with an IME",
          agent_name: agentName,
          messages: [
            { type: "human", id: "human-1", content: "Original question" },
            { type: "ai", id: "ai-1", content: "Original answer" },
          ],
        },
      ],
    });
    let rerunRequests = 0;
    await page.route("**/runs/edit-regenerate/prepare", async (route) => {
      rerunRequests++;
      await route.fulfill({
        status: 409,
        json: { detail: "Test rerun blocked" },
      });
    });
    await page.goto(
      agentName
        ? `/workspace/agents/${agentName}/chats/${MOCK_THREAD_ID}`
        : `/workspace/chats/${MOCK_THREAD_ID}`,
    );
    await expect(
      page.getByText("Original answer", { exact: true }),
    ).toBeVisible();
    await page.getByText("Original question", { exact: true }).hover();
    await page
      .getByRole("button", { name: "Edit and rerun", exact: true })
      .click();
    const editor = page.locator(".is-user textarea");
    await editor.fill("Unfinished draft");
    for (const event of [
      { key: "Escape", isComposing: true },
      { key: "Escape", keyCode: 229 },
      { key: "Enter", ctrlKey: true, isComposing: true },
      { key: "Enter", ctrlKey: true, keyCode: 229 },
      { key: "Enter", metaKey: true, isComposing: true },
      { key: "Enter", metaKey: true, keyCode: 229 },
    ]) {
      await editor.dispatchEvent("keydown", event);
      await expect(editor).toHaveValue("Unfinished draft");
      expect(rerunRequests).toBe(0);
    }
    await editor.press("Escape");
    await expect(editor).toHaveCount(0);
    expect(rerunRequests).toBe(0);
  });
}
