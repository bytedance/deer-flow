import { expect, test } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

test("approval mode is independent of reasoning and is sent with the run", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page);
  await page.route("**/api/features", (route) =>
    route.fulfill({
      json: {
        tool_approval: {
          enabled: true,
          default_mode: "ask",
          allowed_modes: ["ask", "auto", "full"],
        },
      },
    }),
  );
  let body: Record<string, unknown> | undefined;
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    body = route.request().postDataJSON() as Record<string, unknown>;
    return handleRunStream(route);
  });
  await page.goto("/workspace/chats/new");
  await page
    .getByRole("button", { name: "Tool permissions", exact: true })
    .click();
  await testInfo.attach("Tool permissions in the chat composer", {
    body: await page.screenshot({ fullPage: true, animations: "disabled" }),
    contentType: "image/png",
  });
  await page.getByRole("menuitem", { name: /^Auto/ }).click();
  await expect(
    page.getByRole("button", { name: "Tool permissions", exact: true }),
  ).toHaveText("Auto");
  await page
    .getByPlaceholder(/how can i assist you/i)
    .fill("Inspect the project");
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  await expect
    .poll(() => body)
    .toMatchObject({ context: { tool_approval_mode: "auto" } });
});

test("live child approval edits arguments, answers the owning run and revokes grants", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Approval check",
        messages: [{ id: "user", type: "human", content: "Update the record" }],
      },
    ],
  });
  await page.route("**/api/features", (route) =>
    route.fulfill({
      json: {
        tool_approval: {
          enabled: true,
          default_mode: "ask",
          allowed_modes: ["ask", "auto", "full"],
        },
      },
    }),
  );
  let answered: unknown;
  let revoked = false;
  const proposal = {
    version: 2,
    kind: "hitl_approval",
    request_id: "review",
    transport: "live",
    run_id: "run-child",
    agent_id: "worker",
    pending_tool_call_ids: ["call"],
    allowed_decisions: ["approve", "approve_thread", "edit", "reject"],
    actions: [
      {
        request_id: "review",
        tool_call_id: "call",
        tool_name: "update_record",
        args_summary: { value: "original" },
        args: { value: "original" },
        args_schema: {
          type: "object",
          properties: { value: { type: "string" } },
        },
        grant_allowed: true,
      },
    ],
  };
  await page.route("**/api/threads/*/tool-approvals", (route) =>
    route.fulfill({
      json: { requests: answered ? [] : [proposal], grants: [] },
    }),
  );
  await page.route(
    "**/api/threads/*/runs/run-child/tool-approvals/review",
    (route) => {
      answered = route.request().postDataJSON();
      return route.fulfill({ json: { accepted: true } });
    },
  );
  await page.route("**/api/threads/*/tool-approvals/grants", (route) => {
    revoked = route.request().method() === "DELETE";
    return route.fulfill({ json: { revoked: true } });
  });
  await page.goto("/workspace/chats/" + MOCK_THREAD_ID);
  const card = page.getByTestId("tool-approval-card");
  await expect(card).toContainText("A subagent is waiting");
  await testInfo.attach("Pending child approval in the chat", {
    body: await page.screenshot({ fullPage: true, animations: "disabled" }),
    contentType: "image/png",
  });
  await card
    .getByRole("button", { name: "Edit arguments", exact: true })
    .click();
  await card
    .getByRole("textbox", { name: "Edit arguments update_record" })
    .fill("invalid");
  await expect(
    card.getByRole("button", { name: "Submit decisions" }),
  ).toBeDisabled();
  await card
    .getByRole("textbox", { name: "Edit arguments update_record" })
    .fill('{"value":"edited"}');
  await card.getByRole("button", { name: "Submit decisions" }).click();
  await expect
    .poll(() => answered)
    .toMatchObject({
      responses: [
        {
          request_id: "review",
          tool_call_id: "call",
          option_id: "edit",
          args: { value: "edited" },
        },
      ],
    });
  await expect(card).toHaveCount(0);
  await testInfo.attach("Chat after approving edited arguments", {
    body: await page.screenshot({ fullPage: true, animations: "disabled" }),
    contentType: "image/png",
  });
  await page
    .getByRole("button", { name: "Tool permissions", exact: true })
    .click();
  await page.getByRole("menuitem", { name: "Revoke chat approvals" }).click();
  await expect.poll(() => revoked).toBe(true);
});
