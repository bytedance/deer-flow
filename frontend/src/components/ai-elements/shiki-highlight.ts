import { type BundledLanguage, codeToHtml, type ShikiTransformer } from "shiki";

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
  return await codeToHtml(code, {
    lang: language,
    themes: { light: "one-light", dark: "one-dark-pro" },
    defaultColor: "light",
    transformers: showLineNumbers ? [lineNumberTransformer] : [],
  });
}
