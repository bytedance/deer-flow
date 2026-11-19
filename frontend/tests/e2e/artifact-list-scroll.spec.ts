import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000002074";

for (const viewport of [
  { name: "desktop", width: 1280, height: 720 },
  { name: "narrow", width: 390, height: 844 },
]) {
  test.describe(`Artifact list (${viewport.name})`, () => {
    test.use({ viewport });

    for (const count of [1, 30]) {
      test(`can reach and open the last of ${count} files`, async ({
        page,
      }, testInfo) => {
        const artifacts = Array.from(
          { length: count },
          (_, index) => `/mnt/user-data/outputs/report-${index + 1}.txt`,
        );
        const lastPath = artifacts[artifacts.length - 1]!;
        const content = `Contents of report ${count}`;
        mockLangGraphAPI(page, {
          threads: [
            {
              thread_id: THREAD_ID,
              title: "Artifact list scrolling",
              artifacts,
              messages: [
                { type: "human", id: "human", content: "Create the reports" },
                { type: "ai", id: "ai", content: "The reports are ready." },
              ],
            },
          ],
        });
        await page.route(
          `**/api/threads/${THREAD_ID}/artifacts${lastPath}`,
          (route) =>
            route.fulfill({ contentType: "text/plain", body: content }),
        );
        await page.goto(`/workspace/chats/${THREAD_ID}`);
        await page.getByTestId("artifact-trigger").click();

        const panel =
          viewport.name === "desktop"
            ? page.locator("#artifacts")
            : page.getByRole("dialog", { name: "Artifacts", exact: true });
        const firstFile = panel.getByText("report-1.txt", { exact: true });
        const lastFile = panel.getByText(`report-${count}.txt`, {
          exact: true,
        });
        await expect(firstFile).toBeInViewport({ ratio: 1 });
        if (count > 1) {
          await expect(lastFile).not.toBeInViewport();
        }
        await firstFile.hover();
        await page.mouse.wheel(0, 10_000);

        try {
          // Check reachability before click(), which would auto-scroll and
          // hide the missing user-scrollable region on the old layout.
          await expect(lastFile).toBeInViewport({ ratio: 1 });
          await expect(
            panel
              .getByRole("heading", { name: "Artifacts", exact: true })
              .last(),
          ).toBeInViewport({ ratio: 1 });
        } finally {
          const screenshot = testInfo.outputPath(
            "artifact-list-after-scroll.png",
          );
          await page.screenshot({ path: screenshot });
          await testInfo.attach("artifact-list-after-scroll", {
            path: screenshot,
            contentType: "image/png",
          });
        }
        await lastFile.click();
        await expect(panel.locator(".cm-content")).toHaveText(content);
      });
    }
  });
}
