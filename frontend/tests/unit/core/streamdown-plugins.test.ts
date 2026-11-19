import { expect, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { artifactMarkdownPlugins } from "@/components/workspace/artifacts/markdown-preview-plugins";
import { ArtifactLink } from "@/components/workspace/citations/artifact-link";
import { createMarkdownLinkComponent } from "@/components/workspace/messages/markdown-link";
import {
  SafeStreamdown,
  streamdownPlugins,
  toStreamdownComponents,
} from "@/core/streamdown";

function renderArtifactMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(
      SafeStreamdown,
      {
        ...artifactMarkdownPlugins,
        components: toStreamdownComponents({ a: ArtifactLink }),
      },
      content,
    ),
  );
}

function renderSharedMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(SafeStreamdown, streamdownPlugins, content),
  );
}

// Mirrors the memory settings page: shared preset plus the safe link
// component it passes for stored/LLM-generated summary content.
function renderMemorySummaryMarkdown(content: string) {
  return renderToStaticMarkup(
    createElement(
      SafeStreamdown,
      {
        ...streamdownPlugins,
        components: toStreamdownComponents({
          a: createMarkdownLinkComponent(),
        }),
      },
      content,
    ),
  );
}

test("adds GitHub-style heading anchors to artifact markdown previews", () => {
  const html = renderArtifactMarkdown(
    ["[概述](#概述)", "", "## 概述"].join("\n"),
  );

  // Anchors keep sanitize's user-content- clobber prefix; fragment links
  // are translated to the prefixed id so they still resolve.
  expect(html).toContain('href="#user-content-%E6%A6%82%E8%BF%B0"');
  expect(html).toContain('id="user-content-概述"');
  expect(html).not.toContain('id="概述"');
  expect(html).not.toContain("target=");
});

test("scoped heading anchors cannot mint clobberable ids", () => {
  const html = renderArtifactMarkdown(
    ["## current", "", "[go](#current)", "", "## forms"].join("\n"),
  );

  // `id="current"` on a heading is the DOM-clobbering shape rehype-sanitize
  // guards against; the scoped slug must keep the user-content- prefix.
  expect(html).toContain('id="user-content-current"');
  expect(html).not.toContain('id="current"');
  // In-page fragment links are translated to the prefixed anchors.
  expect(html).toContain('href="#user-content-current"');
  expect(html).not.toContain('href="#current"');
});

test("identical artifact markdown renders stable anchors across renders", () => {
  // Streamdown caches the unified processor by plugin name, so the scoped
  // slug's slugger survives across parses — it must reset per tree or the
  // second render of the same heading gets a -1 suffix that keeps growing.
  const content = ["## Stable heading", "", "## Stable heading"].join("\n");
  const first = renderArtifactMarkdown(content);
  const second = renderArtifactMarkdown(content);

  // Streamdown parses blocks separately, so both headings get the base
  // slug; the guard is that repeated RENDERS never grow -1/-2 suffixes.
  expect(first).toContain('id="user-content-stable-heading"');
  expect(second).toContain('id="user-content-stable-heading"');
  expect(first).not.toContain("user-content-stable-heading-1");
  expect(second).not.toContain("user-content-stable-heading-1");
  expect(second).not.toContain("user-content-stable-heading-2");
});

test("footnote references survive the sanitize clobber prefix", () => {
  // remark-rehype emits footnote anchors pre-prefixed (user-content-fn-1);
  // sanitize would double-prefix the ids while leaving hrefs single-prefixed.
  // rehypeClobberFragments normalizes ids back to one prefix and translates
  // unprefixed fragment hrefs, so forward and back references keep resolving.
  const html = renderSharedMarkdown(
    [
      "Body with a note[^1] and a second[^2].",
      "",
      "[^1]: First note.",
      "[^2]: Second note.",
    ].join("\n"),
  );

  // Streamdown renders footnote refs/backrefs as its link component
  // (buttons), so the DOM contract is the id side: single clobber prefix on
  // the footnote/list ids, never double, matching the reference hrefs the
  // link component receives (#user-content-fn-1 before React mapping).
  expect(html).not.toContain("user-content-user-content-");
  expect(html).toContain('id="user-content-fn-1"');
  expect(html).toContain('id="user-content-fn-2"');
  expect(html).toContain('id="user-content-footnote-label"');
});

test("does not add heading anchors to the shared streamdown plugin config", () => {
  const html = [
    renderSharedMarkdown("## Summary"),
    renderSharedMarkdown("## Summary"),
  ].join("");

  expect(html).not.toContain('id="summary"');
});

// Stored-XSS payload: hostile markdown that must not degrade into an
// executable/clickable DOM in any render path. Streamdown@2.5 replaces its
// default [rehype-raw, rehype-sanitize, rehype-harden] chain with whatever
// rehypePlugins the caller passes, so the custom chains under test must
// carry their own sanitize step (core/streamdown/plugins.ts).
const XSS_PAYLOAD = [
  '<a href="javascript:alert(1)">click-me</a>',
  '<img src="x" onerror="alert(2)" />',
  "<script>alert(3)</script>",
  '<iframe src="https://evil.example"></iframe>',
  '<details style="position:fixed" ontoggle="alert(4)">',
  "  <summary>spoofed</summary>body",
  "</details>",
  "<style>body { background: red }</style>",
].join("\n");

test("sanitizes hostile HTML in artifact markdown previews", () => {
  const html = renderArtifactMarkdown(XSS_PAYLOAD);

  // No executable or clickable equivalents survive.
  expect(html).not.toContain("javascript:");
  expect(html).not.toContain("onerror");
  expect(html).not.toContain("ontoggle");
  expect(html).not.toContain("<script");
  expect(html).not.toContain("<iframe");
  expect(html).not.toContain("<style");
  // `script` is stripped with its children; iframe/style are unwrapped.
  expect(html).not.toContain("alert(3)");
  // CSS injection for UI spoofing is dropped (attribute and tag).
  expect(html).not.toContain("position:fixed");
  // Legitimate authored HTML and the visible link label survive.
  expect(html).toContain("<details");
  expect(html).toContain("<summary");
  expect(html).toContain("click-me");
});

test("sanitizes hostile HTML in memory summary markdown", () => {
  const html = renderMemorySummaryMarkdown(XSS_PAYLOAD);

  expect(html).not.toContain("javascript:");
  expect(html).not.toContain("onerror");
  expect(html).not.toContain("ontoggle");
  expect(html).not.toContain("<script");
  expect(html).not.toContain("<iframe");
  expect(html).not.toContain("<style");
  expect(html).not.toContain("alert(3)");
  expect(html).not.toContain("position:fixed");
  // The link label stays visible but never becomes a javascript: anchor
  // (streamdown's image component legitimately emits href="x" preloads).
  expect(html).toContain("click-me");
  expect(html).not.toContain('href="javascript');
});

test("sanitize step preserves legitimate artifact HTML", () => {
  const html = renderArtifactMarkdown(
    [
      '<div align="center">centered</div>',
      "",
      "<table><thead><tr><th>H1</th></tr></thead><tbody><tr><td>D1</td></tr></tbody></table>",
      "",
      '<img src="https://example.com/chart.png" alt="chart" width="100" />',
    ].join("\n"),
  );

  expect(html).toContain('align="center"');
  expect(html).toContain("<table");
  expect(html).toContain("<th");
  expect(html).toContain("<td");
  expect(html).toContain('src="https://example.com/chart.png"');
  expect(html).toContain('width="100"');
});

test("sanitize step does not break KaTeX math rendering", () => {
  const html = renderArtifactMarkdown(
    ["Inline $x^2$ math", "", "$$", "E=mc^2", "$$"].join("\n"),
  );

  // rehype-katex runs after the sanitize step; its output must still be
  // produced (both inline and display math markers survive sanitization).
  expect(html.match(/class="katex"/g)?.length).toBeGreaterThanOrEqual(2);
});
