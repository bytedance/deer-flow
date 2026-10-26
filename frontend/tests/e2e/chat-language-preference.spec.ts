import { expect, test, type Page } from "@playwright/test";

import {
  handleRunStream,
  MOCK_THREAD_ID,
  mockLangGraphAPI,
} from "./utils/mock-api";

async function switchLanguage(
  page: Page,
  language: "English" | "中文",
  screenshotPath?: string,
) {
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: /Settings and more|设置和更多/ })
    .click();
  await page.getByRole("menuitem", { name: /^(Settings|设置)$/ }).click();
  const dialog = page.getByRole("dialog", { name: /^(Settings|设置)$/ });
  await dialog.getByRole("button", { name: /^(Appearance|外观)$/ }).click();
  await dialog.getByRole("combobox").click();
  await page.getByRole("option", { name: language, exact: true }).click();
  await expect(dialog.getByRole("combobox")).toHaveText(language);
  if (screenshotPath) await page.screenshot({ path: screenshotPath });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
}

test("sends the current language after switching in Appearance settings", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page);
  const locales: unknown[] = [];
  await page.route("**/runs/stream", (route) => {
    const body = route.request().postDataJSON() as {
      context?: { locale?: unknown };
    };
    locales.push(body.context?.locale);
    return handleRunStream(route);
  });
  await page.goto("/workspace/chats/new");
  await switchLanguage(
    page,
    "中文",
    testInfo.outputPath("language-settings.png"),
  );
  await page.locator("textarea").fill("Explain this in English");
  await page.locator("textarea").press("Enter");
  await expect.poll(() => locales).toEqual(["zh-CN"]);
  await expect(
    page.getByText("Hello from DeerFlow!", { exact: true }),
  ).toBeVisible();

  await switchLanguage(page, "English");
  await page.locator("textarea").fill("继续");
  await page.locator("textarea").press("Enter");
  await expect.poll(() => locales).toEqual(["zh-CN", "en-US"]);
});

test("regeneration uses the new UI language rather than the original turn", async ({
  page,
}) => {
  const human = { type: "human", id: "user-1", content: "Original question" };
  const answer = { type: "ai", id: "answer-1", content: "Original answer" };
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Language preference",
        messages: [human, answer],
      },
    ],
  });
  await page.route("**/runs/regenerate/prepare", (route) =>
    route.fulfill({
      json: {
        input: { messages: [human] },
        checkpoint: {
          checkpoint_id: "before-user",
          checkpoint_ns: "",
          checkpoint_map: null,
        },
        metadata: {},
        target_run_id: `run-${MOCK_THREAD_ID}`,
      },
    }),
  );
  let locale: unknown;
  await page.route("**/runs/stream", (route) => {
    locale = (
      route.request().postDataJSON() as { context?: { locale?: unknown } }
    ).context?.locale;
    return handleRunStream(route);
  });
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await expect(page.getByText(answer.content, { exact: true })).toBeVisible();
  await switchLanguage(page, "中文");
  await page.locator("[data-assistant-turn]").last().hover();
  await page.getByRole("button", { name: "重新生成", exact: true }).click();
  await expect.poll(() => locale).toBe("zh-CN");
});
