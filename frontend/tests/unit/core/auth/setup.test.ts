import { afterEach, describe, expect, rs, test } from "@rstest/core";

import { AUTH_REQUEST_TIMEOUT_MS } from "@/core/auth/constants";
import {
  canCreateRegularAccount,
  fetchSetupStatus,
  isSystemAlreadyInitializedError,
  setupStatusFetchInit,
} from "@/core/auth/setup";

function pendingUntilAborted(signal: AbortSignal): Promise<Response> {
  return new Promise((_resolve, reject) => {
    signal.addEventListener(
      "abort",
      () => {
        reject(
          signal.reason instanceof Error
            ? signal.reason
            : new Error("The request was aborted"),
        );
      },
      { once: true },
    );
  });
}

function requestSignal(init?: RequestInit): AbortSignal {
  if (!init?.signal) {
    throw new Error("Expected fetch to receive an AbortSignal");
  }
  return init.signal;
}

describe("auth setup helpers", () => {
  afterEach(() => {
    rs.useRealTimers();
    rs.unstubAllGlobals();
  });

  test("setup-status requests bypass browser caches", () => {
    expect(setupStatusFetchInit).toMatchObject({
      cache: "no-store",
      credentials: "include",
    });
  });

  test("fetchSetupStatus uses the shared no-store request options", async () => {
    const fetchMock = rs.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        new Response(JSON.stringify({ needs_setup: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    rs.stubGlobal("fetch", fetchMock);

    await expect(fetchSetupStatus()).resolves.toEqual({ needs_setup: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/setup-status",
      expect.objectContaining(setupStatusFetchInit),
    );
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
  });

  test("aborts a setup-status request that remains pending", async () => {
    rs.useFakeTimers();
    const fetchMock = rs.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      pendingUntilAborted(requestSignal(init)),
    );
    rs.stubGlobal("fetch", fetchMock);

    const request = fetchSetupStatus();
    const rejection = expect(request).rejects.toMatchObject({
      name: "AbortError",
    });

    await rs.advanceTimersByTimeAsync(AUTH_REQUEST_TIMEOUT_MS);
    await rejection;

    expect(fetchMock.mock.calls[0]![1]!.signal!.aborted).toBe(true);
  });

  test("clears the timeout after a successful setup-status response", async () => {
    rs.useFakeTimers();
    const signals: AbortSignal[] = [];
    const fetchMock = rs.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      signals.push(requestSignal(init));
      return Promise.resolve(
        new Response(JSON.stringify({ needs_setup: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    rs.stubGlobal("fetch", fetchMock);

    await expect(fetchSetupStatus()).resolves.toEqual({ needs_setup: false });
    await rs.advanceTimersByTimeAsync(AUTH_REQUEST_TIMEOUT_MS);

    expect(signals[0]!.aborted).toBe(false);
  });

  test("a retry uses a fresh signal after the first request times out", async () => {
    rs.useFakeTimers();
    const signals: AbortSignal[] = [];
    const fetchMock = rs.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const signal = requestSignal(init);
      signals.push(signal);
      if (signals.length === 1) {
        return pendingUntilAborted(signal);
      }
      return Promise.resolve(
        new Response(JSON.stringify({ needs_setup: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    rs.stubGlobal("fetch", fetchMock);

    const firstRequest = fetchSetupStatus();
    const firstRejection = expect(firstRequest).rejects.toMatchObject({
      name: "AbortError",
    });
    await rs.advanceTimersByTimeAsync(AUTH_REQUEST_TIMEOUT_MS);
    await firstRejection;

    await expect(fetchSetupStatus()).resolves.toEqual({ needs_setup: true });

    expect(signals).toHaveLength(2);
    expect(signals[1]!).not.toBe(signals[0]!);
    expect(signals[0]!.aborted).toBe(true);
    expect(signals[1]!.aborted).toBe(false);
  });

  test("preserves setup-status HTTP errors", async () => {
    rs.stubGlobal(
      "fetch",
      rs.fn(() => Promise.resolve(new Response(null, { status: 503 }))),
    );

    await expect(fetchSetupStatus()).rejects.toThrow(
      "setup-status failed: 503",
    );
  });

  test("regular sign-up is disabled only while setup is required or unknown", () => {
    expect(canCreateRegularAccount({ checked: false, status: null })).toBe(
      false,
    );
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: true },
      }),
    ).toBe(false);
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: false },
      }),
    ).toBe(true);
    expect(canCreateRegularAccount({ checked: true, status: null })).toBe(true);
  });

  test("regular sign-up follows the gateway's registration_enabled flag", () => {
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: false, registration_enabled: false },
      }),
    ).toBe(false);
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: false, registration_enabled: true },
      }),
    ).toBe(true);
    // Older Gateways omit the field; absent must not hide the signup entry.
    expect(
      canCreateRegularAccount({
        checked: true,
        status: { needs_setup: false },
      }),
    ).toBe(true);
  });

  test("detects already-initialized setup conflicts", () => {
    expect(
      isSystemAlreadyInitializedError({
        detail: {
          code: "system_already_initialized",
          message: "System already initialized",
        },
      }),
    ).toBe(true);

    expect(
      isSystemAlreadyInitializedError({
        detail: {
          code: "invalid_credentials",
          message: "Wrong password",
        },
      }),
    ).toBe(false);
  });
});
