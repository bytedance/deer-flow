import { expect, rs, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ContextUsageBadge } from "@/components/workspace/context-usage-badge";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      contextUsage: {
        title: "Context window",
        label: "Context",
        badgeAriaLabel: (percentage: string) =>
          `Context window ${percentage}% full`,
      },
    },
  }),
}));

test("keeps a gauge placeholder visible while context usage is unavailable", () => {
  const html = renderToStaticMarkup(
    createElement(ContextUsageBadge, { contextUsage: null }),
  );

  expect(html).toContain('data-context-usage-placeholder="true"');
  expect(html).toContain('aria-label="Context window"');
});

test("renders the current percentage when context usage is available", () => {
  const html = renderToStaticMarkup(
    createElement(ContextUsageBadge, {
      contextUsage: {
        tokenCount: 35_000,
        maxContextTokens: 100_000,
        percentage: 35,
      },
    }),
  );

  expect(html).toContain("35%");
  expect(html).toContain('aria-label="Context window 35% full"');
});
