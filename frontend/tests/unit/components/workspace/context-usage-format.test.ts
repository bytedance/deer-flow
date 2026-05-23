import { expect, test } from "vitest";

import { formatContextUsagePercentage } from "@/components/workspace/context-usage-format";

test("returns null for unknown percentages", () => {
  expect(formatContextUsagePercentage(null)).toBeNull();
  expect(formatContextUsagePercentage(undefined)).toBeNull();
  expect(formatContextUsagePercentage(Number.NaN)).toBeNull();
});

test("renders whole numbers without a decimal point", () => {
  expect(formatContextUsagePercentage(0)).toBe("0");
  expect(formatContextUsagePercentage(35)).toBe("35");
  expect(formatContextUsagePercentage(100)).toBe("100");
});

test("renders fractional percentages with one decimal place", () => {
  expect(formatContextUsagePercentage(35.4)).toBe("35.4");
  expect(formatContextUsagePercentage(35.46)).toBe("35.5");
});

test("clamps negative percentages to zero", () => {
  expect(formatContextUsagePercentage(-1)).toBe("0");
});
