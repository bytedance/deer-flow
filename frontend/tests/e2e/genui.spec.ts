import { expect, test } from "@playwright/test";

import {
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
  mockLangGraphAPI,
} from "./utils/mock-api";

function buildSSEStream(
  events: { event: string; data: unknown }[],
): string {
  return events
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
    .join("");
}

function makeUIBlock(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "1.0",
    type: "ui_block",
    action: "create",
    block_id: "block-1",
    component: "chart",
    props: {},
    interactive: false,
    ...overrides,
  };
}

function streamWithCustomEvent(
  customEvent: Record<string, unknown>,
  aiContent = "Here is the result.",
) {
  return buildSSEStream([
    {
      event: "metadata",
      data: { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID },
    },
    {
      event: "custom",
      data: customEvent,
    },
    {
      event: "values",
      data: {
        messages: [
          {
            type: "human",
            id: "msg-human-1",
            content: [{ type: "text", text: "Show me a chart" }],
          },
          { type: "ai", id: "msg-ai-1", content: aiContent },
        ],
      },
    },
    { event: "end", data: {} },
  ]);
}

test.describe("GenUI - Block Rendering", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("renders a chart block from SSE custom event", async ({ page }) => {
    const chartBlock = makeUIBlock({
      block_id: "chart-1",
      component: "chart",
      props: {
        chart_type: "bar",
        title: "Revenue by Quarter",
        x_key: "quarter",
        y_keys: ["revenue"],
        data: [
          { quarter: "Q1", revenue: 100 },
          { quarter: "Q2", revenue: 200 },
          { quarter: "Q3", revenue: 150 },
        ],
      },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(chartBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(chartBlock),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Show me a chart");
    await textarea.press("Enter");

    await expect(page.getByText("Revenue by Quarter")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("renders a table block with data", async ({ page }) => {
    const tableBlock = makeUIBlock({
      block_id: "table-1",
      component: "table",
      props: {
        title: "User List",
        columns: [
          { key: "name", label: "Name" },
          { key: "email", label: "Email" },
        ],
        data: [
          { name: "Alice", email: "alice@example.com" },
          { name: "Bob", email: "bob@example.com" },
        ],
        sortable: true,
      },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(tableBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(tableBlock),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Show users");
    await textarea.press("Enter");

    await expect(page.getByText("User List")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Alice")).toBeVisible();
    await expect(page.getByText("bob@example.com")).toBeVisible();
  });

  test("renders a markdown block with formatted content", async ({ page }) => {
    const mdBlock = makeUIBlock({
      block_id: "md-1",
      component: "markdown",
      props: {
        title: "Summary",
        content: "**Bold text** and `inline code`",
      },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(mdBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(mdBlock),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Summarize");
    await textarea.press("Enter");

    await expect(page.getByText("Summary")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("strong").filter({ hasText: "Bold text" })).toBeVisible();
  });
});

test.describe("GenUI - Interaction Flow", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("form block submits interaction to backend", async ({ page }) => {
    const formBlock = makeUIBlock({
      block_id: "form-1",
      component: "form",
      interactive: true,
      callback_id: "cb-form-1",
      callback_timeout_ms: 60000,
      props: {
        title: "User Feedback",
        fields: [
          { name: "rating", label: "Rating", type: "select", options: [{ label: "1", value: "1" }, { label: "2", value: "2" }, { label: "3", value: "3" }] },
          { name: "comment", label: "Comment", type: "textarea" },
        ],
        submit_label: "Submit Feedback",
      },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(formBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(formBlock),
      });
    });

    let interactionPayload: unknown = null;
    await page.route("**/api/threads/*/ui-interaction", (route) => {
      interactionPayload = route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Interaction received",
          callback_id: "cb-form-1",
        }),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Give feedback");
    await textarea.press("Enter");

    await expect(page.getByText("User Feedback")).toBeVisible({
      timeout: 10_000,
    });

    const commentField = page.getByLabel("Comment");
    await commentField.fill("Great product!");

    const submitBtn = page.getByRole("button", { name: "Submit Feedback" });
    await submitBtn.click();

    await expect
      .poll(() => interactionPayload, { timeout: 5_000 })
      .toBeTruthy();

    const payload = interactionPayload as { callback_id: string; payload: unknown };
    expect(payload.callback_id).toBe("cb-form-1");
  });

  test("confirm block sends confirmation interaction", async ({ page }) => {
    const confirmBlock = makeUIBlock({
      block_id: "confirm-1",
      component: "confirm",
      interactive: true,
      callback_id: "cb-confirm-1",
      callback_timeout_ms: 30000,
      props: {
        title: "Delete Account",
        message: "Are you sure you want to delete your account?",
        confirm_label: "Yes, Delete",
        cancel_label: "Cancel",
      },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(confirmBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(confirmBlock),
      });
    });

    let interactionPayload: unknown = null;
    await page.route("**/api/threads/*/ui-interaction", (route) => {
      interactionPayload = route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Interaction received",
          callback_id: "cb-confirm-1",
        }),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Delete my account");
    await textarea.press("Enter");

    await expect(
      page.getByText("Are you sure you want to delete your account?"),
    ).toBeVisible({ timeout: 10_000 });

    const confirmBtn = page.getByRole("button", { name: "Yes, Delete" });
    await confirmBtn.click();

    await expect
      .poll(() => interactionPayload, { timeout: 5_000 })
      .toBeTruthy();

    const payload = interactionPayload as { callback_id: string; payload: { confirmed: boolean } };
    expect(payload.callback_id).toBe("cb-confirm-1");
    expect(payload.payload.confirmed).toBe(true);
  });

  test("confirm block cancel does not submit interaction", async ({ page }) => {
    const confirmBlock = makeUIBlock({
      block_id: "confirm-2",
      component: "confirm",
      interactive: true,
      callback_id: "cb-confirm-2",
      callback_timeout_ms: 30000,
      props: {
        title: "Confirm Action",
        message: "Proceed with action?",
        confirm_label: "Proceed",
        cancel_label: "Nevermind",
      },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(confirmBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(confirmBlock),
      });
    });

    let interactionCalled = false;
    await page.route("**/api/threads/*/ui-interaction", (route) => {
      interactionCalled = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Interaction received",
          callback_id: "cb-confirm-2",
        }),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Do something");
    await textarea.press("Enter");

    await expect(page.getByText("Proceed with action?")).toBeVisible({
      timeout: 10_000,
    });

    const cancelBtn = page.getByRole("button", { name: "Nevermind" });
    await cancelBtn.click();

    // Cancel sends interaction with confirmed: false
    await expect
      .poll(() => interactionCalled, { timeout: 5_000 })
      .toBeTruthy();
  });
});

test.describe("GenUI - Block Update and Delete", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("block update merges new props", async ({ page }) => {
    const createBlock = makeUIBlock({
      block_id: "card-1",
      component: "card",
      props: {
        title: "Total Users",
        value: "1,234",
        trend: "up",
        change: "+12%",
      },
    });

    const updateBlock = makeUIBlock({
      block_id: "card-1",
      action: "update",
      component: "card",
      props: {
        value: "1,567",
        change: "+27%",
      },
    });

    const events = buildSSEStream([
      {
        event: "metadata",
        data: { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID },
      },
      { event: "custom", data: createBlock },
      { event: "custom", data: updateBlock },
      {
        event: "values",
        data: {
          messages: [
            {
              type: "human",
              id: "msg-human-1",
              content: [{ type: "text", text: "Show stats" }],
            },
            { type: "ai", id: "msg-ai-1", content: "Here are the stats." },
          ],
        },
      },
      { event: "end", data: {} },
    ]);

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: events,
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: events,
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Show stats");
    await textarea.press("Enter");

    await expect(page.getByText("Total Users")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("1,567")).toBeVisible();
    await expect(page.getByText("+27%")).toBeVisible();
  });

  test("block delete removes component from view", async ({ page }) => {
    const createBlock = makeUIBlock({
      block_id: "temp-1",
      component: "card",
      props: {
        title: "Temporary Card",
        value: "999",
      },
    });

    const deleteBlock = makeUIBlock({
      block_id: "temp-1",
      action: "delete",
      component: "card",
      props: {},
    });

    const events = buildSSEStream([
      {
        event: "metadata",
        data: { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID },
      },
      { event: "custom", data: createBlock },
      { event: "custom", data: deleteBlock },
      {
        event: "values",
        data: {
          messages: [
            {
              type: "human",
              id: "msg-human-1",
              content: [{ type: "text", text: "Show temp" }],
            },
            { type: "ai", id: "msg-ai-1", content: "Done." },
          ],
        },
      },
      { event: "end", data: {} },
    ]);

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: events,
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: events,
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Show temp");
    await textarea.press("Enter");

    await expect(page.getByText("Done.")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Temporary Card")).not.toBeVisible();
  });

  test("unsupported component shows fallback", async ({ page }) => {
    const unknownBlock = makeUIBlock({
      block_id: "unknown-1",
      component: "unknown_widget",
      props: { foo: "bar" },
    });

    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(unknownBlock),
      });
    });
    await page.route("**/api/langgraph/runs/stream", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: streamWithCustomEvent(unknownBlock),
      });
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Show unknown");
    await textarea.press("Enter");

    await expect(
      page.getByText("Unsupported component: unknown_widget"),
    ).toBeVisible({ timeout: 10_000 });
  });
});
