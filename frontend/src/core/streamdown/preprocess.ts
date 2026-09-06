import { INTERNAL_MARKER_TAGS } from "@/core/messages/utils";

import { normalizeMermaidMarkdown } from "./mermaid";

const MERMAID_BLOCK_HINT_RE = /mermaid/i;

// marked's blockquote tokenizer (used by Streamdown to split content into
// memoizable blocks) recurses once per nesting level and overflows the call
// stack at roughly 2,000 levels, replacing the whole chat route with an error
// page. 100 levels is far beyond any legitimate content while keeping a wide
// margin below the crash threshold.
const MAX_BLOCKQUOTE_DEPTH = 100;
const DEEP_BLOCKQUOTE_HINT_RE = new RegExp(
  `^(?:[ \\t]*>){${MAX_BLOCKQUOTE_DEPTH + 1}}`,
  "m",
);
// Only up to 3 leading spaces can start a blockquote; 4+ (or a tab) is an
// indented code block, where ">" runs are literal content.
const BLOCKQUOTE_PREFIX_RE = /^ {0,3}(?:[ \t]*>)+/;
const CODE_FENCE_RE = /^ {0,3}(?:```|~~~)/;
const INDENTED_CODE_RE = /^(?: {4}|\t)/;

// marked's list tokenizer recurses once per nesting level too (list ->
// blockTokens -> list -> ...). In the browser's tighter stack a deeply nested
// list overflows during render and throws "Maximum call stack size exceeded"
// from inside Streamdown's lexing useMemo (see issue #3393); on larger stacks
// the same input instead goes quadratic and exhausts the heap. Each list level
// requires at least ~2 columns of indentation, so capping leading whitespace at
// 200 columns bounds the effective nesting near 100 levels — far beyond any
// legitimate content while keeping marked safe. Anything indented past this is
// pathological nesting, not prose or code.
const MAX_LIST_INDENT = 200;
const DEEP_INDENT_HINT_RE = new RegExp(`^[ \\t]{${MAX_LIST_INDENT + 1},}`, "m");

export function capBlockquoteNesting(markdown: string): string {
  if (!DEEP_BLOCKQUOTE_HINT_RE.test(markdown)) {
    return markdown;
  }

  let insideFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line)) {
        insideFence = !insideFence;
        return line;
      }
      // ">" runs inside fenced or indented code blocks are literal text, not
      // nesting — rewriting them would silently corrupt code content.
      if (insideFence || INDENTED_CODE_RE.test(line)) {
        return line;
      }
      const match = BLOCKQUOTE_PREFIX_RE.exec(line);
      if (!match) {
        return line;
      }
      const prefix = match[0];
      let depth = 0;
      for (let i = 0; i < prefix.length; i++) {
        if (prefix[i] === ">") {
          depth += 1;
          if (depth > MAX_BLOCKQUOTE_DEPTH) {
            return line.slice(0, i) + line.slice(prefix.length);
          }
        }
      }
      return line;
    })
    .join("\n");
}

export function capListNesting(markdown: string): string {
  if (!DEEP_INDENT_HINT_RE.test(markdown)) {
    return markdown;
  }

  let insideFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line)) {
        insideFence = !insideFence;
        return line;
      }
      // Indentation inside fenced code is literal layout (ASCII art, pasted
      // source); collapsing it would corrupt the rendered block.
      if (insideFence) {
        return line;
      }
      const whitespace = /^[ \t]*/.exec(line)![0];
      if (whitespace.length <= MAX_LIST_INDENT) {
        return line;
      }
      return " ".repeat(MAX_LIST_INDENT) + line.slice(whitespace.length);
    })
    .join("\n");
}

// Cap every runaway nesting construct that can take down a message render
// before marked sees the content.
export function capMarkdownNesting(markdown: string): string {
  return capListNesting(capBlockquoteNesting(markdown));
}

type MathDelimiter = {
  close: "\\)" | "\\]";
  replacement: "$" | "$$";
};

type DelimiterState = {
  openBlock: MathDelimiter | null;
  inlineCodeDelimiterLength: number | null;
};

function consumeBacktickRun(line: string, index: number): number {
  let runLength = 0;
  while (line[index + runLength] === "`") {
    runLength += 1;
  }
  return runLength;
}

function convertLatexDelimitersInLine(
  line: string,
  state: DelimiterState,
): { line: string; state: DelimiterState } {
  let result = "";
  let i = 0;
  let inlineCodeDelimiterLength = state.inlineCodeDelimiterLength;
  let currentBlock = state.openBlock;

  while (i < line.length) {
    if (line[i] === "`") {
      const runLength = consumeBacktickRun(line, i);
      result += line.slice(i, i + runLength);
      if (!currentBlock) {
        if (inlineCodeDelimiterLength === null) {
          inlineCodeDelimiterLength = runLength;
        } else if (runLength === inlineCodeDelimiterLength) {
          inlineCodeDelimiterLength = null;
        }
      }
      i += runLength;
      continue;
    }

    const two = line.slice(i, i + 2);
    const inInlineCode = inlineCodeDelimiterLength !== null;

    // Consume escaped backslash as a unit — `\\` is never part of a math
    // delimiter, so skip past both characters to avoid the second `\` being
    // mis-paired with a following `(` or `[`.
    if (two === "\\\\" && !inInlineCode) {
      result += two;
      i += 2;
      continue;
    }

    // Close an open math block
    if (!inInlineCode && currentBlock?.close === two) {
      result += currentBlock.replacement;
      currentBlock = null;
      i += 2;
      continue;
    }

    // Open a new math block
    if (!inInlineCode && !currentBlock && (two === "\\(" || two === "\\[")) {
      const isDisplay = two === "\\[";
      currentBlock = {
        close: isDisplay ? "\\]" : "\\)",
        replacement: isDisplay ? "$$" : "$",
      };
      result += currentBlock.replacement;
      i += 2;
      continue;
    }

    result += line[i];
    i += 1;
  }

  return {
    line: result,
    state: { openBlock: currentBlock, inlineCodeDelimiterLength },
  };
}

/**
 * Normalize common LLM LaTeX delimiters for remark-math.
 *
 * remark-math recognizes `$...$` and `$$...$$`, but many models output
 * `\(...\)` and `\[...\]`. Convert those delimiters outside fenced/indented
 * code so KaTeX can render equations without corrupting code blocks. The
 * conversion is stateful across lines, because display math normally spans
 * several lines:
 *
 *   \[
 *   ...
 *   \]
 */
export function normalizeLatexMathDelimiters(markdown: string): string {
  if (!/[\\][([\])]/.test(markdown)) {
    return markdown;
  }

  let insideFence = false;
  let mathState: DelimiterState = {
    openBlock: null,
    inlineCodeDelimiterLength: null,
  };

  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line) && !mathState.openBlock) {
        insideFence = !insideFence;
        return line;
      }
      if (
        insideFence ||
        (INDENTED_CODE_RE.test(line) && !mathState.openBlock)
      ) {
        return line;
      }
      const converted = convertLatexDelimitersInLine(line, mathState);
      mathState = converted.state;
      return converted.line;
    })
    .join("\n");
}

function hasUnescapedTexComment(line: string): boolean {
  for (let i = 0; i < line.length; i++) {
    if (line[i] !== "%") {
      continue;
    }

    let backslashCount = 0;
    for (let j = i - 1; j >= 0 && line[j] === "\\"; j--) {
      backslashCount += 1;
    }

    if (backslashCount % 2 === 0) {
      return true;
    }
  }

  return false;
}

function flattenDisplayMathBody(lines: string[]): string[] {
  if (lines.some(hasUnescapedTexComment)) {
    return lines;
  }

  return [lines.map((line) => line.trim()).join(" ")];
}

/**
 * Keep complete display-math blocks atomic for Streamdown.
 *
 * Streamdown first splits Markdown into render blocks with marked, then runs
 * react-markdown on each block. Multi-line `$$ ... $$` can be split before
 * remark-math sees the matching delimiters, especially in long numbered
 * responses. Compacting the content between the opening and closing `$$`
 * preserves the LaTeX semantics (visual line breaks still come from `\\`,
 * `aligned`, `matrix`, `cases`, etc.) while keeping the display-math block
 * atomic for Streamdown's splitter.
 */
export function compactDisplayMathBlocks(markdown: string): string {
  if (!markdown.includes("$$")) {
    return markdown;
  }

  const output: string[] = [];
  let insideFence = false;
  let mathLines: string[] | null = null;

  for (const line of markdown.split("\n")) {
    if (CODE_FENCE_RE.test(line) && mathLines === null) {
      insideFence = !insideFence;
      output.push(line);
      continue;
    }

    if (insideFence || (INDENTED_CODE_RE.test(line) && mathLines === null)) {
      output.push(line);
      continue;
    }

    if (line.trim() === "$$") {
      if (mathLines === null) {
        mathLines = [];
      } else {
        const flattenedMathLines = flattenDisplayMathBody(mathLines);
        output.push("$$", ...flattenedMathLines, "$$");
        mathLines = null;
      }
      continue;
    }

    if (mathLines !== null) {
      mathLines.push(line);
      continue;
    }

    output.push(line);
  }

  if (mathLines !== null) {
    output.push("$$", ...mathLines);
  }

  return output.join("\n");
}

export function normalizeStreamdownMathMarkdown(markdown: string): string {
  return compactDisplayMathBlocks(normalizeLatexMathDelimiters(markdown));
}

// Regex matching any opening, closing, or self-closing internal marker tag.
// e.g. <memory>, </memory>, <memory attr="x">, <memory/>
const _INTERNAL_TAG_RE = new RegExp(
  `</?(?:${INTERNAL_MARKER_TAGS.join("|")})(?:\\s[^>]*)?/?>`,
  "g",
);

// Regex matching the start/end of a fenced code block (3+ backticks or tildes).
// Captures the marker string so we can compare character and length.
const FENCE_MARKER_RE = /^ {0,3}(`{3,}|~{3,})/;

/**
 * Strip leaked system-internal HTML tags from markdown content.
 *
 * Backend-injected markers like ``<memory>…</memory>`` can occasionally
 * reach the UI renderer (e.g. when a ``hide_from_ui`` reminder leaks through
 * the filter).  React's DOM renderer logs "unrecognized tag" console errors
 * for unknown HTML elements.  This function strips the tag markers while
 * preserving the inner content — unlike {@link stripInternalMarkers} in
 * ``utils.ts``, which removes the entire block.
 *
 * Code-aware: tags inside fenced code blocks (````` `````) and indented code
 * blocks (4-space indent) are left untouched, so user-written meta-discussions
 * about the memory system are not silently stripped.
 *
 * Fence tracking is marker-aware (tracking the opening character and run
 * length) so that a tilde-fenced block containing a shorter backtick run, or a
 * 4-backtick block containing a 3-backtick run, does not prematurely close the
 * fence.
 */
export function stripLeakedSystemTags(markdown: string): string {
  const lines = markdown.split("\n");
  let fenceMarker: string | null = null;

  return lines
    .map((line) => {
      const fenceMatch = FENCE_MARKER_RE.exec(line);
      if (fenceMatch) {
        const marker = fenceMatch[1]!;
        if (fenceMarker === null) {
          // Opening a fenced code block
          fenceMarker = marker;
        } else if (
          marker.startsWith(fenceMarker.charAt(0)) &&
          marker.length >= fenceMarker.length
        ) {
          // Closing fence: same character and at least as long as opener
          fenceMarker = null;
        }
        // Otherwise: different fence type or shorter run inside a fence
        // (e.g. ``` inside ~~~~, or `` inside `````) — stay inside.
        return line;
      }
      if (fenceMarker !== null || INDENTED_CODE_RE.test(line)) {
        return line;
      }
      return line.replace(_INTERNAL_TAG_RE, "");
    })
    .join("\n");
}

export function preprocessStreamdownMarkdown(markdown: string): string {
  if (!MERMAID_BLOCK_HINT_RE.test(markdown) || !markdown.includes("-.->")) {
    return markdown;
  }

  return normalizeMermaidMarkdown(markdown);
}
