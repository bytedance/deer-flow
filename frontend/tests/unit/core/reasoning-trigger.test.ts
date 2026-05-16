import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";

vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) =>
    createElement("div", null, children),
}));

import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";

test("ReasoningTrigger default message uses phrasing content", () => {
  const html = renderToStaticMarkup(
    createElement(
      Reasoning,
      { isStreaming: false, defaultOpen: false },
      createElement(ReasoningTrigger, null),
      createElement(ReasoningContent, null, "test"),
    ),
  );

  expect(html).toContain("Thought for a few seconds");
  expect(html).not.toMatch(/<button\b[^>]*>[\s\S]*?<p\b/i);
});
