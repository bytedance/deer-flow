import { afterEach, expect, test } from "@rstest/core";

import { formatTimeAgo } from "@/core/utils/datetime";

afterEach(() => {
  document.cookie = "locale=; max-age=0; path=/";
});

test("falls back to a known locale for a malformed locale cookie", () => {
  document.cookie = "locale=zh%FF; path=/";
  expect(() => formatTimeAgo(Date.now() - 5_000)).not.toThrow();
});

test("uses the locale from the cookie", () => {
  document.cookie = "locale=zh-CN; path=/";
  expect(formatTimeAgo(Date.now() - 5_000)).toContain("前");
});
