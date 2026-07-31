import { describe, expect, it, rs } from "@rstest/core";

const codeToHtml = rs.fn(async () => '<pre class="shiki">code</pre>');
rs.mock("shiki", () => ({ codeToHtml }));

describe("highlightCode", () => {
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
});
