import { createHash } from "node:crypto";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const ARTIFACT_PATH = "/artifact-fixtures/report.html";
const MARKDOWN_ARTIFACT_PATH = "/artifact-fixtures/report.md";
const JSON_ARTIFACT_PATH = "/artifact-fixtures/report.json";
const PRESENTED_ARTIFACT_PATH = "/mnt/user-data/outputs/presented-report.md";
const PDF_ARTIFACT_PATH = "/artifact-fixtures/report.pdf";
const LARGE_JSON_ARTIFACT_PATH = "/mnt/user-data/outputs/large-report.json";
const IN_PROGRESS_THREAD_ID = "00000000-0000-0000-0000-000000003119";
const COMPLETE_THREAD_ID = "00000000-0000-0000-0000-000000003120";
const MARKDOWN_THREAD_ID = "00000000-0000-0000-0000-000000003121";
const MARKDOWN_ANCHOR_THREAD_ID = "00000000-0000-0000-0000-000000003123";
const JSON_THREAD_ID = "00000000-0000-0000-0000-000000003122";
const PRESENTED_THREAD_ID = "00000000-0000-0000-0000-000000003123";
const PERSISTED_PANEL_THREAD_ID = "00000000-0000-0000-0000-000000003125";
const PDF_THREAD_ID = "00000000-0000-0000-0000-000000003124";
const LARGE_JSON_THREAD_ID = "00000000-0000-0000-0000-000000003126";

function writeFileMessages({
  path = ARTIFACT_PATH,
  content = "<!doctype html><html><body><h1>Report draft</h1><p>测试内容</p></body></html>",
  toolResult,
}: {
  path?: string;
  content?: string;
  toolResult?: string;
} = {}) {
  const messages: unknown[] = [
    {
      type: "human",
      id: "msg-human-artifact",
      content: [{ type: "text", text: "Create a report artifact" }],
    },
    {
      type: "ai",
      id: "msg-ai-write-artifact",
      content: "",
      tool_calls: [
        {
          id: "write-file-artifact",
          name: "write_file",
          args: {
            description: "Writing report artifact",
            path,
            content,
          },
        },
      ],
    },
  ];

  if (toolResult !== undefined) {
    messages.push({
      type: "tool",
      id: "msg-tool-write-artifact",
      name: "write_file",
      tool_call_id: "write-file-artifact",
      content: toolResult,
    });
  }

  return messages;
}

function presentFilesMessages(path = PRESENTED_ARTIFACT_PATH) {
  return [
    {
      type: "human",
      id: "msg-human-present-file",
      content: [{ type: "text", text: "Create a markdown report" }],
    },
    {
      type: "ai",
      id: "msg-ai-present-file",
      content: "The report has been written. Now let me present the file.",
      tool_calls: [
        {
          id: "present-file-artifact",
          name: "present_files",
          args: {
            filepaths: [path],
          },
        },
      ],
    },
  ];
}

test.describe("Artifact preview stability", () => {
  for (const [index, fixture] of [
    {
      name: "fragment",
      declaration: "",
      mode: "BackCompat",
      publicId: "",
      systemId: "",
    },
    {
      name: "HTML5",
      declaration: "<!doctype html>",
      mode: "CSS1Compat",
      publicId: "",
      systemId: "",
    },
    {
      name: "legacy quirks",
      declaration:
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">',
      mode: "BackCompat",
      publicId: "-//W3C//DTD HTML 4.01 Transitional//EN",
      systemId: "",
    },
    {
      name: "XHTML transitional",
      declaration:
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">',
      mode: "CSS1Compat",
      publicId: "-//W3C//DTD XHTML 1.0 Transitional//EN",
      systemId: "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd",
    },
  ].entries()) {
    test(`keeps a ${fixture.name} report open after resource 401 and rewrites SVG styles`, async ({
      page,
      context,
      baseURL,
    }) => {
      const threadId = `00000000-0000-0000-0000-00000000315${index}`;
      const filepath = "/mnt/user-data/outputs/partial-report.html";
      const content = `<!--before-->${fixture.declaration}<html><body><h1>Partial report</h1><img src="expired.png"><svg xmlns="http://www.w3.org/2000/svg"><style>.chart{filter:url(filters.svg#blur)}</style><rect class="chart" style="fill:url(paint.svg#paint)" width="40" height="40"/></svg></body></html><!--after-->`;
      mockLangGraphAPI(page, {
        threads: [
          {
            thread_id: threadId,
            messages: presentFilesMessages(filepath),
            artifacts: [filepath],
          },
        ],
      });
      await context.addCookies([
        {
          name: "access_token",
          value: "preview-session",
          url: baseURL!,
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
      const resources: Array<{ filename: string; authenticated: boolean }> = [];
      await page.route(
        `**/api/threads/${threadId}/artifacts/mnt/user-data/outputs/*`,
        async (route) => {
          const filename = new URL(route.request().url()).pathname
            .split("/")
            .pop()!;
          const headers = await route.request().allHeaders();
          const authenticated =
            headers.cookie?.includes("access_token=preview-session") ?? false;
          if (filename !== "partial-report.html")
            resources.push({ filename, authenticated });
          if (!authenticated || filename === "expired.png")
            return route.fulfill({
              status: 401,
              contentType: "application/json",
              body: '{"detail":"Unauthorized"}',
            });
          if (filename === "partial-report.html")
            return route.fulfill({ contentType: "text/html", body: content });
          await route.fulfill({
            contentType: "image/svg+xml",
            body: '<svg xmlns="http://www.w3.org/2000/svg"><defs><filter id="blur"><feGaussianBlur stdDeviation="1"/></filter><linearGradient id="paint"><stop stop-color="blue"/></linearGradient></defs></svg>',
          });
        },
      );
      await page.goto(`/workspace/chats/${threadId}`);
      await page
        .getByText("partial-report.html", { exact: true })
        .first()
        .click();
      const panel = page.locator("#artifacts");
      await expect(panel.getByRole("status")).toContainText(
        "Some preview resources could not be loaded",
      );
      const iframe = panel.locator('iframe[title="Artifact preview"]');
      await expect(iframe).toHaveAttribute(
        "sandbox",
        "allow-scripts allow-forms",
      );
      const frame = iframe.contentFrame();
      await expect(frame.locator("h1")).toHaveText("Partial report");
      const result = await frame.locator("body").evaluate(() => ({
        mode: document.compatMode,
        doctype: document.doctype
          ? {
              publicId: document.doctype.publicId,
              systemId: document.doctype.systemId,
            }
          : null,
        stylesheet: document.querySelector("svg style")?.textContent,
        inline: document.querySelector("svg rect")?.getAttribute("style"),
        comments: Array.from(document.childNodes)
          .filter((node) => node.nodeType === Node.COMMENT_NODE)
          .map((node) => node.textContent),
      }));
      expect(result.mode).toBe(fixture.mode);
      expect(result.doctype).toEqual(
        fixture.declaration
          ? { publicId: fixture.publicId, systemId: fixture.systemId }
          : null,
      );
      expect(result.stylesheet).toContain("data:image/svg+xml;base64,");
      expect(result.inline).toContain("data:image/svg+xml;base64,");
      expect(result.stylesheet).toContain("#blur");
      expect(result.inline).toContain("#paint");
      expect(result.comments).toEqual(["before", "after"]);
      expect(resources).toHaveLength(3);
      expect(resources.every((resource) => resource.authenticated)).toBe(true);
      await expect(page).toHaveURL(new RegExp(`/workspace/chats/${threadId}$`));
    });
  }

  test("loads protected HTML sibling resources while retaining an opaque sandbox", async ({
    page,
    context,
    baseURL,
  }, testInfo) => {
    const threadId = "00000000-0000-0000-0000-000000003140";
    const filepath = "/mnt/user-data/outputs/authenticated-report.html";
    const stylesheet =
      '@import "nested.css"; h1{background-image:url(chart.png)}';
    const integrity = `sha256-${createHash("sha256").update(stylesheet).digest("base64")}`;
    const content = `<link rel="stylesheet" href="style.css" integrity="${integrity}"><script src="app.js"></script><h1>Authenticated report</h1><img id="chart" src="chart.png">`;
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: threadId,
          messages: presentFilesMessages(filepath),
          artifacts: [filepath],
        },
      ],
    });
    await context.addCookies([
      {
        name: "access_token",
        value: "preview-session",
        url: baseURL!,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const resources: Array<{ filename: string; authenticated: boolean }> = [];
    await page.route(
      `**/api/threads/${threadId}/artifacts/mnt/user-data/outputs/*`,
      async (route) => {
        const filename = new URL(route.request().url()).pathname
          .split("/")
          .pop()!;
        const headers = await route.request().allHeaders();
        const authenticated =
          headers.cookie?.includes("access_token=preview-session") ?? false;
        if (filename !== "authenticated-report.html")
          resources.push({ filename, authenticated });
        if (!authenticated)
          return route.fulfill({ status: 401, body: "unauthorized" });
        const bodies: Record<
          string,
          { contentType: string; body: string | Buffer }
        > = {
          "authenticated-report.html": {
            contentType: "text/html",
            body: content,
          },
          "style.css": {
            contentType: "text/css",
            body: stylesheet,
          },
          "nested.css": {
            contentType: "text/css",
            body: "h1{color:rgb(1,2,3)}",
          },
          "app.js": {
            contentType: "application/javascript",
            body: "window.addEventListener('DOMContentLoaded',()=>{document.body.dataset.scriptLoaded='true'})",
          },
          "chart.png": {
            contentType: "image/png",
            body: Buffer.from(
              "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yA1kAAAAASUVORK5CYII=",
              "base64",
            ),
          },
        };
        const response = bodies[filename];
        if (!response) return route.fulfill({ status: 404 });
        await route.fulfill(response);
      },
    );
    await page.goto(`/workspace/chats/${threadId}`);
    await page
      .getByText("authenticated-report.html", { exact: true })
      .first()
      .click();
    const iframe = page.locator('#artifacts iframe[title="Artifact preview"]');
    await expect(iframe).toHaveAttribute(
      "sandbox",
      "allow-scripts allow-forms",
    );
    const frame = iframe.contentFrame();
    await expect(frame.locator("body")).toHaveAttribute(
      "data-script-loaded",
      "true",
    );
    await expect(frame.locator("h1")).toHaveCSS("color", "rgb(1, 2, 3)");
    await expect
      .poll(() =>
        frame
          .locator("#chart")
          .evaluate((image) => (image as HTMLImageElement).naturalWidth),
      )
      .toBe(1);
    expect(resources).toHaveLength(4);
    expect(resources.every((resource) => resource.authenticated)).toBe(true);
    expect(
      await frame.locator("body").evaluate(() => {
        try {
          return !!window.parent.document;
        } catch {
          return false;
        }
      }),
    ).toBe(false);
    expect(
      await frame.locator("body").evaluate(() => {
        try {
          return document.cookie;
        } catch {
          return "blocked";
        }
      }),
    ).toBe("blocked");
    await iframe.screenshot({ path: testInfo.outputPath("html-preview.png") });
  });

  for (const [index, filename] of ["constructor", "data.__proto__"].entries()) {
    test(`keeps ${filename} artifacts on the download fallback`, async ({
      page,
    }) => {
      const threadId = `00000000-0000-0000-0000-00000000313${index}`;
      const filepath = `/mnt/user-data/outputs/${filename}`;
      mockLangGraphAPI(page, {
        threads: [
          {
            thread_id: threadId,
            title: "Unknown artifact type",
            messages: presentFilesMessages(filepath),
            artifacts: [filepath],
          },
        ],
      });

      await page.goto(`/workspace/chats/${threadId}`);
      await page.getByText(filename, { exact: true }).first().click();

      const artifactsPanel = page.locator("#artifacts");
      const download = artifactsPanel.getByRole("link", { name: "Download" });
      await expect(download).toBeVisible();
      await expect(download).toHaveAttribute(
        "href",
        `/api/threads/${threadId}/artifacts${filepath}?download=true`,
      );
      await expect(artifactsPanel.locator(".cm-editor")).toHaveCount(0);
      await expect(
        artifactsPanel.getByRole("button", { name: "Edit", exact: true }),
      ).toHaveCount(0);
    });
  }

  test("renders preview iframe for an in-progress write artifact", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: IN_PROGRESS_THREAD_ID,
          title: "Artifact preview in progress",
          messages: writeFileMessages(),
        },
      ],
    });

    await page.goto(`/workspace/chats/${IN_PROGRESS_THREAD_ID}`);

    await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText(ARTIFACT_PATH).click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("report.html")).toBeVisible();
    await expect(
      artifactsPanel.locator('iframe[title="Artifact preview"]'),
    ).toBeVisible();
    await expect(
      artifactsPanel.locator('iframe[title="Artifact preview"]'),
    ).toHaveAttribute("sandbox", "allow-scripts allow-forms");
  });

  test("renders preview iframe after the write artifact succeeds", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: COMPLETE_THREAD_ID,
          title: "Artifact preview complete",
          messages: writeFileMessages({ toolResult: "OK" }),
        },
      ],
    });

    await page.goto(`/workspace/chats/${COMPLETE_THREAD_ID}`);

    await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText(ARTIFACT_PATH).click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("report.html")).toBeVisible();
    await expect(
      artifactsPanel.locator('iframe[title="Artifact preview"]'),
    ).toBeVisible();
  });

  test("renders markdown preview for an in-progress write artifact", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MARKDOWN_THREAD_ID,
          title: "Markdown artifact preview in progress",
          messages: writeFileMessages({
            path: MARKDOWN_ARTIFACT_PATH,
            content: "# Markdown draft\n\n- 测试内容 1\n- English term",
          }),
        },
      ],
    });

    await page.goto(`/workspace/chats/${MARKDOWN_THREAD_ID}`);

    await expect(page.getByText(MARKDOWN_ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText(MARKDOWN_ARTIFACT_PATH).click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("report.md")).toBeVisible();
    await expect(artifactsPanel.getByText("Markdown draft")).toBeVisible();
    await expect(artifactsPanel.getByText("测试内容 1")).toBeVisible();
  });

  test("scrolls markdown artifact preview to heading anchors", async ({
    page,
  }) => {
    const filler = Array.from(
      { length: 40 },
      (_, index) => `填充段落 ${index + 1}`,
    ).join("\n\n");

    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MARKDOWN_ANCHOR_THREAD_ID,
          title: "Markdown artifact anchor navigation",
          messages: writeFileMessages({
            path: MARKDOWN_ARTIFACT_PATH,
            content: [
              "# Report",
              "",
              "- [概述](#概述)",
              "",
              filler,
              "",
              "## 概述",
              "",
              "目标章节内容",
            ].join("\n"),
          }),
        },
      ],
    });

    await page.goto(`/workspace/chats/${MARKDOWN_ANCHOR_THREAD_ID}`);

    await expect(page.getByText(MARKDOWN_ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText(MARKDOWN_ARTIFACT_PATH).click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("report.md")).toBeVisible();

    // Anchors keep rehype-sanitize's user-content- clobber prefix (see
    // rehypeScopedSlug), so the heading id — and the translated fragment
    // link that scrolls to it — are both prefixed.
    const targetHeading = artifactsPanel.locator("h2#user-content-概述");
    await expect(targetHeading).toHaveCount(1);
    await artifactsPanel.getByRole("link", { name: "概述" }).click();

    await expect
      .poll(async () =>
        targetHeading.evaluate((element) => {
          const panel = document.querySelector("#artifacts");
          if (!panel) {
            return false;
          }
          const panelRect = panel.getBoundingClientRect();
          const headingRect = element.getBoundingClientRect();
          return (
            headingRect.top >= panelRect.top &&
            headingRect.top <= panelRect.bottom
          );
        }),
      )
      .toBe(true);
  });

  test("renders code view for an in-progress non-preview write artifact", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: JSON_THREAD_ID,
          title: "JSON artifact code view in progress",
          messages: writeFileMessages({
            path: JSON_ARTIFACT_PATH,
            content:
              '{\n  "status": "draft",\n  "中文字段": "测试内容",\n  "count": 3\n}',
          }),
        },
      ],
    });

    await page.goto(`/workspace/chats/${JSON_THREAD_ID}`);

    await expect(page.getByText(JSON_ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText(JSON_ARTIFACT_PATH).click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("report.json")).toBeVisible();
    await expect(artifactsPanel.getByText('"status": "draft"')).toBeVisible();
    await expect(
      artifactsPanel.getByText('"中文字段": "测试内容"'),
    ).toBeVisible();
  });

  test("loads a large code artifact only after explicit confirmation", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: LARGE_JSON_THREAD_ID,
          title: "Large artifact preview",
          messages: presentFilesMessages(LARGE_JSON_ARTIFACT_PATH),
          artifacts: [LARGE_JSON_ARTIFACT_PATH],
        },
      ],
    });
    const ranges: Array<string | undefined> = [];
    await page.route(
      `**/api/threads/${LARGE_JSON_THREAD_ID}/artifacts/mnt/user-data/outputs/large-report.json`,
      (route) => {
        const range = route.request().headers().range;
        ranges.push(range);
        if (range) {
          const body = '{"preview":"PARTIAL_FILE_MARKER"}';
          return route.fulfill({
            status: 206,
            contentType: "application/json",
            headers: {
              "Content-Range": `bytes 0-${Buffer.byteLength(body) - 1}/2000000`,
            },
            body,
          });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: '{"complete":"FULL_FILE_MARKER"}',
        });
      },
    );

    await page.goto(`/workspace/chats/${LARGE_JSON_THREAD_ID}`);
    await expect(page.getByText("large-report.json").first()).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("large-report.json").first().click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText(/PARTIAL_FILE_MARKER/)).toBeVisible();
    await expect(artifactsPanel.locator(".cm-editor")).toHaveCount(0);
    await artifactsPanel
      .getByRole("button", { name: "Load full file" })
      .click();
    await expect(artifactsPanel.getByText(/FULL_FILE_MARKER/)).toBeVisible();
    expect(ranges).toEqual(["bytes=0-1048575", undefined]);
  });

  test("keeps an opened presented artifact in the header dropdown", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: PRESENTED_THREAD_ID,
          title: "Presented artifact dropdown history",
          messages: presentFilesMessages(),
          artifacts: [MARKDOWN_ARTIFACT_PATH],
        },
      ],
    });
    await page.route(
      `**/api/threads/${PRESENTED_THREAD_ID}/artifacts/mnt/user-data/outputs/presented-report.md`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/markdown",
          body: "# Presented Report\n\nGenerated content",
        }),
    );
    await page.route(
      `**/api/threads/${PRESENTED_THREAD_ID}/artifacts/artifact-fixtures/report.md`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/markdown",
          body: "# Thread Report\n\nTracked artifact content",
        }),
    );

    await page.goto(`/workspace/chats/${PRESENTED_THREAD_ID}`);

    // The file card in the message list shows the basename only.
    await expect(page.getByText("presented-report.md")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("presented-report.md").first().click();

    const artifactsPanel = page.locator("#artifacts");

    await expect(artifactsPanel.getByText("presented-report.md")).toBeVisible();
    await expect(artifactsPanel.getByText("Presented Report")).toBeVisible();

    const artifactSelect = artifactsPanel.getByRole("combobox");
    await artifactSelect.click();
    await page.getByRole("option", { name: "report.md", exact: true }).click();
    await expect(artifactsPanel.getByText("Thread Report")).toBeVisible();

    await artifactSelect.click();
    const presentedOption = page.getByRole("option", {
      name: "presented-report.md",
    });
    await expect(presentedOption).toBeVisible();
    await presentedOption.click();
    await expect(artifactsPanel.getByText("Presented Report")).toBeVisible();
  });

  test("restores the artifact panel and selected file after a page refresh", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: PERSISTED_PANEL_THREAD_ID,
          title: "Persisted artifact panel",
          messages: presentFilesMessages(),
          artifacts: [MARKDOWN_ARTIFACT_PATH],
        },
      ],
    });
    await page.route(
      `**/api/threads/${PERSISTED_PANEL_THREAD_ID}/artifacts/mnt/user-data/outputs/presented-report.md`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/markdown",
          body: "# Presented Report\n\nGenerated content",
        }),
    );

    await page.goto(`/workspace/chats/${PERSISTED_PANEL_THREAD_ID}`);
    await expect(page.getByText("presented-report.md")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("presented-report.md").first().click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("Presented Report")).toBeVisible();

    await page.reload();

    await expect(page.getByTestId("artifact-trigger")).toBeVisible();
    await expect(
      page.locator("#artifacts").getByText("Presented Report"),
    ).toBeVisible();
  });

  test("renders a PDF in an unsandboxed iframe so Chromium's viewer can display it (urlOfArtifact path)", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: PDF_THREAD_ID,
          title: "PDF artifact preview",
          messages: writeFileMessages({
            path: PDF_ARTIFACT_PATH,
            content: "%PDF-fake-content",
          }),
        },
      ],
    });
    await page.route(
      `**/api/threads/${PDF_THREAD_ID}/artifacts${PDF_ARTIFACT_PATH}`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/pdf",
          body: "%PDF-1.4 fake pdf",
        }),
    );

    await page.goto(`/workspace/chats/${PDF_THREAD_ID}`);

    await expect(page.getByText(PDF_ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText(PDF_ARTIFACT_PATH).click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("report.pdf")).toBeVisible();

    // Chromium blocks its built-in PDF viewer inside a sandbox="" iframe, so
    // PDFs render unsandboxed; the endpoint declares application/pdf and the
    // Gateway adds X-Content-Type-Options: nosniff, so the response cannot be
    // reinterpreted as active markup. Non-PDF previewable binaries (images,
    // audio, video) keep the sandbox.
    const urlOfArtifactIframe = artifactsPanel.locator(
      'iframe[title="report.pdf"]',
    );
    await expect(urlOfArtifactIframe).toBeVisible();
    await expect(urlOfArtifactIframe).not.toHaveAttribute("sandbox", "");
  });
});
