import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CitationLink } from "@/components/workspace/citations/citation-link";

describe("CitationLink rendering", () => {
  it("strips the citation prefix from React element arrays", () => {
    const html = renderToStaticMarkup(
      createElement(
        CitationLink,
        { href: "https://example.com/report" },
        createElement("span", { key: "prefix" }, "citation:"),
        createElement("span", { key: "title" }, "Test Source"),
      ),
    );

    expect(html).not.toContain("citation:");
    expect(html).toContain("Test Source");
  });
});
