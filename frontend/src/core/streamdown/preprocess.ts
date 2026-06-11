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
const BLOCKQUOTE_PREFIX_RE = /^(?:[ \t]*>)+/;

export function capBlockquoteNesting(markdown: string): string {
  if (!DEEP_BLOCKQUOTE_HINT_RE.test(markdown)) {
    return markdown;
  }

  return markdown
    .split("\n")
    .map((line) => {
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

export function preprocessStreamdownMarkdown(markdown: string): string {
  if (!MERMAID_BLOCK_HINT_RE.test(markdown) || !markdown.includes("-.->")) {
    return markdown;
  }

  return normalizeMermaidMarkdown(markdown);
}
