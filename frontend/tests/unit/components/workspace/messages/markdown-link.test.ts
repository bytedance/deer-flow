import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  createMarkdownLinkComponent,
  isSafeHref,
} from "@/components/workspace/messages/markdown-link";

describe("isSafeHref", () => {
  it("allows web URLs and same-origin paths", () => {
    expect(isSafeHref("https://example.com/path")).toBe(true);
    expect(isSafeHref("http://example.com/path")).toBe(true);
    expect(isSafeHref("/workspace/chats/1")).toBe(true);
    expect(isSafeHref("#section")).toBe(true);
  });

  it("allows scheme-less relative references", () => {
    expect(isSafeHref("report.md")).toBe(true);
    expect(isSafeHref("./report.md")).toBe(true);
    expect(isSafeHref("../assets/chart.png")).toBe(true);
  });

  it("allows non-executing contact schemes", () => {
    expect(isSafeHref("mailto:someone@example.com")).toBe(true);
    expect(isSafeHref("tel:+15551234567")).toBe(true);
  });

  it("rejects executable, local, and protocol-relative URLs", () => {
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
    expect(isSafeHref("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(isSafeHref("file:///etc/passwd")).toBe(false);
    expect(isSafeHref("//example.com/path")).toBe(false);
    expect(isSafeHref("\\\\evil.com")).toBe(false);
    expect(isSafeHref(undefined)).toBe(false);
  });
});

// Render-level coverage: these tests exercise the component itself, so
// removing (or inverting) the isSafeHref guard inside MarkdownLink fails
// them even though isSafeHref stays untouched.
describe("MarkdownLink rendering", () => {
  const MarkdownLink = createMarkdownLinkComponent();

  it("renders an unsafe href as a disabled span, never an anchor", () => {
    const html = renderToStaticMarkup(
      createElement(MarkdownLink, { href: "javascript:alert(1)" }, "click me"),
    );
    expect(html).not.toContain("<a");
    expect(html).toContain("<span");
    expect(html).toContain("click me");
    expect(html).not.toContain("href=");
  });

  it("blocks unsafe hrefs before the citation branch", () => {
    const html = renderToStaticMarkup(
      createElement(
        MarkdownLink,
        { href: "javascript:alert(1)" },
        "citation:evil",
      ),
    );
    expect(html).not.toContain("<a");
    expect(html).not.toContain("href=");
  });

  it("renders a safe https href as a hardened anchor", () => {
    const html = renderToStaticMarkup(
      createElement(
        MarkdownLink,
        { href: "https://example.com/report" },
        "report",
      ),
    );
    expect(html).toContain("<a");
    expect(html).toContain('href="https://example.com/report"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("renders a scheme-less relative href as a navigable anchor", () => {
    const tests = ["report.md", "./report.md", "../assets/chart.png"];
    for (const href of tests) {
      const html = renderToStaticMarkup(
        createElement(MarkdownLink, { href }, "doc"),
      );
      expect(html).toContain("<a");
      expect(html).toContain(`href="${href}"`);
    }
  });
});
