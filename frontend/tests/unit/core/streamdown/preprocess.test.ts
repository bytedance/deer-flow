import { expect, test } from "@rstest/core";

import {
  capBlockquoteNesting,
  capListNesting,
  capMarkdownNesting,
  compactDisplayMathBlocks,
  normalizeStreamdownMathMarkdown,
  preprocessStreamdownMarkdown,
  stripLeakedSystemTags,
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

test("capListNesting returns normally indented content unchanged", () => {
  const input = "- a\n  - b\n    - c\n\n      code continuation";
  expect(capListNesting(input)).toBe(input);
});

test("capListNesting caps pathologically deep list indentation", () => {
  const deep = "  ".repeat(2000) + "- x";
  const result = capListNesting(deep);
  const indent = /^[ \t]*/.exec(result)![0];
  expect(indent.length).toBe(200);
  expect(result.endsWith("- x")).toBe(true);
});

test("capListNesting leaves fenced code content untouched", () => {
  const literal = " ".repeat(400) + "deeply indented ascii art";
  const input = `\`\`\`text\n${literal}\n\`\`\``;
  expect(capListNesting(input).split("\n")[1]).toBe(literal);
});

// Outside a fence, deep indentation is capped regardless of blank-line context:
// we cannot tell an indented-code line from deeply nested list content (both can
// follow a blank line), and exempting either reopens the crash — blank-separated
// deep-indent lists otherwise blow up marked just like contiguous ones.
test("capListNesting caps deep indentation even after a blank line", () => {
  const input = `- a\n\n${" ".repeat(500)}- deep`;
  const lines = capListNesting(input).split("\n");
  expect(/^[ \t]*/.exec(lines[2]!)![0].length).toBe(200);
});

test("capListNesting only rewrites pathological lines", () => {
  const normal = "    indented paragraph";
  const deep = " ".repeat(500) + "- deep";
  const result = capListNesting(`${normal}\n${deep}\nplain`);
  const lines = result.split("\n");
  expect(lines[0]).toBe(normal);
  expect(/^[ \t]*/.exec(lines[1]!)![0].length).toBe(200);
  expect(lines[2]).toBe("plain");
});

test("capMarkdownNesting caps both blockquote and list nesting", () => {
  const input = `${"> ".repeat(3000)}quote\n${" ".repeat(500)}- item`;
  const result = capMarkdownNesting(input);
  const lines = result.split("\n");
  expect((lines[0]?.match(/>/g) ?? []).length).toBe(100);
  expect(/^[ \t]*/.exec(lines[1]!)![0].length).toBe(200);
});

test("normalizeStreamdownMathMarkdown converts inline math delimiters", () => {
  expect(
    normalizeStreamdownMathMarkdown("Given \\(x\\), compute \\(x^2\\)."),
  ).toBe("Given $x$, compute $x^2$.");
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
  const expected = [
    "Before",
    "$$",
    "\\begin{aligned} x_t &= \\sqrt{\\bar{\\alpha}_t}x_0 + \\sqrt{1-\\bar{\\alpha}_t}\\epsilon, \\\\ \\hat{x}_0 &= x_t \\end{aligned}",
    "$$",
    "After",
  ].join("\n");
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

test("compactDisplayMathBlocks preserves TeX comments in display math", () => {
  const input = ["Before", "$$", "a % step 1", "+ b", "$$", "After"].join("\n");
  expect(compactDisplayMathBlocks(input)).toBe(input);
});

test("compactDisplayMathBlocks compacts escaped percent in display math", () => {
  const input = ["Before", "$$", "a \\% step 1", "+ b", "$$", "After"].join(
    "\n",
  );
  const expected = ["Before", "$$", "a \\% step 1 + b", "$$", "After"].join(
    "\n",
  );
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

test("preprocessStreamdownMarkdown applies only Mermaid fixes (not math)", () => {
  const input = [
    "Before \\(x\\)",
    "```mermaid",
    "graph TD",
    "  A -.-> B",
    "```",
  ].join("\n");
  const expected = [
    "Before \\(x\\)",
    "```mermaid",
    "graph TD",
    "  A -.-> B",
    "```",
  ].join("\n");
  expect(preprocessStreamdownMarkdown(input)).toBe(expected);
});

test("normalizeStreamdownMathMarkdown preserves escaped backslash before parens", () => {
  // When the backslash itself is escaped (\\), the following ( is not a math open
  const input = "Use \\\\( to start inline math.";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(
    "Use \\\\( to start inline math.",
  );
});

test("normalizeStreamdownMathMarkdown preserves escaped backslash before brackets", () => {
  const input = "Escape: \\\\[ is not math.";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(
    "Escape: \\\\[ is not math.",
  );
});

test("normalizeStreamdownMathMarkdown preserves delimiters inside multi-line code spans", () => {
  // A backtick code span opened on line 1 should protect line 2 content
  const input = ["`code span", "with \\(x\\) inside`"].join("\n");
  expect(normalizeStreamdownMathMarkdown(input)).toBe(input);
});

test("normalizeStreamdownMathMarkdown preserves delimiters inside multi-backtick code spans", () => {
  const input = "Use ``\\(literal\\)`` here";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(input);
});

test("normalizeStreamdownMathMarkdown requires matching backtick run to close code spans", () => {
  const input = "Use ``\\(literal\\)` and still code`` then \\(x\\)";
  const expected = "Use ``\\(literal\\)` and still code`` then $x$";
  expect(normalizeStreamdownMathMarkdown(input)).toBe(expected);
});

// ---------------------------------------------------------------------------
// stripLeakedSystemTags
// ---------------------------------------------------------------------------

test("stripLeakedSystemTags strips <memory> tags preserving content", () => {
  expect(stripLeakedSystemTags("<memory>hello</memory>")).toBe("hello");
});

test("stripLeakedSystemTags strips all internal marker tags", () => {
  expect(
    stripLeakedSystemTags(
      "<system-reminder>reminder</system-reminder> <current_date>2024</current_date>",
    ),
  ).toBe("reminder 2024");
});

test("stripLeakedSystemTags strips self-closing tags", () => {
  expect(stripLeakedSystemTags("text<memory/>more")).toBe("textmore");
});

test("stripLeakedSystemTags strips tags with attributes", () => {
  expect(stripLeakedSystemTags('<memory class="x">text</memory>')).toBe("text");
});

test("stripLeakedSystemTags handles multiple occurrences", () => {
  expect(
    stripLeakedSystemTags(
      "<memory>a</memory> <memory>b</memory> <memory>c</memory>",
    ),
  ).toBe("a b c");
});

test("stripLeakedSystemTags leaves fenced code content untouched", () => {
  const input = [
    "<memory>outside</memory>",
    "```text",
    "<memory>inside code</memory>",
    "```",
    "<memory>after</memory>",
  ].join("\n");
  const expected = [
    "outside",
    "```text",
    "<memory>inside code</memory>",
    "```",
    "after",
  ].join("\n");
  expect(stripLeakedSystemTags(input)).toBe(expected);
});

test("stripLeakedSystemTags leaves indented code content untouched", () => {
  const input = [
    "<memory>outside</memory>",
    "    <memory>indented code</memory>",
  ].join("\n");
  const expected = ["outside", "    <memory>indented code</memory>"].join("\n");
  expect(stripLeakedSystemTags(input)).toBe(expected);
});

test("stripLeakedSystemTags passes plain text unchanged", () => {
  expect(stripLeakedSystemTags("plain text")).toBe("plain text");
});

test("stripLeakedSystemTags returns empty string unchanged", () => {
  expect(stripLeakedSystemTags("")).toBe("");
});

test("stripLeakedSystemTags handles no tags present", () => {
  const input = "normal text with **bold** and `code`";
  expect(stripLeakedSystemTags(input)).toBe(input);
});

test("stripLeakedSystemTags strips <uploaded_files> tag", () => {
  expect(
    stripLeakedSystemTags("<uploaded_files>file.pdf</uploaded_files>"),
  ).toBe("file.pdf");
});

test("stripLeakedSystemTags strips <slash_skill_activation> tag", () => {
  expect(
    stripLeakedSystemTags(
      "<slash_skill_activation>skill</slash_skill_activation>",
    ),
  ).toBe("skill");
});

test("stripLeakedSystemTags handles mixed tags on same line", () => {
  expect(
    stripLeakedSystemTags(
      "<memory>a</memory><system-reminder>b</system-reminder>",
    ),
  ).toBe("ab");
});

test("stripLeakedSystemTags handles multiple fences correctly", () => {
  const input = [
    "<memory>a</memory>",
    "```",
    "<memory>inside 1</memory>",
    "```",
    "<memory>b</memory>",
    "```",
    "<memory>inside 2</memory>",
    "```",
  ].join("\n");
  const expected = [
    "a",
    "```",
    "<memory>inside 1</memory>",
    "```",
    "b",
    "```",
    "<memory>inside 2</memory>",
    "```",
  ].join("\n");
  expect(stripLeakedSystemTags(input)).toBe(expected);
});

test("stripLeakedSystemTags preserves tags inside tilde fence with inner backtick fence", () => {
  const input = [
    "<memory>outside</memory>",
    "~~~~",
    "```",
    "<memory>inside tilde</memory>",
    "```",
    "~~~~",
    "<memory>after</memory>",
  ].join("\n");
  const expected = [
    "outside",
    "~~~~",
    "```",
    "<memory>inside tilde</memory>",
    "```",
    "~~~~",
    "after",
  ].join("\n");
  expect(stripLeakedSystemTags(input)).toBe(expected);
});

test("stripLeakedSystemTags preserves tags inside 4-backtick fence with inner 3-backtick fence", () => {
  const input = [
    "<memory>outside</memory>",
    "````",
    "```",
    "<memory>inside 4-backtick</memory>",
    "```",
    "````",
    "<memory>after</memory>",
  ].join("\n");
  const expected = [
    "outside",
    "````",
    "```",
    "<memory>inside 4-backtick</memory>",
    "```",
    "````",
    "after",
  ].join("\n");
  expect(stripLeakedSystemTags(input)).toBe(expected);
});

test("stripLeakedSystemTags handles backtick fence inside tilde fence with shorter tilde closing", () => {
  // A 4-tilde fence containing a 3-backtick sub-fence; the closing tilde run
  // is shorter (3 vs 4) so it should NOT close the fence.
  const input = [
    "<memory>outside</memory>",
    "~~~~",
    "```",
    "<memory>inside</memory>",
    "```",
    "~~~",
  ].join("\n");
  const expected = [
    "outside",
    "~~~~",
    "```",
    "<memory>inside</memory>",
    "```",
    "~~~",
  ].join("\n");
  expect(stripLeakedSystemTags(input)).toBe(expected);
});

test("stripLeakedSystemTags strips tags after real closing fence", () => {
  const input = [
    "~~~~",
    "<memory>inside</memory>",
    "~~~~",
    "<memory>after</memory>",
  ].join("\n");
  const expected = ["~~~~", "<memory>inside</memory>", "~~~~", "after"].join(
    "\n",
  );
  expect(stripLeakedSystemTags(input)).toBe(expected);
});
