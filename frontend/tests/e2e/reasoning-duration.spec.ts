import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const answer = "你好！有什么可以帮你的吗？";
const reasoning = "先理解用户的需求，再给出简洁的回答。";

for (const encoding of ["provider", "inline", "none"] as const) {
  test(`shows one compact Chinese duration header: ${encoding}`, async ({
    page,
  }, testInfo) => {
    await page
      .context()
      .addCookies([
        { name: "locale", value: "zh-CN", url: testInfo.project.use.baseURL! },
      ]);
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "耗时标题预览",
          messages: [
            { type: "human", id: "human-duration", content: "你好" },
            {
              type: "ai",
              id: "ai-duration",
              content:
                encoding === "inline"
                  ? `<think>${reasoning}</think>${answer}`
                  : answer,
              additional_kwargs: {
                turn_duration: 31,
                ...(encoding === "provider"
                  ? { reasoning_content: reasoning }
                  : {}),
              },
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const label = page.getByTestId("run-duration");
    await expect(label).toHaveCount(1);
    await expect(label).toHaveText("用时 31 秒");
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await expect(page.getByText("本次任务耗时", { exact: false })).toHaveCount(
      0,
    );

    const trigger = page.getByRole("button", {
      name: "用时 31 秒",
      exact: true,
    });
    if (encoding !== "none") {
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await trigger.click();
      await expect(page.getByText(reasoning, { exact: true })).toBeVisible();
      await trigger.press("Enter");
      await expect(
        page.getByText(reasoning, { exact: true }),
      ).not.toBeVisible();
    } else {
      await expect(trigger).toHaveCount(0);
    }

    const labelBox = await label.boundingBox();
    const answerBox = await page
      .getByText(answer, { exact: true })
      .boundingBox();
    expect(labelBox!.y + labelBox!.height).toBeLessThan(answerBox!.y);
    await page.reload();
    await expect(label).toHaveCount(1);
    await expect(label).toHaveText("用时 31 秒");
    if (encoding !== "none") {
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
    }
    await page.mouse.move(0, 0);
    if (encoding !== "none") {
      await expect(trigger).toHaveCSS("color", "oklch(0.556 0 0)");
    }
    await page.screenshot({
      animations: "disabled",
      path: testInfo.outputPath(`duration-${encoding}.png`),
    });
  });
}
