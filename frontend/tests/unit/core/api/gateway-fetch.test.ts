import { afterEach, expect, test } from "vitest";

import {
  DEFAULT_GATEWAY_USER_ID,
  defaultGatewayUserHeaders,
  mergeGatewayFetchInit,
  setGatewayUserIdOverride,
} from "@/core/api/gateway-fetch";

afterEach(() => {
  setGatewayUserIdOverride(null);
});

test("defaultGatewayUserHeaders matches backend x-user-info JSON shape", () => {
  const h = defaultGatewayUserHeaders();
  expect(h["x-user-info"]).toBe(
    JSON.stringify({ user_id: DEFAULT_GATEWAY_USER_ID }),
  );
});

test("mergeGatewayFetchInit lets caller override x-user-info", () => {
  const init = mergeGatewayFetchInit({
    headers: { "x-user-info": JSON.stringify({ user_id: "other" }) },
  });
  const headers = new Headers(init.headers);
  expect(JSON.parse(headers.get("x-user-info")!)).toEqual({ user_id: "other" });
});

test("mergeGatewayFetchInit preserves additional headers", () => {
  const init = mergeGatewayFetchInit({
    headers: { "Content-Type": "application/json" },
  });
  const headers = new Headers(init.headers);
  expect(headers.get("Content-Type")).toBe("application/json");
  expect(JSON.parse(headers.get("x-user-info")!)).toEqual({
    user_id: DEFAULT_GATEWAY_USER_ID,
  });
});

test("setGatewayUserIdOverride is reflected in defaultGatewayUserHeaders", () => {
  setGatewayUserIdOverride("oa-user-1");
  const h = defaultGatewayUserHeaders();
  expect(JSON.parse(h["x-user-info"]!)).toEqual({ user_id: "oa-user-1" });
});
