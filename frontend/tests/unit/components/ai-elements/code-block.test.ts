import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const codeToHtml = rs.fn(async () => '<pre class="shiki">code</pre>');
rs.mock("shiki", () => ({ codeToHtml }));

describe("highlightCode", () => {
  beforeEach(async () => {
    codeToHtml.mockClear();
    const { clearHighlightCacheForTests } =
      await import("@/components/ai-elements/shiki-highlight");
    clearHighlightCacheForTests();
  });

  it("creates one dual-theme highlighted tree", async () => {
    const { highlightCode } =
      await import("@/components/ai-elements/shiki-highlight");

    expect(await highlightCode("const n = 1", "typescript", true)).toContain(
      'class="shiki"',
    );
    expect(codeToHtml).toHaveBeenCalledTimes(1);
    expect(codeToHtml).toHaveBeenCalledWith(
      "const n = 1",
      expect.objectContaining({
        themes: { light: "one-light", dark: "one-dark-pro" },
      }),
    );
  });

  it("reuses results and evicts the least recently used entry at the bound", async () => {
    const { HIGHLIGHT_CACHE_LIMIT, highlightCode } =
      await import("@/components/ai-elements/shiki-highlight");

    await highlightCode("first", "typescript");
    await highlightCode("first", "typescript");
    expect(codeToHtml).toHaveBeenCalledTimes(1);

    for (let index = 1; index <= HIGHLIGHT_CACHE_LIMIT; index += 1) {
      await highlightCode(`code-${index}`, "typescript");
    }
    expect(codeToHtml).toHaveBeenCalledTimes(HIGHLIGHT_CACHE_LIMIT + 1);

    await highlightCode("first", "typescript");
    expect(codeToHtml).toHaveBeenCalledTimes(HIGHLIGHT_CACHE_LIMIT + 2);
  });

  it("does not retain oversized source strings in the highlight cache", async () => {
    const { HIGHLIGHT_CACHE_MAX_CODE_LENGTH, highlightCode } =
      await import("@/components/ai-elements/shiki-highlight");
    const oversizedCode = "x".repeat(HIGHLIGHT_CACHE_MAX_CODE_LENGTH + 1);

    await highlightCode(oversizedCode, "typescript");
    await highlightCode(oversizedCode, "typescript");

    expect(codeToHtml).toHaveBeenCalledTimes(2);
  });
});
