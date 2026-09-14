import type { Extension } from "@uiw/react-codemirror";

export type CodeEditorLanguage =
  | "css"
  | "html"
  | "javascript"
  | "json"
  | "markdown"
  | "python"
  | "text";

export function normalizeCodeEditorLanguage(
  language: string | null | undefined,
): CodeEditorLanguage {
  switch (language?.toLowerCase()) {
    case "css":
    case "scss":
    case "sass":
    case "less":
      return "css";
    case "html":
    case "xml":
      return "html";
    case "javascript":
    case "typescript":
    case "jsx":
    case "tsx":
      return "javascript";
    case "json":
    case "jsonc":
    case "json5":
      return "json";
    case "markdown":
    case "mdx":
      return "markdown";
    case "python":
    case "py":
      return "python";
    default:
      return "text";
  }
}

async function loadLanguageExtension(
  language: CodeEditorLanguage,
): Promise<Extension[]> {
  switch (language) {
    case "css":
      return [(await import("@codemirror/lang-css")).css()];
    case "html":
      return [(await import("@codemirror/lang-html")).html()];
    case "javascript":
      return [(await import("@codemirror/lang-javascript")).javascript()];
    case "json":
      return [(await import("@codemirror/lang-json")).json()];
    case "markdown": {
      const markdownModule = await import("@codemirror/lang-markdown");
      return [
        markdownModule.markdown({ base: markdownModule.markdownLanguage }),
      ];
    }
    case "python":
      return [(await import("@codemirror/lang-python")).python()];
    case "text":
      return [];
  }
}

async function loadTheme(theme: "light" | "dark"): Promise<Extension> {
  if (theme === "dark") {
    const { monokaiInit } = await import("@uiw/codemirror-theme-monokai");
    return monokaiInit({
      settings: {
        background: "transparent",
        gutterBackground: "transparent",
        gutterForeground: "#555",
        gutterActiveForeground: "#fff",
        fontSize: "var(--text-sm)",
      },
    });
  }
  const { basicLightInit } = await import("@uiw/codemirror-theme-basic");
  return basicLightInit({
    settings: {
      background: "transparent",
      fontSize: "var(--text-sm)",
    },
  });
}

export async function loadCodeEditorExtensions(
  language: string | null | undefined,
  theme: "light" | "dark",
) {
  const normalizedLanguage = normalizeCodeEditorLanguage(language);
  const [extensions, loadedTheme] = await Promise.all([
    loadLanguageExtension(normalizedLanguage),
    loadTheme(theme),
  ]);
  return { extensions, theme: loadedTheme };
}
