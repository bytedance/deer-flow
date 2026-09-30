import { expect, test } from "@rstest/core";

import { extractTitleFromMarkdown } from "@/core/utils/markdown";

test("reads the title from a leading ATX heading", () => {
  expect(extractTitleFromMarkdown("# Real Title\n\nbody")).toBe("Real Title");
});

test("strips CommonMark closing ATX heading hashes", () => {
  expect(extractTitleFromMarkdown("# Release Notes ###\n\nbody")).toBe(
    "Release Notes",
  );
  expect(extractTitleFromMarkdown("# Title ##\n")).toBe("Title");
  expect(extractTitleFromMarkdown("# Title ###   ")).toBe("Title");
  expect(extractTitleFromMarkdown("# Title #\t\n")).toBe("Title");
});

test("preserves literal hashes that are not closing ATX syntax", () => {
  // Hashes not preceded by space or tab remain part of the title
  expect(extractTitleFromMarkdown("# Learning C#\n\nbody")).toBe("Learning C#");
  expect(extractTitleFromMarkdown("# Tag#1\n")).toBe("Tag#1");
  // Mid-title hashes remain intact
  expect(extractTitleFromMarkdown("# Heading ### with details")).toBe(
    "Heading ### with details",
  );
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

test.each([" \t", "  \t", "   \t"])(
  "does not treat mixed indentation %j as a heading",
  (indent) => {
    expect(
      extractTitleFromMarkdown(`${indent}# Code comment\n# Later heading`),
    ).toBeUndefined();
    expect(
      extractTitleFromMarkdown(`\n  \n${indent}# Code comment`),
    ).toBeUndefined();
  },
);

test.each(["", " ", "  ", "   "])(
  "accepts a heading with %j indentation and CRLF line endings",
  (indent) => {
    expect(extractTitleFromMarkdown(`\r\n${indent}# Real Title\r\nbody`)).toBe(
      "Real Title",
    );
  },
);

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
