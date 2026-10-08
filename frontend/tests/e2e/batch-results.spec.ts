import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

let gateway: ChildProcess;
let gatewayURL: string;

test.beforeAll(async ({ request }) => {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const address = probe.address();
  if (!address || typeof address === "string")
    throw new Error("Missing test port");
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  gatewayURL = `http://127.0.0.1:${address.port}`;
  const backend = path.resolve(process.cwd(), "../backend");
  const python =
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python";
  gateway = spawn(
    path.join(backend, python),
    [
      "-m",
      "extension_test_fixtures.batch_results_gateway",
      String(address.port),
    ],
    { cwd: backend, stdio: "pipe" },
  );
  let diagnostics = "";
  gateway.stderr?.on("data", (chunk) => {
    diagnostics += String(chunk);
  });
  await expect
    .poll(
      async () => {
        if (gateway.exitCode !== null) throw new Error(diagnostics);
        return request
          .get(`${gatewayURL}/health`)
          .then((response) => response.status())
          .catch(() => 0);
      },
      { timeout: 20_000 },
    )
    .toBe(200);
});

test.afterAll(async () => {
  if (gateway?.exitCode === null) {
    const exited = new Promise<void>((resolve) =>
      gateway.once("exit", () => resolve()),
    );
    gateway.kill("SIGTERM");
    await exited;
  }
});

for (const custom of [false, true]) {
  for (const mobile of [false, true]) {
    test(`native batch reports: ${custom ? "Custom Agent" : "default chat"}, ${mobile ? "mobile" : "desktop"}`, async ({
      page,
    }, testInfo) => {
      if (mobile) await page.setViewportSize({ width: 390, height: 844 });
      const agent = custom ? "researcher" : undefined;
      mockLangGraphAPI(page, {
        agents: agent
          ? [{ name: agent, description: "Research assistant" }]
          : [],
        threads: [
          {
            thread_id: MOCK_THREAD_ID,
            title: "Research",
            agent_name: agent,
            messages: [
              { id: "u", type: "human", content: "Research the documents" },
              { id: "a", type: "ai", content: "Research submitted" },
            ],
          },
        ],
      });
      await page.route("**/api/features", async (route) =>
        route.fulfill({
          json: {
            agents_api: { enabled: true },
            subagent_batches: {
              repository_available: true,
              worker_running: false,
              enabled: false,
            },
          },
        }),
      );
      const reads: string[] = [];
      await page.route("**/api/threads/*/subagent-batches**", async (route) => {
        const url = new URL(route.request().url());
        reads.push(url.pathname + url.search);
        const response = await route.fetch({
          url: gatewayURL + url.pathname + url.search,
          headers: { ...route.request().headers(), "x-test-user": "alice" },
        });
        await route.fulfill({ response });
      });
      const entry = agent
        ? `/workspace/agents/${agent}/chats/${MOCK_THREAD_ID}`
        : `/workspace/chats/${MOCK_THREAD_ID}`;
      await page.goto(entry);
      await page.getByTestId("subagent-batches-trigger").click();
      await expect(
        page.getByText("Historical research", { exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "View items", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Load more", exact: true })
        .click();
      await expect(page.getByText("topic-100", { exact: true })).toBeVisible();
      expect(reads.some((url) => url.includes("offset=100"))).toBe(true);
      expect(reads.some((url) => url.endsWith("/result"))).toBe(false);
      await page
        .getByRole("button", { name: "View report", exact: true })
        .first()
        .scrollIntoViewIfNeeded();
      await testInfo.attach("native-entry", {
        body: await page.screenshot({
          path: testInfo.outputPath("native-entry.png"),
        }),
        contentType: "image/png",
      });
      await page
        .getByRole("button", { name: "View report", exact: true })
        .first()
        .click();
      const report = page.getByTestId("batch-saved-report");
      await expect(report).toContainText("Full saved report");
      await expect(report).toContainText("No criteria");
      await expect(report).not.toContainText("Unverified");
      await expect(
        report.locator("code").filter({ hasText: "[citation:1]" }),
      ).toHaveCount(1);
      const citations = page.getByRole("button", {
        name: "View source: Captured.pdf",
      });
      await expect(citations).toHaveCount(2);
      const citation = citations.first();
      await expect(citation).toContainText("2");
      await expect(citations.last()).toContainText("3");
      await expect(
        report.locator("code").filter({ hasText: "quoted example" }),
      ).toHaveCount(1);
      const dialog = page.getByRole("dialog").last();
      const bounds = await dialog.boundingBox();
      expect(bounds?.width).toBeLessThanOrEqual(mobile ? 390 : 896);
      await dialog.evaluate(async (element) => {
        await Promise.all(
          element.getAnimations().map((animation) => animation.finished),
        );
      });
      await testInfo.attach("native-report", {
        body: await page.screenshot({
          path: testInfo.outputPath("native-report.png"),
        }),
        contentType: "image/png",
      });
      await citation.click();
      await expect(page.getByRole("dialog").last()).toContainText(
        "Original source <script>window.PWNED = true</script>",
      );
      expect(
        await page.evaluate(() => Reflect.get(window, "PWNED")),
      ).toBeUndefined();
      await page
        .getByRole("dialog")
        .last()
        .evaluate(async (element) => {
          await Promise.all(
            element.getAnimations().map((animation) => animation.finished),
          );
        });
      await testInfo.attach("captured-evidence", {
        body: await page.screenshot({
          path: testInfo.outputPath("captured-evidence.png"),
        }),
        contentType: "image/png",
      });
      await page
        .getByRole("dialog")
        .last()
        .getByRole("button", { name: "Close", exact: true })
        .click();
      await expect(citation).toBeFocused();
      await expect(report).toBeVisible();
      await page
        .getByRole("dialog")
        .last()
        .getByRole("button", { name: "Close", exact: true })
        .click();
      await expect(page.getByText("topic-100", { exact: true })).toBeVisible();
      await expect(page).toHaveURL(new RegExp(entry + "$"));
      expect(reads.filter((url) => url.endsWith("/result"))).toEqual([
        `/api/threads/${MOCK_THREAD_ID}/subagent-batches/research-batch/items/0/result`,
      ]);
    });
  }
}

test("native report HTTP boundary rejects a different owner and denied thread permission", async ({
  request,
}) => {
  const url = `${gatewayURL}/api/threads/${MOCK_THREAD_ID}/subagent-batches/research-batch/items/0/result`;
  for (const [headers, status] of [
    [{ "x-test-user": "bob" }, 404],
    [{ "x-test-user": "alice", "x-test-denied": "1" }, 403],
  ] as const) {
    const response = await request.get(url, { headers });
    expect(response.status()).toBe(status);
    expect(await response.text()).not.toContain("Full saved report");
  }
});
