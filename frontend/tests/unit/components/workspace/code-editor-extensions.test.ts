import { describe, expect, it } from "@rstest/core";

import {
  loadCodeEditorExtensions,
  normalizeCodeEditorLanguage,
} from "@/components/workspace/code-editor-extensions";

describe("CodeEditor extension loading", () => {
  it.each([
    ["tsx", "javascript"],
    ["scss", "css"],
    ["mdx", "markdown"],
    ["py", "python"],
    ["yaml", "text"],
  ] as const)("normalizes %s to %s", (input, expected) => {
    expect(normalizeCodeEditorLanguage(input)).toBe(expected);
  });

  it("loads only the selected language and theme extension", async () => {
    const loaded = await loadCodeEditorExtensions("python", "dark");
    expect(loaded.extensions).toHaveLength(1);
    expect(loaded.theme).toBeTruthy();
  });
});
