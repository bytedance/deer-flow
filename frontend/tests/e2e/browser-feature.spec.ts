import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe("Browser feature flag", () => {
  test("shows browser trigger only when browser_control is enabled", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [{ thread_id: MOCK_THREAD_ID, title: "Browser Enabled" }],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    await expect(page.getByTestId("browser-trigger")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("hides browser trigger when browser_control is disabled", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [{ thread_id: MOCK_THREAD_ID, title: "Browser Disabled" }],
      features: { browserControlEnabled: false },
    });

    const featuresResponse = page.waitForResponse((response) =>
      response.url().includes("/api/features"),
    );
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const features = (await (await featuresResponse).json()) as {
      browser_control?: { enabled?: boolean };
    };
    expect(features.browser_control?.enabled).toBe(false);

    await expect(page.getByTestId("browser-trigger")).toHaveCount(0);
  });
});
