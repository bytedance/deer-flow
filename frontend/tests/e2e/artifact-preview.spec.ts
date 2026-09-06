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

  test("renders sandboxed iframe for a browser-previewable non-code file (urlOfArtifact path)", async ({
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

    const urlOfArtifactIframe = artifactsPanel.locator("iframe:not([title])");
    await expect(urlOfArtifactIframe).toBeVisible();
    await expect(urlOfArtifactIframe).toHaveAttribute("sandbox", "");
  });
});
