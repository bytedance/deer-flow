import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ArtifactLink } from "@/components/workspace/citations/artifact-link";

// Render-level coverage for the .md artifact preview link renderer: a
// prompt-injected javascript:/data: href must never reach a real anchor in
// the main document (mirrors the MarkdownLink guard).
describe("ArtifactLink rendering", () => {
  it("renders an unsafe href as a disabled span, never an anchor", () => {
    const html = renderToStaticMarkup(
      createElement(ArtifactLink, { href: "javascript:alert(1)" }, "click me"),
    );
    expect(html).not.toContain("<a");
    expect(html).toContain("<span");
    expect(html).toContain("click me");
    expect(html).not.toContain("href=");
  });

  it("renders a safe https href as a hardened anchor", () => {
    const html = renderToStaticMarkup(
      createElement(ArtifactLink, { href: "https://example.com/x" }, "site"),
    );
    expect(html).toContain("<a");
    expect(html).toContain('href="https://example.com/x"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("renders scheme-less relative hrefs as navigable anchors", () => {
    const tests = ["report.md", "./report.md", "../assets/chart.png"];
    for (const href of tests) {
      const html = renderToStaticMarkup(
        createElement(ArtifactLink, { href }, "doc"),
      );
      expect(html).toContain("<a");
      expect(html).toContain(`href="${href}"`);
    }
  });
});
