import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const threadId = "00000000-0000-0000-0000-000000003141";
const filepath = "/mnt/user-data/outputs/performance.csv";
const normal =
  "ID,Note\n" +
  Array.from({ length: 12_000 }, (_, i) => `${i},${"x".repeat(80)}\n`).join("");
const wide = '"",'.repeat(349_000) + '""\n';
const viewerURL = (name = filepath) =>
  `/artifacts/view?path=${encodeURIComponent(name)}&thread_id=${threadId}`;

type Metrics = {
  started: number;
  firstTable: number | null;
  beats: number;
  maxHeartbeatGap: number;
  longTasks: number[];
};

type MeasuredWindow = Window & { __csvMetrics: Metrics };

async function setup(page: Page, body: string) {
  mockLangGraphAPI(page);
  await page
    .context()
    .route(`**/api/threads/${threadId}/artifacts/**`, async (route) => {
      // Start after the viewer has requested its content. Include cold Worker and
      // table chunk loading in the reported latency, excluding page navigation.
      await page.evaluate(() => {
        const measured = window as unknown as MeasuredWindow;
        const metrics: Metrics = {
          started: performance.now(),
          firstTable: null,
          beats: 0,
          maxHeartbeatGap: 0,
          longTasks: [],
        };
        measured.__csvMetrics = metrics;
        let previous = metrics.started;
        const timer = setInterval(() => {
          const now = performance.now();
          if (metrics.firstTable !== null) return;
          metrics.beats++;
          metrics.maxHeartbeatGap = Math.max(
            metrics.maxHeartbeatGap,
            now - previous,
          );
          previous = now;
        }, 16);
        const observer = new MutationObserver(() => {
          if (
            document.querySelector(
              '[data-testid="artifact-table-preview"] table',
            )
          ) {
            metrics.firstTable ??= performance.now();
            observer.disconnect();
          }
        });
        observer.observe(document.documentElement, {
          childList: true,
          subtree: true,
        });
        const longTasks = new PerformanceObserver((entries) => {
          for (const entry of entries.getEntries()) {
            if (
              entry.startTime >= metrics.started &&
              (metrics.firstTable === null ||
                entry.startTime <= metrics.firstTable)
            )
              metrics.longTasks.push(entry.duration);
          }
        });
        longTasks.observe({ type: "longtask", buffered: false });
        window.addEventListener(
          "pagehide",
          () => {
            clearInterval(timer);
            observer.disconnect();
            longTasks.disconnect();
          },
          { once: true },
        );
      });
      await route.fulfill({
        status: 200,
        contentType: "text/csv",
        body,
      });
    });
}

async function report(page: Page, name: string, bytes: number) {
  const metrics = await page.evaluate(
    () => (window as unknown as MeasuredWindow).__csvMetrics,
  );
  const report = {
    sample: name,
    bytes,
    firstTableMs:
      metrics.firstTable === null ? null : metrics.firstTable - metrics.started,
    heartbeatCount: metrics.beats,
    maxHeartbeatGapMs: metrics.maxHeartbeatGap,
    longTaskCount: metrics.longTasks.length,
    longTaskDurationsMs: metrics.longTasks,
  };
  console.log("CSV browser performance", JSON.stringify(report));
  await test.info().attach(`${name}-performance`, {
    body: JSON.stringify(report, null, 2),
    contentType: "application/json",
  });
  return report;
}

test("measures a cold real Worker with a normal approximately 1 MiB CSV", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await setup(page, normal);
  await page.goto(viewerURL());
  await expect(page.getByRole("table")).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText("Preview of first 200 rows", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "0", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("row")).toHaveCount(51);
  const metrics = await report(page, "normal-1mib", Buffer.byteLength(normal));
  expect(metrics.firstTableMs).not.toBeNull();
  // Report actual latency/long tasks, without asserting hardware-specific targets.
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByText(/^51–100/)).toBeVisible();
});

test("keeps the main thread responsive during an extremely wide quoted record", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await setup(page, wide);
  const workerStarted = page.waitForEvent("worker");
  await page.goto(viewerURL());
  await workerStarted;
  // An actual DOM interaction must finish while the real parser runs in its
  // Worker. This probe is deliberately independent of the chat composer.
  await page.evaluate(() => {
    const button = document.createElement("button");
    button.textContent = "Responsiveness probe";
    button.onclick = () => {
      button.textContent = "Probe acknowledged";
    };
    document.body.prepend(button);
  });
  await page.getByRole("button", { name: "Responsiveness probe" }).click();
  await expect(
    page.getByRole("button", { name: "Probe acknowledged" }),
  ).toBeVisible();
  await expect
    .poll(async () =>
      page.evaluate(
        () => (window as unknown as MeasuredWindow).__csvMetrics.beats,
      ),
    )
    .toBeGreaterThan(2);
  await expect(
    page
      .getByRole("table")
      .or(page.getByText(/Unable to preview this table reliably/)),
  ).toBeVisible({ timeout: 15_000 });
  await report(page, "wide-quoted-1mib", Buffer.byteLength(wide));
});

test("can leave a pathological parse and open another real Worker result", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await setup(page, wide);
  const workerStarted = page.waitForEvent("worker");
  await page.goto(viewerURL());
  const worker = await workerStarted;
  let closed = false;
  worker.on("close", () => {
    closed = true;
  });
  await page
    .context()
    .route(`**/api/threads/${threadId}/artifacts/**/replacement.csv`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/csv",
        body: "ID,Note\nreplacement,ready\n",
      }),
    );
  await page.goto(viewerURL("/mnt/user-data/outputs/replacement.csv"));
  await expect(
    page.getByRole("cell", { name: "replacement", exact: true }),
  ).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => closed).toBe(true);
  await expect(page.getByRole("row")).toHaveCount(2);
});
