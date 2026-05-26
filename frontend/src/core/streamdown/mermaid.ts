const MERMAID_FENCE_RE =
  /(^|\n)((```+|~~~+)[ \t]*mermaid[^\n]*\n)([\s\S]*?)(^\3[ \t]*(?=\n|$))/gim;

const LABELLED_DOTTED_ARROW_RE =
  /^(\s*)(.+?)\s+--\s+("[^"\n]+"|'[^'\n]+')\s+-\.->\s+(.+?)\s*$/;

function normalizeMermaidCode(code: string): string {
  return code
    .split("\n")
    .map((line) =>
      line.replace(
        LABELLED_DOTTED_ARROW_RE,
        (
          _match,
          indent: string,
          source: string,
          label: string,
          target: string,
        ) => `${indent}${source} -. ${label} .-> ${target}`,
      ),
    )
    .join("\n");
}

export function normalizeMermaidMarkdown(markdown: string): string {
  return markdown.replace(
    MERMAID_FENCE_RE,
    (
      _match,
      prefix: string,
      openingFence: string,
      _fence: string,
      code: string,
      closingFence: string,
    ) => `${prefix}${openingFence}${normalizeMermaidCode(code)}${closingFence}`,
  );
}
