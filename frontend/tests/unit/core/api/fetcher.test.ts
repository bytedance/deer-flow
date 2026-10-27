import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { fetch as apiFetch } from "@/core/api/fetcher";

describe("api fetcher Request inputs", () => {
  let sent: Request[];

  beforeEach(() => {
    sent = [];
    rs.stubGlobal("document", { cookie: "csrf_token=cookie-token" });
    rs.stubGlobal(
      "fetch",
      rs.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        sent.push(new Request(input, init));
        return new Response("ok");
      }),
    );
  });

  afterEach(() => {
    rs.unstubAllGlobals();
  });

  it("preserves a Request's method, body, headers and cancellation", async () => {
    const controller = new AbortController();
    const request = new Request("http://localhost/api/threads", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Request-ID": "run-1" },
      body: JSON.stringify({ title: "Research" }),
      signal: controller.signal,
    });

    await apiFetch(request);

    expect(sent[0]?.method).toBe("POST");
    expect(await sent[0]?.text()).toBe(JSON.stringify({ title: "Research" }));
    expect(sent[0]?.headers.get("Content-Type")).toBe("application/json");
    expect(sent[0]?.headers.get("X-Request-ID")).toBe("run-1");
    expect(sent[0]?.headers.get("X-CSRF-Token")).toBe("cookie-token");
    expect(sent[0]?.credentials).toBe("include");
    expect(request.headers.has("X-CSRF-Token")).toBe(false);
    controller.abort();
    expect(sent[0]?.signal.aborted).toBe(true);
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"])(
    "injects CSRF for a Request with method %s",
    async (method) => {
      await apiFetch(new Request("http://localhost/api/threads", { method }));
      expect(sent[0]?.method).toBe(method);
      expect(sent[0]?.headers.get("X-CSRF-Token")).toBe("cookie-token");
    },
  );

  it.each(["GET", "HEAD", "OPTIONS"])(
    "does not inject CSRF for a Request with method %s",
    async (method) => {
      await apiFetch(new Request("http://localhost/api/threads", { method }));
      expect(sent[0]?.method).toBe(method);
      expect(sent[0]?.headers.has("X-CSRF-Token")).toBe(false);
    },
  );

  it("does not inject CSRF for TRACE in init", async () => {
    // Native Request rejects TRACE, so inspect options before that boundary.
    const nativeFetch = rs.fn().mockResolvedValue(new Response("ok"));
    rs.stubGlobal("fetch", nativeFetch);

    await apiFetch("http://localhost/api/threads", { method: "TRACE" });

    expect(nativeFetch).toHaveBeenCalledWith("http://localhost/api/threads", {
      method: "TRACE",
      headers: undefined,
      credentials: "include",
    });
  });

  it("preserves an explicit CSRF header inherited from the Request", async () => {
    await apiFetch(
      new Request("http://localhost/api/threads", {
        method: "POST",
        headers: { "X-CSRF-Token": "explicit-token" },
      }),
    );
    expect(sent[0]?.headers.get("X-CSRF-Token")).toBe("explicit-token");
  });

  it("lets init replace Request headers and body without mutating either header set", async () => {
    const request = new Request("http://localhost/api/threads", {
      method: "POST",
      headers: { "X-Original": "original", "X-CSRF-Token": "request-token" },
      body: "original body",
    });
    const headers = new Headers({ "X-Override": "override" });

    await apiFetch(request, {
      method: "PUT",
      headers,
      body: "replacement body",
    });

    expect(sent[0]?.method).toBe("PUT");
    expect(await sent[0]?.text()).toBe("replacement body");
    expect(sent[0]?.headers.get("X-Override")).toBe("override");
    expect(sent[0]?.headers.has("X-Original")).toBe(false);
    expect(sent[0]?.headers.get("X-CSRF-Token")).toBe("cookie-token");
    expect(headers.has("X-CSRF-Token")).toBe(false);
    expect(request.headers.get("X-CSRF-Token")).toBe("request-token");
  });

  it("uses an init method override when deciding whether CSRF is required", async () => {
    await apiFetch(
      new Request("http://localhost/api/threads", { method: "DELETE" }),
      { method: "GET" },
    );
    expect(sent[0]?.method).toBe("GET");
    expect(sent[0]?.headers.has("X-CSRF-Token")).toBe(false);
  });

  it("preserves Request headers and body when there is no CSRF cookie", async () => {
    document.cookie = "";
    await apiFetch(
      new Request("http://localhost/api/threads", {
        method: "POST",
        headers: { "X-Request-ID": "run-2" },
        body: "payload",
      }),
    );
    expect(sent[0]?.headers.get("X-Request-ID")).toBe("run-2");
    expect(sent[0]?.headers.has("X-CSRF-Token")).toBe(false);
    expect(await sent[0]?.text()).toBe("payload");
  });

  it("retains string-input behavior and an explicit init CSRF header", async () => {
    await apiFetch("http://localhost/api/threads", {
      method: "POST",
      headers: { "X-CSRF-Token": "init-token" },
      body: "payload",
    });
    expect(sent[0]?.method).toBe("POST");
    expect(sent[0]?.headers.get("X-CSRF-Token")).toBe("init-token");
    expect(await sent[0]?.text()).toBe("payload");
  });

  it.each(["%E0%A4%A", "abc%", "a+b%zz"])(
    "forwards a malformed CSRF cookie verbatim instead of throwing: %s",
    async (cookieValue) => {
      document.cookie = `csrf_token=${cookieValue}`;

      await apiFetch("http://localhost/api/threads", { method: "POST" });

      expect(sent[0]?.headers.get("X-CSRF-Token")).toBe(cookieValue);
    },
  );

  it("still decodes a percent-encoded CSRF cookie", async () => {
    document.cookie = "csrf_token=cookie%2Dtoken";

    await apiFetch("http://localhost/api/threads", { method: "POST" });

    expect(sent[0]?.headers.get("X-CSRF-Token")).toBe("cookie-token");
  });
});
