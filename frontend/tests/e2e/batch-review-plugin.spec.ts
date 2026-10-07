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
  gateway = spawn(
    path.join(backend, ".venv/bin/python"),
    [
      "-m",
      "extension_test_fixtures.batch_review_gateway",
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
  test(`batch reports through ${custom ? "Custom Agent" : "default chat"}: actual page entry, saved excerpt, worker stopped and paging`, async ({
    page,
    request,
  }, testInfo) => {
    const agent = custom ? "researcher" : undefined;
    mockLangGraphAPI(page, {
      agents: agent ? [{ name: agent, description: "Research assistant" }] : [],
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
    const calls: string[] = [];
    await page.route("**/api/plugins**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.includes("/actions/")) calls.push(url.pathname);
      const response = await route.fetch({
        url: gatewayURL + url.pathname.slice(url.pathname.indexOf("/api/")),
        headers: { ...route.request().headers(), "x-test-user": "alice" },
      });
      await route.fulfill({ response });
    });
    await page.goto(
      agent
        ? `/workspace/agents/${agent}/chats/${MOCK_THREAD_ID}`
        : `/workspace/chats/${MOCK_THREAD_ID}`,
    );
    await page
      .getByRole("button", { name: "Batch reports", exact: true })
      .click();
    await testInfo.attach("conversation-entry", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    await page
      .getByRole("menuitem", { name: "Review this conversation's results" })
      .click();
    await expect(page).toHaveURL(
      new RegExp(
        `/workspace/extensions/community.batch-review/results\\?thread=${MOCK_THREAD_ID}`,
      ),
    );
    await expect(
      page.getByRole("textbox", { name: "Conversation ID" }),
    ).toHaveValue(MOCK_THREAD_ID);
    await page
      .getByRole("button", { name: "Historical research ·", exact: false })
      .click();
    await page.getByRole("button", { name: "topic-0 · succeeded" }).click();
    await expect(page.getByTestId("batch-saved-report")).toContainText(
      "Full saved report",
    );
    await expect(page.getByTestId("batch-saved-report")).toContainText(
      "<script>window.PWNED = true</script>",
    );
    await expect(
      page.getByRole("button", { name: "citation:1", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "citation:1", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText(
      "Original source <script>window.PWNED = true</script>",
    );
    await testInfo.attach("saved-report-and-evidence", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    expect(
      await page.evaluate(() => Reflect.get(window, "PWNED")),
    ).toBeUndefined();
    await page.getByRole("button", { name: "Close source" }).click();
    await expect(
      page.getByRole("region", { name: "Saved result" }),
    ).toContainText("Acceptance: Not requested");
    // Viewing never needs a running worker and does not issue provider requests.
    expect(
      calls.every((call) => /\/actions\/(batches|items|result)$/.test(call)),
    ).toBe(true);
    await page.getByRole("button", { name: "Load more items" }).click();
    await expect(
      page.getByRole("button", { name: "topic-50 · pending" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Load more items" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "topic-50 · pending" }).click();
    await expect(
      page.getByRole("region", { name: "Saved result" }),
    ).toContainText("No saved report for this item yet.");
    await expect(
      page.getByRole("button", { name: "citation:1", exact: true }),
    ).toHaveCount(0);
    // Real HTTP action admission retains owner isolation after arbitrary browser context.
    const response = await request.post(
      `${gatewayURL}/api/plugins/community.batch-review/actions/result`,
      {
        headers: { "x-test-user": "bob" },
        data: {
          thread_id: MOCK_THREAD_ID,
          batch_id: "research-batch",
          position: 0,
        },
      },
    );
    expect(response.status()).toBe(404);
    const denied = await request.post(
      `${gatewayURL}/api/plugins/community.batch-review/actions/result`,
      {
        headers: { "x-test-denied": "1" },
        data: {
          thread_id: MOCK_THREAD_ID,
          batch_id: "research-batch",
          position: 0,
        },
      },
    );
    expect(denied.status()).toBe(403);
    await page
      .getByRole("button", { name: "Return to conversation and controls" })
      .click();
    await expect(page).toHaveURL(
      agent
        ? `/workspace/agents/${agent}/chats/${MOCK_THREAD_ID}`
        : `/workspace/chats/${MOCK_THREAD_ID}`,
    );
    await page
      .getByRole("link", { name: "Batch reports", exact: true })
      .click();
    await expect(
      page.getByRole("textbox", { name: "Conversation ID" }),
    ).toHaveValue("");
    await page
      .getByRole("textbox", { name: "Conversation ID" })
      .fill(MOCK_THREAD_ID);
    await page
      .getByRole("button", { name: "Load reports", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Historical research ·", exact: false })
      .click();
    await page.getByRole("button", { name: "topic-0 · succeeded" }).click();
    await expect(page.getByTestId("batch-saved-report")).toContainText(
      "Full saved report",
    );
  });
}

test("browser code boundaries, malformed/legacy evidence and read-error recovery", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let failures = 1;
  let codeExample = false;
  let legacy = false;
  await page.route("**/api/plugins**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/actions/result") && failures-- > 0) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Storage unavailable" }),
      });
      return;
    }
    const response = await route.fetch({
      url: gatewayURL + url.pathname.slice(url.pathname.indexOf("/api/")),
    });
    if (url.pathname.endsWith("/actions/result") && response.ok()) {
      const saved = await response.json();
      if (codeExample) {
        const id = saved.evidence.sources[0].id;
        const cite = `[citation:1](#knowledge-${id})`;
        saved.result = `~~~\n${cite}\n~~~\n\`\`${cite}\`\`\n    ${cite}\n\t${cite}\n\`a\n    b\n${cite}\nc\`\n\\\\\`${cite}\`\n> ~~~\n> ${cite}\n> ~~~\n${cite}\n\`\`\`\n${cite}`;
      }
      if (legacy) saved.evidence = null;
      await route.fulfill({
        response,
        contentType: "application/json",
        body: JSON.stringify(saved),
      });
    } else await route.fulfill({ response });
  });
  await page.goto(
    `/workspace/extensions/community.batch-review/results?thread=${MOCK_THREAD_ID}`,
  );
  await page
    .getByRole("button", { name: "Historical research ·", exact: false })
    .click();
  await page.getByRole("button", { name: "topic-0 · succeeded" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Unable to load saved results",
  );
  await page.getByRole("button", { name: "Retry read" }).click();
  await expect(page.getByTestId("batch-saved-report")).toContainText(
    "Full saved report",
  );
  codeExample = true;
  await page.getByRole("button", { name: "Refresh selected result" }).click();
  await expect(page.getByTestId("batch-saved-report")).toContainText("~~~");
  // Only the single real citation outside all code regions becomes an action.
  await expect(
    page.getByRole("button", { name: "citation:1", exact: true }),
  ).toHaveCount(1);
  legacy = true;
  await page.getByRole("button", { name: "Refresh selected result" }).click();
  await expect(
    page.getByRole("region", { name: "Saved result" }),
  ).toContainText("No captured evidence snapshot");
  await expect(
    page.getByRole("button", { name: "citation:1", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Captured.pdf", exact: true }),
  ).toHaveCount(0);
});

test("rapid selection cancels obsolete detail reads and never restores old report/source", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let release: (() => void) | undefined;
  let announced: (() => void) | undefined;
  const started = new Promise<void>((resolve) => {
    announced = resolve;
  });
  const withheld = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/plugins**", async (route) => {
    const url = new URL(route.request().url());
    const response = await route.fetch({
      url: gatewayURL + url.pathname.slice(url.pathname.indexOf("/api/")),
    });
    if (
      url.pathname.endsWith("/actions/result") &&
      route.request().postDataJSON().position === 0
    ) {
      announced!();
      await withheld;
    }
    await route.fulfill({ response }).catch(() => undefined);
  });
  await page.goto(
    `/workspace/extensions/community.batch-review/results?thread=${MOCK_THREAD_ID}`,
  );
  await page
    .getByRole("button", { name: "Historical research ·", exact: false })
    .click();
  await page.getByRole("button", { name: "topic-0 · succeeded" }).click();
  await started;
  await page.getByRole("button", { name: "topic-1 · pending" }).click();
  await expect(
    page.getByRole("region", { name: "Saved result" }),
  ).toContainText("No saved report for this item yet.");
  release!();
  await expect(
    page.getByRole("region", { name: "Saved result" }),
  ).toContainText("topic-1");
  await expect(page.getByTestId("batch-saved-report")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Captured.pdf", exact: true }),
  ).toHaveCount(0);
});
