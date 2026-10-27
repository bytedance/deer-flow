import { expect, rs, test } from "@rstest/core";

import {
  appendHtmlPreviewBaseHref,
  appendHtmlPreviewScrollRestoration,
} from "@/core/artifacts/preview";

const ARTIFACT_URL = "/api/threads/thread-1/artifacts/report/index.html";
const CURRENT_HREF = "https://deerflow.example/workspace/chats/thread-1";
const BASE_ELEMENT =
  '<base href="https://deerflow.example/api/threads/thread-1/artifacts/report/">';

// Textarea/title RCDATA is checked in a real browser: happy-dom misparses it here.
test("skips DOM construction when HTML contains no base text", () => {
  const html = `<!doctype html><html><head></head><body>${"<p>Report</p>".repeat(1024)}<img src="chart.png"></body></html>`;
  const createElement = rs.spyOn(document, "createElement");

  try {
    expect(appendHtmlPreviewBaseHref(html, ARTIFACT_URL, CURRENT_HREF)).toBe(
      html.replace("<head>", `<head>${BASE_ELEMENT}`),
    );
    expect(createElement).not.toHaveBeenCalled();
  } finally {
    createElement.mockRestore();
  }
});

test.each([
  ["comment", '<!-- <base href="/"> is disabled -->'],
  [
    "JSON script",
    '<script type="application/json">{"example":"<base href=\\"/\\">"}</script>',
  ],
  ["template", '<template><base href="/"></template>'],
])("ignores base-tag text in a %s", (_name, literal) => {
  const html = `<!doctype html><html><head>${literal}</head><body><img src="chart.png"></body></html>`;

  expect(appendHtmlPreviewBaseHref(html, ARTIFACT_URL, CURRENT_HREF)).toBe(
    html.replace("<head>", `<head>${BASE_ELEMENT}`),
  );
});

test("ignores a commented base in a fragment", () => {
  const html = '<!-- <base href="/"> --><img src="chart.png">';

  expect(appendHtmlPreviewBaseHref(html, ARTIFACT_URL, CURRENT_HREF)).toBe(
    `${BASE_ELEMENT}${html}`,
  );
});

test("preserves a real base element and the original HTML", () => {
  const html =
    '<!doctype html><html><head><BASE HREF="https://assets.example/"></head><body><img src="chart.png"></body></html>';

  expect(appendHtmlPreviewBaseHref(html, ARTIFACT_URL, CURRENT_HREF)).toBe(
    html,
  );
});

test("leaves HTML unchanged without an artifact URL", () => {
  const html = '<!-- <base href="/"> --><img src="chart.png">';

  expect(appendHtmlPreviewBaseHref(html)).toBe(html);
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
    "/artifact-fixtures/report.html",
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

test("does not mistake <header> for <head> when injecting the base href", () => {
  // Agent-generated fragments often have no <head> but open with <header>;
  // the base must then be prepended so assets before the tag resolve too.
  const html =
    '<img src="logo.png"><header class="top">Report</header><main>content</main>';

  const result = appendHtmlPreviewBaseHref(
    html,
    "/demo/threads/thread-1/user-data/outputs/report.html",
    "http://localhost/workspace/chats/thread-1",
  );

  expect(result).toBe(
    '<base href="http://localhost/demo/threads/thread-1/user-data/outputs/">' +
      html,
  );
});

test("injects the base href inside an attributed <head> tag", () => {
  const html =
    '<!doctype html><html><head lang="en"><meta charset="utf-8"></head><body>x</body></html>';

  const result = appendHtmlPreviewBaseHref(
    html,
    "/demo/threads/thread-1/user-data/outputs/report.html",
    "http://localhost/workspace/chats/thread-1",
  );

  expect(result).toContain(
    '<head lang="en"><base href="http://localhost/demo/threads/thread-1/user-data/outputs/">',
  );
});
