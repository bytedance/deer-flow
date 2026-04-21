/// <reference lib="webworker" />

// Shiki syntax-highlighting worker.
//
// Runs in a dedicated thread so the CPU-heavy TextMate tokenizer for large
// HTML/JS code blocks does not stall the main thread while streaming
// responses. The worker owns Shiki's singleton highlighter via `codeToHtml`
// (which lazily loads grammars and caches them), so language bundles are
// only fetched on first use.

import {
  codeToHtml,
  type BundledLanguage,
  type ShikiTransformer,
} from "shiki";

// Mirror of the transformer in code-block.tsx. Defined here because
// transformer objects cannot be transferred across the worker boundary —
// postMessage only carries structured-clonable values, not functions.
const lineNumberTransformer: ShikiTransformer = {
  name: "line-numbers",
  line(node, line) {
    node.children.unshift({
      type: "element",
      tagName: "span",
      properties: {
        className: [
          "inline-block",
          "min-w-10",
          "mr-4",
          "text-right",
          "select-none",
          "text-muted-foreground",
        ],
      },
      children: [{ type: "text", value: String(line) }],
    });
  },
};

export interface HighlightRequest {
  id: number;
  code: string;
  lang: BundledLanguage;
  showLineNumbers: boolean;
}

export interface HighlightResponse {
  id: number;
  light?: string;
  dark?: string;
  error?: string;
}

const ctx = self as unknown as DedicatedWorkerGlobalScope;

ctx.addEventListener("message", async (event: MessageEvent<HighlightRequest>) => {
  const { id, code, lang, showLineNumbers } = event.data;
  const transformers: ShikiTransformer[] = showLineNumbers
    ? [lineNumberTransformer]
    : [];

  try {
    const [light, dark] = await Promise.all([
      codeToHtml(code, { lang, theme: "one-light", transformers }),
      codeToHtml(code, { lang, theme: "one-dark-pro", transformers }),
    ]);
    const response: HighlightResponse = { id, light, dark };
    ctx.postMessage(response);
  } catch (err) {
    const response: HighlightResponse = {
      id,
      error: err instanceof Error ? err.message : String(err),
    };
    ctx.postMessage(response);
  }
});
