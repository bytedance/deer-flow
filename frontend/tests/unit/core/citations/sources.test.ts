import { describe, expect, it } from "@rstest/core";

import {
  extractCitationSources,
  formatCitationMarkdownReference,
} from "@/core/citations/sources";

describe("extractCitationSources", () => {
  it("extracts citation markdown links in first-seen order", () => {
    const markdown = [
      "Deep research needs evidence [citation:Paper A](https://example.com/a).",
      "A second claim cites [citation:Report B](https://news.example.org/report?x=1).",
    ].join("\n");
    const firstIndex = markdown.indexOf("[citation:Paper A]");
    const secondIndex = markdown.indexOf("[citation:Report B]");

    expect(extractCitationSources(markdown)).toEqual([
      {
        id: "https://example.com/a",
        title: "Paper A",
        url: "https://example.com/a",
        domain: "example.com",
        count: 1,
        occurrences: [{ index: firstIndex, title: "Paper A" }],
      },
      {
        id: "https://news.example.org/report?x=1",
        title: "Report B",
        url: "https://news.example.org/report?x=1",
        domain: "news.example.org",
        count: 1,
        occurrences: [{ index: secondIndex, title: "Report B" }],
      },
    ]);
  });

  it("deduplicates repeated citation URLs and preserves occurrence titles", () => {
    const markdown = [
      "First [citation:Original Title](https://example.com/research).",
      "Later [citation:Updated Title](https://example.com/research).",
    ].join("\n");
    const firstIndex = markdown.indexOf("[citation:Original Title]");
    const secondIndex = markdown.indexOf("[citation:Updated Title]");

    expect(extractCitationSources(markdown)).toEqual([
      {
        id: "https://example.com/research",
        title: "Original Title",
        url: "https://example.com/research",
        domain: "example.com",
        count: 2,
        occurrences: [
          { index: firstIndex, title: "Original Title" },
          { index: secondIndex, title: "Updated Title" },
        ],
      },
    ]);
  });

  it("ignores normal links, image links, and citations inside fenced code", () => {
    const markdown = [
      "[Normal](https://example.com/normal)",
      "![citation:Image](https://example.com/image.png)",
      "```md",
      "[citation:Example](https://example.com/example)",
      "```",
      "Real source [citation:Real](https://example.com/real).",
    ].join("\n");
    const realIndex = markdown.indexOf("[citation:Real]");

    expect(extractCitationSources(markdown)).toEqual([
      {
        id: "https://example.com/real",
        title: "Real",
        url: "https://example.com/real",
        domain: "example.com",
        count: 1,
        occurrences: [{ index: realIndex, title: "Real" }],
      },
    ]);
  });

  it("keeps every source when citations are directly adjacent", () => {
    const markdown =
      "[citation:A](https://example.com/a)[citation:B](https://example.com/b)[citation:C](https://example.com/c)";

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/a",
      "https://example.com/b",
      "https://example.com/c",
    ]);
  });

  it("keeps URLs that contain multiple balanced parenthetical groups", () => {
    const markdown = "[citation:W](https://en.wikipedia.org/wiki/Foo_(a)_(b))";

    expect(extractCitationSources(markdown)[0]).toMatchObject({
      url: "https://en.wikipedia.org/wiki/Foo_(a)_(b)",
      domain: "en.wikipedia.org",
    });
  });

  it("ignores citations inside inline code spans", () => {
    const markdown =
      "Example: `[citation:X](https://x.com/inline)` then real [citation:Real](https://example.com/real).";

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("keeps a citation whose paragraph sits between two unclosed backtick runs", () => {
    // An inline span cannot cross a blank line, so neither stray backtick opens
    // a span here and the citation is a rendered link, not sample code.
    const markdown = [
      "Install it with `npm i",
      "",
      "The upstream guide is [citation:Docs](https://example.com/docs).",
      "",
      "Then run `npm start` to serve it.",
    ].join("\n");

    const sources = extractCitationSources(markdown);

    expect(sources.map((source) => source.url)).toEqual([
      "https://example.com/docs",
    ]);
    expect(sources[0]?.occurrences[0]?.index).toBe(
      markdown.indexOf("[citation:Docs]"),
    );
  });

  it("still masks a code span that closes inside its own paragraph", () => {
    const markdown = [
      "Install it with `npm i",
      "",
      "Example: `[citation:Fake](https://example.com/fake)` then real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("ends a paragraph on a CRLF blank line, as the inline scanner does", () => {
    const markdown =
      "Install it with `npm i\r\n\r\nThe upstream guide is [citation:Docs](https://example.com/docs).\r\n\r\nThen run `npm start` to serve it.";

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/docs",
    ]);
  });

  it("ignores citations inside an unclosed fenced code block", () => {
    const markdown = [
      "Streaming output:",
      "```md",
      "[citation:Streaming](https://example.com/streaming)",
    ].join("\n");

    expect(extractCitationSources(markdown)).toEqual([]);
  });

  it("ends an inline span at a heading, thematic break or list marker", () => {
    // CommonMark ends the paragraph at these block boundaries too, so "Use
    // `npm" cannot steal the opener of `npm start` two lines later and the
    // citation between them is a rendered link, not sample code.
    for (const boundary of ["## Title", "---", "- item"]) {
      const markdown = [
        "Use `npm",
        boundary,
        "See [citation:X](https://example.com/x) and `npm start`.",
      ].join("\n");

      expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
        "https://example.com/x",
      ]);
    }
  });

  it("ends an inline span at a blank line inside a blockquote", () => {
    const markdown = [
      "> Install it with `npm i",
      ">",
      "> The guide is [citation:Docs](https://example.com/docs) and `npm start`.",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/docs",
    ]);
  });

  it("masks citations inside a fenced block nested in a list item", () => {
    // The fence is indented past the list marker, so recognising it needs the
    // container prefix; the blank line inside keeps it open across paragraphs.
    const markdown = [
      "- run:",
      "    ```md",
      "    [citation:Fake1](https://example.com/fake1)",
      "",
      "    [citation:Fake2](https://example.com/fake2)",
      "    ```",
      "",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("masks a blockquoted fence, and stops at the line that ends the quote", () => {
    // Fake1 is inside the fence. The blank line has no `>` marker, so it closes
    // the blockquote — and the fence with it — which makes Fake2 a rendered link
    // again. Verified against remark-parse rather than by eye.
    const markdown = [
      "> ```md",
      "> [citation:Fake1](https://example.com/fake1)",
      "",
      "> [citation:Fake2](https://example.com/fake2)",
      "> ```",
      "",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/fake2",
      "https://example.com/real",
    ]);
  });

  it("does not open a fence from a backtick run in the middle of a line", () => {
    const markdown = [
      "Run ```md please",
      "[citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("keeps a fence open across a shorter backtick run inside it", () => {
    const markdown = [
      "````md",
      "```",
      "[citation:Inside](https://example.com/inside)",
      "```",
      "````",
      "",
      "Outside [citation:Outside](https://example.com/outside).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/outside",
    ]);
  });

  it("keeps an indented top-level fence open for unindented content", () => {
    // The opener's own indentation is not container indentation: content lines
    // may sit further left than the marker, and the closer only has to come back
    // within three columns of the opener.
    const markdown = [
      "Intro text.",
      "  ```md",
      "[citation:Fake](https://example.com/fake)",
      "  ```",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("treats a four-space indented marker inside a column-zero fence as content", () => {
    const markdown = [
      "```md",
      "    ```",
      "[citation:Fake](https://example.com/fake)",
      "```",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("does not open a fence from a marker indented four columns at the top level", () => {
    // Four columns past the container's content column is an indented code
    // block, not a fence opener, so the citation below it renders as a link.
    const markdown = [
      "    ```md",
      "[citation:Real](https://example.com/real)",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("still opens a fence from a marker indented three columns at the top level", () => {
    // The limit is three columns, so the next case up pins the boundary rather
    // than overshooting it.
    const markdown = [
      "   ```md",
      "[citation:Fake](https://example.com/fake)",
      "   ```",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("does not open a fence from a list marker with no space after it", () => {
    // `-` has to be followed by indentation to start a list item, so `-```md`
    // is ordinary paragraph text and nothing behind it is code.
    const markdown = [
      "-```md",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("ends a fence when a line drops out of the inner blockquote", () => {
    const markdown = [
      ">> ```md",
      ">> [citation:Fake](https://example.com/fake)",
      "> Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("does not let a marker with an info string close the fence", () => {
    // A closing fence is bare, so ` ```text ` here is literal content and the
    // citation after it stays inside the block instead of becoming a source.
    const markdown = [
      "```md",
      "```text",
      "[citation:Fake](https://example.com/fake)",
      "```",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("does not open a backtick fence whose info string holds a backtick", () => {
    // ` ```md `x` ` is paragraph text, so the citation below it is a link the
    // reader can reach and must not be masked away.
    const markdown = [
      "```md `x`",
      "[citation:Real](https://example.com/real)",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("opens a tilde fence whatever its info string says", () => {
    // Tilde fences take backticks in the info string, so the boundary above is
    // about the marker character rather than a blanket rule.
    const markdown = [
      "~~~md `x`",
      "[citation:Fake](https://example.com/fake)",
      "~~~",
      "Real [citation:Real](https://example.com/real).",
    ].join("\n");

    expect(extractCitationSources(markdown).map((s) => s.url)).toEqual([
      "https://example.com/real",
    ]);
  });

  it("uses the source domain when the citation label is generic", () => {
    const markdown = "See [citation:Source](https://www.example.com/path).";

    expect(extractCitationSources(markdown)[0]).toMatchObject({
      title: "example.com",
      domain: "example.com",
      url: "https://www.example.com/path",
    });
  });
});

describe("formatCitationMarkdownReference", () => {
  it("formats a source as a reusable markdown reference", () => {
    const [source] = extractCitationSources(
      "Evidence [citation:Paper A](https://example.com/a).",
    );

    expect(formatCitationMarkdownReference(source!)).toBe(
      "[Paper A](https://example.com/a)",
    );
  });
});
