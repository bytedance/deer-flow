import { expect, test } from "@rstest/core";
import { code, type HighlightResult } from "@streamdown/code";
import { mermaid } from "@streamdown/mermaid";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";

import {
  reasoningPlugins,
  streamdownPlugins,
  streamdownRenderingPlugins,
  streamdownWordAnimation,
} from "@/core/streamdown/plugins";

test("shared streamdown configs disable single-tilde strikethrough", () => {
  const expectedGfmPlugin = [remarkGfm, { singleTilde: false }];

  expect(streamdownPlugins.remarkPlugins).toContainEqual(expectedGfmPlugin);
});

test("streaming word animation uses Streamdown's stable incremental animation", () => {
  expect(streamdownWordAnimation).toEqual({
    animation: "fadeIn",
    duration: 200,
    sep: "word",
  });
});

test("streamdownPlugins includes rehypeRaw", () => {
  expect(streamdownPlugins.rehypePlugins).toContain(rehypeRaw);
});

test("shared streamdown configs register code highlighting and Mermaid", () => {
  expect(streamdownRenderingPlugins).toEqual({ code, mermaid });
  expect(streamdownPlugins.plugins).toBe(streamdownRenderingPlugins);
  expect(reasoningPlugins.plugins).toBe(streamdownRenderingPlugins);
});

test("the shared code plugin produces highlighted Shiki tokens", async () => {
  const source = "const answer: number = 42;";
  const highlighted = await new Promise<HighlightResult>((resolve) => {
    const cached = code.highlight(
      {
        code: source,
        language: "typescript",
        themes: code.getThemes(),
      },
      resolve,
    );
    if (cached) {
      resolve(cached);
    }
  });

  expect(
    highlighted.tokens
      .flat()
      .some((token) =>
        /^#[0-9A-Fa-f]{6}$/.test(String(token.htmlStyle?.color ?? "")),
      ),
  ).toBe(true);
});

test("reasoningPlugins does not include rehypeRaw", () => {
  const flat = reasoningPlugins.rehypePlugins?.flat();
  expect(flat).not.toContain(rehypeRaw);
});
