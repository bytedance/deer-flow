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

type MathDelimiter = {
  close: "\\)" | "\\]";
  replacement: "$" | "$$";
};

function convertLatexDelimitersInLine(
  line: string,
  openBlock: MathDelimiter | null,
): { line: string; openBlock: MathDelimiter | null } {
  let result = "";
  let i = 0;
  let inInlineCode = false;
  let currentBlock = openBlock;

  while (i < line.length) {
    const two = line.slice(i, i + 2);

    if (line[i] === "`") {
      result += line[i];
      if (!currentBlock) {
        inInlineCode = !inInlineCode;
      }
      i += 1;
      continue;
    }

    if (!inInlineCode && currentBlock?.close === two) {
      result += currentBlock.replacement;
      currentBlock = null;
      i += 2;
      continue;
    }

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

  return { line: result, openBlock: currentBlock };
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
  let openMath: MathDelimiter | null = null;

  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line) && !openMath) {
        insideFence = !insideFence;
        return line;
      }
      if (insideFence || (INDENTED_CODE_RE.test(line) && !openMath)) {
        return line;
      }
      const converted = convertLatexDelimitersInLine(line, openMath);
      openMath = converted.openBlock;
      return converted.line;
    })
    .join("\n");
}

function flattenDisplayMathBody(lines: string[]): string {
  return lines.map((line) => line.trim()).join(" ");
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
        output.push("$$", flattenDisplayMathBody(mathLines), "$$");
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

export function preprocessStreamdownMarkdown(markdown: string): string {
  const mathNormalized = normalizeStreamdownMathMarkdown(markdown);

  if (
    !MERMAID_BLOCK_HINT_RE.test(mathNormalized) ||
    !mathNormalized.includes("-.->")
  ) {
    return mathNormalized;
  }

  return normalizeMermaidMarkdown(mathNormalized);
}
