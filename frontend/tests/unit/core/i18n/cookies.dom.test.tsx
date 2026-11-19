import { afterEach, expect, test } from "@rstest/core";

import { getLocaleFromCookie } from "@/core/i18n/cookies";

function setLocaleCookie(value: string) {
  document.cookie = `locale=${value}; path=/`;
}

afterEach(() => {
  document.cookie = "locale=; max-age=0; path=/";
});

test("decodes an encoded locale", () => {
  setLocaleCookie("zh-CN");
  expect(getLocaleFromCookie()).toBe("zh-CN");
});

test("does not throw on a malformed percent-encoding", () => {
  setLocaleCookie("%E0%A4%A");
  expect(getLocaleFromCookie()).toBe("%E0%A4%A");
});

test("keeps a cookie value that contains '='", () => {
  setLocaleCookie("en=US");
  expect(getLocaleFromCookie()).toBe("en=US");
});
