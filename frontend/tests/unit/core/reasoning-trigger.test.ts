import { expect, test, rs } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

rs.mock("streamdown", () => ({
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

test("ReasoningTrigger labels a finished duration as elapsed work, not thinking (#4152)", () => {
  // `duration` comes from backend turn_duration = run wall-clock (tools included),
  // so the completed-state copy must not claim it was all thinking time.
  const html = renderToStaticMarkup(
    createElement(
      Reasoning,
      { isStreaming: false, defaultOpen: false, duration: 114 },
      createElement(ReasoningTrigger, null),
      createElement(ReasoningContent, null, "test"),
    ),
  );

  expect(html).toContain("Worked for 114 seconds");
  expect(html).not.toContain("Thought for 114 seconds");
});
