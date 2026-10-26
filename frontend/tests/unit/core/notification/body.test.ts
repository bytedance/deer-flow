import { expect, test } from "@rstest/core";

import {
  MAX_NOTIFICATION_BODY_CODE_POINTS,
  notificationBody,
} from "@/core/notification/body";

const LONE_SURROGATE =
  /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

test("quotes the last message when it fits", () => {
  expect(notificationBody("Done in 3 steps.")).toBe("Done in 3 steps.");
});

test("falls back when there is no text to quote", () => {
  expect(notificationBody(null)).toBe("Conversation finished");
  expect(notificationBody(undefined)).toBe("Conversation finished");
  expect(notificationBody("")).toBe("Conversation finished");
  expect(notificationBody("", "Custom fallback")).toBe("Custom fallback");
});

test("a body that fits the code-point budget keeps its trailing emoji", () => {
  // 200 code points but 201 UTF-16 units: UTF-16 counting would cut this.
  const text = `${"a".repeat(MAX_NOTIFICATION_BODY_CODE_POINTS - 1)}😀`;
  expect(notificationBody(text)).toBe(text);
});

test("a truncated body never ends in half an emoji", () => {
  // 201 code points; the old UTF-16 cut landed inside the surrogate pair.
  const text = `${"a".repeat(MAX_NOTIFICATION_BODY_CODE_POINTS - 1)}😀b`;
  const body = notificationBody(text);
  expect(body).toBe(
    `${"a".repeat(MAX_NOTIFICATION_BODY_CODE_POINTS - 1)}😀...`,
  );
  expect(body).not.toMatch(LONE_SURROGATE);
});
