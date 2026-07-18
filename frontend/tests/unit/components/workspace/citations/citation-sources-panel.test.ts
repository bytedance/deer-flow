import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CitationSourcesPanel } from "@/components/workspace/citations/citation-sources-panel";
import type { CitationSource } from "@/core/citations/sources";
import { I18nContext } from "@/core/i18n/context";

const sources: CitationSource[] = [
  {
    id: "https://example.com/a",
    title: "Paper A",
    url: "https://example.com/a",
    domain: "example.com",
    count: 2,
    occurrences: [
      { index: 10, title: "Paper A" },
      { index: 90, title: "Paper A" },
    ],
  },
  {
    id: "https://news.example.org/report",
    title: "Report B",
    url: "https://news.example.org/report",
    domain: "news.example.org",
    count: 1,
    occurrences: [{ index: 120, title: "Report B" }],
  },
];

describe("CitationSourcesPanel", () => {
  it("renders nothing when there are no sources", () => {
    expect(renderPanel([], "en-US")).toBe("");
  });

  it("renders a compact source list with occurrence counts", () => {
    const html = renderPanel(sources, "en-US");

    expect(html).toContain("Used 2 sources");
    expect(html).toContain("Paper A");
    expect(html).toContain("example.com");
    expect(html).toContain("2 cites");
    expect(html).toContain("Report B");
    expect(html).toContain("news.example.org");
    expect(html).toContain('href="https://news.example.org/report"');
  });

  it("constrains long source lists inside an internal scroll area", () => {
    const html = renderPanel(sources, "en-US");

    expect(html).toContain("max-h-80");
    expect(html).toContain("overflow-y-auto");
    expect(html).toContain("overscroll-contain");
  });

  it("uses localized summary and cite labels", () => {
    const html = renderPanel(sources, "zh-CN");

    expect(html).toContain("使用了 2 个来源");
    expect(html).toContain("2 次引用");
    expect(html).toContain("复制 Paper A 引用");
  });

  it("renders accessible copied-state labels for copy feedback", () => {
    const html = renderPanel(sources, "en-US");

    expect(html).toContain("Copy Paper A reference");
    expect(html).toContain('data-copied-label="Copied Paper A reference"');
  });
});

function renderPanel(
  panelSources: CitationSource[],
  initialLocale: "en-US" | "zh-CN",
) {
  return renderToStaticMarkup(
    createElement(
      I18nContext.Provider,
      {
        value: {
          locale: initialLocale,
          setLocale: () => undefined,
        },
      },
      createElement(CitationSourcesPanel, { sources: panelSources }),
    ),
  );
}
