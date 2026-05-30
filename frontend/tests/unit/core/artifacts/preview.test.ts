import { expect, test } from "vitest";

import {
  appendHtmlPreviewBaseHref,
  appendHtmlPreviewScrollRestoration,
  buildWriteFileDraftContent,
  createHtmlPreviewScrollKey,
  getArtifactViewState,
} from "@/core/artifacts/preview";

const ARTIFACT_PATH = "/artifact-fixtures/report.html";
const UNSUPPORTED_ARTIFACT_PATH = "/artifact-fixtures/data.csv";

test("allows in-progress write artifacts to render a throttled preview", () => {
  expect(
    getArtifactViewState({
      filepath: `write-file:${ARTIFACT_PATH}?message_id=ai-1&tool_call_id=call-1`,
      isSupportPreview: true,
    }),
  ).toEqual({
    canPreview: true,
    initialViewMode: "preview",
  });
});

test("allows preview for a write artifact once the tool call has a result", () => {
  expect(
    getArtifactViewState({
      filepath: `write-file:${ARTIFACT_PATH}?message_id=ai-1&tool_call_id=call-1`,
      isSupportPreview: true,
      toolResult: "OK",
    }),
  ).toEqual({
    canPreview: true,
    initialViewMode: "preview",
  });
});

test("keeps failed write artifacts in code view", () => {
  expect(
    getArtifactViewState({
      filepath: `write-file:${ARTIFACT_PATH}?message_id=ai-1&tool_call_id=call-1`,
      isSupportPreview: true,
      toolResult: "Error: Failed to write file",
    }),
  ).toEqual({
    canPreview: false,
    initialViewMode: "code",
  });
});

test("keeps completed artifacts on their existing preview defaults", () => {
  expect(
    getArtifactViewState({
      filepath: ARTIFACT_PATH,
      isSupportPreview: true,
    }),
  ).toEqual({
    canPreview: true,
    initialViewMode: "preview",
  });
});

test("keeps unsupported artifacts in code view", () => {
  expect(
    getArtifactViewState({
      filepath: UNSUPPORTED_ARTIFACT_PATH,
      isSupportPreview: false,
    }),
  ).toEqual({
    canPreview: false,
    initialViewMode: "code",
  });
});

test("builds a draft write-file artifact from successful writes plus the selected in-progress append", () => {
  const filepath = `write-file:${ARTIFACT_PATH}?message_id=ai-2&tool_call_id=call-2`;

  expect(
    buildWriteFileDraftContent({
      filepath,
      messages: [
        {
          type: "ai",
          id: "ai-1",
          tool_calls: [
            {
              id: "call-1",
              name: "write_file",
              args: {
                path: ARTIFACT_PATH,
                content: "<!doctype html><html><body>",
              },
            },
          ],
        },
        {
          type: "tool",
          id: "tool-1",
          name: "write_file",
          tool_call_id: "call-1",
          content: "OK",
        },
        {
          type: "ai",
          id: "ai-2",
          tool_calls: [
            {
              id: "call-2",
              name: "write_file",
              args: {
                append: true,
                path: ARTIFACT_PATH,
                content: "<p>追加内容</p>",
              },
            },
          ],
        },
      ],
    }),
  ).toBe("<!doctype html><html><body><p>追加内容</p>");
});

test("does not include failed writes in a draft artifact", () => {
  const filepath = `write-file:${ARTIFACT_PATH}?message_id=ai-3&tool_call_id=call-3`;

  expect(
    buildWriteFileDraftContent({
      filepath,
      messages: [
        {
          type: "ai",
          id: "ai-1",
          tool_calls: [
            {
              id: "call-1",
              name: "write_file",
              args: {
                path: ARTIFACT_PATH,
                content: "<html>",
              },
            },
          ],
        },
        {
          type: "tool",
          id: "tool-1",
          name: "write_file",
          tool_call_id: "call-1",
          content: "OK",
        },
        {
          type: "ai",
          id: "ai-2",
          tool_calls: [
            {
              id: "call-2",
              name: "write_file",
              args: {
                append: true,
                path: ARTIFACT_PATH,
                content: "<p>失败内容</p>",
              },
            },
          ],
        },
        {
          type: "tool",
          id: "tool-2",
          name: "write_file",
          tool_call_id: "call-2",
          content: "Error: write failed",
        },
        {
          type: "ai",
          id: "ai-3",
          tool_calls: [
            {
              id: "call-3",
              name: "write_file",
              args: {
                append: true,
                path: ARTIFACT_PATH,
                content: "</html>",
              },
            },
          ],
        },
      ],
    }),
  ).toBe("<html></html>");
});

test("returns undefined when the selected append failed so the caller can fall back", () => {
  const filepath = `write-file:${ARTIFACT_PATH}?message_id=ai-2&tool_call_id=call-2`;

  expect(
    buildWriteFileDraftContent({
      filepath,
      messages: [
        {
          type: "ai",
          id: "ai-1",
          tool_calls: [
            {
              id: "call-1",
              name: "write_file",
              args: {
                path: ARTIFACT_PATH,
                content: "<html>",
              },
            },
          ],
        },
        {
          type: "tool",
          id: "tool-1",
          name: "write_file",
          tool_call_id: "call-1",
          content: "OK",
        },
        {
          type: "ai",
          id: "ai-2",
          tool_calls: [
            {
              id: "call-2",
              name: "write_file",
              args: {
                append: true,
                path: ARTIFACT_PATH,
                content: "<p>失败的追加内容</p>",
              },
            },
          ],
        },
        {
          type: "tool",
          id: "tool-2",
          name: "write_file",
          tool_call_id: "call-2",
          content: "Error: write failed",
        },
      ],
    }),
  ).toBeUndefined();
});

test("injects scroll restoration at the start of the HTML head", () => {
  const html =
    '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="script-src \'none\'"></head><body><main>content</main></body></html>';

  expect(appendHtmlPreviewScrollRestoration(html, ARTIFACT_PATH)).toContain(
    "<script data-deerflow-artifact-scroll-restoration>",
  );
  expect(appendHtmlPreviewScrollRestoration(html, ARTIFACT_PATH)).toContain(
    "<head><script data-deerflow-artifact-scroll-restoration>",
  );
});

test("preserves existing head elements when injecting scroll restoration", () => {
  const html =
    '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="script-src \'none\'"></head><body><main>content</main></body></html>';
  const result = appendHtmlPreviewScrollRestoration(
    appendHtmlPreviewBaseHref(
      html,
      "/demo/threads/thread-1/user-data/outputs/report.html?download=true",
      "http://localhost/workspace/chats/thread-1",
    ),
    ARTIFACT_PATH,
  );

  expect(result).toContain(
    '<base href="http://localhost/demo/threads/thread-1/user-data/outputs/">',
  );
  expect(
    result.indexOf("data-deerflow-artifact-scroll-restoration"),
  ).toBeLessThan(
    result.indexOf(
      '<base href="http://localhost/demo/threads/thread-1/user-data/outputs/">',
    ),
  );
});

test("does not duplicate HTML scroll restoration script", () => {
  const html = appendHtmlPreviewScrollRestoration(
    "<html><body>x</body></html>",
  );

  expect(
    appendHtmlPreviewScrollRestoration(html).match(
      /data-deerflow-artifact-scroll-restoration/g,
    ),
  ).toHaveLength(1);
});

test("scopes HTML scroll restoration without exposing the artifact path", () => {
  const artifactPath =
    '/artifact-fixtures/a</script><script>alert("x")</script>.html';
  const html = appendHtmlPreviewScrollRestoration(
    "<html><body>x</body></html>",
    artifactPath,
  );

  expect(html).toContain(createHtmlPreviewScrollKey(artifactPath));
  expect(html).toContain("window.parent.postMessage");
  expect(html).not.toContain("window.name");
  expect(html).not.toContain("/artifact-fixtures/a");
  expect(html).not.toContain("<script>alert");
});
