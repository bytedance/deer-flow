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
      ![
        "index.mjs",
        "center.mjs",
        "copy.mjs",
        "library.mjs",
        "library-copy.mjs",
        "graph.mjs",
        "styles.css",
      ].includes(filename)
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
    await page
      .getByRole("button", {
        name: zh ? "知识条目" : "Knowledge entries",
        exact: true,
      })
      .click();
    await expect(
      page.getByText(
        zh ? /此连接未提供这项能力/ : /This connection does not offer/,
      ),
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

async function setupLibrary(page: Page, locale = "en-US", conflict = false) {
  const fixture = await setup(page, { locale });
  const mutations: Request[] = [];
  let version = 2;
  const entry = {
    key: "concept/cedar",
    title: "Cedar",
    content: "Current text",
    summary: "A tree",
    version,
    status: "published",
  };
  const operations = [
    ...resource.operations,
    "documents",
    "entries",
    "entry",
    "revisions",
    "revision",
    "entry_edit",
    "entry_restore",
    "graph",
  ];
  await page.route(`**${api}/**/capabilities`, (route) =>
    route.fulfill({
      json: { operations, processing_options: [], pipeline: {} },
    }),
  );
  await page.route(`**${api}/**/library/**`, (route) => {
    fixture.calls.push(route.request());
    const url = new URL(route.request().url());
    const action = url.pathname.split("/").pop();
    const data = {
      provider: "weknora",
      connection_id: "local",
      dataset_id: "wk1_fixture",
      title: "Handbook",
      page: Number(url.searchParams.get("page") ?? 1),
      page_size: 20,
      total: 1,
      documents: [],
      entries: [],
      revisions: [],
      entry: null,
      graph: null,
    };
    if (action === "documents")
      return route.fulfill({
        json: {
          ...data,
          documents: [{ title: "Team guide", processing: result }],
        },
      });
    if (action === "entries")
      return route.fulfill({ json: { ...data, entries: [entry] } });
    if (action === "revisions")
      return route.fulfill({
        json: {
          ...data,
          entry: { ...entry, version },
          revisions: [
            {
              version: 1,
              editor: "Alice",
              source: "user",
              edited_at: "2026-01-01",
            },
          ],
        },
      });
    if (action === "graph")
      return route.fulfill({
        json: {
          ...data,
          graph: {
            bounded: true,
            entities: [
              { id: "Cedar", description: "A tree" },
              { id: "Forest", description: "A place" },
            ],
            relations: [
              {
                source: "Cedar",
                target: "Forest",
                description: "Grows in",
                evidence_ids: ["chunk-a"],
              },
            ],
            evidence: [
              { id: "chunk-a", content: "Cedar grows in the forest." },
            ],
          },
        },
      });
    return route.fulfill({
      json: {
        ...data,
        entry: {
          ...entry,
          version: action === "revision" ? 1 : version,
          content: action === "revision" ? "Old text" : entry.content,
        },
      },
    });
  });
  await page.route(`**${api}/**/entry**`, (route) => {
    if (!["PUT", "POST"].includes(route.request().method()))
      return route.fallback();
    mutations.push(route.request());
    if (conflict) return route.fulfill({ status: 409, json: {} });
    version++;
    return route.fulfill({
      json: {
        provider: "weknora",
        connection_id: "local",
        dataset_id: "wk1_fixture",
        entry: { ...entry, version, content: "Saved text" },
      },
    });
  });
  return { ...fixture, mutations };
}

for (const zh of [false, true]) {
  test(`knowledge library directories, editing, history and graph (${zh ? "zh mobile" : "en"})`, async ({
    page,
  }) => {
    if (zh) await page.setViewportSize({ width: 375, height: 812 });
    const { mutations } = await setupLibrary(page, zh ? "zh-CN" : "en-US");
    await page.goto(pageURL, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("button", { name: "Team guide", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Team guide", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "doc-1", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", {
        name: zh ? "知识条目" : "Knowledge entries",
        exact: true,
      })
      .click();
    await page.getByRole("button", { name: "Cedar", exact: true }).click();
    const editor = page.getByLabel(zh ? "条目正文" : "Entry content", {
      exact: true,
    });
    await expect(editor).toHaveValue("Current text");
    await editor.fill("Saved text");
    await expect(
      page.getByLabel(zh ? "知识库" : "Knowledge base", { exact: true }),
    ).toBeDisabled();
    await page
      .getByRole("button", {
        name: zh ? "保存条目" : "Save entry",
        exact: true,
      })
      .click();
    await expect(editor).toHaveValue("Saved text");
    await expect.poll(() => mutations.length).toBe(1);
    await expect(editor).toBeEnabled();
    expect(mutations[0]!.postDataJSON()).toMatchObject({
      expected_version: 2,
      content: "Saved text",
      entry: "concept/cedar",
    });
    await page
      .getByRole("button", {
        name: zh ? "版本历史" : "Version history",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", {
        name: zh ? "查看版本 1" : "View version 1",
        exact: true,
      })
      .click();
    await expect(page.getByText("Old text", { exact: true })).toBeVisible();
    await page
      .getByRole("button", {
        name: zh ? "恢复此版本" : "Restore this version",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", {
        name: zh ? "确认恢复" : "Confirm restore",
        exact: true,
      })
      .click();
    await expect.poll(() => mutations.length).toBe(2);
    expect(mutations[1]!.postDataJSON()).toMatchObject({
      expected_version: 3,
      version: 1,
    });
    await page
      .getByRole("button", {
        name: zh ? "实体关系" : "Entities and relations",
        exact: true,
      })
      .click();
    await page
      .getByLabel(zh ? "关系查询" : "Relation query", { exact: true })
      .fill("Cedar");
    await page
      .getByRole("button", {
        name: zh ? "查询图谱" : "Query graph",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("img", {
        name: zh ? "实体关系图" : "Entity relation graph",
      }),
    ).toBeVisible();
    await expect(
      page.getByText("Cedar grows in the forest.", { exact: true }),
    ).toBeVisible();
    if (!zh)
      await page.evaluate(() => document.documentElement.classList.add("dark"));
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    if (process.env.KNOWLEDGE_SCREENSHOT_DIR) {
      await page.setViewportSize({ width: zh ? 375 : 1280, height: 1400 });
      await page
        .getByRole("button", {
          name: zh ? "实体关系" : "Entities and relations",
          exact: true,
        })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(
          process.env.KNOWLEDGE_SCREENSHOT_DIR,
          zh ? "library-zh-mobile.png" : "library-en.png",
        ),
        fullPage: true,
      });
    }
  });
}

test("entry conflict keeps draft and requires reconciliation without retry", async ({
  page,
}) => {
  const { mutations } = await setupLibrary(page, "en-US", true);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page
    .getByRole("button", { name: "Knowledge entries", exact: true })
    .click();
  await page.getByRole("button", { name: "Cedar", exact: true }).click();
  await page.getByLabel("Entry content", { exact: true }).fill("My draft");
  await page.getByRole("button", { name: "Save entry", exact: true }).click();
  await expect(page.getByLabel("Entry content", { exact: true })).toHaveValue(
    "My draft",
  );
  await expect(
    page.getByRole("button", { name: "Save entry", exact: true }),
  ).toBeDisabled();
  await expect.poll(() => mutations.length).toBe(1);
  await expect(
    page.getByRole("button", {
      name: "I checked the upstream result",
      exact: true,
    }),
  ).toBeVisible();
});

test("document directory sends real search and processing filters", async ({
  page,
}) => {
  const { calls } = await setupLibrary(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Search directory", { exact: true }).fill("Team guide");
  await page
    .getByLabel("Processing filter", { exact: true })
    .selectOption("processing");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect
    .poll(
      () =>
        calls.filter(
          (req) =>
            req.url().includes("/library/documents") &&
            new URL(req.url()).searchParams.get("state") === "processing",
        ).length,
    )
    .toBe(1);
  const req = calls
    .filter((req) => req.url().includes("/library/documents"))
    .at(-1)!;
  expect(new URL(req.url()).searchParams.get("search")).toBe("Team guide");
  expect(new URL(req.url()).searchParams.get("page")).toBe("1");
});

test("entry fields lock during save and unsaved navigation requires consent", async ({
  page,
}) => {
  await setupLibrary(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page
    .getByRole("button", { name: "Knowledge entries", exact: true })
    .click();
  await page.getByRole("button", { name: "Cedar", exact: true }).click();
  const editor = page.getByLabel("Entry content", { exact: true });
  await editor.fill("Draft remains");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await expect(editor).toHaveValue("Draft remains");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**${api}/**/entry`, async (route) => {
    await gate;
    await route.fallback();
  });
  try {
    await page.getByRole("button", { name: "Save entry", exact: true }).click();
    await expect(editor).toBeDisabled();
  } finally {
    release();
  }
  await expect(editor).toBeEnabled();
});

test("a directory read started before cancellation cannot render stale rows", async ({
  page,
}) => {
  await setupLibrary(page);
  await page.goto(pageURL, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Team guide", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "doc-1", exact: true }),
  ).toBeVisible();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**${api}/**/library/documents?**`, async (route) => {
    await gate;
    await route.fulfill({
      json: {
        provider: "weknora",
        connection_id: "local",
        dataset_id: "wk1_fixture",
        documents: [{ title: "Stale directory entry", processing: result }],
        page_size: 20,
        total: 1,
      },
    });
  });
  try {
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByText("Loading…", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Cancel processing", exact: true })
      .click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(page.getByText(/Submission returned/)).toBeVisible();
  } finally {
    release();
  }
  await expect(page.getByText("Loading…", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Stale directory entry", exact: true }),
  ).toHaveCount(0);
});
