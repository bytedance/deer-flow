import { expect, test } from "vitest";

import { normalizeMermaidMarkdown } from "@/core/streamdown/mermaid";

test("normalizes labelled dotted arrows inside mermaid fences", () => {
  const markdown = [
    "```mermaid",
    "flowchart TD",
    '    A -- "sealed memory" -.-> F',
    '    B -- "resonance" -.-> A',
    "```",
  ].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    [
      "```mermaid",
      "flowchart TD",
      '    A -. "sealed memory" .-> F',
      '    B -. "resonance" .-> A',
      "```",
    ].join("\n"),
  );
});

test("does not rewrite non-mermaid code fences", () => {
  const markdown = ["```text", 'A -- "sealed memory" -.-> F', "```"].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(markdown);
});

test("preserves mermaid fence metadata", () => {
  const markdown = [
    '```mermaid title="relationships"',
    'A -- "sealed memory" -.-> F',
    "```",
  ].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    [
      '```mermaid title="relationships"',
      'A -. "sealed memory" .-> F',
      "```",
    ].join("\n"),
  );
});

test("preserves empty mermaid fences", () => {
  const markdown = ["```mermaid", "```"].join("\n");

  expect(normalizeMermaidMarkdown(markdown)).toBe(markdown);
});

test("normalizes labelled dotted arrows inside tilde mermaid fences", () => {
  const markdown = ["~~~mermaid", 'A -- "sealed memory" -.-> F', "~~~"].join(
    "\n",
  );

  expect(normalizeMermaidMarkdown(markdown)).toBe(
    ["~~~mermaid", 'A -. "sealed memory" .-> F', "~~~"].join("\n"),
  );
});
