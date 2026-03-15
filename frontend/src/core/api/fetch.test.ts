import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, apiJson } from "./fetch";

vi.mock("../config", () => ({
  getBackendBaseURL: () => "",
}));

describe("api fetch helpers", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("maps timeout abort to timeout api error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    const promise = apiFetch("/api/test", { timeout: 10 });
    const assertion = expect(promise).rejects.toMatchObject({
      detail: "timeout",
    });
    await vi.advanceTimersByTimeAsync(20);
    await assertion;
  });

  it("maps caller abort to cancelled api error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    const controller = new AbortController();
    const promise = apiFetch("/api/test", {
      signal: controller.signal,
      timeout: 5_000,
    });
    controller.abort();

    await expect(promise).rejects.toMatchObject({ detail: "aborted" });
  });

  it("returns undefined from apiJson on empty body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("", {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );

    const result = await apiJson<unknown>("/api/test");
    expect(result).toBeUndefined();
  });

  it("throws ApiError when apiJson receives invalid json", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("not-json", {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );

    await expect(apiJson("/api/test")).rejects.toBeInstanceOf(ApiError);
  });
});
