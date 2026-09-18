import { expect, test } from "@rstest/core";

import { extractTitleFromMarkdown } from "@/core/utils/markdown";

test("reads the title from a leading ATX heading", () => {
  expect(extractTitleFromMarkdown("# Real Title\n\nbody")).toBe("Real Title");
});

test("skips blank lines before the first heading", () => {
  expect(extractTitleFromMarkdown("\n# Real Title\n\nbody")).toBe("Real Title");
  expect(extractTitleFromMarkdown("  \n\n# Real Title")).toBe("Real Title");
});

test("accepts the up-to-three-space indentation CommonMark allows", () => {
  expect(extractTitleFromMarkdown("   # Real Title")).toBe("Real Title");
});

test("ignores an indented code block that starts with a hash", () => {
  expect(extractTitleFromMarkdown("    # Not A Title")).toBeUndefined();
  expect(extractTitleFromMarkdown("\t# Not A Title")).toBeUndefined();
});

test("ignores headings that are not level 1", () => {
  expect(extractTitleFromMarkdown("## Section")).toBeUndefined();
  expect(extractTitleFromMarkdown("#NoSpace")).toBeUndefined();
});

test("does not report an empty heading as a title", () => {
  expect(extractTitleFromMarkdown("# \n\nbody")).toBeUndefined();
  expect(extractTitleFromMarkdown("#")).toBeUndefined();
});

test("returns undefined when the document has no content", () => {
  expect(extractTitleFromMarkdown("")).toBeUndefined();
  expect(extractTitleFromMarkdown("   \n  ")).toBeUndefined();
  expect(
    extractTitleFromMarkdown("Plain text with no heading"),
  ).toBeUndefined();
});
