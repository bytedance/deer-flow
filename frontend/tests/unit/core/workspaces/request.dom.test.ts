import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { fetch as apiFetch } from "@/core/api/fetcher";

const SPACE = "11111111-1111-1111-1111-111111111111";

describe("workspace selectors carried by native Request objects", () => {
  let forwarded: Request | undefined;

  beforeEach(() => {
    forwarded = undefined;
    document.cookie = "csrf_token=workspace-request-fixture; path=/";
    rs.stubGlobal(
      "fetch",
      async (input: RequestInfo | URL, init?: RequestInit) => {
        // happy-dom Request does not consume the worker's Headers instance as
        // native fetch does. Normalize that standard iterable at the test boundary.
        const headers = init?.headers
          ? Object.fromEntries(new Headers(init.headers).entries())
          : undefined;
        forwarded = new Request(input, { ...init, headers });
        return Response.json({ accepted: true });
      },
    );
  });

  afterEach(() => {
    document.cookie = "csrf_token=; max-age=0; path=/";
    rs.unstubAllGlobals();
  });

  it("keeps the selected workspace, method and body while adding CSRF", async () => {
    const source = new Request("http://localhost:3000/api/threads", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Deerflow-Workspace": SPACE,
      },
      body: JSON.stringify({ thread_id: "selected-space-thread" }),
    });

    await apiFetch(source);

    expect(forwarded?.headers.get("X-Deerflow-Workspace")).toBe(SPACE);
    expect(forwarded?.method).toBe("POST");
    expect(await forwarded?.json()).toEqual({
      thread_id: "selected-space-thread",
    });
    expect(forwarded?.headers.get("X-CSRF-Token")).toBe(
      "workspace-request-fixture",
    );
    expect(forwarded?.credentials).toBe("include");
    expect(source.headers.has("X-CSRF-Token")).toBe(false);
  });

  it("keeps Request cancellation and explicit RequestInit header overrides", async () => {
    const controller = new AbortController();
    const source = new Request("http://localhost:3000/api/threads/selected", {
      headers: { "X-Deerflow-Workspace": SPACE, "X-Caller": "original" },
      signal: controller.signal,
    });
    await apiFetch(source, {
      headers: { "X-Deerflow-Workspace": SPACE, "X-Caller": "override" },
    });
    controller.abort();
    expect(forwarded?.signal.aborted).toBe(true);
    expect(forwarded?.headers.get("X-Caller")).toBe("override");
    expect(source.headers.get("X-Caller")).toBe("original");
  });
});
