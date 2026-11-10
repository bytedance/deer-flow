import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const { status, body, message } of [
  {
    status: 502,
    body: '{"detail":"upstream failed"}',
    message:
      "The service is temporarily unavailable (HTTP 502). Please try again.",
  },
  {
    status: 409,
    body: '{"detail":"Another run is active"}',
    message: 'HTTP 409: {"detail":"Another run is active"}',
  },
]) {
  test(`shows the expected chat error for HTTP ${status}`, async ({ page }) => {
    const streamWarnings: string[] = [];
    page.on("console", (entry) => {
      if (
        entry.type() === "warning" &&
        entry.text().startsWith("Chat stream request failed:")
      ) {
        streamWarnings.push(entry.text());
      }
    });

    mockLangGraphAPI(page);
    await page.route(
      /\/api\/langgraph\/(?:threads\/[^/]+\/)?runs\/stream$/,
      (route) =>
        route.fulfill({ status, contentType: "application/json", body }),
    );

    await page.goto("/workspace/chats/new");
    const composer = page.getByRole("textbox", {
      name: /how can i assist you/i,
    });
    await composer.fill("Send a message");
    await composer.press("Enter");

    await expect(page.locator("[data-sonner-toast]").last()).toHaveText(
      message,
    );
    expect(streamWarnings).toEqual(
      status === 502 ? [`Chat stream request failed: HTTP 502: ${body}`] : [],
    );
  });
}

// Upstream #8039: a first send whose run request is rejected never became a
// turn. The composer must keep the text (and its draft across a reload), the
// welcome layout must come back, and the zero-message thread that Gateway
// admission may have created must be rolled back.
test("restores the draft and welcome state when the first send fails", async ({
  page,
}) => {
  const deletedThreads: string[] = [];
  mockLangGraphAPI(page);
  // No checkpoint: a thread created only by run admission for the rejected
  // send. That is the row the page is allowed to roll back.
  await page.route(/\/api\/langgraph\/threads\/[^/]+\/state$/, (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: '{"detail":"Thread not found"}',
    }),
  );
  await page.route(/\/api\/langgraph\/threads\/[^/]+$/, (route) => {
    if (route.request().method() !== "DELETE") {
      return route.fallback();
    }
    deletedThreads.push(
      decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-1)!,
      ),
    );
    return route.fulfill({ status: 204 });
  });
  await page.route(
    /\/api\/langgraph\/(?:threads\/[^/]+\/)?runs\/stream$/,
    (route) =>
      route.fulfill({
        status: 502,
        contentType: "application/json",
        body: '{"detail":"upstream failed"}',
      }),
  );

  await page.goto("/workspace/chats/new");
  const composer = page.getByRole("textbox", {
    name: /how can i assist you/i,
  });
  await composer.fill("Send a message");
  await composer.press("Enter");

  await expect(page.locator("[data-sonner-toast]").last()).toHaveText(
    "The service is temporarily unavailable (HTTP 502). Please try again.",
  );
  // The welcome layout is back and the text never left the composer.
  await expect(page.getByText("Hello, again!").first()).toBeVisible();
  await expect(composer).toHaveValue("Send a message");
  // The rejected session is rolled back once its state read proves it holds
  // no checkpoint.
  await expect.poll(() => deletedThreads.length).toBeGreaterThan(0);

  // The draft survives a reload as a stored draft, not just live state.
  await expect
    .poll(() =>
      page.evaluate(() => Object.values(window.sessionStorage).join("\n")),
    )
    .toContain("Send a message");
  await page.reload();
  await expect(page.getByText("Hello, again!").first()).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: /how can i assist you/i }),
  ).toHaveValue("Send a message");
});
