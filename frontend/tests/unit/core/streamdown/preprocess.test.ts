import { expect, test } from "vitest";

import {
  capBlockquoteNesting,
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

test("capBlockquoteNesting only rewrites pathological lines", () => {
  const normal = "> normal quote";
  const deep = "> ".repeat(3000) + "deep";
  const result = capBlockquoteNesting(`${normal}\n${deep}\nplain`);
  const lines = result.split("\n");
  expect(lines[0]).toBe(normal);
  expect((lines[1]?.match(/>/g) ?? []).length).toBe(100);
  expect(lines[2]).toBe("plain");
});

test("preprocessStreamdownMarkdown leaves non-mermaid content unchanged", () => {
  const input = "just some text";
  expect(preprocessStreamdownMarkdown(input)).toBe(input);
});
