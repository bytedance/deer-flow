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

test("keeps the placeholder visible for an empty breakdown", () => {
  const html = renderToStaticMarkup(
    createElement(ContextUsageBadge, {
      contextUsage: {
        usedTokens: 0,
        maxContextTokens: 100_000,
        percentage: 0,
        breakdown: [],
      },
    }),
  );

  expect(html).toContain('data-context-usage-placeholder="true"');
});
