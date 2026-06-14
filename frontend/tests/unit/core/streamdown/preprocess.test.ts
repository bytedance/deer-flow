import { expect, test } from "vitest";

import {
  capBlockquoteNesting,
  compactDisplayMathBlocks,
  normalizeStreamdownMathMarkdown,
  preprocessStreamdownMarkdown,
} from "@/core/streamdown/preprocess";

test("capBlockquoteNesting returns normal content unchanged", () => {
  const input = "# Title\n\n> a quote\n>> nested\n\nsome `code`";
  expect(capBlockquoteNesting(input)).toBe(input);
});

test("capBlockquoteNesting keeps nesting at or below the cap untouched", () => {
  const input = "> ".repeat(100) + "hi";
  expect(capBlockquoteNesting(input)).toBe(input);
});

test("capBlockquoteNesting caps pathological nesting and preserves content", () => {
  const result = capBlockquoteNesting("> ".repeat(5000) + "hi");
  expect((result.match(/>/g) ?? []).length).toBe(100);
  expect(result.endsWith("hi")).toBe(true);
});

test("capBlockquoteNesting handles markers without spaces", () => {
  const result = capBlockquoteNesting(">".repeat(5000) + "hi");
  expect((result.match(/>/g) ?? []).length).toBe(100);
  expect(result.endsWith("hi")).toBe(true);
});

test("capBlockquoteNesting leaves fenced code content untouched", () => {
  const literal = ">".repeat(150);
  const input = `${"> ".repeat(3000)}hi\n\`\`\`text\n${literal}\n\`\`\``;
  const result = capBlockquoteNesting(input);
  expect(result.split("\n")[2]).toBe(literal);
});

test("capBlockquoteNesting leaves indented code blocks untouched", () => {
  const literal = "    " + ">".repeat(150);
  const input = `${"> ".repeat(3000)}hi\n\n${literal}`;
  const result = capBlockquoteNesting(input);
  expect(result.split("\n")[2]).toBe(literal);
});

test("capBlockquoteNesting only rewrites pathological lines", () => {
  const normal = "> normal quote";
  const deep = "> ".repeat(3000) + "deep";
  const result = capBlockquoteNesting(`${normal}\n${deep}\nplain`);
  const lines = result.split("\n");
  expect(lines[0]).toBe(normal);
  expect((lines[1]?.match(/>/g) ?? []).length).toBe(100);
  expect(lines[2]).toBe("plain");
});

test("normalizeStreamdownMathMarkdown converts inline math delimiters", () => {
  expect(normalizeStreamdownMathMarkdown("Given \\(x\\), compute \\(x^2\\)."))
    .toBe("Given $x$, compute $x^2$.");
});

test("normalizeStreamdownMathMarkdown converts multiline display math delimiters", () => {
  const input = [
    "Before",
    "\\[",
    "\\begin{aligned}",
    "x_t &= \\sqrt{\\bar{\\alpha}_t}x_0 + \\sqrt{1-\\bar{\\alpha}_t}\\epsilon, \\\\",
    "\\hat{x}_0 &= x_t",
    "\\end{aligned}",
    "\\]",
    "After",
  ].join("\n");
  const expected = input.replace("\\[", "$$").replace("\\]", "$$");
  expect(normalizeStreamdownMathMarkdown(input)).toBe(expected);
});

test("normalizeStreamdownMathMarkdown leaves fenced and indented code untouched", () => {
  const input = [
    "Text \\(x\\)",
    "```tex",
    "\\[",
    "x^2",
    "\\]",
    "```",
    "    \\(literal\\)",
  ].join("\n");
  const expected = [
    "Text $x$",
    "```tex",
    "\\[",
    "x^2",
    "\\]",
    "```",
    "    \\(literal\\)",
  ].join("\n");
  expect(normalizeStreamdownMathMarkdown(input)).toBe(expected);
});

test("compactDisplayMathBlocks keeps display math as display math", () => {
  const input = ["Before", "$$", "x", "=", "y", "$$", "After"].join("\n");
  const expected = ["Before", "$$", "x = y", "$$", "After"].join("\n");
  expect(compactDisplayMathBlocks(input)).toBe(expected);
});

test("compactDisplayMathBlocks leaves fenced code content untouched", () => {
  const input = [
    "```md",
    "$$",
    "x = y",
    "$$",
    "```",
    "$$",
    "a",
    "=",
    "b",
    "$$",
  ].join("\n");
  const expected = [
    "```md",
    "$$",
    "x = y",
    "$$",
    "```",
    "$$",
    "a = b",
    "$$",
  ].join("\n");
  expect(compactDisplayMathBlocks(input)).toBe(expected);
});

test("preprocessStreamdownMarkdown normalizes math before Mermaid fixes", () => {
  const input = [
    "Before \\(x\\)",
    "```mermaid",
    "graph TD",
    "  A -.-> B",
    "```",
  ].join("\n");
  const expected = [
    "Before $x$",
    "```mermaid",
    "graph TD",
    "  A -.-> B",
    "```",
  ].join("\n");
  expect(preprocessStreamdownMarkdown(input)).toBe(expected);
});
