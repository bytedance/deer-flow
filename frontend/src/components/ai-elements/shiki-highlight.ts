import { type BundledLanguage, codeToHtml, type ShikiTransformer } from "shiki";

export const HIGHLIGHT_CACHE_LIMIT = 64;
export const HIGHLIGHT_CACHE_MAX_CODE_LENGTH = 100_000;
const HIGHLIGHT_CONFIGURATION_VERSION = 1;
const highlightCache = new Map<string, Promise<string>>();

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

export async function highlightCode(
  code: string,
  language: BundledLanguage,
  showLineNumbers = false,
) {
  const render = () =>
    codeToHtml(code, {
      lang: language,
      themes: { light: "one-light", dark: "one-dark-pro" },
      defaultColor: "light",
      transformers: showLineNumbers ? [lineNumberTransformer] : [],
    });
  if (code.length > HIGHLIGHT_CACHE_MAX_CODE_LENGTH) {
    return await render();
  }

  const key = JSON.stringify([
    HIGHLIGHT_CONFIGURATION_VERSION,
    code,
    language,
    showLineNumbers,
  ]);
  const cached = highlightCache.get(key);
  if (cached) {
    highlightCache.delete(key);
    highlightCache.set(key, cached);
    return await cached;
  }

  const highlighted = render();
  highlightCache.set(key, highlighted);
  if (highlightCache.size > HIGHLIGHT_CACHE_LIMIT) {
    const oldestKey = highlightCache.keys().next().value;
    if (oldestKey !== undefined) highlightCache.delete(oldestKey);
  }

  try {
    return await highlighted;
  } catch (error) {
    if (highlightCache.get(key) === highlighted) highlightCache.delete(key);
    throw error;
  }
}

export function clearHighlightCacheForTests() {
  highlightCache.clear();
}
