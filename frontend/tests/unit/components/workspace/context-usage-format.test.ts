import { expect, test } from "@rstest/core";

import {
  formatContextUsagePercentage,
  formatContextUsageTokens,
} from "@/components/workspace/context-usage-format";

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
  expect(formatContextUsagePercentage(0.1)).toBe("0.1");
});

test("renders a non-zero share below a tenth as less than 0.1", () => {
  expect(formatContextUsagePercentage(0.01)).toBe("<0.1");
  expect(formatContextUsagePercentage(0.099)).toBe("<0.1");
  expect(formatContextUsagePercentage(0)).toBe("0");
});

test("clamps negative percentages to zero", () => {
  expect(formatContextUsagePercentage(-1)).toBe("0");
});

test("formatContextUsageTokens uses K from a thousand tokens", () => {
  expect(formatContextUsageTokens(0)).toBe("0");
  expect(formatContextUsageTokens(999)).toBe("999");
  expect(formatContextUsageTokens(1000)).toBe("1.0K");
  expect(formatContextUsageTokens(5749)).toBe("5.7K");
  expect(formatContextUsageTokens(1_048_576)).toBe("1048.6K");
});

test("formatContextUsageTokens clamps invalid input", () => {
  expect(formatContextUsageTokens(-5)).toBe("0");
  expect(formatContextUsageTokens(Number.NaN)).toBe("0");
});
