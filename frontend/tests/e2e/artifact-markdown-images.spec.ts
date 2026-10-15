import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000003141";
const REPORT = "/mnt/user-data/outputs/report.md";
const IMAGE = "/mnt/user-data/outputs/chart.png";
const IMAGE_API = `/api/threads/${THREAD_ID}/artifacts${IMAGE}`;
const softExpect = expect.configure({ soft: true });
const REPORT_BODY = [
  "# Fare analysis",
  "",
  "The chart below is stored beside this report.",
  "",
  `![Absolute chart](${IMAGE})`,
  "",
  "![Relative chart](./chart.png)",
].join("\n");

for (const width of [1280, 375]) {
  test(`loads Markdown report images in the panel and viewer at ${width}px`, async ({
    page,
    context,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Report image regression",
          messages: [
            { type: "human", id: "request", content: "Create a fare report." },
            {
              type: "ai",
              id: "report",
              content: "",
              tool_calls: [
                {
                  id: "present-report",
                  name: "present_files",
                  args: { filepaths: [REPORT] },
                },
              ],
            },
            {
              type: "tool",
              id: "presented",
              tool_call_id: "present-report",
              name: "present_files",
              content: "Report presented.",
            },
            { type: "ai", id: "answer", content: `![Chat chart](${IMAGE})` },
          ],
          artifacts: [REPORT, IMAGE],
        },
      ],
    });
    await context.route(
      `**/api/threads/${THREAD_ID}/artifacts${REPORT}`,
      (route) =>
        route.fulfill({ contentType: "text/markdown", body: REPORT_BODY }),
    );
    await context.route(`**${IMAGE_API}`, (route) =>
      route.fulfill({
        contentType: "image/png",
        path: "public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/fare_analysis.png",
      }),
    );
    await context.route("**/artifacts/archive", (route) =>
      route.fulfill({ status: 404, body: "No archive in this fixture" }),
    );

    await page.goto(`/workspace/chats/${THREAD_ID}`);
    await expect(
      page.getByRole("img", { name: "Chat chart", exact: true }),
    ).toBeVisible({ timeout: 30000 });
    await expect
      .poll(() =>
        page
          .getByRole("img", { name: "Chat chart", exact: true })
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      )
      .toBeGreaterThan(0);
    await page.getByText("report.md", { exact: true }).first().click();
    const panel =
      width < 768
        ? page.getByRole("dialog", { name: "Artifacts", exact: true })
        : page.locator("#artifacts");
    await expect(
      panel.getByRole("heading", { name: "Fare analysis" }),
    ).toBeVisible({ timeout: 30000 });

    for (const alt of ["Absolute chart", "Relative chart"]) {
      const image = panel.getByRole("img", { name: alt, exact: true });
      await softExpect
        .poll(() =>
          image.evaluateAll((images: HTMLImageElement[]) =>
            images.some((img) => img.complete && img.naturalWidth > 0),
          ),
        )
        .toBe(true);
    }

    await page.screenshot({ path: testInfo.outputPath("report-panel.png") });

    const popup = context.waitForEvent("page");
    await panel.getByRole("button", { name: "Open in new window" }).click();
    const viewer = await popup;
    await viewer.setViewportSize({ width, height: 900 });
    await expect(
      viewer.getByRole("heading", { name: "Fare analysis" }),
    ).toBeVisible({ timeout: 30000 });
    for (const alt of ["Absolute chart", "Relative chart"]) {
      const image = viewer.getByRole("img", { name: alt, exact: true });
      await softExpect
        .poll(() =>
          image.evaluateAll((images: HTMLImageElement[]) =>
            images.some((img) => img.complete && img.naturalWidth > 0),
          ),
        )
        .toBe(true);
    }
    await viewer.close();
  });
}
