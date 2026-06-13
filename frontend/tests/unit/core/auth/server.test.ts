import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AUTH_DISABLED_USER } from "@/core/auth/auth-disabled-user";
import { STATIC_WEBSITE_USER } from "@/core/auth/static-user";

vi.mock("next/headers", () => ({
  cookies: vi.fn(() => {
    throw new Error("cookies should not be read in static website mode");
  }),
}));

const ENV_KEYS = [
  "DEER_FLOW_AUTH_DISABLED",
  "DEER_FLOW_ENV",
  "ENVIRONMENT",
  "NEXT_PUBLIC_STATIC_WEBSITE_ONLY",
] as const;

type EnvSnapshot = Partial<
  Record<(typeof ENV_KEYS)[number], string | undefined>
>;

function snapshotEnv(): EnvSnapshot {
  const snapshot: EnvSnapshot = {};
  for (const key of ENV_KEYS) {
    snapshot[key] = process.env[key];
  }
  return snapshot;
}

function setEnv(key: (typeof ENV_KEYS)[number], value: string | undefined) {
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[key];
  } else {
    env[key] = value;
  }
}

function restoreEnv(snapshot: EnvSnapshot) {
  for (const key of ENV_KEYS) {
    setEnv(key, snapshot[key]);
  }
}

async function loadFreshServerAuth() {
  vi.resetModules();
  return await import("@/core/auth/server");
}

describe("getServerSideUser", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("DEER_FLOW_ENV", undefined);
    setEnv("ENVIRONMENT", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    vi.unstubAllGlobals();
  });

  test("bypasses gateway auth in static website mode", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");
    const fetchSpy = vi.fn(() => {
      throw new Error("fetch should not be called in static website mode");
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "authenticated",
      user: STATIC_WEBSITE_USER,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("bypasses gateway auth in auth-disabled mode", async () => {
    setEnv("DEER_FLOW_AUTH_DISABLED", "1");
    const fetchSpy = vi.fn(() => {
      throw new Error("fetch should not be called in auth-disabled mode");
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "authenticated",
      user: AUTH_DISABLED_USER,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("does not enable auth-disabled mode in explicit production environments", async () => {
    setEnv("DEER_FLOW_AUTH_DISABLED", "1");
    setEnv("DEER_FLOW_ENV", "production");

    const { isAuthDisabledMode } =
      await import("@/core/auth/auth-disabled-user");

    expect(isAuthDisabledMode()).toBe(false);
  });
});

describe("getServerSideUser — gateway_unavailable contract (issue #3493)", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    vi.unstubAllGlobals();
    vi.doUnmock("next/headers");
  });

  test("returns gateway_unavailable when /auth/me fetch rejects (e.g. AbortError)", async () => {
    vi.doMock("next/headers", () => ({
      cookies: vi.fn(async () => ({
        get: (name: string) =>
          name === "access_token" ? { value: "stub-token" } : undefined,
      })),
    }));
    const abortErr = new DOMException("Aborted", "AbortError");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(abortErr)),
    );

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "gateway_unavailable",
    });
  });

  test("returns gateway_unavailable when /auth/me responds with a 5xx", async () => {
    vi.doMock("next/headers", () => ({
      cookies: vi.fn(async () => ({
        get: (name: string) =>
          name === "access_token" ? { value: "stub-token" } : undefined,
      })),
    }));
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response("upstream error", {
            status: 503,
            statusText: "Service Unavailable",
          }),
        ),
      ),
    );

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "gateway_unavailable",
    });
  });
});
