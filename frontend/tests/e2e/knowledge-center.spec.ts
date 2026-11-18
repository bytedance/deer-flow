import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page, type Request } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const pageURL = "/workspace/extensions/knowledge-center/library";
const api = "/api/extensions/knowledge-platform";
const assetRoot = path.resolve(
  process.cwd(),
  "../examples/deerflow-extension-knowledge-center/deerflow_extension_knowledge_center",
);
const resource = {
  resource_id: "resource-a",
  provider: "weknora",
  connection_id: "local",
  native_base_id: "Team handbook",
  dataset_id: "wk1_fixture",
  operations: [
    "capabilities",
    "manual",
    "url",
    "upload",
    "status",
    "reprocess",
    "cancel",
  ],
  tools: [],
  processing: {},
};
const result = {
  version: 1,
  provider: "weknora",
  connection_id: "local",
  dataset_id: "wk1_fixture",
  document_id: "doc-1",
  state: "unknown",
  provider_state: "new-provider-state",
  searchable: false,
};

async function setup(
  page: Page,
  options: {
    locale?: string;
    capabilitiesStatus?: number;
    writeStatus?: number;
    disabled?: boolean;
    empty?: boolean;
  } = {},
) {
  mockLangGraphAPI(page);
  const calls: Request[] = [];
  let operations = [...resource.operations];
  await page.route("**/api/plugins**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const entry = `/api/plugins/knowledge-center/assets/${"a".repeat(64)}/static/index.mjs`;
    if (pathname.endsWith("/api/plugins"))
      return route.fulfill({
        json: [
          {
            namespace: "knowledge-center",
            viewer_id: "default",
            title: "Knowledge center",
            description: "",
            module: "knowledge-center.v1",
            entry,
            transport: "assets-v1",
            settings: { enabled: !options.disabled },
            backend_actions: [],
          },
        ],
      });
    const filename = pathname.split("/").pop()!;
    if (
      !["index.mjs", "center.mjs", "copy.mjs", "styles.css"].includes(filename)
    )
      return route.fulfill({ status: 404 });
    return route.fulfill({
      body: await readFile(path.join(assetRoot, "static", filename)),
      contentType: filename.endsWith("css") ? "text/css" : "text/javascript",
    });
  });
  await page.route(`**${api}/**`, async (route) => {
    const req = route.request();
    calls.push(req);
    const pathname = new URL(req.url()).pathname;
    if (pathname.endsWith("/spaces"))
      return route.fulfill({
        json: {
          revision: 1,
          items: options.empty
            ? []
            : [{ space_id: "team", title: "Research team", role: "manager" }],
        },
      });
    if (pathname.endsWith("/spaces/team"))
      return route.fulfill({
        json: {
          revision: 1,
          title: "Research team",
          resources: [
            resource,
            {
              ...resource,
              resource_id: "resource-b",
              native_base_id: "Other handbook",
            },
          ],
        },
      });
    if (pathname.endsWith("/capabilities"))
      return route.fulfill({
        status: options.capabilitiesStatus ?? 200,
        json: {
          version: 1,
          operations,
          processing_options: [
            "summary_enabled",
            "chunk_size",
            "chunk_overlap",
          ],
          pipeline: {},
        },
      });
    if (req.method() === "POST")
      return route.fulfill({
        status: options.writeStatus ?? 202,
        json: result,
      });
    return route.fulfill({
      json: {
        ...result,
        state: "completed",
        provider_state: "done",
        searchable: true,
      },
    });
  });
  await page.context().addCookies([
    {
      name: "locale",
      value: options.locale ?? "en-US",
      url: test.info().project.use.baseURL!,
    },
    {
      name: "csrf_token",
      value: "knowledge-test-token",
      url: test.info().project.use.baseURL!,
    },
  ]);
  return {
    calls,
    revoke: () => {
      operations = ["capabilities", "status"];
    },
  };
}

for (const zh of [false, true]) {
  test(`knowledge center import, status and explicit processing (${zh ? "zh mobile" : "en desktop"})`, async ({
    page,
  }) => {
    if (zh) await page.setViewportSize({ width: 375, height: 812 });
    const { calls } = await setup(page, { locale: zh ? "zh-CN" : "en-US" });
    await page.goto(pageURL, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", {
        name: zh ? "让知识随时可用" : "Your knowledge, ready to work",
      }),
    ).toBeVisible();
    await page
      .getByLabel(zh ? "标题" : "Title", { exact: true })
      .fill("A source worth keeping");
    await page
      .getByLabel(zh ? "文档内容" : "Document text", { exact: true })
      .fill("Synthetic knowledge for a browser contract test.");
    await page
      .getByRole("button", { name: zh ? "提交文档" : "Submit document" })
      .click();
    const row = page
      .getByRole("article")
      .filter({ has: page.getByRole("heading", { name: "doc-1" }) });
    await expect(row).toContainText(
      zh ? "处理状态: 未知" : "Processing state: Unknown",
    );
    expect(calls.filter((r) => r.method() === "POST")).toHaveLength(1);
    expect(
      calls.find((r) => r.method() === "POST")!.headers()["x-csrf-token"],
    ).toBe("knowledge-test-token");
    await row
      .getByRole("button", { name: zh ? "刷新状态" : "Refresh status" })
      .click();
    await expect(row).toContainText(
      zh ? "处理状态: 已完成" : "Processing state: Completed",
    );
    await row
      .getByRole("button", { name: zh ? "重新处理" : "Reprocess", exact: true })
      .click();
    expect(calls.filter((r) => r.method() === "POST")).toHaveLength(1);
    await row
      .getByRole("button", { name: zh ? "确认操作" : "Confirm", exact: true })
      .click();
    await expect
      .poll(() => calls.filter((r) => r.method() === "POST").length)
      .toBe(2);
    await expect(
      page.getByRole("button", { name: zh ? "提交文档" : "Submit document" }),
    ).toBeEnabled();
    await row
      .getByRole("button", {
        name: zh ? "取消处理" : "Cancel processing",
        exact: true,
      })
      .click();
    await row
      .getByRole("button", { name: zh ? "确认操作" : "Confirm", exact: true })
      .click();
    await expect
      .poll(() => calls.filter((r) => r.method() === "POST").length)
      .toBe(3);
    await expect(
      page.getByText(zh ? /此连接暂不支持/ : /Entry editing, version history/),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (process.env.EXTENSION_SCREENSHOT_DIR) {
      await page
        .getByRole("heading", {
          name: zh ? "让知识随时可用" : "Your knowledge, ready to work",
        })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(
          process.env.EXTENSION_SCREENSHOT_DIR,
          `knowledge-${zh ? "zh-mobile" : "en-desktop"}.png`,
        ),
        fullPage: true,
      });
    }
  });
}

test("URL and raw file submission preserve processing fields", async ({
  page,
}) => {
  const { calls } = await setup(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Import document", { exact: true }).selectOption("url");
  await page.getByLabel("Document URL").fill("https://example.com/document");
  await page.getByText("Processing options", { exact: true }).click();
  await page.getByLabel("Summary", { exact: true }).selectOption("false");
  await page.getByRole("button", { name: "Submit document" }).click();
  await expect
    .poll(() => calls.filter((r) => r.method() === "POST").length)
    .toBe(1);
  expect(
    calls.find((r) => r.method() === "POST")!.postDataJSON(),
  ).toMatchObject({ kind: "url", processing: { summary_enabled: false } });
  await expect(
    page.getByRole("button", { name: "Submit document" }),
  ).toBeEnabled();
  await page
    .getByLabel("Import document", { exact: true })
    .selectOption("upload");
  await page.getByLabel("File (up to 16 MiB)").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("synthetic upload"),
  });
  await page.getByRole("button", { name: "Submit document" }).click();
  await expect
    .poll(() => calls.filter((r) => r.method() === "POST").length)
    .toBe(2);
  const upload = calls.filter((r) => r.method() === "POST")[1]!;
  expect(upload.url()).toContain("/files?filename=notes.txt");
  expect(upload.postData()).toBe("synthetic upload");
  expect(upload.headers()["x-processing-options"]).toBe(
    '{"summary_enabled":false}',
  );
});

test("uncertain writes require reconciliation and never replay", async ({
  page,
}) => {
  const { calls } = await setup(page, { writeStatus: 504 });
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Title", { exact: true }).fill("Uncertain write");
  await page.getByLabel("Document text").fill("Synthetic text");
  await page.getByRole("button", { name: "Submit document" }).click();
  await expect(page.getByText(/The provider may have accepted/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Submit document" }),
  ).toBeDisabled();
  expect(calls.filter((r) => r.method() === "POST")).toHaveLength(1);
  await page
    .getByRole("button", { name: "I checked the upstream result" })
    .click();
  await expect(
    page.getByRole("button", { name: "Submit document" }),
  ).toBeEnabled();
  expect(calls.filter((r) => r.method() === "POST")).toHaveLength(1);
});

test("invalid URL, chunk pair and oversized upload never submit", async ({
  page,
}) => {
  const { calls } = await setup(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  const mode = page.getByLabel("Import document", { exact: true });
  const submit = page.getByRole("button", { name: "Submit document" });
  await mode.selectOption("url");
  await page
    .getByLabel("Document URL")
    .fill("https://user:password@example.com/document");
  await submit.click();
  await expect(
    page.getByRole("alert").filter({ hasText: /without credentials/ }),
  ).toBeVisible();
  await page.getByLabel("Document URL").fill("https://example.com/document");
  await page.getByText("Processing options", { exact: true }).click();
  await page.getByLabel("Chunk size (64–8192)").fill("256");
  await submit.click();
  await expect(
    page.getByRole("alert").filter({ hasText: /Supply both chunk fields/ }),
  ).toBeVisible();
  await page.getByLabel("Chunk size (64–8192)").fill("");
  await mode.selectOption("upload");
  await page.getByLabel("File (up to 16 MiB)").setInputFiles({
    name: "large.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(16 * 1024 * 1024 + 1),
  });
  await submit.click();
  await expect(
    page.getByRole("alert").filter({ hasText: /no larger than 16 MiB/ }),
  ).toBeVisible();
  expect(calls.filter((r) => r.method() === "POST")).toHaveLength(0);
});

test("revoked capabilities stop submission before any write", async ({
  page,
}) => {
  const fixture = await setup(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Title", { exact: true }).fill("Revoked write");
  await page.getByLabel("Document text").fill("Synthetic text");
  fixture.revoke();
  await page.getByRole("button", { name: "Submit document" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: /does not support/ }),
  ).toBeVisible();
  expect(fixture.calls.filter((r) => r.method() === "POST")).toHaveLength(0);
});

test("browse-only members see no management controls", async ({ page }) => {
  await setup(page, { capabilitiesStatus: 403 });
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/You can browse this space/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Submit document" }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Knowledge base", { exact: true }),
  ).toBeEnabled();
});

test("a late status read cannot overwrite a confirmed cancellation", async ({
  page,
}) => {
  await setup(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Document ID", { exact: true }).fill("doc-1");
  await page.getByRole("button", { name: "Check status", exact: true }).click();
  const row = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: "doc-1" }) });
  await expect(row).toContainText("Completed");
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  let readStarted = false;
  await page.route(`**${api}/**/documents/doc-1`, async (route) => {
    readStarted = true;
    await delayed;
    await route.fulfill({ json: { ...result, state: "running" } });
  });
  await page.route(`**${api}/**/documents/doc-1/cancel`, (route) =>
    route.fulfill({ status: 202, json: { ...result, state: "cancelled" } }),
  );
  await row.getByRole("button", { name: "Refresh status" }).click();
  await expect.poll(() => readStarted).toBe(true);
  await row
    .getByRole("button", { name: "Cancel processing", exact: true })
    .click();
  await row.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(row).toContainText("Cancelled");
  const response = page.waitForResponse((r) =>
    r.url().endsWith("/documents/doc-1"),
  );
  release();
  await (await response).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => {
          requestAnimationFrame(() => resolve());
        }),
      ),
  );
  await expect(row).toContainText("Cancelled");
});

test("dark theme follows host tokens and unavailable platform has a recovery control", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  await setup(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("Title", { exact: true })).toBeVisible();
  if (process.env.EXTENSION_SCREENSHOT_DIR)
    await page.screenshot({
      path: path.join(
        process.env.EXTENSION_SCREENSHOT_DIR,
        "knowledge-dark.png",
      ),
      fullPage: true,
    });
  await page.route(`**${api}/spaces`, (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.getByRole("button", { name: "Reload spaces" }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: /request could not be completed/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reload spaces" }),
  ).toBeEnabled();
});

test("resource changes clear snapshots and do not accumulate listeners", async ({
  page,
}) => {
  const { calls } = await setup(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Document ID", { exact: true }).fill("doc-1");
  await page.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(page.getByRole("heading", { name: "doc-1" })).toBeVisible();
  const selector = page.getByLabel("Knowledge base", { exact: true });
  await selector.selectOption("resource-b");
  await expect(page.getByRole("heading", { name: "doc-1" })).toHaveCount(0);
  await expect(page.getByLabel("Document ID", { exact: true })).toBeVisible();
  const before = calls.filter((r) => r.url().endsWith("/capabilities")).length;
  await page.getByRole("button", { name: "Reload spaces" }).click();
  await expect(page.getByLabel("Document ID", { exact: true })).toBeVisible();
  await selector.selectOption("resource-b");
  await expect(page.getByLabel("Document ID", { exact: true })).toBeVisible();
  expect(
    calls.filter((r) => r.url().endsWith("/capabilities")).length - before,
  ).toBe(2);
});

test("disabled page and empty membership have explicit states", async ({
  page,
}) => {
  await setup(page, { empty: true });
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/No accessible spaces/)).toBeVisible();
  await setup(page, { disabled: true });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Extension page unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Knowledge center", exact: true }),
  ).toHaveCount(0);
});
