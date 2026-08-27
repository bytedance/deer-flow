import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Thread endpoints the workspace shell polls that `mockLangGraphAPI` does not
 * cover. Left unmocked they reach a real Gateway when one happens to be
 * running locally, and its 401 bounces the page to /login before the artifact
 * panel ever opens. Answer with the same 5xx a missing backend produces, which
 * these panels already tolerate.
 */
async function stubUnmockedThreadEndpoints(page: Page, threadId: string) {
  for (const suffix of ["token-usage", "mcp-tasks**"]) {
    await page.route(`**/api/threads/${threadId}/${suffix}`, (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: "{}",
      }),
    );
  }
}

const MARKDOWN_ARTIFACT_PATH = "/mnt/user-data/outputs/presented-report.md";
const HTML_ARTIFACT_PATH = "/mnt/user-data/outputs/presented-report.html";
const MARKDOWN_THREAD_ID = "00000000-0000-0000-0000-000000003130";
const HTML_THREAD_ID = "00000000-0000-0000-0000-000000003131";
const EXPIRED_THREAD_ID = "00000000-0000-0000-0000-000000003132";
const ARTIFACT_VIEWER_PATH = "/artifacts/view";

function presentFilesMessages(path: string) {
  return [
    {
      type: "human",
      id: "msg-human-present-file",
      content: [{ type: "text", text: "Create a report" }],
    },
    {
      type: "ai",
      id: "msg-ai-present-file",
      content: "The report has been written. Now let me present the file.",
      tool_calls: [
        {
          id: "present-file-artifact",
          name: "present_files",
          args: { filepaths: [path] },
        },
      ],
    },
  ];
}

test.describe("Artifact viewer window", () => {
  test("renders a markdown artifact instead of its source in the new window", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MARKDOWN_THREAD_ID,
          title: "Markdown artifact viewer window",
          messages: presentFilesMessages(MARKDOWN_ARTIFACT_PATH),
          artifacts: [MARKDOWN_ARTIFACT_PATH],
        },
      ],
    });
    await stubUnmockedThreadEndpoints(page, MARKDOWN_THREAD_ID);
    // Registered on the context, not the page: the detached viewer window
    // fetches the same artifact and page routes do not reach it.
    await page
      .context()
      .route(
        `**/api/threads/${MARKDOWN_THREAD_ID}/artifacts/mnt/user-data/outputs/presented-report.md`,
        (route) =>
          route.fulfill({
            status: 200,
            contentType: "text/markdown",
            body: "# Quarterly Report\n\n测试内容 1\n",
          }),
      );

    await page.goto(`/workspace/chats/${MARKDOWN_THREAD_ID}`);
    await expect(page.getByText("presented-report.md")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("presented-report.md").first().click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("Quarterly Report")).toBeVisible();

    const viewerPromise = page.context().waitForEvent("page");
    await artifactsPanel
      .getByRole("button", { name: "Open in new window" })
      .click();
    const viewer = await viewerPromise;
    await viewer.waitForLoadState("domcontentloaded");

    await expect
      .poll(() => new URL(viewer.url()).pathname)
      .toBe("/artifacts/view");
    const params = new URL(viewer.url()).searchParams;
    expect(params.get("path")).toBe(MARKDOWN_ARTIFACT_PATH);
    expect(params.get("thread_id")).toBe(MARKDOWN_THREAD_ID);

    await expect(
      viewer.getByRole("heading", { name: "Quarterly Report" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(viewer.getByText("测试内容 1")).toBeVisible();
    // The raw markdown source must not be what the window shows.
    await expect(viewer.getByText("# Quarterly Report")).toHaveCount(0);
    await expect(viewer).toHaveTitle(/presented-report\.md/);

    await viewer.close();
  });

  test("keeps html artifacts on the gateway URL so they stay downloads", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: HTML_THREAD_ID,
          title: "Html artifact viewer window",
          messages: presentFilesMessages(HTML_ARTIFACT_PATH),
          artifacts: [HTML_ARTIFACT_PATH],
        },
      ],
    });
    await stubUnmockedThreadEndpoints(page, HTML_THREAD_ID);
    await page
      .context()
      .route(
        `**/api/threads/${HTML_THREAD_ID}/artifacts/mnt/user-data/outputs/presented-report.html`,
        (route) =>
          route.fulfill({
            status: 200,
            contentType: "text/html",
            body: "<!doctype html><html><body><h1>Report draft</h1></body></html>",
          }),
      );

    await page.goto(`/workspace/chats/${HTML_THREAD_ID}`);
    await expect(page.getByText("presented-report.html")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("presented-report.html").first().click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(
      artifactsPanel.locator('iframe[title="Artifact preview"]'),
    ).toBeVisible();

    const openedPromise = page.context().waitForEvent("page");
    await artifactsPanel
      .getByRole("button", { name: "Open in new window" })
      .click();
    const opened = await openedPromise;

    await expect
      .poll(() => new URL(opened.url()).pathname)
      .toBe(
        `/api/threads/${HTML_THREAD_ID}/artifacts/mnt/user-data/outputs/presented-report.html`,
      );

    await opened.close();
  });

  test("returns to the same artifact after an expired session", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: EXPIRED_THREAD_ID,
          title: "Expired session viewer window",
          messages: presentFilesMessages(MARKDOWN_ARTIFACT_PATH),
          artifacts: [MARKDOWN_ARTIFACT_PATH],
        },
      ],
    });
    await stubUnmockedThreadEndpoints(page, EXPIRED_THREAD_ID);
    // The session is valid for the panel and lapsed for the detached window,
    // keyed off the requesting frame so the panel's own refetches cannot race
    // for the 401.
    await page
      .context()
      .route(
        `**/api/threads/${EXPIRED_THREAD_ID}/artifacts/mnt/user-data/outputs/presented-report.md`,
        (route) =>
          route.request().frame().url().includes(ARTIFACT_VIEWER_PATH)
            ? route.fulfill({
                status: 401,
                contentType: "application/json",
                body: JSON.stringify({ detail: "Not authenticated" }),
              })
            : route.fulfill({
                status: 200,
                contentType: "text/markdown; charset=utf-8",
                body: "# Quarterly Report\n",
              }),
      );

    // Record the popup's navigation *requests*, not its committed URLs. This
    // harness runs with DEER_FLOW_AUTH_DISABLED, so `(auth)/layout` treats the
    // window as signed in and answers /login with a server redirect that never
    // commits — the request is the only place the redirect target is visible.
    const navigated: string[] = [];
    page.context().on("page", (opened) => {
      opened.on("request", (request) => {
        if (request.isNavigationRequest()) {
          navigated.push(request.url());
        }
      });
    });

    await page.goto(`/workspace/chats/${EXPIRED_THREAD_ID}`);
    await expect(page.getByText("presented-report.md")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("presented-report.md").first().click();

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel.getByText("Quarterly Report")).toBeVisible();

    const viewerPromise = page.context().waitForEvent("page");
    await artifactsPanel
      .getByRole("button", { name: "Open in new window" })
      .click();
    const viewer = await viewerPromise;

    // `about:blank` can appear here and `new URL` throws on an empty string,
    // so parse defensively — otherwise the poll predicate errors out instead
    // of retrying.
    const findLogin = () =>
      navigated.find((url) => {
        try {
          return new URL(url).pathname === "/login";
        } catch {
          return false;
        }
      });

    await expect.poll(findLogin, { timeout: 15_000 }).toBeDefined();

    const loginUrl = new URL(findLogin()!);
    const next = loginUrl.searchParams.get("next");
    expect(next).not.toBe(null);
    // The whole viewer address travels through login — query string included —
    // so the user comes back to this artifact, not the default workspace.
    const returned = new URL(next!, loginUrl.origin);
    expect(returned.pathname).toBe(ARTIFACT_VIEWER_PATH);
    expect(returned.searchParams.get("path")).toBe(MARKDOWN_ARTIFACT_PATH);
    expect(returned.searchParams.get("thread_id")).toBe(EXPIRED_THREAD_ID);

    await viewer.close();
  });
});
