import { expect, test } from "vitest";

import { breakdownToSegments } from "@/components/workspace/context-usage-bar";
import type { ContextUsageBreakdownItem } from "@/core/threads/token-usage";

const _label = (row: ContextUsageBreakdownItem) => row.key;

test("uses the model's context window as the denominator when set", () => {
  const segments = breakdownToSegments(
    [
      { key: "messages", tokens: 200, active: true },
      { key: "free_space", tokens: 800, active: false },
    ],
    1000,
    _label,
  );

  expect(segments).toEqual([
    { key: "messages", ratio: 0.2, label: "messages", active: true },
    { key: "free_space", ratio: 0.8, label: "free_space", active: false },
  ]);
});

test("falls back to the sum of breakdown rows when the window is unknown", () => {
  const segments = breakdownToSegments(
    [
      { key: "messages", tokens: 200, active: true },
      { key: "system_prompt", tokens: 300, active: true },
    ],
    null,
    _label,
  );

  expect(segments.map((s) => s.ratio)).toEqual([0.4, 0.6]);
});

test("returns an empty array when there is nothing to render", () => {
  expect(breakdownToSegments([], 1000, _label)).toEqual([]);
  expect(
    breakdownToSegments(
      [{ key: "messages", tokens: 0, active: true }],
      null,
      _label,
    ),
  ).toEqual([]);
});
