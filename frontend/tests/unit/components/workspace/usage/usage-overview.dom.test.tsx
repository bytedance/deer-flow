import { afterEach, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { UsageOverview } from "@/components/workspace/usage/usage-overview";
import { enUS } from "@/core/i18n/locales/en-US";
import type { UsageSummary } from "@/core/usage/types";

afterEach(cleanup);

const day = { date: "2026-11-27", input_tokens: 400, output_tokens: 100 };

test("a window with only batch item usage is not shown as empty", () => {
  const usage: UsageSummary = {
    days: [{ ...day, total_tokens: 500, runs: 0, batch_items: 2 }],
    by_model: {
      "model-a": {
        tokens: 500,
        runs: 0,
        input_tokens: 400,
        cache_read_tokens: 0,
      },
    },
    total_tokens: 500,
    total_runs: 0,
    total_batch_items: 2,
  };
  render(<UsageOverview usage={usage} locale="en-US" text={enUS.usage} />);
  expect(screen.queryByText(enUS.usage.noUsage)).toBeNull();
  expect(screen.getByText("model-a")).toBeTruthy();
});

test("a window without runs or batch items stays empty", () => {
  const usage: UsageSummary = {
    days: [
      { ...day, input_tokens: 0, output_tokens: 0, total_tokens: 0, runs: 0 },
    ],
    by_model: {},
    total_tokens: 0,
    total_runs: 0,
  };
  render(<UsageOverview usage={usage} locale="en-US" text={enUS.usage} />);
  expect(screen.getByText(enUS.usage.noUsage)).toBeTruthy();
});
