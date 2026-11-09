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
