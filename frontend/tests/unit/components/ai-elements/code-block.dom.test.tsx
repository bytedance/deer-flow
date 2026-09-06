import { describe, expect, it, rs } from "@rstest/core";
import { render, screen } from "@testing-library/react";

rs.mock("shiki", () => ({
  codeToHtml: rs.fn(async () => {
    throw new Error("highlighter unavailable");
  }),
}));

describe("CodeBlock", () => {
  it("shows raw code while the async highlighter is unavailable", async () => {
    const { CodeBlock } = await import("@/components/ai-elements/code-block");

    render(<CodeBlock code="const immediate = true" language="typescript" />);

    expect(screen.getByText("const immediate = true")).toBeTruthy();
  });
});
