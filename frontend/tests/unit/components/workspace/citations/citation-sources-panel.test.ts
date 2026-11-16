import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CitationSourcesPanel } from "@/components/workspace/citations/citation-sources-panel";
import type { CitationSource } from "@/core/citations/sources";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

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
  it("renders knowledge evidence without inventing external navigation", () => {
    const id = "a".repeat(32);
    const evidenceSource: CitationSource = {
      id: `#knowledge-source-${id}`,
      title: "Guide",
      url: `#knowledge-source-${id}`,
      domain: "lightrag",
      count: 1,
      occurrences: [{ index: 0, title: "Guide" }],
      knowledge: {
        id,
        provider: "lightrag",
        title: "Guide",
        excerpt: "Actual retrieved text.",
        page: 3,
      },
    };
    const html = renderPanel([evidenceSource], "en-US");
    expect(html).toContain("Actual retrieved text.");
    expect(html).toContain("lightrag");
    expect(html).not.toContain("href=");
    expect(html).not.toContain("p. 1");
    expect(html).toContain("Pages 3");
    expect(renderPanel([evidenceSource], "zh-CN")).toContain("第 3 页");
  });
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
          t: initialLocale === "zh-CN" ? zhCN : enUS,
        },
      },
      createElement(CitationSourcesPanel, { sources: panelSources }),
    ),
  );
}
