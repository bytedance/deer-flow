import { afterEach, describe, expect, test, vi } from "vitest";

import {
  DEFAULT_GATEWAY_USER_ID,
  applyDefaultGatewayUserHeadersIfMissing,
  defaultGatewayUserHeaders,
  gatewayFetch,
  mergeGatewayFetchInit,
  setGatewayCredentialsHook,
  setGatewayUserIdOverride,
} from "@/core/api/gateway-fetch";

afterEach(() => {
  setGatewayUserIdOverride(null);
  setGatewayCredentialsHook(null);
  vi.unstubAllGlobals();
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

test("setGatewayUserIdOverride trims whitespace and treats blank as cleared", () => {
  setGatewayUserIdOverride("   alice   ");
  expect(JSON.parse(defaultGatewayUserHeaders()["x-user-info"]!)).toEqual({
    user_id: "alice",
  });
  setGatewayUserIdOverride("   ");
  expect(JSON.parse(defaultGatewayUserHeaders()["x-user-info"]!)).toEqual({
    user_id: DEFAULT_GATEWAY_USER_ID,
  });
});

test("applyDefaultGatewayUserHeadersIfMissing fills only when absent", () => {
  const empty = new Headers();
  applyDefaultGatewayUserHeadersIfMissing(empty);
  expect(JSON.parse(empty.get("x-user-info")!)).toEqual({
    user_id: DEFAULT_GATEWAY_USER_ID,
  });

  const preset = new Headers({ "x-user-info": "preset-by-caller" });
  applyDefaultGatewayUserHeadersIfMissing(preset);
  expect(preset.get("x-user-info")).toBe("preset-by-caller");
});

describe("gatewayFetch credentials policy", () => {
  test('defaults to "same-origin" when no hook is registered', async () => {
    const fetchSpy = vi
      .fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(new Response("ok"));
    vi.stubGlobal("fetch", fetchSpy);

    await gatewayFetch("/api/example");

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("same-origin");
  });

  test("uses the credentials hook return value when registered", async () => {
    const fetchSpy = vi
      .fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(new Response("ok"));
    vi.stubGlobal("fetch", fetchSpy);
    setGatewayCredentialsHook(() => "include");

    await gatewayFetch("/api/example");

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("include");
  });

  test("respects an explicit init.credentials over the hook", async () => {
    const fetchSpy = vi
      .fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(new Response("ok"));
    vi.stubGlobal("fetch", fetchSpy);
    setGatewayCredentialsHook(() => "include");

    await gatewayFetch("/api/example", { credentials: "omit" });

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("omit");
  });
});
